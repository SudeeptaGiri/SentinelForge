import React from 'react';
import VisGraph from './VisGraph';

export default function AnalysisPhase({ analysis: a, graph }) {
  if (!a) return null;

  const gs = a.graph_summary || {};
  const cards = [
    ['Detected Platform', a.detected_platform],
    ['Web Framework', a.framework],
    ['Architecture Style', a.architecture_type],
    ['Dockerfile Found', a.has_dockerfile ? 'Yes ✓' : 'No'],
    ['Autoscaling Found', a.has_autoscaling ? 'Yes ✓' : 'No (Cost Risk)'],
    ['Total Files Analyzed', gs.total_files ?? a.files_of_interest?.length ?? '—'],
  ];

  return (
    <section className="phase-card">
      <h2 className="phase-title">
        <span className="phase-num">2</span> Codebase Analysis &amp; GraphRAG Knowledge Engine
      </h2>
      <div className="analysis-grid">
        <div className="analysis-left">
          <div className="info-cards">
            {cards.map(([l, v]) => (
              <div key={l} className="info-card">
                <div className="card-label">{l}</div>
                <div className="card-value">{v || '—'}</div>
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
              {(a.endpoints || []).length ? (
                a.endpoints.map((e, i) => (
                  <li key={i}>
                    {typeof e === 'string' ? e : `${e.method || ''} ${e.path || e}`}
                  </li>
                ))
              ) : (
                <li className="muted">No routes detected</li>
              )}
            </ul>
          </div>

          <div className="panel-box">
            <h3>Key Package Dependencies</h3>
            <div className="tag-cloud">
              {(a.dependencies || []).map((d) => (
                <span key={d} className="dep-tag">
                  {d}
                </span>
              ))}
            </div>
          </div>

          <div className="panel-box">
            <h3>Modernization Recommendations</h3>
            <ul className="rec-list">
              {(a.recommendations || []).map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          </div>
        </div>

        <div className="analysis-right">
          <div className="panel-box graph-box">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
              <h3>Code Knowledge Graph</h3>
              <span className="badge-muted" style={{ fontSize: '11px', background: '#1c2436', padding: '3px 8px', borderRadius: '4px' }}>
                GraphRAG · AST Index
              </span>
            </div>
            <VisGraph nodes={graph?.nodes || []} edges={graph?.edges || []} />
            <div className="graph-legend">
              <span className="legend-dot file"></span> File
              <span className="legend-dot route"></span> REST Route
              <span className="legend-dot dep"></span> Dependency
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
