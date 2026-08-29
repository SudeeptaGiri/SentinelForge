"""E2E Testing & Log Diagnosis Self-Healing Agent.

Description: Executes unit/E2E tests in sandboxes; diagnoses logs and
             auto-applies self-healing fix patches.
Need: Generated code frequently fails on first try; requiring a human to
      manually debug every failure would defeat the purpose of automation.
Motive: Close the loop between "code generated" and "code verified working"
        by iterating on test failures autonomously before requesting the
        Gate 4 security audit.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

from src.mcp_servers.server_git import GitOperations
from src.utils.genai_client import build_genai_client

logger = logging.getLogger(__name__)


class TestResult:
    """Result of a test execution."""
    
    def __init__(self, passed: bool, output: str, failed_tests: list[str] | None = None):
        self.passed = passed
        self.output = output
        self.failed_tests = failed_tests or []
        self.total_tests = 0
        self.passed_tests = 0
        self.failed_count = len(failed_tests) if failed_tests else 0


class HealingAttempt:
    """Record of a single healing attempt."""
    
    def __init__(self, attempt_number: int, error_type: str, fix_applied: str, success: bool):
        self.attempt_number = attempt_number
        self.error_type = error_type
        self.fix_applied = fix_applied
        self.success = success


class QAAgent:
    """Runs tests in an ephemeral sandbox and self-heals failures via patches.
    
    Uses Gemini to intelligently analyze test failures and generate fixes,
    with a bounded retry mechanism to prevent infinite loops.
    """
    
    def __init__(self, model: str = "gemini-2.5-pro", api_key: str | None = None):
        """Initialize the QA agent.
        
        Args:
            model: Gemini model to use (default from agent_config.yaml)
            api_key: Deprecated for Person 4 flow (ADC is required)
        """
        self._model = model
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self._client = None
        self._auth_mode = None
        self._project = None
        
        # Load config
        config_path = Path(__file__).parents[2] / "config" / "agent_config.yaml"
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f)
                agent_config = config.get("agents", {}).get("qa_agent", {})
                self._model = agent_config.get("model", self._model)
                self.max_retries = agent_config.get("max_retries", 3)
        else:
            self.max_retries = 3
        
        # Initialize Gemini client with ADC-first auth.
        self._client, self._auth_mode, self._project = build_genai_client(api_key=self._api_key)
        if self._auth_mode != "adc":
            if self._api_key:
                logger.warning("QAAgent ignores API key auth; configure ADC instead")
            self._client = None
            self._auth_mode = None
        if self._client:
            logger.info(
                "QAAgent initialized with %s using %s auth",
                self._model,
                self._auth_mode,
            )
        
        self.healing_history: list[HealingAttempt] = []
    
    @property
    def enabled(self) -> bool:
        """Check if Gemini client is available."""
        return self._client is not None
    
    def generate_and_run_tests(
        self,
        code_path: str,
        plan_text: str | None = None
    ) -> dict[str, Any]:
        """Generate test cases from plan and run them with self-healing.
        
        Args:
            code_path: Path to the code directory
            plan_text: Plan text content for test generation
            
        Returns:
            Dictionary with test results and healing metadata
        """
        code_path = Path(code_path)
        
        # Generate tests if plan provided
        if plan_text and self.enabled:
            logger.info("Generating test cases from plan...")
            self._generate_test_cases(code_path, plan_text)
        
        # Run tests with self-healing
        return self.run_tests_with_self_heal(str(code_path))
    
    def _generate_test_cases(self, code_path: Path, plan_text: str) -> None:
        """Generate test cases based on plan text."""
        tests_dir = code_path / "tests"
        tests_dir.mkdir(exist_ok=True)
        
        # Create __init__.py
        (tests_dir / "__init__.py").write_text("")
        
        # Read actual generated app to understand its structure
        app_file = code_path / "app.py"
        if not app_file.exists():
            logger.error("app.py not found, cannot generate tests")
            return
        
        app_code = app_file.read_text()
        
        prompt = f"""Generate pytest test cases based on this plan and the actual generated code.

PLAN:
{plan_text}

ACTUAL GENERATED CODE (app.py):
```python
{app_code}
```

CRITICAL REQUIREMENTS:
1. Import app correctly: from app import app (since app.py is in parent directory)
2. Use pytest fixture for Flask test client
3. Test /healthz endpoint returns 200 and {{"status": "healthy"}}
4. Test hello_world() function if it exists
5. Use sys.path.insert to ensure imports work from tests/ subdirectory
6. Keep tests simple and focused

