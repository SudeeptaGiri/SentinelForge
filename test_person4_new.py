"""Updated Person 4 Demo - Plan-driven Code Generation with Review & Testing.

This demonstrates the new workflow:
1. Read plan file (*Plan.yaml)
2. Generate code to deployable folder
3. Review code (normal + epic)
4. Fix based on reviews
5. Generate and run tests
6. Green check for next agent
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.agents.code_gen_agent import CodeGeneratorAgent
from src.agents.review_agent import ReviewAgent
from src.agents.qa_agent import QAAgent

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def print_section(title: str):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")


def main():
    print_section("🚀 PERSON 4: PLAN-DRIVEN CODE GENERATION & REVIEW")
    
    # Step 1: Locate plan file
    plan_file = Path(__file__).parent / "test_plans" / "TestPlan.yaml"
    
    if not plan_file.exists():
        logger.error(f"Plan file not found: {plan_file}")
        return 1
    
    logger.info(f"✅ Found plan file: {plan_file.name}")
    
    # Step 2: Generate code from plan
    print_section("📋 Step 1: Generate Code from Plan")
    
    try:
        code_gen = CodeGeneratorAgent()
        
        if not code_gen.enabled:
            logger.error("❌ Gemini ADC auth required")
            logger.error("   Run: gcloud auth application-default login")
            return 1
        
        result = code_gen.generate_from_plan_file(
            plan_file_path=str(plan_file),
            output_dir="generated_output"
        )
        
        output_path = Path(result["output_path"])
        logger.info(f"✅ Code generated in: {output_path}")
        logger.info(f"📝 Files: {', '.join(result['files_generated'])}")
        
    except Exception as e:
        logger.error(f"❌ Code generation failed: {e}")
        return 1
    
    # Step 3: Review code
    print_section("🔍 Step 2: Review Generated Code")
    
    try:
        reviewer = ReviewAgent()
        
        if not reviewer.enabled:
            logger.warning("⚠️  Review agent disabled, skipping reviews")
            review_report = None
        else:
            review_report = reviewer.review_code(output_path, mode="both")
            
            logger.info(f"Normal review: {len(review_report.normal_issues)} issues")
            logger.info(f"Epic review: {len(review_report.epic_issues)} issues")
            logger.info(f"Critical issues: {review_report.critical_count()}")
            
            # Apply fixes if critical issues found
            if review_report.critical_count() > 0:
                print_section("🔧 Step 3: Apply Review Fixes")
                fixes = reviewer.generate_fix_suggestions(review_report, output_path)
                
                for file_path, fixed_code in fixes.items():
                    fix_file = output_path / file_path
                    fix_file.write_text(fixed_code)
                    logger.info(f"✅ Applied fix to {file_path}")
    
    except Exception as e:
        logger.error(f"❌ Review failed: {e}")
        review_report = None
    
    # Step 4: Generate and run tests
    print_section("🧪 Step 4: Generate and Run Tests")
    
    try:
        qa_agent = QAAgent()
        
        if not qa_agent.enabled:
            logger.error("❌ QA agent disabled - ADC auth required")
            return 1
        
        # Read plan text for test generation
        plan_text = plan_file.read_text()
        
        test_result = qa_agent.generate_and_run_tests(
            code_path=str(output_path),
            plan_text=plan_text
        )
        
        logger.info(f"Test attempts: {test_result['total_attempts']}")
        logger.info(f"Healing applied: {test_result['healing_applied']}")
        
        if test_result["success"]:
            logger.info("✅ All tests passed!")
        else:
            logger.error(f"❌ Tests failed: {test_result.get('reason', 'Unknown')}")
    
    except Exception as e:
        logger.error(f"❌ Testing failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    # Step 5: Final report
    print_section("📊 FINAL REPORT")
    
    status = {
        "Code Generation": "✅ Complete",
        "Review (Normal)": f"✅ {len(review_report.normal_issues) if review_report else 0} issues" if review_report else "⏭️  Skipped",
        "Review (Epic)": f"✅ {len(review_report.epic_issues) if review_report else 0} issues" if review_report else "⏭️  Skipped",
        "Testing": "✅ Passed" if test_result.get("success") else "❌ Failed",
        "Output Location": str(output_path),
        "Deployable": "✅ Yes" if result.get("deployable") else "❌ No"
    }
    
    for key, value in status.items():
        print(f"  {key:.<40} {value}")
    
    print("\n" + "="*70)
    if test_result.get("success"):
        print("  ✅ GREEN CHECK - Ready for next agent")
    else:
        print("  ❌ Issues detected - Review required")
    print("="*70 + "\n")
    
    return 0 if test_result.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())

