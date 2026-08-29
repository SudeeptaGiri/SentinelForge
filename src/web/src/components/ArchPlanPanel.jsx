import React from 'react';

export default function ArchPlanPanel({ steps, specData }) {
  const done = (id) => steps.find((s) => s.step_id === id && s.status === 'COMPLETED');
  const s1 = done(1), s2 = done(2), s3 = done(3), s4 = done(4), s5 = done(5), s6 = done(6);

  if (!s1) {
    return (
      <div className="arch-plan-panel panel-box">
        <h3>Architecture Modernization Plan</h3>
        <p className="muted">Pipeline will populate plan live as steps execute…</p>
      </div>
    );
  }

  return (
    <div className="arch-plan-panel panel-box">
      <h3>Architecture Modernization Plan</h3>

      {s1 && (
        <div className="plan-section">
          <div className="plan-section-title">🔍 Codebase Analysis &amp; Sizing</div>
          <p>{s1.latest_log || 'Codebase AST parsed, dependencies identified, resource profile evaluated.'}</p>
        </div>
      )}

      {s2 && (
        <div className="plan-section">
          <div className="plan-section-title">📐 Architecture &amp; Approach Proposal</div>
          <p>{s2.latest_log || 'Target architecture proposed: Cloud Run Serverless with GCS and Cloud SQL.'}</p>
          {specData && (
            <div className="spec-plan-block" style={{ marginTop: '12px', background: '#0b0f19', padding: '12px', borderRadius: '8px', border: '1px solid var(--panel-border)' }}>
              <div className="plan-section-title" style={{ color: 'var(--accent)', fontSize: '13px' }}>
                📋 Target API Contract (SpecAgent · OpenAPI 3.1)
              </div>
              <p style={{ margin: '4px 0 8px', fontSize: '13px' }}>
                <strong>{specData.title}</strong>
                {specData.summary ? ` — ${specData.summary}` : ''}
              </p>
              {specData.endpoints?.length > 0 && (
                <table className="plan-table" style={{ width: '100%', fontSize: '12px', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--panel-border)', textAlign: 'left' }}>
                      <th style={{ padding: '4px 8px' }}>Method</th>
                      <th style={{ padding: '4px 8px' }}>Path</th>
                      <th style={{ padding: '4px 8px' }}>Summary</th>
                    </tr>
                  </thead>
                  <tbody>
                    {specData.endpoints.map((e, i) => (
                      <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                        <td style={{ padding: '4px 8px', fontWeight: 'bold', color: e.method === 'GET' ? 'var(--success)' : 'var(--accent)' }}>
                          {e.method || 'GET'}
                        </td>
                        <td style={{ padding: '4px 8px' }}>
                          <code>{e.path || e}</code>
                        </td>
                        <td style={{ padding: '4px 8px', color: 'var(--muted)' }}>{e.summary || ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {specData.data_models?.length > 0 && (
                <p style={{ marginTop: '8px', fontSize: '12px' }}>
                  <strong>Schemas: </strong>
                  {specData.data_models.map((m) => (
                    <span key={m.name || m} className="dep-tag" style={{ marginRight: '4px' }}>
                      {m.name || m}
                    </span>
                  ))}
                </p>
              )}
              {specData.workload_spec?.cpu_cores && (
                <p style={{ fontSize: '11px', color: 'var(--muted)', marginTop: '8px' }}>
                  Target Sizing: {specData.workload_spec.cpu_cores} vCPU &middot; {specData.workload_spec.ram_gb} GB RAM &middot;{' '}
                  {(specData.workload_spec.monthly_requests || 0).toLocaleString()} req/mo &middot; Stateful:{' '}
                  {specData.workload_spec.is_stateful ? 'Yes' : 'No'}
                </p>
              )}
            </div>
          )}
        </div>
      )}

      {s3 && (
        <div className="plan-section">
          <div className="plan-section-title">⚙️ Application Code Generation &amp; Self-Healing</div>
          <p>{s3.latest_log || 'Application refactored for containerized runtime. Added health checks and tests.'}</p>
        </div>
      )}

      {s4 && (
        <div className="plan-section">
          <div className="plan-section-title">🏗️ Infrastructure &amp; Cost Optimization</div>
          <p>{s4.latest_log || 'Terraform HCL generated (main.tf), Cloud Build specs prepared, monthly savings evaluated.'}</p>
        </div>
      )}

      {s5 && (
        <div className="plan-section">
          <div className="plan-section-title">🔒 Security Pentest &amp; DAST Audit (Strix)</div>
          <p>{s5.latest_log || 'Security audit passed. Zero critical vulnerabilities detected.'}</p>
        </div>
      )}

      {s6 && (
        <div className="plan-section">
          <div className="plan-section-title">🚀 Cloud Build CI/CD &amp; Deployment</div>
          <p>{s6.latest_log || 'Workload deployed successfully to GCP staging environment.'}</p>
        </div>
      )}
    </div>
  );
}
