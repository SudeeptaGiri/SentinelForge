"""Vertex Agent Engine session state & conversation history.

Description: Manages conversation memory, session checkpoints, and state
             persistence on Vertex AI Agent Engine.
Need: Long-running, multi-step agent workflows (spanning analysis, code-gen,
      cost, infra, QA, and security stages) must survive process restarts and
      resume from the last approved checkpoint.
Motive: Provide a single abstraction over Agent Engine's managed state so
        other components never touch storage/session APIs directly.
"""


class SessionStateManager:
    """Persists and retrieves agent session state and checkpoints."""

    def save_checkpoint(self, session_id: str, payload: dict) -> None:
        raise NotImplementedError

    def load_checkpoint(self, session_id: str) -> dict:
        raise NotImplementedError
