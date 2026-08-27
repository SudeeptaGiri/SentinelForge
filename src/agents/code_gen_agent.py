"""E2E App Code Generation & Refactoring Agent.

Description: Generates full app codebases (Greenfield) or refactors existing
             files (Ongoing Tasks/Migration).
Need: The core value of the system is turning an approved approach/spec into
      real, working code without manual authoring.
Motive: Automate the highest-effort part of the SDLC (writing/refactoring
        code) while producing a reviewable diff for the Gate 2 HITL check.
"""


class CodeGeneratorAgent:
    """Generates or refactors application code based on the approved spec/plan."""

    def refactor_module(self, module_path: str, plan: dict) -> str:
        raise NotImplementedError
