import React, { useState } from 'react';

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
        return 'var(--muted)';
    }
  };

  return (
    <header className="app-header">
      <div className="brand">
        <span className="brand-mark">⚡</span>
        <div>
          <h1>SentinelForge</h1>
          <p>Autonomous AI DevSecOps Agent · Google Cloud Vertex AI</p>
        </div>
      </div>
      <div className="header-actions">
        {activeId && <div className="run-badge">RUN · {activeId.slice(-8)}</div>}
        <div style={{ position: 'relative' }}>
          <button
            className="btn btn-sm"
            style={{ background: '#1c2436', color: 'var(--text)' }}
            onClick={() => setOpen((v) => !v)}
          >
            ⏱️ History ({history.length})
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
                  <div style={{ fontSize: '10px', color: 'var(--muted)' }}>
                    {(r.intent || '').replace(/_/g, ' ')} · {r.repo || ''}
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
