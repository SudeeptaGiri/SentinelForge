// SentinelForge — React frontend
const { useState, useEffect, useRef, useCallback } = React;

// ── localStorage ────────────────────────────────────────────────────────────
const LS_KEY = "sf_history_v2";
function loadHistory() {
  try { return JSON.parse(localStorage.getItem(LS_KEY) || "[]"); } catch { return []; }
}
function saveHistory(h) { localStorage.setItem(LS_KEY, JSON.stringify(h.slice(0, 15))); }

// ── Intents ─────────────────────────────────────────────────────────────────
const INTENTS = [
  { value: "migrate_cloud",  icon: "\u2601\uFE0F",  label: "Migrate to Cloud" },
  { value: "migrate_modern", icon: "\u26A1",  label: "Modernise Stack" },
  { value: "new_feature",    icon: "\u2728",  label: "Add New Feature" },
  { value: "from_scratch",   icon: "\uD83C\uDFD7\uFE0F", label: "Build From Scratch" },
];

// ── VisGraph ─────────────────────────────────────────────────────────────────
function VisGraph({ nodes, edges }) {
  const ref = useRef(null);
  const net = useRef(null);
  useEffect(() => {
    if (!ref.current || !nodes.length) return;
    const data = { nodes: new vis.DataSet(nodes), edges: new vis.DataSet(edges) };
    const opts = {
      physics: { stabilization: { iterations: 100 }, barnesHut: { gravitationalConstant: -4000 } },
      interaction: { hover: true, tooltipDelay: 200 },
      edges: { smooth: { type: "curvedCW", roundness: 0.2 }, width: 1.5 },
      nodes: { shape: "dot", size: 13, borderWidth: 2, font: { size: 11 } },
    };
    net.current = new vis.Network(ref.current, data, opts);
    return () => net.current && net.current.destroy();
  }, [nodes, edges]);
  return <div ref={ref} className="graph-canvas" />;
}

// ── SetupPhase ───────────────────────────────────────────────────────────────
function SetupPhase({ onStart, loading }) {
  const [repo, setRepo] = useState("fixtures/sample_legacy_app");
  const [name, setName] = useState("legacy-app");
  const [intent, setIntent] = useState("migrate_cloud");
  return (
    <section className="phase-card">
      <h2 className="phase-title"><span className="phase-num">1</span> Configure Your Project</h2>
      <div className="setup-form">
        <div className="form-group">
          <label>Repository Path or GitHub URL</label>
          <input type="text" value={repo} onChange={e => setRepo(e.target.value)}
            placeholder="fixtures/sample_legacy_app  or  https://github.com/org/repo" />
        </div>
        <div className="form-group">
          <label>Application Name</label>
          <input type="text" value={name} onChange={e => setName(e.target.value)} placeholder="my-service" />
        </div>
        <div className="form-group">
          <label>What do you want to do?</label>
          <div className="intent-grid">
            {INTENTS.map(i => (
              <label key={i.value} className={`intent-card${intent === i.value ? " selected" : ""}`}
                onClick={() => setIntent(i.value)}>
                <span className="intent-icon">{i.icon}</span>
                <span className="intent-label">{i.label}</span>
              </label>
            ))}
          </div>
        </div>
        <button className="btn btn-primary btn-lg" disabled={loading}
          onClick={() => onStart({ repo, name, intent })}>
          {loading ? "\u23F3 Starting\u2026" : "\u25B6 Analyse & Build Plan"}
        </button>
      </div>
    </section>
  );
}

