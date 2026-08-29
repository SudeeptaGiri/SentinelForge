import asyncio
import builtins

import pytest

from src.models.schemas import GateDecision, GateRequest
from src.orchestrator.hitl_gate import (
    ApprovalChannel, AsyncHITLGateController, HITLGateController,
    ScriptedApprovalChannel, TerminalApprovalChannel, WebApprovalChannel,
)
from src.orchestrator.state_manager import SessionStateManager


def _req():
    return GateRequest(step_id=2, gate_name="Gate 1 - Approach", summary="do it")


def test_terminal_channel_yes_approves(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda *_: "y")
    d = TerminalApprovalChannel().request_approval(_req())
    assert d.approved is True and d.step_id == 2


def test_terminal_channel_text_rejects_with_feedback(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda *_: "add a healthz route")
    d = TerminalApprovalChannel().request_approval(_req())
    assert d.approved is False
    assert d.feedback == "add a healthz route"


def test_scripted_channel_pops_in_order():
    ch = ScriptedApprovalChannel([
        GateDecision(step_id=2, approved=False, feedback="fix"),
        GateDecision(step_id=2, approved=True),
    ])
    assert ch.request_approval(_req()).approved is False
    assert ch.request_approval(_req()).approved is True
    with pytest.raises(RuntimeError):
        ch.request_approval(_req())


def test_web_channel_is_stub():
    with pytest.raises(NotImplementedError):
        WebApprovalChannel().request_approval(_req())


def test_controller_records_gate_on_state():
    sm = SessionStateManager()
    sm.create_run("p1")
    ctrl = HITLGateController(ScriptedApprovalChannel([GateDecision(step_id=2, approved=True)]), sm)
    d = ctrl.request_gate_approval("p1", _req())
    assert d.approved is True
    assert sm.get("p1").gate_checkpoints[0].gate_name == "Gate 1 - Approach"


def test_terminal_channel_empty_input_rejects(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda *_: "")
    d = TerminalApprovalChannel().request_approval(_req())
    assert d.approved is False
    assert d.feedback == "rejected"


def test_terminal_channel_uppercase_yes_approves(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda *_: "YES")
    d = TerminalApprovalChannel().request_approval(_req())
    assert d.approved is True


def test_channel_is_abstract():
    assert issubclass(TerminalApprovalChannel, ApprovalChannel)


def _run(coro):
    return asyncio.run(coro)


def test_async_gate_stores_artifact():
    ctrl = AsyncHITLGateController()
    artifact = {"platform": "CloudRun", "savings_usd": 434.0}

    async def _scenario():
        task = asyncio.create_task(
            ctrl.request_gate_approval(2, "Approach", "summary text", artifact=artifact)
        )
        await asyncio.sleep(0)  # let the gate register
        ctrl.submit_decision(2, approved=True)
        return await task

    _run(_scenario())
    detail = ctrl.get_gate_detail(2)
    assert detail is not None
    assert detail["artifact"] == artifact
    assert detail["gate_name"] == "Approach"
    assert detail["summary"] == "summary text"


def test_async_gate_detail_returns_none_for_unknown_step():
    ctrl = AsyncHITLGateController()
    assert ctrl.get_gate_detail(99) is None


def test_async_gate_detail_returns_latest_on_retry():
    ctrl = AsyncHITLGateController()
    first_artifact = {"attempt": 1}
    second_artifact = {"attempt": 2}

    async def _scenario():
        # First gate request
        task1 = asyncio.create_task(
            ctrl.request_gate_approval(2, "Approach", "first", artifact=first_artifact)
        )
        await asyncio.sleep(0)
        ctrl.submit_decision(2, approved=False, feedback="redo it")
        await task1

        # Second gate request (retry)
        task2 = asyncio.create_task(
            ctrl.request_gate_approval(2, "Approach", "second", artifact=second_artifact)
        )
        await asyncio.sleep(0)
        ctrl.submit_decision(2, approved=True)
        await task2

    _run(_scenario())
    detail = ctrl.get_gate_detail(2)
    assert detail["artifact"] == second_artifact  # latest wins
