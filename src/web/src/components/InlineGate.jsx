import React, { useState } from 'react';
import { IconShield, IconX, IconCheck, IconRefresh } from './Icons';

export default function InlineGate({ step, onApprove, onReject, onAbort }) {
  const [feedback, setFeedback] = useState('');
  const [showFeedback, setShowFeedback] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  async function handleApprove() {
    setSubmitting(true);
    try {
      await onApprove(step.step_id);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRegenerate() {
    if (!showFeedback) {
      setShowFeedback(true);
      return;
    }
    if (!feedback.trim()) {
      alert('Please provide feedback for regeneration');
      return;
    }
    setSubmitting(true);
    try {
      await onReject(step.step_id, feedback);
      setFeedback('');
      setShowFeedback(false);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleAbort() {
    if (confirm('Are you sure you want to abort the entire pipeline?')) {
      setSubmitting(true);
      try {
        await onAbort?.();
      } finally {
        setSubmitting(false);
      }
    }
  }

  return (
    <div className="inline-gate">
      <div className="gate-header">
        <span className="gate-badge"><IconShield size={12} /> Approval Required</span>
        <p className="gate-message">
          {step.latest_log || 'Please review the generated artifact and choose an action below.'}
        </p>
      </div>

      {showFeedback && (
        <div className="gate-feedback">
          <label>Provide feedback for regeneration:</label>
          <textarea
            rows={3}
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            placeholder="Explain what needs to be changed (e.g., 'Add Redis for caching', 'Use PostgreSQL instead of MySQL', 'Increase memory allocation to 4GB')"
            disabled={submitting}
          />
        </div>
      )}

      <div className="gate-actions">
        <button
          className="btn btn-ghost btn-abort"
          onClick={handleAbort}
          disabled={submitting}
          title="Abort entire pipeline"
        >
          <IconX size={14} className="btn-icon" />
          <span>Abort Pipeline</span>
        </button>

        <div className="gate-actions-primary">
          <button
            className="btn btn-secondary btn-regenerate"
            onClick={handleRegenerate}
            disabled={submitting}
          >
            <IconRefresh size={14} className="btn-icon" />
            <span>{showFeedback ? 'Submit & Regenerate' : 'Request Changes'}</span>
          </button>

          <button
            className="btn btn-primary btn-approve"
            onClick={handleApprove}
            disabled={submitting}
          >
            <IconCheck size={14} className="btn-icon" />
            <span>Approve & Proceed</span>
          </button>
        </div>
      </div>
    </div>
  );
}