EXAMPLE STRUCTURE:
```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from app import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_healthz(client):
    response = client.get('/healthz')
    assert response.status_code == 200
    assert response.json == {{"status": "healthy"}}
```

Return ONLY the complete test_app.py code following this pattern. No explanations."""
        
        try:
            response = self._client.models.generate_content(model=self._model, contents=prompt)
            test_code = response.text.strip()
            
            if "```python" in test_code:
                test_code = test_code.split("```python")[1].split("```")[0].strip()
            elif "```" in test_code:
                test_code = test_code.split("```")[1].split("```")[0].strip()
            
            test_file = tests_dir / "test_app.py"
            test_file.write_text(test_code)
            logger.info(f"✅ Generated test cases in {test_file}")
        except Exception as e:
            logger.error(f"Failed to generate tests: {e}")
    
    def run_tests_with_self_heal(
        self, 
        code_path: str, 
        max_retries: int | None = None
    ) -> dict[str, Any]:
        """Run tests and apply self-healing if failures occur.
        
        Args:
            code_path: Path to the code directory containing tests
            max_retries: Maximum healing attempts (uses config default if None)
            
        Returns:
            Dictionary with test results and healing metadata
        """
        max_retries = max_retries or self.max_retries
        code_path = Path(code_path)
        
        logger.info(f"Starting test execution with self-healing (max {max_retries} retries)")
        
        attempt = 0
        result = None  # Initialize to avoid potential unassigned reference
        while attempt <= max_retries:
            logger.info(f"\n{'='*60}")
            logger.info(f"Test Run #{attempt + 1}")
            logger.info(f"{'='*60}")
            
            # Execute tests
            result = self._execute_tests(code_path)
            
            if result.passed:
                logger.info(f"✅ All tests passed on attempt {attempt + 1}")
                return self._generate_report(
                    success=True,
                    final_result=result,
                    total_attempts=attempt + 1
                )
            
            # Tests failed
            if attempt >= max_retries:
                logger.error(f"❌ Max retries ({max_retries}) exceeded. Cannot heal failures.")
                return self._generate_report(
                    success=False,
                    final_result=result,
                    total_attempts=attempt + 1,
                    reason="Max retries exceeded"
                )
            
            # Attempt self-healing
            logger.warning(f"⚠️  Tests failed. Attempting self-healing (attempt {attempt + 1}/{max_retries})...")
            
            healing_success = self._analyze_and_heal(code_path, result)
            
            if not healing_success:
                logger.error("❌ Failed to apply healing fix")
                return self._generate_report(
                    success=False,
                    final_result=result,
                    total_attempts=attempt + 1,
                    reason="Healing failed"
                )
            
            logger.info("🔧 Fix applied. Re-running tests...")
            attempt += 1
        
        # Should not reach here
        return self._generate_report(success=False, final_result=result, total_attempts=attempt)
    
    def _execute_tests(self, code_path: Path) -> TestResult:
        """Execute pytest in the specified directory.
        
        Args:
            code_path: Path to the code directory
            
        Returns:
            TestResult object with execution details
        """
        try:
            result = subprocess.run(
                ["pytest", "tests/", "-v", "--tb=short"],
                cwd=code_path,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            output = result.stdout + "\n" + result.stderr
            passed = result.returncode == 0
            
            # Parse failed tests
            failed_tests = self._parse_failed_tests(output)
            
            logger.info(f"Test execution completed. Passed: {passed}")
            if failed_tests:
                logger.warning(f"Failed tests: {', '.join(failed_tests)}")
            
            return TestResult(passed=passed, output=output, failed_tests=failed_tests)
            
        except subprocess.TimeoutExpired:
            logger.error("Test execution timed out")
            return TestResult(passed=False, output="Test execution timed out", failed_tests=["timeout"])
        except Exception as exc:
            logger.error(f"Test execution failed: {exc}")
            return TestResult(passed=False, output=str(exc), failed_tests=["execution_error"])
    
    def _parse_failed_tests(self, output: str) -> list[str]:
        """Parse pytest output to extract failed test names.
        
        Args:
            output: Pytest output text
            
        Returns:
            List of failed test names
        """
        failed: list[str] = []

        # Pattern A: FAILED tests/test_file.py::test_name
        prefix_pattern = r"FAILED\s+tests[\\/][\w\\/]+\.py::(\w+)"
        failed.extend(re.findall(prefix_pattern, output))

        # Pattern B: tests/test_file.py::test_name FAILED
        suffix_pattern = r"tests[\\/][\w\\/]+\.py::(\w+)\s+FAILED"
        failed.extend(re.findall(suffix_pattern, output))

        # Preserve order while removing duplicates.
        return list(dict.fromkeys(failed))
    
    def _analyze_and_heal(self, code_path: Path, result: TestResult) -> bool:
        """Analyze test failures and apply healing fix.
        
        Args:
            code_path: Path to the code directory
            result: Test result with failure information
            
        Returns:
            True if fix was applied successfully, False otherwise
        """
        error_context = self._extract_error_context(result.output)
        
        if not error_context:
            logger.error("Could not extract meaningful error context")
            return False
        
        logger.info(f"📋 Error context: {error_context[:200]}...")

        if not self.enabled:
            logger.error("Gemini ADC auth unavailable; self-healing fallback is disabled")
            return False

        # Use Gemini to generate intelligent fix
        fix_code = self._generate_fix_with_gemini(code_path, error_context, result.output)
        
        if not fix_code:
            logger.error("Failed to generate fix")
            return False
        
        # Apply the fix
        return self._apply_fix(code_path, fix_code, error_context)
    
    def _extract_error_context(self, output: str) -> str:
        """Extract meaningful error context from test output.
        
        Args:
            output: Full test output
            
        Returns:
            Concise error context string
        """
        lines = output.split("\n")
        
        # Look for assertion errors, exceptions, etc.
        error_lines = []
        capture = False
        
        for line in lines:
            if "FAILED" in line or "ERROR" in line or "AssertionError" in line:
                capture = True
            if capture:
                error_lines.append(line)
                if len(error_lines) > 15:  # Limit context size
                    break
        
        if error_lines:
            return "\n".join(error_lines)
        
        # Fallback: last 20 lines
        return "\n".join(lines[-20:])
    
    def _generate_fix_with_gemini(
        self, 
        code_path: Path, 
        error_context: str,
        full_output: str
    ) -> str | None:
        """Generate fix using Gemini AI.
        
        Args:
            code_path: Path to the code directory
            error_context: Extracted error context
            full_output: Complete test output
            
        Returns:
            Fix code as string, or None if generation failed
        """
        # Read the current app.py
        app_file = code_path / "app.py"
        if not app_file.exists():
            return None
        
        current_code = app_file.read_text()
        
        prompt = f"""You are a QA self-healing agent. A test has failed and you need to fix the code.

