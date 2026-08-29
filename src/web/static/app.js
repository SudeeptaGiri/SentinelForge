// SentinelForge live pipeline stepper — SSE client + gate approval UI.
let pipelineId = null;
let eventSource = null;
let pendingGateStepId = null;

const startBtn = document.getElementById("start-btn");
const pipelineIdLabel = document.getElementById("pipeline-id");
const resultBox = document.getElementById("result-box");
const progressFill = document.getElementById("progress-fill");
const progressLabel = document.getElementById("progress-label");

// Gate modal elements
const gateModal = document.getElementById("gate-modal");
const gateTitle = document.getElementById("gate-title");
const gateSummary = document.getElementById("gate-summary");
const gateApproveBtn = document.getElementById("gate-approve");
const gateRejectBtn = document.getElementById("gate-reject");

// Rejection reason modal elements
const rejectModal = document.getElementById("reject-modal");
const rejectGateTitle = document.getElementById("reject-gate-title");
const rejectArtifact = document.getElementById("reject-artifact");
const rejectReason = document.getElementById("reject-reason");
const rejectConfirmBtn = document.getElementById("reject-confirm-btn");
const rejectCancelBtn = document.getElementById("reject-cancel-btn");

// ── Event listeners ───────────────────────────────────────────────────────────
startBtn.addEventListener("click", startPipeline);
gateApproveBtn.addEventListener("click", () => submitGateDecision(true));
gateRejectBtn.addEventListener("click", openRejectModal);
rejectCancelBtn.addEventListener("click", closeRejectModal);
rejectConfirmBtn.addEventListener("click", confirmReject);
rejectReason.addEventListener("input", () => {
  rejectConfirmBtn.disabled = rejectReason.value.trim().length === 0;
});

// ── Pipeline start ────────────────────────────────────────────────────────────
async function startPipeline() {
  startBtn.disabled = true;
  resultBox.classList.add("hidden");
  const res = await fetch("/api/pipeline/start", { method: "POST" });
  const data = await res.json();
  pipelineId = data.pipeline_id;
  pipelineIdLabel.textContent = `Run: ${pipelineId}`;
  attachEventStream(pipelineId);
}

function attachEventStream(id) {
  if (eventSource) eventSource.close();
  eventSource = new EventSource(`/api/pipeline/${id}/events`);
  eventSource.onmessage = (evt) => {
    const state = JSON.parse(evt.data);
    renderState(state);
  };
}

// ── State rendering ───────────────────────────────────────────────────────────
function renderState(state) {
  progressFill.style.width = `${state.pipeline_progress_pct}%`;
  progressLabel.textContent = `${state.pipeline_progress_pct}% complete`;

  state.steps.forEach((step) => {
    const li = document.querySelector(`.step[data-step-id="${step.step_id}"]`);
    const statusEl = document.getElementById(`status-${step.step_id}`);
    const agentEl = document.getElementById(`agent-${step.step_id}`);
    const logEl = document.getElementById(`log-${step.step_id}`);

    li.className = `step status-${step.status.toLowerCase()}`;
    statusEl.textContent = step.status.replace(/_/g, " ");
    agentEl.textContent = step.sub_agent ? `${step.sub_agent}` : "";
    logEl.textContent = step.latest_log || "";

    if (step.status === "WAITING_APPROVAL" && pendingGateStepId !== step.step_id) {
      openGateModal(step);
    }
  });

  fetchAndMaybeShowResult();
}

// ── Gate modal (approval) ─────────────────────────────────────────────────────
function openGateModal(step) {
  pendingGateStepId = step.step_id;
  gateTitle.textContent = `Confirm: ${step.name}`;
  gateSummary.textContent = step.latest_log;
  gateModal.classList.remove("hidden");
}

async function submitGateDecision(approved, feedback = null) {
  if (!pendingGateStepId || !pipelineId) return;
  gateModal.classList.add("hidden");
  await fetch(`/api/pipeline/${pipelineId}/gate/${pendingGateStepId}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approved, feedback }),
  });
  pendingGateStepId = null;
}

// ── Rejection reason modal ────────────────────────────────────────────────────
async function openRejectModal() {
  if (!pendingGateStepId || !pipelineId) return;
  gateModal.classList.add("hidden");

  // Fetch the step artifact from the backend
  let detail = null;
  try {
    const res = await fetch(`/api/pipeline/${pipelineId}/gate/${pendingGateStepId}/detail`);
    if (res.ok) {
      detail = await res.json();
    }
  } catch (_) {
    // Fallback: show the summary text already in the modal
  }

  rejectGateTitle.textContent = detail
    ? `Gate: ${detail.gate_name}`
    : gateTitle.textContent;

  rejectArtifact.textContent = detail && detail.artifact && Object.keys(detail.artifact).length
    ? JSON.stringify(detail.artifact, null, 2)
    : (detail && detail.summary) || gateSummary.textContent || "(no artifact details available)";

  // Reset form
  rejectReason.value = "";
  rejectConfirmBtn.disabled = true;
  rejectModal.classList.remove("hidden");
  rejectReason.focus();
}

function closeRejectModal() {
  rejectModal.classList.add("hidden");
  rejectReason.value = "";
  rejectConfirmBtn.disabled = true;
  // Restore the gate modal so the user can reconsider
  gateModal.classList.remove("hidden");
}

async function confirmReject() {
  const reason = rejectReason.value.trim();
  if (!reason) return;
  rejectModal.classList.add("hidden");
  rejectReason.value = "";
  rejectConfirmBtn.disabled = true;
  await submitGateDecision(false, reason);
}

// ── Result polling ────────────────────────────────────────────────────────────
async function fetchAndMaybeShowResult() {
  if (!pipelineId) return;
  const res = await fetch(`/api/pipeline/${pipelineId}/state`);
  const data = await res.json();
  if (data.result || data.error) {
    resultBox.classList.remove("hidden");
    resultBox.textContent = data.error
      ? `ERROR: ${data.error}`
      : JSON.stringify(data.result, null, 2);
    startBtn.disabled = false;
  }
}
