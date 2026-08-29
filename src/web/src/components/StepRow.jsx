import React from 'react';
import InlineGate from './InlineGate';
import { IconCheck, IconX, IconAgent, IconTool } from './Icons';

export default function StepRow({ step, onApprove, onReject, onAbort }) {
  const st = (step.status || 'PENDING').toLowerCase();

  return (
    <li className={`step status-${st}`}>
      <div className="step-icon">
        {st === 'completed' ? <IconCheck size={13} /> : st === 'failed' ? <IconX size={13} /> : step.step_id}
      </div>
      <div className="step-body">
        <div className="step-title-row">
          <span className="step-name">{step.name}</span>
          <span className={`step-status`}>
            {(step.status || 'PENDING').replace(/_/g, ' ')}
          </span>
        </div>
        {(step.sub_agent || step.latest_log || step.active_tool) && (
          <div className="step-meta">
            {step.sub_agent && <span className="step-agent"><IconAgent size={12} /> {step.sub_agent}</span>}
            {step.active_tool && <span className="step-tool"><IconTool size={12} /> {step.active_tool}</span>}
            {step.latest_log && !st.includes('waiting') && (
              <span className="step-log">{step.latest_log}</span>
            )}
          </div>
        )}
        {st === 'in_progress' && step.logs?.length > 0 && (
          <ul className="step-log-list">
            {step.logs.slice(-3).map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        )}
        {st === 'waiting_approval' && (
          <InlineGate
            step={step}
            onApprove={onApprove}
            onReject={onReject}
            onAbort={onAbort}
          />
        )}
      </div>
    </li>
  );
}
