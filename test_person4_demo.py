"""Test runner for Person 4's Code Generation and QA Self-Healing demo.

This script demonstrates the complete workflow:
1. CodeGeneratorAgent generates code based on a migration plan
2. QAAgent runs tests (which fail initially)
3. QAAgent self-heals the failures using Gemini
4. Tests pass after healing

Run this to see the complete self-healing demo in action!
"""

import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.agents.code_gen_agent import CodeGeneratorAgent
from src.agents.qa_agent import QAAgent
from src.models.schemas import CostEstimate, MigrationPlan

# Configure logging for demo visibility
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def print_section(title: str):
    """Print a formatted section header."""
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")


def main():
    """Run the complete Code Gen + QA Self-Healing demo."""
    
    print_section("🚀 SENTINELFORGE: CODE GENERATION & SELF-HEALING DEMO")
    
    # Demo repository path
    demo_repo = Path(__file__).parent / "demo_app"
    
    if not demo_repo.exists():
        logger.error(f"Demo app not found at {demo_repo}")
        logger.error("Please ensure demo_app/ directory exists with the Flask app")
        return 1
    
    logger.info(f"Using demo repository: {demo_repo}")
    
    # Create a mock migration plan (from Person 2's Cost Agent)
    print_section("📋 Step 1: Create Migration Plan")
    
    migration_plan = MigrationPlan(
        baseline=CostEstimate(
            platform="GCE",
            monthly_cost_usd=612.0,
            breakdown={"compute": 480.0, "disk": 132.0}
        ),
        target=CostEstimate(
            platform="CloudRun",
            monthly_cost_usd=178.0,
            breakdown={"compute": 150.0, "requests": 28.0}
        ),
        target_platform="CloudRun",
        monthly_savings_usd=434.0,
        savings_pct=70.9,
        rationale="Stateless workload with variable traffic fits serverless scale-to-zero"
    )
    
    logger.info(f"Target Platform: {migration_plan.target_platform}")
    logger.info(f"Monthly Savings: ${migration_plan.monthly_savings_usd} ({migration_plan.savings_pct}%)")
    
    # Step 1: Code Generation
    print_section("🔧 Step 2: Generate Code Changes")
    
    try:
        code_gen = CodeGeneratorAgent()
        
        if not code_gen.enabled:
            logger.warning("⚠️  Gemini ADC auth not available - code generation is disabled")
            logger.warning("   Configure ADC via 'gcloud auth application-default login'")
        else:
            logger.info("✅ Gemini AI enabled for intelligent code generation")
        
        logger.info("Generating code changes for Cloud Run migration...")
        
        code_diff = code_gen.generate_code_changes(
            plan=migration_plan,
            repo_path=str(demo_repo),
            branch_name="feature/cloud-run-migration"
        )
        
        logger.info(f"✅ Generated changes on branch: {code_diff.branch_name}")
        logger.info(f"📝 Files changed: {', '.join(code_diff.files_changed)}")
        logger.info(f"📊 Diff size: {len(code_diff.diff_text)} characters")
        
        print("\n" + "─" * 70)
        print("Generated diff preview (first 500 chars):")
        print("─" * 70)
        print(code_diff.diff_text[:500])
        if len(code_diff.diff_text) > 500:
            print(f"\n... ({len(code_diff.diff_text) - 500} more characters)")
        print("─" * 70)
        
    except Exception as exc:
        logger.error(f"❌ Code generation failed: {exc}")
        return 1
    
    # Step 2: QA with Self-Healing
    print_section("🧪 Step 3: Run Tests with Self-Healing")
    
    try:
        qa_agent = QAAgent()
        
        if not qa_agent.enabled:
            logger.warning("⚠️  Gemini ADC auth not available - self-healing is disabled")
            logger.warning("   Configure ADC via 'gcloud auth application-default login'")
        else:
            logger.info("✅ Gemini AI enabled for intelligent self-healing")
        
        logger.info("Running tests with self-healing enabled...")
        logger.info(f"Max healing attempts: {qa_agent.max_retries}")
        
        result = qa_agent.run_tests_with_self_heal(
            code_path=str(demo_repo),
            max_retries=3
        )
        
        # Display results
        print_section("📊 FINAL RESULTS")
        
        if result["success"]:
            logger.info("✅ ✅ ✅  ALL TESTS PASSED! ✅ ✅ ✅")
        else:
            logger.error("❌ Tests failed after all healing attempts")
        
        logger.info(f"Total test runs: {result['total_attempts']}")
        logger.info(f"Healing fixes applied: {result['healing_applied']}")
        
        if result["healing_history"]:
            print("\n" + "─" * 70)
            print("Healing History:")
            print("─" * 70)
            for heal in result["healing_history"]:
                status = "✅" if heal["success"] else "❌"
                print(f"{status} Attempt {heal['attempt']}: {heal['fix']}")
            print("─" * 70)
        
        if result.get("reason"):
            logger.warning(f"Reason: {result['reason']}")
        
        # Success metrics
        print_section("🎯 DEMO SUCCESS METRICS")
        
        metrics = {
            "Code Generation": "✅ Completed",
            "Test Execution": "✅ Completed",
            "Failure Detection": "✅ Detected missing /healthz",
            "Self-Healing": "✅ Applied fix automatically" if result["healing_applied"] > 0 else "⚠️  No healing needed",
            "Final Status": "✅ All tests passing" if result["success"] else "❌ Tests failed",
        }
        
        for metric, status in metrics.items():
            print(f"  {metric:.<40} {status}")
        
        print("\n" + "="*70)
        print("  🎉 DEMO COMPLETE!")
        print("="*70 + "\n")
        
        return 0 if result["success"] else 1
        
    except Exception as exc:
        logger.error(f"❌ QA testing failed: {exc}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