TEST FAILURE OUTPUT:
{error_context}

CURRENT CODE (app.py):
{current_code}

TASK:
1. Analyze the test failure
2. Identify what's missing or broken
3. Generate the COMPLETE fixed version of app.py
4. The fix should be minimal and targeted

CONSTRAINTS:
- Keep all existing functionality intact
- Only add/modify what's necessary to fix the test
- Follow Flask best practices
- Ensure the fix is production-ready

Return ONLY the complete fixed app.py file content, no explanations or markdown."""

        try:
            logger.info("🤖 Asking Gemini to generate fix...")
            response = self._client.models.generate_content(
                model=self._model,
                contents=prompt
            )
            
            fix_code = response.text.strip()
            
            # Extract code from markdown if present
            if "```python" in fix_code:
                fix_code = fix_code.split("```python")[1].split("```")[0].strip()
            elif "```" in fix_code:
                fix_code = fix_code.split("```")[1].split("```")[0].strip()
            
            logger.info("✅ Fix generated by Gemini")
            return fix_code
            
        except Exception as exc:
            logger.error(f"Gemini fix generation failed: {exc}")
            return None
    
    def _generate_fix_fallback(self, code_path: Path, error_context: str) -> str | None:
        """Deprecated fallback fixer retained for backward compatibility.

        Person 4 now runs in ADC-only mode and this method is not used in the
        active self-healing path.
        
        Args:
            code_path: Path to the code directory
            error_context: Extracted error context
            
        Returns:
            Fix code as string, or None if no pattern matches
        """
        logger.info("Using fallback pattern-based fix generation")
        
        app_file = code_path / "app.py"
        if not app_file.exists():
            return None
        
        current_code = app_file.read_text()
        error_lower = error_context.lower()
        
        # Pattern 1: Missing /healthz endpoint (multiple detection methods)
        healthz_patterns = [
            "test_healthz" in error_lower,
            "/healthz" in error_lower,
            "404" in error_lower and "health" in error_lower,
            "not found" in error_lower and "health" in error_lower,
        ]
        
        if any(healthz_patterns):
            logger.info("Detected: Missing /healthz endpoint")
            
            # Check if route already exists
            if "@app.route('/healthz')" in current_code or '@app.route("/healthz")' in current_code:
                logger.info("Health endpoint route already exists, skipping")
                return None
            
            healthz_code = '''

@app.route('/healthz')
def healthz():
    """Health check endpoint for Cloud Run readiness probe."""
    return jsonify({"status": "healthy"}), 200
'''
            
            if "if __name__" in current_code:
                parts = current_code.split("if __name__")
                return parts[0].rstrip() + healthz_code + "\n\nif __name__" + parts[1]
            else:
                return current_code.rstrip() + healthz_code
        
        # Pattern 2: Missing import for jsonify
        if "jsonify" in error_lower and ("not defined" in error_lower or "name error" in error_lower):
            logger.info("Detected: Missing jsonify import")
            if "from flask import" in current_code and "jsonify" not in current_code:
                # Add jsonify to existing import
                import_line = [line for line in current_code.split("\n") if "from flask import" in line][0]
                if not import_line.endswith(("jsonify", "jsonify,")):
                    new_import = import_line.rstrip() + ", jsonify"
                    return current_code.replace(import_line, new_import)
        
        # Add more patterns as needed
        logger.warning("No fallback pattern matched the error")
        return None
    
    def _apply_fix(self, code_path: Path, fix_code: str, error_type: str) -> bool:
        """Apply the generated fix to the codebase.
        
        Args:
            code_path: Path to the code directory
            fix_code: Complete fixed code
            error_type: Type/description of the error
            
        Returns:
            True if fix was applied successfully
        """
        try:
            app_file = code_path / "app.py"
            
            # Backup current version (simple file backup, not git)
            backup_file = code_path / "app.py.backup"
            if app_file.exists():
                backup_file.write_text(app_file.read_text())
            
            # Write the fix
            app_file.write_text(fix_code)
            
            # Save healing record to file
            healing_file = code_path / "HEALING_LOG.txt"
            healing_entry = f"""
{'=' * 70}
HEALING ATTEMPT #{len(self.healing_history) + 1}
{'=' * 70}
Error Type: {error_type[:100]}
Fix Applied: {error_type[:50]}
Timestamp: {__import__('datetime').datetime.now().isoformat()}
Status: Success
{'=' * 70}

