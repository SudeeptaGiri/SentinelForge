import React from 'react';
import ArchPlanPanel from './ArchPlanPanel';
import StepRow from './StepRow';

export default function PipelinePhase({ steps, specData, onApprove, onReject, result, error }) {
  const done = steps.filter((s) => s.status === 'COMPLETED').length;
  const pct = steps.length ? Math.round((done / steps.length) * 100) : 0;

  return (
    <section className="phase-card">
      <h2 className="phase-title">
        <span className="phase-num">3</span> Live Pipeline Execution &amp; HITL Gates
      </h2>
      <div className="pipeline-grid">
        <ArchPlanPanel steps={steps} specData={specData} />
        <div className="stepper-panel panel-box">
          <div className="stepper-header">
            <h3>Pipeline Stepper</h3>
            <div className="progress-track">
              <div className="progress-fill" style={{ width: `${pct}%` }} />
            </div>
            <span className="muted" style={{ fontSize: '12px' }}>{pct}% complete ({done}/{steps.length})</span>
          </div>

          <ol className="stepper">
            {steps.map((s) => (
              <StepRow key={s.step_id} step={s} onApprove={onApprove} onReject={onReject} />
            ))}
          </ol>

          {(result || error) && (
            <div
              className="result-box"
              style={{
                marginTop: '16px',
                padding: '16px',
                borderRadius: '8px',
                background: error ? 'rgba(240, 84, 107, 0.1)' : 'rgba(51, 196, 129, 0.1)',
                border: `1px solid ${error ? 'var(--danger)' : 'var(--success)'}`,
              }}
            >
              <h4 style={{ margin: '0 0 8px', color: error ? 'var(--danger)' : 'var(--success)' }}>
                {error ? '❌ Pipeline Failed / Terminated' : '🎉 Pipeline Completed Successfully!'}
              </h4>
              <pre style={{ margin: 0, fontSize: '12px', whiteSpace: 'pre-wrap', color: 'var(--text)' }}>
                {error ? String(error) : JSON.stringify(result, null, 2)}
              </pre>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
