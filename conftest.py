import sys
from unittest.mock import MagicMock

# Properly store attributes so test_infra_agent_adk_wrapping passes
class MockAgent:
    def __init__(self, name, description, model, instruction, tools):
        self.name = name
        self.description = description
        self.model = model
        self.instruction = instruction
        self.tools = tools

sys.modules['google.adk'] = MagicMock()
sys.modules['google.adk.agents'] = MagicMock()
sys.modules['google.adk.agents'].Agent = MockAgent
