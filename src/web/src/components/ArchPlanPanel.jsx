import React from 'react';
import { IconSearch, IconBlueprint, IconSettings, IconLayers, IconShield, IconRocket } from './Icons';
import FileEditor from './FileEditor';

export default function ArchPlanPanel({ steps, specData, planData, codegenData, fileEdits, onFileEdit }) {
  const done = (id) => steps.find((s) => s.step_id === id && s.status === 'COMPLETED');
  const s1 = done(1);
  // Show proposal/codegen sections as soon as they're awaiting approval, not only once
  // approved — so the human can review (and, for codegen, edit files) before deciding.
  const s2 = steps.find((s) => s.step_id === 2 && ['WAITING_APPROVAL', 'COMPLETED'].includes(s.status));
  const s3 = steps.find((s) => s.step_id === 3 && ['WAITING_APPROVAL', 'COMPLETED'].includes(s.status));
  const s4 = done(4), s5 = done(5), s6 = done(6);

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
          <div className="plan-section-title"><IconSearch size={13} /> Codebase Analysis &amp; Sizing</div>
          <p>{s1.latest_log || 'Codebase AST parsed, dependencies identified, resource profile evaluated.'}</p>
        </div>
      )}

      {s2 && (
        <div className="plan-section">
          <div className="plan-section-title"><IconBlueprint size={13} /> Architecture &amp; Approach Proposal</div>
          <p>{s2.latest_log || 'Target architecture proposed: Cloud Run Serverless with GCS and Cloud SQL.'}</p>

          {planData && (
            <div className="spec-plan-block">
              <div className="plan-section-title" style={{ fontSize: '13px' }}>Cost Comparison</div>
              <div className="plan-table-wrap">
                <table className="plan-table">
                  <thead>
                    <tr>
                      <th>Platform</th>
                      <th>Monthly Cost</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td>{planData.baseline?.platform}</td>
                      <td>${planData.baseline?.monthly_cost_usd?.toFixed(2)}</td>
                    </tr>
                    <tr>
                      <td style={{ fontWeight: 600, color: 'var(--accent)' }}>{planData.target?.platform}</td>
                      <td style={{ fontWeight: 600, color: 'var(--success)' }}>${planData.target?.monthly_cost_usd?.toFixed(2)}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <p style={{ marginTop: '8px', fontSize: '13px' }}>
                <strong style={{ color: 'var(--success)' }}>
                  Save ${planData.monthly_savings_usd?.toFixed(2)}/mo ({planData.savings_pct}%)
                </strong>
              </p>
              <p style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '4px' }}>{planData.rationale}</p>
            </div>
          )}

          {specData && (
            <div className="spec-plan-block">
              <div className="plan-section-title" style={{ fontSize: '13px' }}>
                Target API Contract (SpecAgent &middot; OpenAPI 3.1)
              </div>
              <p style={{ margin: '4px 0 8px', fontSize: '13px' }}>
                <strong>{specData.title}</strong>
                {specData.summary ? ` — ${specData.summary}` : ''}
              </p>
              {specData.endpoints?.length > 0 && (
                <div className="plan-table-wrap">
                  <table className="plan-table">
                    <colgroup>
                      <col style={{ width: '54px' }} />
                      <col style={{ width: '38%' }} />
                      <col />
                    </colgroup>
                    <thead>
                      <tr>
                        <th>Method</th>
                        <th>Path</th>
                        <th>Summary</th>
                      </tr>
                    </thead>
                    <tbody>
                      {specData.endpoints.map((e, i) => (
                        <tr key={i}>
                          <td style={{ fontWeight: 600, color: e.method === 'GET' ? 'var(--success)' : 'var(--accent)' }}>
                            {e.method || 'GET'}
                          </td>
                          <td>
                            <code>{e.path || e}</code>
                          </td>
                          <td style={{ color: 'var(--text-tertiary)' }}>{e.summary || ''}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {specData.data_models?.length > 0 && (
                <div style={{ marginTop: '8px' }}>
                  <p style={{ fontSize: '12px', marginBottom: '6px' }}><strong>Schemas</strong></p>
                  <div className="tag-cloud">
                    {specData.data_models.map((m) => (
                      <span key={m.name || m} className="dep-tag">
                        {m.name || m}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              {specData.workload_spec?.cpu_cores && (
                <p style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '8px' }}>
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
          <div className="plan-section-title"><IconSettings size={13} /> Application Code Generation &amp; Self-Healing</div>
          <p>{s3.latest_log || 'Application refactored for containerized runtime. Added health checks and tests.'}</p>
          {codegenData?.file_contents && Object.keys(codegenData.file_contents).length > 0 && (
            <FileEditor files={codegenData.file_contents} edits={fileEdits} onEdit={onFileEdit} />
          )}
        </div>
      )}

      {s4 && (
        <div className="plan-section">
          <div className="plan-section-title"><IconLayers size={13} /> Infrastructure &amp; Cost Optimization</div>
          <p>{s4.latest_log || 'Terraform HCL generated (main.tf), Cloud Build specs prepared, monthly savings evaluated.'}</p>
        </div>
      )}

      {s5 && (
        <div className="plan-section">
          <div className="plan-section-title"><IconShield size={13} /> Security Pentest &amp; DAST Audit (Strix)</div>
          <p>{s5.latest_log || 'Security audit passed. Zero critical vulnerabilities detected.'}</p>
        </div>
      )}

      {s6 && (
        <div className="plan-section">
          <div className="plan-section-title"><IconRocket size={13} /> Cloud Build CI/CD &amp; Deployment</div>
          <p>{s6.latest_log || 'Workload deployed successfully to GCP staging environment.'}</p>
        </div>
      )}
    </div>
  );
}