"""
            # Append to healing log
            if healing_file.exists():
                current = healing_file.read_text()
                healing_file.write_text(current + healing_entry)
            else:
                healing_file.write_text("SELF-HEALING LOG\n" + "=" * 70 + "\n" + healing_entry)
            
            logger.info(f"✅ Fix applied and logged to {healing_file}")
            
            self.healing_history.append(
                HealingAttempt(
                    attempt_number=len(self.healing_history) + 1,
                    error_type=error_type,
                    fix_applied=f"Fix applied: {error_type[:50]}",
                    success=True
                )
            )
            return True
                
        except Exception as exc:
            logger.error(f"Failed to apply fix: {exc}")
            return False
    
    def _generate_report(
        self,
        success: bool,
        final_result: TestResult,
        total_attempts: int,
        reason: str | None = None
    ) -> dict[str, Any]:
        """Generate final test and healing report.
        
        Args:
            success: Whether tests ultimately passed
            final_result: Final test execution result
            total_attempts: Total number of test runs
            reason: Failure reason if applicable
            
        Returns:
            Report dictionary
        """
        return {
            "success": success,
            "total_attempts": total_attempts,
            "healing_applied": len(self.healing_history),
            "healing_history": [
                {
                    "attempt": h.attempt_number,
                    "error_type": h.error_type,
                    "fix": h.fix_applied,
                    "success": h.success
                }
                for h in self.healing_history
            ],
            "final_test_output": final_result.output[-500:],  # Last 500 chars
            "failed_tests": final_result.failed_tests,
            "reason": reason
        }
    
    def self_heal_test_failure(self, failure_log: str) -> str:
        """Legacy single-shot healing method.
        
        Args:
            failure_log: Test failure log
            
        Returns:
            Status message
        """
        # This is for backward compatibility
        # Real implementation uses run_tests_with_self_heal
        return "Use run_tests_with_self_heal() for full self-healing workflow"

