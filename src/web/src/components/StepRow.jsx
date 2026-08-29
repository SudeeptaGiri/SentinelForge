import React from 'react';
import InlineGate from './InlineGate';

export default function StepRow({ step, onApprove, onReject }) {
  const st = (step.status || 'PENDING').toLowerCase();

  return (
    <li className={`step status-${st}`}>
      <div className="step-icon">
        {st === 'completed' ? '✓' : st === 'failed' ? '✗' : step.step_id}
      </div>
      <div className="step-body">
        <div className="step-title-row">
          <span className="step-name">{step.name}</span>
          <span className={`step-status status-badge-${st}`}>
            {(step.status || 'PENDING').replace(/_/g, ' ')}
          </span>
        </div>
        {(step.sub_agent || step.latest_log || step.active_tool) && (
          <div className="step-meta">
            {step.sub_agent && <span className="step-agent">🤖 {step.sub_agent}</span>}
            {step.active_tool && <span className="step-tool" style={{ color: 'var(--accent)', fontSize: '11px' }}>🛠️ {step.active_tool}</span>}
            {step.latest_log && <span className="step-log">{step.latest_log}</span>}
          </div>
        )}
        {st === 'waiting_approval' && (
          <InlineGate step={step} onApprove={onApprove} onReject={onReject} />
        )}
      </div>
    </li>
  );
}
