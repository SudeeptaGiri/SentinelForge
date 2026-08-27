"""ADK Specialist Sub-Agents package.

Description: Contains the 7 specialist agents (spec, analysis, code_gen,
             cost, infra, qa, pentest) that the supervisor delegates to.
Need: Each DevSecOps concern (spec alignment, analysis, codegen, cost,
      infra, QA, security) needs an isolated, independently testable agent.
Motive: Enforce single-responsibility per agent so behavior/prompts for one
        concern can evolve without affecting the others.
"""
