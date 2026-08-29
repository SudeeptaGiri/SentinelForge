import React, { useState, useEffect } from 'react';
import { IconTool } from './Icons';

/**
 * Editable file review panel for CodeGeneratorAgent output.
 * Lets the reviewer tweak proposed file contents in-browser before approving —
 * edits are collected by the parent and sent with the gate decision.
 */
export default function FileEditor({ files, edits, onEdit }) {
  const paths = Object.keys(files || {});
  const [active, setActive] = useState(paths[0] || null);

  useEffect(() => {
    if (!active && paths.length) setActive(paths[0]);
  }, [paths, active]);

  if (!paths.length) return null;

  const content = edits?.[active] ?? files[active] ?? '';
  const isEdited = active in (edits || {});

  return (
    <div className="file-editor">
      <div className="file-tabs">
        {paths.map((p) => (
          <button
            key={p}
            type="button"
            className={`file-tab${p === active ? ' active' : ''}${p in (edits || {}) ? ' edited' : ''}`}
            onClick={() => setActive(p)}
          >
            <IconTool size={12} />
            <span>{p}</span>
            {p in (edits || {}) && <span className="file-tab-dot" title="Edited" />}
          </button>
        ))}
      </div>
      <textarea
        className="file-editor-textarea"
        value={content}
        onChange={(e) => onEdit(active, e.target.value)}
        spellCheck={false}
        rows={14}
      />
      {isEdited && <p className="file-editor-hint">Edited — will be applied when you approve this step.</p>}
    </div>
  );
}
