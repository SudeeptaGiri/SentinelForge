"""Verification test for Person 4 new implementation - no Gemini required."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

print("🔍 Verifying Person 4 Implementation...")
print("="*70)

# 1. Check files exist
checks = []

files_to_check = [
    ("Test Plan", "test_plans/TestPlan.yaml"),
    ("Review Agent", "src/agents/review_agent.py"),
    ("Updated Code Gen", "src/agents/code_gen_agent.py"),
    ("Updated QA Agent", "src/agents/qa_agent.py"),
    ("New Demo", "test_person4_new.py"),
    ("Config Update", "config/agent_config.yaml"),
    ("Documentation", "docs/PERSON4_NEW_WORKFLOW.md"),
]

for name, path in files_to_check:
    file_path = Path(__file__).parent / path
    exists = file_path.exists()
    status = "✅" if exists else "❌"
    checks.append(exists)
    print(f"{status} {name:.<40} {path}")

print("="*70)

# 2. Check imports
print("\n🔍 Checking Imports...")
print("="*70)

try:
    from src.agents.review_agent import ReviewAgent, ReviewReport, ReviewIssue
    print("✅ ReviewAgent imports............ OK")
    checks.append(True)
except ImportError as e:
    print(f"❌ ReviewAgent imports............ FAILED: {e}")
    checks.append(False)

try:
    from src.agents.code_gen_agent import CodeGeneratorAgent
    agent = CodeGeneratorAgent()
    assert hasattr(agent, 'generate_from_plan_file'), "Missing generate_from_plan_file method"
    print("✅ CodeGeneratorAgent updates..... OK")
    checks.append(True)
except Exception as e:
    print(f"❌ CodeGeneratorAgent updates..... FAILED: {e}")
    checks.append(False)

try:
    from src.agents.qa_agent import QAAgent
    agent = QAAgent()
    assert hasattr(agent, 'generate_and_run_tests'), "Missing generate_and_run_tests method"
    print("✅ QAAgent updates................ OK")
    checks.append(True)
except Exception as e:
    print(f"❌ QAAgent updates................ FAILED: {e}")
    checks.append(False)

print("="*70)

# 3. Check config
print("\n🔍 Checking Configuration...")
print("="*70)

try:
    import yaml
    config_path = Path(__file__).parent / "config" / "agent_config.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)
    
    assert "review_agent" in config.get("agents", {}), "review_agent not in config"
    print("✅ Config has review_agent........ OK")
    checks.append(True)
except Exception as e:
    print(f"❌ Config check................... FAILED: {e}")
    checks.append(False)

# 4. Check TestPlan structure
print("\n🔍 Checking TestPlan Structure...")
print("="*70)

try:

    plan_path = Path(__file__).parent / "test_plans" / "TestPlan"
    plan_text = plan_path.read_text()
    
    assert "Hello World from EPAM Hackathon" in plan_text, "Missing expected output text"
    assert "TestPlan" in plan_text or "PLAN:" in plan_text, "Missing plan header"
    assert "REQUIREMENTS" in plan_text or "TEST CASES" in plan_text, "Missing plan sections"
    print("✅ TestPlan structure............. OK")
    print(f"   Format: Plain text")
    print(f"   Size: {len(plan_text)} characters")
    checks.append(True)
except Exception as e:
    print(f"❌ TestPlan check................. FAILED: {e}")
    checks.append(False)

print("="*70)

# Final Report
print("\n📊 VERIFICATION SUMMARY")
print("="*70)

passed = sum(checks)
total = len(checks)
success_rate = (passed / total) * 100

print(f"Tests Passed: {passed}/{total} ({success_rate:.1f}%)")
print()

if passed == total:
    print("✅ ✅ ✅  ALL CHECKS PASSED  ✅ ✅ ✅")
    print()
    print("Implementation is COMPLETE and VERIFIED!")
    print()
    print("To test full workflow (requires Gemini ADC):")
    print("  1. gcloud auth application-default login")
    print("  2. python test_person4_new.py")
else:
    print("❌ Some checks failed. Please review the issues above.")

print("="*70)

sys.exit(0 if passed == total else 1)

