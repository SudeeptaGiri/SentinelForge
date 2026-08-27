"""Confirmation Gate checkpoint payload schemas.

Description: Pydantic schemas for the payloads sent to/from the HITL Gate
             Controller at each of the 5 confirmation gates.
Need: Each gate (Approach, Code Review, Cost & Infra, Security, Sign-off)
      needs a well-defined, validated payload shape for the UI to render.
Motive: Prevent malformed or incomplete gate requests from silently
        bypassing human review.
"""

from pydantic import BaseModel


class GateCheckpoint(BaseModel):
    gate_name: str
    session_id: str
    payload: dict
    approved: bool | None = None
