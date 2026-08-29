import React, { useState, useEffect, useRef, useCallback } from 'react';
import ArchPlanPanel from './ArchPlanPanel';
import StepRow from './StepRow';

export default function PipelinePhase({ steps, specData, planData, codegenData, fileEdits, onFileEdit, onApprove, onReject, onAbort, result, error }) {
  const [leftWidth, setLeftWidth] = useState(45);
  const [isDragging, setIsDragging] = useState(false);
  const containerRef = useRef(null);

  const handleMouseDown = useCallback((e) => {
    setIsDragging(true);
    e.preventDefault();
  }, []);

  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e) => {
      if (!containerRef.current) return;
      const container = containerRef.current;
      const rect = container.getBoundingClientRect();
      const newWidth = ((e.clientX - rect.left) / rect.width) * 100;
      if (newWidth >= 30 && newWidth <= 70) {
        setLeftWidth(newWidth);
      }
    };

    const handleMouseUp = () => {
      setIsDragging(false);
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging]);

  const done = steps.filter((s) => s.status === 'COMPLETED').length;
  const pct = steps.length ? Math.round((done / steps.length) * 100) : 0;

  return (
    <section className="phase-card">
      <h2 className="phase-title">
        <span className="phase-num">3</span> Live Pipeline Execution &amp; HITL Gates
      </h2>
      <div className="pipeline-container" ref={containerRef}>
        <div className="pipeline-left" style={{ flex: `0 0 ${leftWidth}%` }}>
          <ArchPlanPanel
            steps={steps}
            specData={specData}
            planData={planData}
            codegenData={codegenData}
            fileEdits={fileEdits}
            onFileEdit={onFileEdit}
          />
        </div>
        <div className="pipeline-splitter" onMouseDown={handleMouseDown}>
          <div className="splitter-handle"></div>
        </div>
        <div className="pipeline-right" style={{ flex: 1 }}>
          <div className="stepper-panel">
            <div className="stepper-header">
              <h3>Pipeline Progress</h3>
              <div className="progress-info">
                <span className="progress-text">{done} of {steps.length} completed</span>
                <span className="progress-percent">{pct}%</span>
              </div>
              <div className="progress-track">
                <div className="progress-fill" style={{ width: `${pct}%` }} />
              </div>
            </div>

            <ol className="stepper">
              {steps.map((s) => (
                <StepRow
                  key={s.step_id}
                  step={s}
                  onApprove={onApprove}
                  onReject={onReject}
                  onAbort={onAbort}
                />
              ))}
            </ol>

            {(result || error) && (
              <div className={`result-box ${error ? 'error' : 'success'}`}>
                <h4>{error ? '❌ Pipeline Failed' : '✅ Pipeline Completed'}</h4>
                <pre>{error ? String(error) : JSON.stringify(result, null, 2)}</pre>
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
