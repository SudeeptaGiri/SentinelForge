import React, { useState, useEffect, useRef } from 'react';
import Header from './components/Header';
import SetupPhase from './components/SetupPhase';
import AnalysisPhase from './components/AnalysisPhase';
import PipelinePhase from './components/PipelinePhase';

const LS_KEY = 'sf_history_v2';

function loadHistory() {
  try {
    return JSON.parse(localStorage.getItem(LS_KEY) || '[]');
  } catch {
    return [];
  }
}

function saveHistory(h) {
  localStorage.setItem(LS_KEY, JSON.stringify(h.slice(0, 20)));
}

export default function App() {
  const [phase, setPhase] = useState('setup');
  const [loading, setLoading] = useState(false);
  const [activeId, setActiveId] = useState(null);
  const [history, setHistory] = useState(loadHistory);
  const [steps, setSteps] = useState([]);
  const [analysis, setAnalysis] = useState(null);
  const [graph, setGraph] = useState({ nodes: [], edges: [] });
  const [specData, setSpecData] = useState(null);
  const [planData, setPlanData] = useState(null);
  const [codegenData, setCodegenData] = useState(null);
  const [fileEdits, setFileEdits] = useState({});
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const esRef = useRef(null);
  const aPolled = useRef(false);
  const lastProposalLog = useRef(null);
  const lastCodegenLog = useRef(null);
  const metaRef = useRef({});

  function upsert(run) {
    setHistory((prev) => {
      const next = [run, ...prev.filter((r) => r.id !== run.id)];
      saveHistory(next);
      return next;
    });
  }

  async function handleStart({ repo, name, intent }) {
    setLoading(true);
    setAnalysis(null);
    setGraph({ nodes: [], edges: [] });
    setSpecData(null);
    setPlanData(null);
    setCodegenData(null);
    setFileEdits({});
    setResult(null);
    setError(null);
    setSteps([]);
    aPolled.current = false;
    lastProposalLog.current = null;
    lastCodegenLog.current = null;

    try {
      const res = await fetch('/api/pipeline/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_path: repo, app_name: name, intent }),
      });
      const data = await res.json();
      const id = data.pipeline_id;
      setActiveId(id);
      metaRef.current = { id, name, repo, intent, ts: Date.now() };
      upsert({ id, name, repo, intent, status: 'RUNNING', ts: Date.now() });
      setPhase('running');
      attachSSE(id);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  function attachSSE(id) {
    if (esRef.current) esRef.current.close();
    const es = new EventSource(`/api/pipeline/${id}/events`);
    esRef.current = es;

    es.onmessage = (evt) => {
      try {
        const state = JSON.parse(evt.data);
        setSteps(state.steps || []);

        if (!aPolled.current && state.steps?.[0]?.status === 'COMPLETED') {
          aPolled.current = true;
          setTimeout(() => pollAnalysis(id), 600);
        }

        // Step 2 (Proposal) can regenerate multiple times on reject+feedback;
        // re-poll every time its log message changes while awaiting/entering approval.
        const proposalStep = state.steps?.[1];
        const proposalLog = proposalStep?.latest_log || null;
        if (
          proposalStep &&
          ['WAITING_APPROVAL', 'COMPLETED'].includes(proposalStep.status) &&
          proposalLog !== lastProposalLog.current
        ) {
          lastProposalLog.current = proposalLog;
          setTimeout(() => pollSpec(id), 600);
        }

        // Step 3 (Codegen) can also regenerate on reject+feedback; re-poll on each change.
        const codegenStep = state.steps?.[2];
        const codegenLog = codegenStep?.latest_log || null;
        if (
          codegenStep &&
          ['WAITING_APPROVAL', 'COMPLETED'].includes(codegenStep.status) &&
          codegenLog !== lastCodegenLog.current
        ) {
          lastCodegenLog.current = codegenLog;
          setFileEdits({});
          setTimeout(() => pollCodegen(id), 600);
        }

        pollResult(id);
      } catch (err) {
        console.error('Failed to parse SSE event:', err);
      }
    };

    es.onerror = () => {
      // Re-polling fallback on SSE disruption
      pollResult(id);
    };
  }

  async function pollAnalysis(id) {
    try {
      const res = await fetch(`/api/pipeline/${id}/analysis`);
      const d = await res.json();
      if (d.analysis) setAnalysis(d.analysis);
      if (d.graph?.nodes?.length) setGraph(d.graph);
    } catch {}
  }

  async function pollSpec(id) {
    try {
      const res = await fetch(`/api/pipeline/${id}/analysis`);
      const d = await res.json();
      if (d.spec) setSpecData(d.spec);
      if (d.plan) setPlanData(d.plan);
    } catch {}
  }

  async function pollCodegen(id) {
    try {
      const res = await fetch(`/api/pipeline/${id}/analysis`);
      const d = await res.json();
      if (d.codegen) setCodegenData(d.codegen);
    } catch {}
  }

  async function pollResult(id) {
    try {
      const res = await fetch(`/api/pipeline/${id}/state`);
      const d = await res.json();
      if (d.result) {
        setResult(d.result);
        setPhase('done');
        upsert({ ...metaRef.current, status: d.result.status || 'COMPLETED' });
        esRef.current?.close();
      } else if (d.error) {
        setError(d.error);
        setPhase('done');
        upsert({ ...metaRef.current, status: 'FAILED' });
        esRef.current?.close();
      }
    } catch {}
  }

  async function handleApprove(stepId) {
    const editedFiles = stepId === 3 && Object.keys(fileEdits).length ? fileEdits : null;
    await fetch(`/api/pipeline/${activeId}/gate/${stepId}/decision`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approved: true, feedback: null, edited_files: editedFiles }),
    });
  }

  async function handleReject(stepId, feedback) {
    await fetch(`/api/pipeline/${activeId}/gate/${stepId}/decision`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approved: false, feedback: feedback || null }),
    });
  }

  function handleFileEdit(path, content) {
    setFileEdits((prev) => ({ ...prev, [path]: content }));
  }

  async function handleAbort() {
    if (!activeId) return;
    try {
      await fetch(`/api/pipeline/${activeId}/abort`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      setPhase('done');
      setError('Pipeline aborted by user');
      upsert({ ...metaRef.current, status: 'ABORTED' });
      esRef.current?.close();
    } catch (e) {
      console.error('Failed to abort pipeline:', e);
    }
  }

  function handleSelect(run) {
    setActiveId(run.id);
    setPhase('done');
    setSpecData(null);
    setPlanData(null);
    setCodegenData(null);
    setFileEdits({});
    setResult(run.result || null);
    setError(run.error || null);
    setSteps([]);
    setAnalysis(null);
    setGraph({ nodes: [], edges: [] });
    metaRef.current = run;

    fetch(`/api/pipeline/${run.id}/state`)
      .then((r) => r.json())
      .then((d) => {
        if (d.steps) setSteps(d.steps);
        if (d.result) setResult(d.result);
        if (d.error) setError(d.error);

        const live = d.steps?.some((s) => ['IN_PROGRESS', 'WAITING_APPROVAL'].includes(s.status));
        if (live) {
          aPolled.current = !!d.steps?.find((s) => s.step_id === 1 && s.status === 'COMPLETED');
          lastProposalLog.current = d.steps?.[1]?.latest_log || null;
          lastCodegenLog.current = d.steps?.[2]?.latest_log || null;
          setPhase('running');
          attachSSE(run.id);
        }
        pollAnalysis(run.id);
        pollSpec(run.id);
        pollCodegen(run.id);
      })
      .catch(() => {});
  }

  function handleNewRun() {
    esRef.current?.close();
    setPhase('setup');
    setActiveId(null);
    setSteps([]);
    setAnalysis(null);
    setGraph({ nodes: [], edges: [] });
    setSpecData(null);
    setPlanData(null);
    setCodegenData(null);
    setFileEdits({});
    setResult(null);
    setError(null);
  }

  return (
    <div className="app">
      <Header
        history={history}
        activeId={activeId}
        onSelect={handleSelect}
        onNewRun={handleNewRun}
      />
      <SetupPhase onStart={handleStart} loading={loading} />
      {analysis && <AnalysisPhase analysis={analysis} graph={graph} />}
      {phase !== 'setup' && (
        <PipelinePhase
          steps={steps}
          specData={specData}
          planData={planData}
          codegenData={codegenData}
          fileEdits={fileEdits}
          onFileEdit={handleFileEdit}
          onApprove={handleApprove}
          onReject={handleReject}
          onAbort={handleAbort}
          result={result}
          error={error}
        />
      )}
    </div>
  );
}
