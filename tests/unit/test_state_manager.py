from src.models.schemas import RunStatus, GateDecision
from src.orchestrator.state_manager import SessionStateManager


def test_create_run_starts_pending():
    sm = SessionStateManager()
    run = sm.create_run("p1")
    assert run.status == RunStatus.PENDING
    assert sm.get("p1") is run


def test_set_status_and_current():
    sm = SessionStateManager()
    sm.create_run("p1")
    sm.set_current("p1", 3)
    sm.set_status("p1", RunStatus.RUNNING)
    assert sm.get("p1").current_step_id == 3
    assert sm.get("p1").status == RunStatus.RUNNING


def test_record_gate_appends_checkpoint_and_history():
    sm = SessionStateManager()
    sm.create_run("p1")
    sm.record_gate("p1", GateDecision(step_id=2, approved=True), "Gate 1 - Approach")
    run = sm.get("p1")
    assert len(run.gate_checkpoints) == 1
    assert run.gate_checkpoints[0].gate_name == "Gate 1 - Approach"
    assert run.gate_checkpoints[0].approved is True
    assert any(e["event"] == "gate_decision" for e in run.history)


def test_record_error_logged_in_history():
    sm = SessionStateManager()
    sm.create_run("p1")
    sm.record_error("p1", 4, "boom")
    assert any(e["event"] == "error" and e["error"] == "boom" for e in sm.get("p1").history)


def test_to_dict_shape():
    sm = SessionStateManager()
    sm.create_run("p1")
    d = sm.to_dict("p1")
    assert set(d) >= {"pipeline_id", "status", "current_step_id", "history", "gate_checkpoints"}
    assert d["status"] == "PENDING"


def test_checkpoint_roundtrip():
    sm = SessionStateManager()
    sm.save_checkpoint("s1", {"step": 2})
    assert sm.load_checkpoint("s1") == {"step": 2}
