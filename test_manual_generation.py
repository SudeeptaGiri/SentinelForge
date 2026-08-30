import sys
from unittest.mock import MagicMock

# Mock google.adk before importing InfraBuilderAgent
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

from src.agents.infra_agent import InfraBuilderAgent

def manual_test():
    print("🚀 Initializing InfraBuilderAgent...")
    agent = InfraBuilderAgent()

    # Sample resource spec for a Hello World application
    resource_spec = {
        "service_name": "hello-world-app",
        "target_platform": "cloud_run",
        "region": "us-central1",
        "cpu": "1",
        "memory": "512Mi",
        "image_uri": "gcr.io/my-demo-project/hello-world-app:latest"
    }

    print("\n--- 1. Generating Terraform HCL for Cloud Run ---")
    try:
        terraform_hcl = agent.render_terraform(resource_spec)
        print("\n[SUCCESS] Generated Terraform HCL:")
        print(terraform_hcl)
    except Exception as e:
        print(f"\n[ERROR] Terraform generation failed: {e}")

    print("\n--- 2. Generating CI/CD Pipeline (cloudbuild.yaml) ---")
    try:
        cicd_yaml = agent.render_cicd_pipeline(resource_spec)
        print("\n[SUCCESS] Generated Cloud Build YAML:")
        print(cicd_yaml)
    except Exception as e:
        print(f"\n[ERROR] CI/CD pipeline generation failed: {e}")

if __name__ == "__main__":
    manual_test()
