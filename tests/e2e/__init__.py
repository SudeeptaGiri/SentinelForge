"""Full pipeline end-to-end integration tests.

Description: Exercises the complete Idea -> Deploy pipeline (all 5 HITL
             gates) against a staging sandbox.
Need: The individual agents can each work correctly yet still fail when
      chained together through the supervisor's control flow.
Motive: Provide confidence that the entire orchestrated pipeline, including
        self-healing and security gating, behaves correctly end-to-end.
"""
