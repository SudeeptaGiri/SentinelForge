import React, { useState } from 'react';
import { IconBolt, IconClock } from './Icons';

export default function Header({ history, activeId, onSelect, onNewRun }) {
  const [open, setOpen] = useState(false);

  const statusColor = (s) => {
    switch (s) {
      case 'COMPLETED':
      case 'DEPLOYED':
        return 'var(--success)';
      case 'FAILED':
      case 'ERROR':
      case 'REJECTED':
      case 'ABORTED':
        return 'var(--danger)';
      case 'RUNNING':
      case 'IN_PROGRESS':
        return 'var(--warning)';
      default:
        return 'var(--text-tertiary)';
    }
  };

  return (
    <header className="app-header">
      <div className="brand">
        <span className="brand-mark"><IconBolt size={16} /></span>
        <div>
          <h1>SentinelForge</h1>
          <p>Autonomous AI DevSecOps Agent &middot; Google Cloud Vertex AI</p>
        </div>
      </div>
      <div className="header-actions">
        {activeId && <div className="run-badge">RUN &middot; {activeId.slice(-8)}</div>}
        <div style={{ position: 'relative' }}>
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => setOpen((v) => !v)}
          >
            <IconClock size={14} /> History ({history.length})
          </button>
          {open && (
            <div className="history-panel">
              <div className="history-header">
                <span>Previous Runs</span>
                <button
                  className="btn btn-sm btn-primary"
                  onClick={() => {
                    setOpen(false);
                    onNewRun();
                  }}
                >
                  + New Run
                </button>
              </div>
              {history.length === 0 && (
                <p className="muted" style={{ padding: '12px 16px' }}>
                  No previous runs yet.
                </p>
              )}
              {history.map((r) => (
                <div
                  key={r.id}
                  className={`history-item${r.id === activeId ? ' active' : ''}`}
                  onClick={() => {
                    setOpen(false);
                    onSelect(r);
                  }}
                >
                  <div className="history-name">{r.name || r.id.slice(-8)}</div>
                  <div style={{ fontSize: '10px', color: 'var(--text-tertiary)' }}>
                    {(r.intent || '').replace(/_/g, ' ')} &middot; {r.repo || ''}
                  </div>
                  {r.status && (
                    <div style={{ fontSize: '10px', fontWeight: 700, color: statusColor(r.status) }}>
                      {r.status}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
