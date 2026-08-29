import React, { useState } from 'react';

export default function InlineGate({ step, onApprove, onReject }) {
  const [fb, setFb] = useState('');
  const [showFb, setShowFb] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  async function handleApprove() {
    setSubmitting(true);
    try {
      await onApprove(step.step_id);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleReject() {
    if (!showFb) {
      setShowFb(true);
      return;
    }
    setSubmitting(true);
    try {
      await onReject(step.step_id, fb);
      setFb('');
      setShowFb(false);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="inline-gate">
      <div className="gate-header-row" style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
        <span className="gate-badge" style={{ background: 'var(--accent)', color: 'white', padding: '2px 8px', borderRadius: '4px', fontSize: '11px', fontWeight: 'bold' }}>
          HITL Gate Required
        </span>
        <span style={{ fontSize: '13px', color: 'var(--text)' }}>
          {step.latest_log || 'Review artifact and authorize execution to proceed.'}
        </span>
      </div>

      {showFb && (
        <div className="inline-feedback" style={{ marginBottom: '10px' }}>
          <textarea
            rows={2}
            value={fb}
            onChange={(e) => setFb(e.target.value)}
            placeholder="Explain required changes (e.g. 'Add Redis cache layer', 'Increase CPU allocation'). The agent will re-generate..."
            style={{ width: '100%', padding: '8px', background: '#0b0f19', border: '1px solid var(--panel-border)', borderRadius: '6px', color: 'var(--text)', fontSize: '13px' }}
          />
        </div>
      )}

      <div className="inline-gate-actions" style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
        <button
          className="btn btn-danger btn-sm"
          disabled={submitting}
          onClick={handleReject}
        >
          {showFb ? '↩ Submit Feedback & Re-generate' : '✗ Reject / Request Changes'}
        </button>
        <button
          className="btn btn-success btn-sm"
          disabled={submitting}
          onClick={handleApprove}
        >
          ✓ Approve &amp; Proceed
        </button>
      </div>
    </div>
  );
}
