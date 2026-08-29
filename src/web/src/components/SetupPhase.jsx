import React, { useState } from 'react';
import { IconCloud, IconZap, IconSparkle, IconBlueprint } from './Icons';

const INTENTS = [
  { value: 'migrate_cloud', Icon: IconCloud, label: 'Migrate to Cloud', desc: 'Optimize legacy GCE VM to serverless Cloud Run' },
  { value: 'migrate_modern', Icon: IconZap, label: 'Modernise Stack', desc: 'Refactor monolith into microservices & containers' },
  { value: 'new_feature', Icon: IconSparkle, label: 'Add New Feature', desc: 'Implement new REST endpoint with self-healing tests' },
  { value: 'from_scratch', Icon: IconBlueprint, label: 'Build From Scratch', desc: 'Contract-first OpenAPI generation with SpecAgent' },
];

export default function SetupPhase({ onStart, loading }) {
  const [repo, setRepo] = useState('fixtures/sample_legacy_app');
  const [name, setName] = useState('legacy-app');
  const [intent, setIntent] = useState('migrate_cloud');

  return (
    <section className="phase-card">
      <h2 className="phase-title">
        <span className="phase-num">1</span> Configure Your Project &amp; Workload
      </h2>
      <div className="setup-form">
        <div className="form-group">
          <label>Repository Path or Remote Git URL</label>
          <div style={{ display: 'flex', gap: '8px' }}>
            <input
              type="text"
              value={repo}
              onChange={(e) => setRepo(e.target.value)}
              placeholder="fixtures/sample_legacy_app  or  https://github.com/org/repo"
              style={{ flex: 1 }}
            />
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => {
                setRepo('fixtures/sample_legacy_app');
                setName('legacy-flask-app');
              }}
            >
              Load Sample Fixture
            </button>
          </div>
        </div>

        <div className="form-group">
          <label>Application Service Name</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="my-service"
          />
        </div>

        <div className="form-group">
          <label>What do you want to accomplish?</label>
          <div className="intent-grid">
            {INTENTS.map((i) => (
              <label
                key={i.value}
                className={`intent-card${intent === i.value ? ' selected' : ''}`}
                onClick={() => setIntent(i.value)}
              >
                <span className="intent-icon"><i.Icon size={18} /></span>
                <span className="intent-label">{i.label}</span>
                <span style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '2px' }}>{i.desc}</span>
              </label>
            ))}
          </div>
        </div>

        <button
          className="btn btn-primary btn-lg"
          disabled={loading || !repo.trim()}
          onClick={() => onStart({ repo, name, intent })}
          style={{ marginTop: 'var(--space-1)' }}
        >
          {loading ? 'Initiating DevSecOps Supervisor…' : 'Analyse Codebase & Build Migration Plan'}
        </button>
      </div>
    </section>
  );
}
