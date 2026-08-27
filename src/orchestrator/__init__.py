"""ADK Supervisor & State Management package.

Description: Contains the top-level orchestrator that routes tasks across
             specialist sub-agents and manages session state/HITL gates.
Need: A dedicated package separates orchestration concerns from the
      specialist agents themselves.
Motive: Keep routing/control-flow logic isolated and testable.
"""
