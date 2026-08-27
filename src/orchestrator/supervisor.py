"""Main ADK Supervisor Agent (routes tasks & manages context).

Description: Primary ADK Supervisor Agent; evaluates user intent (idea, ticket,
             or repo link) and routes tasks across the 7 specialist sub-agents
             (spec, analysis, code_gen, cost, infra, qa, pentest).
Need: Without a central router, sub-agents would need to know about each other
      directly, creating tight coupling and unpredictable execution order.
Motive: Provide one place that owns the end-to-end control flow described in
        the architecture's Data & Control Flow diagram, delegating each step
        to the correct specialist agent and pausing at HITL gates.
"""


class DevSecOpsSupervisor:
    """Routes tasks across specialist sub-agents and enforces HITL gates."""

    def route(self, user_input: str) -> None:
        raise NotImplementedError