// ── AnalysisPhase ────────────────────────────────────────────────────────────
function AnalysisPhase({ analysis: a, graph }) {
  if (!a) return null;
  const gs = a.graph_summary || {};
  const cards = [
    ["Platform", a.detected_platform],
    ["Framework", a.framework],
    ["Architecture", a.architecture_type],
    ["Dockerfile", a.has_dockerfile ? "Yes \u2713" : "No"],
    ["Autoscaling", a.has_autoscaling ? "Yes \u2713" : "No"],
    ["Files", gs.total_files ?? a.files_of_interest?.length ?? "\u2014"],
  ];
  return (
    <section className="phase-card">
      <h2 className="phase-title"><span className="phase-num">2</span> Codebase Analysis &amp; GraphRAG</h2>
      <div className="analysis-grid">
        <div className="analysis-left">
          <div className="info-cards">
            {cards.map(([l, v]) => (
              <div key={l} className="info-card">
                <div className="card-label">{l}</div>
                <div className="card-value">{v || "\u2014"}</div>
              </div>
            ))}
          </div>
          <div className="panel-box">
            <h3>Architecture Summary</h3>
            <p className="summary-text">{a.summary}</p>
          </div>
          <div className="panel-box">
            <h3>Detected Endpoints</h3>
            <ul className="tag-list">
              {(a.endpoints||[]).length
                ? (a.endpoints).map((e,i) => <li key={i}>{typeof e==="string"?e:`${e.method||""} ${e.path||e}`}</li>)
                : <li className="muted">No routes detected</li>}
            </ul>
          </div>
          <div className="panel-box">
            <h3>Key Dependencies</h3>
            <div className="tag-cloud">{(a.dependencies||[]).map(d=><span key={d} className="dep-tag">{d}</span>)}</div>
          </div>
          <div className="panel-box">
            <h3>Recommendations</h3>
            <ul className="rec-list">{(a.recommendations||[]).map((r,i)=><li key={i}>{r}</li>)}</ul>
          </div>
        </div>
        <div className="analysis-right">
          <div className="panel-box graph-box">
            <h3>Code Knowledge Graph <span className="badge-muted">GraphRAG</span></h3>
            <VisGraph nodes={graph.nodes||[]} edges={graph.edges||[]} />
            <div className="graph-legend">
              <span className="legend-dot file"></span> File
              <span className="legend-dot route"></span> Route
              <span className="legend-dot dep"></span> Dependency
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

// ── InlineGate ───────────────────────────────────────────────────────────────
function InlineGate({ step, onApprove, onReject }) {
  const [fb, setFb] = useState("");
  const [showFb, setShowFb] = useState(false);
  function handleReject() {
    if (!showFb) { setShowFb(true); return; }
    onReject(step.step_id, fb);
    setFb(""); setShowFb(false);
  }
  return (
    <div className="inline-gate">
      <p className="gate-inline-msg">
        <span className="gate-badge">HITL Gate</span> {step.latest_log||"Review and approve to continue."}
      </p>
      {showFb && (
        <div className="inline-feedback">
          <textarea rows={2} value={fb} onChange={e=>setFb(e.target.value)}
            placeholder="What should change? The agent will regenerate with your feedback\u2026" />
        </div>
      )}
      <div className="inline-gate-actions">
        <button className="btn btn-danger btn-sm" onClick={handleReject}>
          {showFb ? "\u21A9 Submit & Regenerate" : "\u2717 Reject & Revise"}
        </button>
        <button className="btn btn-success btn-sm" onClick={()=>onApprove(step.step_id)}>
          \u2713 Approve &amp; Proceed
        </button>
      </div>
    </div>
  );
}

// ── StepRow ──────────────────────────────────────────────────────────────────
function StepRow({ step, onApprove, onReject }) {
  const st = (step.status||"PENDING").toLowerCase();
  return (
    <li className={`step status-${st}`}>
      <div className="step-icon">{st === "completed" ? "\u2713" : step.step_id}</div>
      <div className="step-body">
        <div className="step-title-row">
          <span className="step-name">{step.name}</span>
          <span className="step-status">{(step.status||"PENDING").replace(/_/g," ")}</span>
        </div>
        {(step.sub_agent||step.latest_log) && (
          <div className="step-meta">
            {step.sub_agent && <span className="step-agent">{step.sub_agent}</span>}
            {step.latest_log && <span className="step-log">{step.latest_log}</span>}
          </div>
        )}
        {st === "waiting_approval" && (
          <InlineGate step={step} onApprove={onApprove} onReject={onReject} />
        )}
      </div>
    </li>
  );
}

// ── ArchPlanPanel ─────────────────────────────────────────────────────────────
function ArchPlanPanel({ steps, specData }) {
  const done = id => steps.find(s=>s.step_id===id&&s.status==="COMPLETED");
  const s1=done(1), s2=done(2), s3=done(3), s4=done(4), s5=done(5), s6=done(6);
  if (!s1) return <div className="arch-plan-panel panel-box"><h3>Architecture Plan</h3><p className="muted">Running pipeline\u2026</p></div>;
  return (
    <div className="arch-plan-panel panel-box">
      <h3>Architecture Plan</h3>
      {s1 && <div className="plan-section"><div className="plan-section-title">\uD83D\uDD0D Codebase Analysis</div><p>{s1.latest_log||"Analysis complete."}</p></div>}
      {s2 && (
        <div className="plan-section">
          <div className="plan-section-title">\uD83D\uDCCF Architecture &amp; Approach Proposal</div>
          <p>{s2.latest_log||"Proposal generated."}</p>
          {specData && (
            <div className="spec-plan-block">
              <div className="plan-section-title" style={{marginTop:"10px"}}>\uD83D\uDCCB Target API Contract (SpecAgent)</div>
              <p><strong>{specData.title}</strong>{specData.summary ? ` \u2014 ${specData.summary}` : ""}</p>
              {specData.endpoints?.length > 0 && (
                <table className="plan-table">
                  <thead><tr><th>Method</th><th>Path</th><th>Summary</th></tr></thead>
                  <tbody>{specData.endpoints.map((e,i)=>(
                    <tr key={i}><td>{e.method||"\u2014"}</td><td><code>{e.path||e}</code></td><td>{e.summary||""}</td></tr>
                  ))}</tbody>
                </table>
              )}
              {specData.data_models?.length > 0 && (
                <p style={{marginTop:"8px"}}><strong>Models: </strong>
                  {specData.data_models.map(m=><span key={m.name||m} className="dep-tag" style={{marginRight:"4px"}}>{m.name||m}</span>)}
                </p>
              )}
              {specData.workload_spec?.cpu_cores && (
                <p style={{fontSize:"11px",color:"var(--muted)",marginTop:"6px"}}>
                  Sized: {specData.workload_spec.cpu_cores} vCPU &middot; {specData.workload_spec.ram_gb} GB RAM &middot; {(specData.workload_spec.monthly_requests||0).toLocaleString()} req/mo &middot; Stateful: {specData.workload_spec.is_stateful ? "Yes" : "No"}
                </p>
              )}
            </div>
          )}
        </div>
      )}
      {s3 && <div className="plan-section"><div className="plan-section-title">\u2699\uFE0F Code Changes</div><p>{s3.latest_log||"Branch created."}</p></div>}
      {s4 && <div className="plan-section"><div className="plan-section-title">\uD83C\uDFD7\uFE0F Infrastructure</div><p>{s4.latest_log||"Terraform validated."}</p></div>}
      {s5 && <div className="plan-section"><div className="plan-section-title">\uD83D\uDD12 Security Audit</div><p>{s5.latest_log||"Pentest complete."}</p></div>}
      {s6 && <div className="plan-section"><div className="plan-section-title">\uD83D\uDE80 Deployment</div><p>{s6.latest_log||"Deployed."}</p></div>}
    </div>
  );
}

// ── PipelinePhase ─────────────────────────────────────────────────────────────
function PipelinePhase({ steps, specData, onApprove, onReject, result, error }) {
  const [leftWidth, setLeftWidth] = useState(40);
  const [isDragging, setIsDragging] = useState(false);
  const containerRef = useRef(null);

  const handleMouseDown = useCallback((e) => {
    setIsDragging(true);
    e.preventDefault();
  }, []);

  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e) => {
      if (!containerRef.current) return;
      const container = containerRef.current;
      const rect = container.getBoundingClientRect();
      const newWidth = ((e.clientX - rect.left) / rect.width) * 100;
      if (newWidth >= 25 && newWidth <= 75) {
        setLeftWidth(newWidth);
      }
    };

    const handleMouseUp = () => {
      setIsDragging(false);
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging]);

  const done = steps.filter(s=>s.status==="COMPLETED").length;
  const pct = steps.length ? Math.round(done/steps.length*100) : 0;

  return (
    <section className="phase-card">
      <h2 className="phase-title"><span className="phase-num">3</span> Live Pipeline Execution &amp; HITL Gates</h2>
      <div className="pipeline-grid" ref={containerRef}>
        <div className="pipeline-left" style={{flex: `0 0 ${leftWidth}%`}}>
          <ArchPlanPanel steps={steps} specData={specData} />
        </div>
        <div className="pipeline-splitter" onMouseDown={handleMouseDown} />
        <div className="pipeline-right" style={{flex: 1}}>
          <div className="stepper-panel panel-box">
            <div className="stepper-header">
              <h3>Pipeline Steps</h3>
              <div className="progress-track"><div className="progress-fill" style={{width:`${pct}%`}} /></div>
              <span className="muted">{pct}% complete</span>
            </div>
            <ol className="stepper">
              {steps.map(s=><StepRow key={s.step_id} step={s} onApprove={onApprove} onReject={onReject} />)}
            </ol>
            {(result||error) && (
              <div className="result-box" style={{borderColor:error?"var(--danger)":"var(--success)"}}>
                {error ? `ERROR: ${error}` : JSON.stringify(result, null, 2)}
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

// ── Header ───────────────────────────────────────────────────────────────────
function Header({ history, activeId, onSelect, onNewRun }) {
  const [open, setOpen] = useState(false);
  const statusColor = s => s==="DEPLOYED"?"var(--success)":s==="ERROR"||s==="ABORTED"?"var(--danger)":"var(--muted)";
  return (
    <header className="app-header">
      <div className="brand">
        <span className="brand-mark">\u25CF</span>
        <div>
          <h1>SentinelForge</h1>
          <p>Autonomous AI DevSecOps Agent</p>
        </div>
      </div>
      <div className="header-actions">
        {activeId && <div className="run-badge">RUN \u00B7 {activeId.slice(-8)}</div>}
        <div style={{position:"relative"}}>
          <button className="btn btn-sm" style={{background:"#1c2436",color:"var(--text)"}}
            onClick={()=>setOpen(v=>!v)}>
            \uD83D\uDD50 History ({history.length})
          </button>
          {open && (
            <div className="history-panel">
              <div className="history-header">
                <span>Previous Runs</span>
                <button className="btn btn-sm btn-primary" onClick={()=>{setOpen(false);onNewRun();}}>+ New Run</button>
              </div>
              {history.length===0 && <p className="muted" style={{padding:"12px 16px"}}>No previous runs yet.</p>}
              {history.map(r=>(
                <div key={r.id} className={`history-item${r.id===activeId?" active":""}`}
                  onClick={()=>{setOpen(false);onSelect(r);}}>
                  <div className="history-name">{r.name||r.id.slice(-8)}</div>
                  <div style={{fontSize:"10px",color:"var(--muted)"}}>{(r.intent||"").replace(/_/g," ")} \u00B7 {r.repo||""}</div>
                  {r.status && <div style={{fontSize:"10px",fontWeight:700,color:statusColor(r.status)}}>{r.status}</div>}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </header>
  );
}

// ── App ───────────────────────────────────────────────────────────────────────
function App() {
  const [phase, setPhase] = useState("setup");
  const [loading, setLoading] = useState(false);
  const [activeId, setActiveId] = useState(null);
  const [history, setHistory] = useState(loadHistory);
  const [steps, setSteps] = useState([]);
  const [analysis, setAnalysis] = useState(null);
  const [graph, setGraph] = useState({nodes:[],edges:[]});
  const [specData, setSpecData] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const esRef = useRef(null);
  const aPolled = useRef(false);
  const sPolled = useRef(false);
  const metaRef = useRef({});

  function upsert(run) {
    setHistory(prev => { const next=[run,...prev.filter(r=>r.id!==run.id)]; saveHistory(next); return next; });
  }

  async function handleStart({ repo, name, intent }) {
    setLoading(true);
    setAnalysis(null); setGraph({nodes:[],edges:[]}); setSpecData(null);
    setResult(null); setError(null); setSteps([]);
    aPolled.current=false; sPolled.current=false;
    try {
      const res = await fetch("/api/pipeline/start",{method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({repo_path:repo,app_name:name,intent})});
      const {pipeline_id:id} = await res.json();
      setActiveId(id);
      metaRef.current = {id,name,repo,intent,ts:Date.now()};
      upsert({id,name,repo,intent,status:"RUNNING",ts:Date.now()});
      setPhase("running");
      attachSSE(id);
    } catch(e) { setError(String(e)); }
    finally { setLoading(false); }
  }

  function attachSSE(id) {
    if (esRef.current) esRef.current.close();
    const es = new EventSource(`/api/pipeline/${id}/events`);
    esRef.current = es;
    es.onmessage = evt => {
      const state = JSON.parse(evt.data);
      setSteps(state.steps||[]);
      if (!aPolled.current && state.steps?.[0]?.status==="COMPLETED") {
        aPolled.current=true; setTimeout(()=>pollAnalysis(id),800);
      }
      if (!sPolled.current && state.steps?.[1]?.status==="COMPLETED") {
        sPolled.current=true; setTimeout(()=>pollSpec(id),800);
      }
      pollResult(id);
    };
  }

  async function pollAnalysis(id) {
    try {
      const d = await (await fetch(`/api/pipeline/${id}/analysis`)).json();
      if (d.analysis) setAnalysis(d.analysis);
      if (d.graph?.nodes?.length) setGraph(d.graph);
    } catch {}
  }

  async function pollSpec(id) {
    try {
      const d = await (await fetch(`/api/pipeline/${id}/analysis`)).json();
      if (d.spec) setSpecData(d.spec);
    } catch {}
  }

  async function pollResult(id) {
    try {
      const d = await (await fetch(`/api/pipeline/${id}/state`)).json();
      if (d.result) {
        setResult(d.result); setPhase("done");
        upsert({...metaRef.current, status:d.result.status||"DONE"});
        esRef.current?.close();
      } else if (d.error) {
        setError(d.error); setPhase("done");
        upsert({...metaRef.current, status:"ERROR"});
        esRef.current?.close();
      }
    } catch {}
  }

  async function handleApprove(stepId) {
    await fetch(`/api/pipeline/${activeId}/gate/${stepId}/decision`,
      {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({approved:true,feedback:null})});
  }

  async function handleReject(stepId, feedback) {
    await fetch(`/api/pipeline/${activeId}/gate/${stepId}/decision`,
      {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({approved:false,feedback:feedback||null})});
  }

  function handleSelect(run) {
    setActiveId(run.id); setPhase("done"); setSpecData(null);
    setResult(run.result||null); setError(run.error||null); setSteps([]);
    setAnalysis(null); setGraph({nodes:[],edges:[]});
    metaRef.current = run;
    fetch(`/api/pipeline/${run.id}/state`).then(r=>r.json()).then(d=>{
      if (d.steps) setSteps(d.steps);
      if (d.result) setResult(d.result);
      if (d.error) setError(d.error);
      const live = d.steps?.some(s=>["IN_PROGRESS","WAITING_APPROVAL"].includes(s.status));
      if (live) {
        aPolled.current = !!d.steps?.find(s=>s.step_id===1&&s.status==="COMPLETED");
        sPolled.current = !!d.steps?.find(s=>s.step_id===2&&s.status==="COMPLETED");
        setPhase("running"); attachSSE(run.id);
      }
      pollAnalysis(run.id); pollSpec(run.id);
    }).catch(()=>{});
  }

  function handleNewRun() {
    esRef.current?.close();
    setPhase("setup"); setActiveId(null); setSteps([]);
    setAnalysis(null); setGraph({nodes:[],edges:[]}); setSpecData(null);
    setResult(null); setError(null);
  }

  return (
    <div className="app">
      <Header history={history} activeId={activeId} onSelect={handleSelect} onNewRun={handleNewRun} />
      <SetupPhase onStart={handleStart} loading={loading} />
      {analysis && <AnalysisPhase analysis={analysis} graph={graph} />}
      {phase!=="setup" && <PipelinePhase steps={steps} specData={specData}
        onApprove={handleApprove} onReject={handleReject} result={result} error={error} />}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
