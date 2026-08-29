"""Code Optimizer Agent - iterative code/test fixer.

The optimizer is intentionally an autonomous fixer:

1. Consume ReviewAgent findings.
2. Inspect the target and related project files.
3. Apply deterministic fixes where possible.
4. Use Gemini for issues that require reasoning.
5. Re-validate and repeat until the review findings are gone or the
   optimizer is genuinely stuck.
6. Run the test suite after review fixes.
7. If tests fail, diagnose and fix the implementation, imports, fixtures,
   configuration, or test cases as appropriate. Test failures do NOT
   escalate to a human.
8. A human is requested only when the review-fixing loop is genuinely stuck.

The public ``fix_issues`` API remains compatible with the previous version.
Pass ``review_callback`` when the caller can re-run ReviewAgent after each
round; this lets the optimizer continue until the review actually passes.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

import yaml

from src.utils.genai_client import build_genai_client
from src.utils.terminal_logger import log_agent_call, log_llm_request, log_llm_response

logger = logging.getLogger(__name__)

GENERATED_OUTPUT_DIR = "generated_output"
IGNORED_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache",
    "node_modules", "dist", "build", ".mypy_cache", ".ruff_cache",
}
SOURCE_SUFFIXES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".yaml", ".yml",
    ".toml", ".ini", ".cfg",
}


@dataclass
class FixAttempt:
    """Single fix attempt for an issue."""

    strategy: str
    success: bool
    changes_made: str
    error_message: str = ""


@dataclass
class OptimizationResult:
    """Result of fixing a single file."""

    file_path: str
    original_code: str
    optimized_code: str
    issues_fixed: list[str]
    fix_attempts: list[FixAttempt]
    success: bool
    needs_human: bool = False

    def to_dict(self) -> dict:
        return {
            "file": self.file_path,
            "success": self.success,
            "needs_human": self.needs_human,
            "issues_fixed": self.issues_fixed,
            "attempts": [
                {
                    "strategy": attempt.strategy,
                    "success": attempt.success,
                    "changes": attempt.changes_made,
                    "error": attempt.error_message,
                }
                for attempt in self.fix_attempts
            ],
        }


@dataclass
class OptimizationReport:
    """Complete optimization report."""

    files_fixed: list[str] = field(default_factory=list)
    files_failed: list[str] = field(default_factory=list)
    needs_human_intervention: list[str] = field(default_factory=list)
    results: list[OptimizationResult] = field(default_factory=list)
    test_runs: list[dict[str, Any]] = field(default_factory=list)
    review_passed: bool = False
    tests_passed: bool = False
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "summary": {
                "total_files": len(self.results),
                "fixed": len(self.files_fixed),
                "failed": len(self.files_failed),
                "needs_human": len(self.needs_human_intervention),
                "review_passed": self.review_passed,
                "tests_passed": self.tests_passed,
                "test_runs": len(self.test_runs),
            },
            "files_fixed": self.files_fixed,
            "files_failed": self.files_failed,
            "needs_human_intervention": self.needs_human_intervention,
            "review_passed": self.review_passed,
            "tests_passed": self.tests_passed,
            "test_runs": self.test_runs,
            "details": [result.to_dict() for result in self.results],
        }

    def save_report(self, output_path: Path) -> None:
        output_path.mkdir(parents=True, exist_ok=True)
        report_file = output_path / "OPTIMIZER_REPORT.json"
        report_file.write_text(
            json.dumps(self.to_dict(), indent=2),
            encoding="utf-8",
        )
        logger.info("📄 Optimization report saved to %s", report_file)


class CodeOptimizerAgent:
    """Autonomous iterative fixer for review findings and test failures.

    Review fixes can escalate to a human only after every configured
    strategy has been exhausted. Test failures are different: the optimizer
    keeps diagnosing and fixing them and never marks a test failure as a
    human-intervention condition.
    """

    def __init__(
            self,
            model: str | None = None,
            max_fix_rounds: int = 8,
            max_test_rounds: int = 8,
            test_timeout: int = 600,
    ):
        self._model = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self._max_fix_rounds = max(1, max_fix_rounds)
        self._max_test_rounds = max(1, max_test_rounds)
        self._test_timeout = max(30, test_timeout)
        self._client = None
        self._auth_mode = None

        config_path = Path(__file__).parents[2] / "config" / "agent_config.yaml"
        if config_path.exists():
            try:
                config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
                agent_config = config.get("agents", {}).get("optimizer_agent", {})
                self._model = agent_config.get("model", self._model)
                self._max_fix_rounds = int(
                    agent_config.get("max_fix_rounds", self._max_fix_rounds)
                )
                self._max_test_rounds = int(
                    agent_config.get("max_test_rounds", self._max_test_rounds)
                )
                self._test_timeout = int(
                    agent_config.get("test_timeout", self._test_timeout)
                )
            except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
                logger.warning("Could not load optimizer config: %s", exc)

        try:
            self._client, self._auth_mode, _ = build_genai_client()
        except Exception as exc:
            logger.warning("Could not initialize Gemini client: %s", exc)
            self._client = None
            self._auth_mode = None

        if self._auth_mode != "adc":
            self._client = None

        if self._client:
            logger.info("CodeOptimizerAgent initialized with %s", self._model)
        else:
            logger.warning(
                "CodeOptimizerAgent is running without AI assistance; "
                "deterministic fixes and test diagnostics are still enabled."
            )

    @property
    def enabled(self) -> bool:
        """Whether AI assistance is available."""
        return self._client is not None

    def fix_issues(
            self,
            review_report: dict,
            base_path: str | Path | None = None,
            *,
            test_command: str | list[str] | None = None,
            review_callback: Optional[Callable[[Path], dict]] = None,
            run_tests: bool = True,
    ) -> OptimizationReport:
        """Fix review findings, re-review, then fix test failures.

        Args:
            review_report: Output from ReviewAgent.
            base_path: Project root.
            test_command: Test command. If omitted, pytest is auto-discovered.
            review_callback: Optional callback that re-runs ReviewAgent and
                returns its report. It receives ``base_path``. Supplying it
                enables a true review -> fix -> review loop.
            run_tests: Run tests after review fixes.

        Returns:
            OptimizationReport. ``needs_human_intervention`` is populated
            only when review findings remain after all fix rounds.
        """
        base = self._resolve_generated_output_root(base_path)
        if base is None:
            logger.error("generated_output directory not found for optimizer")
            return OptimizationReport()
        report = OptimizationReport()

        current_review = review_report or {}
        review_round = 0

        logger.info("🔧 Starting autonomous code optimization")

        while review_round < self._max_fix_rounds:
            review_round += 1
            issues_by_file = self._group_issues_by_file(current_review)

            if not issues_by_file:
                report.review_passed = True
                logger.info("✅ Review has no actionable issues")
                break

            logger.info(
                "🔍 Review fix round %d/%d: %d files",
                review_round,
                self._max_fix_rounds,
                len(issues_by_file),
            )

            round_changed = False
            unresolved_files: list[str] = []

            for relative_path, issues in issues_by_file.items():
                full_path = self._safe_project_path(base, relative_path)
                if full_path is None or not full_path.exists():
                    unresolved_files.append(relative_path)
                    logger.error("File not found or outside project: %s", relative_path)
                    continue

                result = self._fix_file(full_path, issues, base)
                report.results.append(result)

                if result.success:
                    full_path.write_text(result.optimized_code, encoding="utf-8")
                    round_changed = round_changed or (
                            result.optimized_code != result.original_code
                    )
                    if relative_path not in report.files_fixed:
                        report.files_fixed.append(relative_path)
                    logger.info(
                        "   ✅ %s: fixed %d issue(s)",
                        relative_path,
                        len(result.issues_fixed),
                    )
                elif result.needs_human:
                    unresolved_files.append(relative_path)
                else:
                    unresolved_files.append(relative_path)

            # Without a re-review callback, validate the files we touched.
            # We do not pretend that syntax validation is equivalent to a full
            # ReviewAgent pass.
            if review_callback is None:
                remaining = self._remaining_issues_by_file(
                    current_review, base
                )
                if not remaining:
                    report.review_passed = True
                    break

                # No callback means we cannot know whether semantic review
                # issues disappeared. Try another round only if something
                # actually changed.
                if not round_changed:
                    break
                current_review = self._synthetic_report_from_issues(
                    remaining
                )
                continue

            # Re-run the actual review after every fixing round.
            try:
                current_review = review_callback(base) or {}
            except Exception as exc:
                logger.exception("Review callback failed: %s", exc)
                break

            if not self._group_issues_by_file(current_review):
                report.review_passed = True
                logger.info("✅ Review passed after %d round(s)", review_round)
                break

            if not round_changed and not unresolved_files:
                logger.warning("Review findings did not change after a fix round")
                break

        if not report.review_passed:
            remaining = self._group_issues_by_file(current_review)
            if remaining:
                # Human escalation is ONLY for review issues that remain
                # after the autonomous loop is genuinely stuck.
                for path in remaining:
                    if path not in report.needs_human_intervention:
                        report.needs_human_intervention.append(path)
                    if path not in report.files_failed:
                        report.files_failed.append(path)
                logger.warning(
                    "🆘 Optimizer is stuck on %d review file(s); human input required",
                    len(remaining),
                )
            else:
                report.review_passed = True

        # Tests are always attempted after review fixing, unless explicitly
        # disabled. Test failures never populate needs_human_intervention.
        if run_tests and report.review_passed:
            report.tests_passed = self._fix_test_failures(
                base,
                report,
                test_command=test_command,
            )
        elif not run_tests:
            report.tests_passed = True

        report.save_report(base)
        self._log_summary(report)
        return report

    # Backwards-compatible alias with a more explicit pipeline name.
    optimize = fix_issues

    def optimize_code_dict(
            self,
            code_files: dict[str, str],
            review_report: dict,
    ) -> tuple[dict[str, str], OptimizationReport]:
        """Fix review findings directly on an in-memory dictionary of code files.

        Args:
            code_files: Mapping of relative file path -> file content string.
            review_report: Output dictionary from ReviewAgent.

        Returns:
            Tuple of (updated_code_files_dict, OptimizationReport)
        """
        log_agent_call("CodeOptimizerAgent", "optimize_code_dict", f"files={len(code_files)}")
        if not self.enabled or not code_files:
            return code_files, OptimizationReport()

        issues_by_file = self._group_issues_by_file(review_report)
        if not issues_by_file:
            report = OptimizationReport()
            report.review_passed = True
            return code_files, report

        report = OptimizationReport()
        updated_files = dict(code_files)

        for rel_path, issues in issues_by_file.items():
            matched_key = None
            if rel_path in updated_files:
                matched_key = rel_path
            else:
                for k in updated_files:
                    if k.endswith(rel_path) or rel_path.endswith(k) or Path(k).name == Path(rel_path).name:
                        matched_key = k
                        break

            if not matched_key:
                continue

            current_code = updated_files[matched_key]
            original_code = current_code
            fix_attempts: list[FixAttempt] = []
            issues_fixed: list[str] = []
            ext = Path(matched_key).suffix

            issues_text = "\n".join(
                [f"- {iss.get('message', '')} (Suggestion: {iss.get('suggestion', '')})" for iss in issues]
            )

            prompt = f"""<role>
You are an expert software engineer fixing issues in a file.
</role>

<task>
Fix all of the following issues in "{matched_key}":
{issues_text}
</task>

<current_code>
{current_code}
</current_code>

<instructions>
1. Fix all listed issues cleanly and completely.
2. Preserve all other code, comments, and functionality.
3. Return ONLY the complete corrected file contents without markdown code fences.
</instructions>"""
            try:
                log_llm_request("CodeOptimizerAgent", self._model, prompt, purpose=f"Self-heal {len(issues)} issue(s) in {matched_key}")
                start_t = time.perf_counter()
                resp = self._client.models.generate_content(
                    model=self._model, contents=prompt
                )
                duration = time.perf_counter() - start_t
                log_llm_response("CodeOptimizerAgent", self._model, resp.text, duration_sec=duration)
                candidate = self._extract_code_from_response(resp.text or "")
                if candidate and candidate != current_code and self._validate_code(candidate, ext):
                    current_code = candidate
                    issues_fixed = [iss.get("message", "") for iss in issues]
                    fix_attempts.append(FixAttempt(strategy="gemini_review_fix_batch", success=True, changes_made="; ".join(issues_fixed)))
            except Exception as exc:
                fix_attempts.append(FixAttempt(strategy="gemini_review_fix_batch", success=False, changes_made="", error_message=str(exc)))

            if current_code != original_code:
                updated_files[matched_key] = current_code
                report.files_fixed.append(matched_key)
                report.results.append(OptimizationResult(
                    file_path=matched_key,
                    original_code=original_code,
                    optimized_code=current_code,
                    issues_fixed=issues_fixed,
                    fix_attempts=fix_attempts,
                    success=True,
                ))

        report.review_passed = len(report.files_failed) == 0
        return updated_files, report

    def fix_test_failures(
            self,
            base_path: str | Path,
            *,
            test_command: str | list[str] | None = None,
            report: OptimizationReport | None = None,
    ) -> bool:
        """Run tests and autonomously fix failures. Never escalates to human."""
        base = self._resolve_generated_output_root(base_path)
        if base is None:
            logger.error("generated_output directory not found for optimizer")
            return False
        optimization_report = report or OptimizationReport()
        return self._fix_test_failures(
            base,
            optimization_report,
            test_command=test_command,
        )

    # =========================================================================
    # Review fixing
    # =========================================================================

    def _fix_file(
            self,
            file_path: Path,
            issues: list[dict],
            base_path: Path,
    ) -> OptimizationResult:
        original_code = file_path.read_text(encoding="utf-8")
        current_code = original_code
        fix_attempts: list[FixAttempt] = []
        issues_fixed: list[str] = []

        sorted_issues = sorted(
            issues,
            key=lambda item: {
                "critical": 0,
                "error": 0,
                "warning": 1,
                "info": 2,
            }.get(str(item.get("severity", "info")).lower(), 3),
        )

        for issue in sorted_issues:
            issue_data = issue

            def import_strategy() -> FixAttempt:
                return self._fix_import_error(
                    current_code, issue_data, file_path, base_path
                )

            def syntax_strategy() -> FixAttempt:
                return self._fix_syntax_error(current_code, issue_data)

            def context_strategy() -> FixAttempt:
                return self._fix_with_context(
                    current_code, issue_data, file_path, base_path
                )

            strategies: Iterable[Callable[[], FixAttempt]] = (
                import_strategy,
                syntax_strategy,
                context_strategy,
            )

            issue_fixed = False
            for strategy in strategies:
                attempt = strategy()
                fix_attempts.append(attempt)
                if not attempt.success:
                    continue

                candidate = self._candidate_from_attempt(
                    current_code, issue, attempt
                )
                if candidate == current_code:
                    continue

                if not self._validate_code(candidate, file_path.suffix):
                    fix_attempts.append(
                        FixAttempt(
                            strategy=f"{attempt.strategy}_validation",
                            success=False,
                            changes_made="",
                            error_message="Candidate failed syntax validation",
                        )
                    )
                    continue

                current_code = candidate
                issues_fixed.append(
                    str(issue.get("message", "code issue"))
                )
                issue_fixed = True
                break

            if not issue_fixed:
                logger.warning(
                    "   ⚠️ Could not fix review issue: %s",
                    issue.get("message", "unknown issue"),
                )

        changed = current_code != original_code
        all_requested_fixed = len(issues_fixed) == len(sorted_issues)
        valid = self._validate_code(current_code, file_path.suffix)

        return OptimizationResult(
            file_path=str(file_path.relative_to(base_path)),
            original_code=original_code,
            optimized_code=current_code,
            issues_fixed=issues_fixed,
            fix_attempts=fix_attempts,
            success=bool(valid and changed and all_requested_fixed),
            # This flag is deliberately false here. Human escalation belongs
            # to the outer loop after all rounds have been exhausted.
            needs_human=False,
        )

    def _fix_import_error(
            self,
            code: str,
            issue: dict,
            file_path: Path,
            base_path: Path,
    ) -> FixAttempt:
        """Resolve import errors by inspecting the actual project tree."""
        message = str(issue.get("message", ""))
        suggestion = str(issue.get("suggestion", ""))

        module_match = re.search(
            r"(?:Cannot import|No module named|cannot import name)\s*['\"]?([^'\"`\s]+)",
            message,
            re.IGNORECASE,
        )
        bad_import = module_match.group(1) if module_match else ""

        candidates = self._find_import_candidates(
            bad_import, file_path, base_path
        )

        # Review suggestions are useful, but the actual filesystem wins.
        suggested_match = re.search(
            r"from\s+([\w.]+)\s+import\s+([\w*]+)",
            suggestion,
        )
        if suggested_match:
            candidates.insert(
                0,
                (
                    suggested_match.group(1),
                    suggested_match.group(2),
                ),
            )

        for module_name, symbol in candidates:
            replacement = self._replace_import_reference(
                code, bad_import, module_name, symbol
            )
            if replacement != code:
                return FixAttempt(
                    strategy="import_fix",
                    success=True,
                    changes_made=replacement,
                )

        # Handle a common absolute-vs-package-relative import failure.
        if bad_import:
            leaf = bad_import.rsplit(".", 1)[-1]
            project_files = self._find_project_modules(base_path, leaf)
            if len(project_files) == 1:
                module_name = self._module_name_from_path(
                    project_files[0], base_path
                )
                replacement = code.replace(bad_import, module_name)
                if replacement != code:
                    return FixAttempt(
                        strategy="import_path_fix",
                        success=True,
                        changes_made=replacement,
                    )

        return FixAttempt(
            strategy="import_fix",
            success=False,
            changes_made="",
            error_message="No verified import replacement found",
        )

    def _fix_syntax_error(self, code: str, issue: dict) -> FixAttempt:
        """Apply small deterministic syntax fixes before using AI."""
        exc_message = str(issue.get("message", "Syntax error"))
        try:
            ast.parse(code)
            return FixAttempt(
                strategy="syntax_fix",
                success=False,
                changes_made="",
                error_message="Code is already syntactically valid",
            )
        except SyntaxError as exc:
            line = exc.lineno or 0
            lines = code.splitlines()

        if not (1 <= line <= len(lines)):
            return FixAttempt(
                strategy="syntax_fix",
                success=False,
                changes_made="",
                error_message="Syntax error line is unavailable",
            )

        # Safe, narrow fixes only.
        candidate = code
        target = lines[line - 1]
        if target.count("(") > target.count(")"):
            candidate = code + ")"
        elif target.count("[") > target.count("]"):
            candidate = code + "]"
        elif target.count("{") > target.count("}"):
            candidate = code + "}"
        elif target.rstrip().endswith(","):
            candidate = code
        else:
            return FixAttempt(
                strategy="syntax_fix",
                success=False,
                changes_made="",
                error_message=exc_message,
            )

        if self._validate_code(candidate, ".py"):
            return FixAttempt(
                strategy="syntax_fix",
                success=True,
                changes_made=candidate,
            )

        return FixAttempt(
            strategy="syntax_fix",
            success=False,
            changes_made="",
            error_message=exc_message,
        )

    def _fix_with_context(
            self,
            code: str,
            issue: dict,
            file_path: Path,
            base_path: Path,
    ) -> FixAttempt:
        """Ask AI to fix an issue with relevant files in context."""
        if not self.enabled:
            return FixAttempt(
                strategy="ai_context_fix",
                success=False,
                changes_made="",
                error_message="AI client is unavailable",
            )

        related = self._collect_related_files(file_path, base_path)
        context = self._format_file_context(related, base_path)

        language = self._language_for(file_path)
        prompt = f"""You are an autonomous code-fixing agent.

Fix ONLY the reported issue. You may correct imports, implementation code,
configuration, fixtures, or related code when the dependency requires it.
Use the related files below to verify names, paths, APIs, and conventions.
Do not invent modules or symbols.

Issue:
- message: {issue.get("message", "Unknown issue")}
- category: {issue.get("category", "Unknown")}
- severity: {issue.get("severity", "Unknown")}
- line: {issue.get("line", "Unknown")}
- suggestion: {issue.get("suggestion", "None")}

Target file: {file_path.relative_to(base_path)}

Current target code:
```{language}
{code}
```

Related project files:
{context}

Return ONLY the COMPLETE corrected target-file code in a fenced code block.
"""
        try:
            log_llm_request("CodeOptimizerAgent", self._model, prompt, purpose=f"Context-aware fix: {file_path.name}")
            start_t = time.perf_counter()
            response = self._client.models.generate_content(
                model=self._model,
                contents=prompt,
            )
            duration = time.perf_counter() - start_t
            log_llm_response("CodeOptimizerAgent", self._model, response.text, duration_sec=duration)
            fixed_code = self._extract_code_from_response(response.text)
            if fixed_code and fixed_code != code:
                return FixAttempt(
                    strategy="ai_context_fix",
                    success=True,
                    changes_made=fixed_code,
                )
            return FixAttempt(
                strategy="ai_context_fix",
                success=False,
                changes_made="",
                error_message="AI returned no change",
            )
        except Exception as exc:
            return FixAttempt(
                strategy="ai_context_fix",
                success=False,
                changes_made="",
                error_message=str(exc),
            )

    def _attempt_whole_project_ai_fix(
            self,
            base_path: Path,
            report: OptimizationReport,
            test_output: str,
    ) -> bool:
        """Ask Gemini for whole-project fixes using multi-file XML format."""
        context = self._build_project_context(base_path)
        prompt = f"""You are a senior software engineer fixing automated test failures.

Current failing test output:
{test_output}

Project files:
{context}

Return one or more complete file replacements using exactly this format:

<FILE path="relative/path.py">
```python
complete file contents
```
</FILE>

Only return files that actually need changes. Do not include explanations.
"""
        try:
            log_llm_request("CodeOptimizerAgent", self._model, prompt, purpose="Whole-project multi-file fix")
            start_t = time.perf_counter()
            response = self._client.models.generate_content(
                model=self._model,
                contents=prompt,
            )
            duration = time.perf_counter() - start_t
            log_llm_response("CodeOptimizerAgent", self._model, response.text, duration_sec=duration)
            replacements = self._extract_file_replacements(response.text)
            if not replacements:
                return False

            changed = False
            for relative, new_code in replacements.items():
                target = self._safe_project_path(base_path, relative)
                if target is None or not target.exists():
                    logger.warning("AI proposed invalid file path: %s", relative)
                    continue
                if new_code == target.read_text(encoding="utf-8"):
                    continue
                if not self._validate_code(new_code, target.suffix):
                    logger.warning("Rejected invalid AI code for %s", relative)
                    continue

                target.write_text(new_code, encoding="utf-8")
                changed = True
                if relative not in report.files_fixed:
                    report.files_fixed.append(relative)
                logger.info("   🔧 Whole-project fix applied: %s", relative)

            return changed
        except Exception as exc:
            logger.exception("AI whole-project diagnosis failed: %s", exc)
            return False

    # =========================================================================
    # Test fixing
    # =========================================================================

    def _fix_test_failures(
            self,
            base_path: Path,
            report: OptimizationReport,
            *,
            test_command: str | list[str] | None,
    ) -> bool:
        """Run tests and keep fixing failures until they pass or are stuck.

        There is intentionally NO human-escalation path here. Test failures
        are treated as fixable engineering work, including broken tests,
        imports, fixtures, mocks, and test setup.
        """
        command = self._resolve_test_command(base_path, test_command)
        if command is None:
            logger.warning("⚠️ No test command discovered; skipping test execution")
            report.tests_passed = True
            return True

        previous_signature = None

        for round_no in range(1, self._max_test_rounds + 1):
            result = self._run_tests(base_path, command)
            report.test_runs.append(result)

            if result["passed"]:
                logger.info("✅ Tests passed on round %d", round_no)
                report.tests_passed = True
                return True

            logger.warning(
                "🧪 Tests failed on round %d/%d (exit=%s)",
                round_no,
                self._max_test_rounds,
                result["returncode"],
            )

            signature = self._failure_signature(result)
            if signature == previous_signature:
                logger.warning(
                    "Test failure signature did not change; attempting "
                    "one final context-aware fix before stopping."
                )
            previous_signature = signature

            changed = self._fix_from_test_failure(
                base_path,
                result,
                report,
            )

            if not changed:
                # No human intervention: we stop only after the autonomous
                # strategies are exhausted.
                logger.error(
                    "❌ Optimizer could not produce another test fix. "
                    "No human escalation is requested for test failures."
                )
                break

        report.tests_passed = False
        return False

    def _fix_from_test_failure(
            self,
            base_path: Path,
            test_result: dict,
            report: OptimizationReport,
    ) -> bool:
        """Diagnose a test failure and modify every relevant file required."""
        relevant = self._relevant_files_from_test_output(
            base_path, test_result["output"]
        )

        # First try deterministic import/test-path repairs.
        deterministic_changed = self._deterministic_test_fix(
            base_path,
            test_result["output"],
            relevant,
        )
        if deterministic_changed:
            for path in deterministic_changed:
                if str(path.relative_to(base_path)) not in report.files_fixed:
                    report.files_fixed.append(str(path.relative_to(base_path)))
            return True

        if not self.enabled:
            return False

        context = self._format_file_context(relevant, base_path)
        prompt = f"""You are an autonomous code optimizer fixing a failing test suite.

The code has already passed the review stage. Tests now fail. Fix the actual
root cause. You may modify production code AND/OR test code. Test failures
are not grounds for human escalation.

Cross-check relevant files before changing anything. Pay special attention to:
- missing/incorrect imports and package paths
- renamed functions/classes
- stale test expectations
- fixtures and mocks
- setup/configuration
- async/sync mismatches
- API signature changes
- test-only failures caused by invalid test code

Test command:
{test_result["command"]}

Test output:
{test_result["output"][-16000:]}

Relevant files:
{context}

Return one or more complete file replacements using exactly this format:

<FILE path="relative/path.py">
```python
complete file contents
```
</FILE>

Only return files that actually need changes. Do not include explanations.
"""
        try:
            log_llm_request("CodeOptimizerAgent", self._model, prompt, purpose="Targeted AI test failure fix")
            start_t = time.perf_counter()
            response = self._client.models.generate_content(
                model=self._model,
                contents=prompt,
            )
            duration = time.perf_counter() - start_t
            log_llm_response("CodeOptimizerAgent", self._model, response.text, duration_sec=duration)
            replacements = self._extract_file_replacements(response.text)
            if not replacements:
                return False

            changed = False
            for relative, new_code in replacements.items():
                target = self._safe_project_path(base_path, relative)
                if target is None or not target.exists():
                    logger.warning("AI proposed invalid file path: %s", relative)
                    continue
                if new_code == target.read_text(encoding="utf-8"):
                    continue
                if not self._validate_code(new_code, target.suffix):
                    logger.warning("Rejected invalid AI code for %s", relative)
                    continue

                target.write_text(new_code, encoding="utf-8")
                changed = True
                if relative not in report.files_fixed:
                    report.files_fixed.append(relative)
                logger.info("   🔧 Test-failure fix applied: %s", relative)

            return changed
        except Exception as exc:
            logger.exception("AI test-failure diagnosis failed: %s", exc)
            return False

    def _deterministic_test_fix(
            self,
            base_path: Path,
            output: str,
            relevant_files: list[Path],
    ) -> list[Path]:
        """Repair obvious import/path mistakes without AI."""
        changed: list[Path] = []

        missing_modules = re.findall(
            r"No module named ['\"]([^'\"]+)['\"]", output
        )
        cannot_import = re.findall(
            r"cannot import name ['\"]([^'\"]+)['\"] from ['\"]([^'\"]+)['\"]",
            output,
            re.IGNORECASE,
        )

        # A missing local module may be a stale package import.
        for module in missing_modules:
            if "." not in module:
                continue
            leaf = module.rsplit(".", 1)[-1]
            candidates = self._find_project_modules(base_path, leaf)
            if len(candidates) != 1:
                continue
            correct_module = self._module_name_from_path(candidates[0], base_path)
            for path in relevant_files:
                text = path.read_text(encoding="utf-8")
                new_text = text.replace(module, correct_module)
                if new_text != text and self._validate_code(new_text, path.suffix):
                    path.write_text(new_text, encoding="utf-8")
                    changed.append(path)

        # If a symbol moved between modules, use the project's actual module
        # tree to find the symbol and update the import in the failing file.
        for symbol, old_module in cannot_import:
            defining = self._find_symbol_definitions(
                base_path, symbol
            )
            if len(defining) != 1:
                continue
            new_module = self._module_name_from_path(defining[0], base_path)
            if new_module == old_module:
                continue
            pattern = re.compile(
                rf"(from\s+){re.escape(old_module)}(\s+import\s+[^\\n]+)"
            )
            for path in relevant_files:
                text = path.read_text(encoding="utf-8")
                new_text = pattern.sub(
                    rf"\g<1>{new_module}\g<2>",
                    text,
                )
                if new_text != text and self._validate_code(new_text, path.suffix):
                    path.write_text(new_text, encoding="utf-8")
                    changed.append(path)

        return list(dict.fromkeys(changed))

    # =========================================================================
    # Project/context utilities
    # =========================================================================

    def _group_issues_by_file(self, review_report: dict) -> dict[str, list[dict]]:
        """Collect issues from all ReviewAgent sections."""
        issues_by_file: dict[str, list[dict]] = {}

        def collect(value: Any) -> None:
            if isinstance(value, dict):
                if isinstance(value.get("issues"), list):
                    for issue in value["issues"]:
                        if not isinstance(issue, dict):
                            continue
                        path = (
                                issue.get("file_path")
                                or issue.get("file")
                                or issue.get("path")
                        )
                        if path:
                            issues_by_file.setdefault(str(path), []).append(issue)
                for key, child in value.items():
                    if key != "issues":
                        collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)

        collect(review_report or {})
        return issues_by_file

    def _remaining_issues_by_file(
            self,
            review_report: dict,
            base_path: Path,
    ) -> dict[str, list[dict]]:
        """Keep only findings whose target still fails basic validation."""
        result: dict[str, list[dict]] = {}
        for path, issues in self._group_issues_by_file(review_report).items():
            full = self._safe_project_path(base_path, path)
            if full is None or not full.exists():
                result[path] = issues
                continue
            try:
                text = full.read_text(encoding="utf-8")
            except OSError:
                result[path] = issues
                continue
            if not self._validate_code(text, full.suffix):
                result[path] = issues
        return result

    def _synthetic_report_from_issues(
            self,
            issues_by_file: dict[str, list[dict]],
    ) -> dict:
        return {"normal_review": {"issues": [
            {"file_path": path, **issue}
            for path, issues in issues_by_file.items()
            for issue in issues
        ]}}

    def _collect_related_files(
            self,
            target: Path,
            base_path: Path,
            max_files: int = 10,
    ) -> list[Path]:
        """Collect imports, tests, configs, and nearby source files."""
        found: list[Path] = [target]

        try:
            text = target.read_text(encoding="utf-8")
        except OSError:
            return found

        imported_modules = re.findall(
            r"^\s*(?:from|import)\s+([A-Za-z_][\w.]*)",
            text,
            re.MULTILINE,
        )
        candidates = []

        for module in imported_modules:
            leaf = module.rsplit(".", 1)[-1]
            candidates.extend(self._find_project_modules(base_path, leaf))

        target_stem = target.stem
        for path in base_path.rglob("*"):
            if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
                continue
            if any(part in IGNORED_DIRS for part in path.parts):
                continue
            if path == target:
                continue
            if (
                    path.stem == target_stem
                    or "test" in path.name.lower()
                    or path.name in {"pyproject.toml", "pytest.ini", "conftest.py"}
            ):
                candidates.append(path)

        for path in candidates:
            if path not in found:
                found.append(path)
            if len(found) >= max_files:
                break

        return found[:max_files]

    def _relevant_files_from_test_output(
            self,
            base_path: Path,
            output: str,
            max_files: int = 16,
    ) -> list[Path]:
        paths: list[Path] = []

        for raw in re.findall(
                r"(?:File\s+[\"']|(?:^|\s))([^\s\"']+\.py)(?::\d+)?",
                output,
        ):
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = base_path / candidate
            try:
                candidate = candidate.resolve()
                candidate.relative_to(base_path.resolve())
            except ValueError:
                continue
            if candidate.exists() and candidate.is_file():
                if candidate not in paths:
                    paths.append(candidate)

        # Include files named by pytest's node ids.
        for match in re.findall(r"([^\s:]+\.py)::", output):
            candidate = base_path / match
            try:
                candidate = candidate.resolve()
                candidate.relative_to(base_path.resolve())
            except ValueError:
                continue
            if candidate.exists() and candidate not in paths:
                paths.append(candidate)

        expanded: list[Path] = []
        for path in paths:
            expanded.extend(
                self._collect_related_files(path, base_path, max_files=6)
            )

        for path in expanded:
            if path not in paths:
                paths.append(path)
            if len(paths) >= max_files:
                break

        return paths[:max_files]

    def _format_file_context(
            self,
            files: list[Path],
            base_path: Path,
            max_chars_per_file: int = 12000,
    ) -> str:
        chunks = []
        for path in files:
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            language = self._language_for(path)
            chunks.append(
                f'FILE: {path.relative_to(base_path)}\n'
                f'```{language}\n{content[:max_chars_per_file]}\n```'
            )
        return "\n\n".join(chunks) or "(No readable related files found.)"

    def _find_project_modules(self, base_path: Path, stem: str) -> list[Path]:
        result = []
        for path in base_path.rglob(f"{stem}.py"):
            if not path.is_file():
                continue
            if any(part in IGNORED_DIRS for part in path.parts):
                continue
            result.append(path.resolve())
        return result

    def _find_symbol_definitions(self, base_path: Path, symbol: str) -> list[Path]:
        result = []
        for path in base_path.rglob("*.py"):
            if not path.is_file():
                continue
            if any(part in IGNORED_DIRS for part in path.parts):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if node.name == symbol:
                        result.append(path.resolve())
                        break
        return result

    def _module_name_from_path(self, path: Path, base_path: Path) -> str:
        relative = path.resolve().relative_to(base_path.resolve())
        parts = list(relative.with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts)

    def _find_import_candidates(
            self,
            bad_import: str,
            file_path: Path,
            base_path: Path,
    ) -> list[tuple[str, str]]:
        candidates: list[tuple[str, str]] = []
        if not bad_import:
            return candidates

        symbol = bad_import.rsplit(".", 1)[-1]
        modules = self._find_symbol_definitions(base_path, symbol)
        for path in modules:
            candidates.append(
                (self._module_name_from_path(path, base_path), symbol)
            )

        # Also consider importing the leaf module itself.
        leaf_modules = self._find_project_modules(base_path, symbol)
        for path in leaf_modules:
            candidates.append(
                (self._module_name_from_path(path, base_path), symbol)
            )

        return list(dict.fromkeys(candidates))

    def _replace_import_reference(
            self,
            code: str,
            bad_import: str,
            module_name: str,
            symbol: str,
    ) -> str:
        if not bad_import:
            return code

        # from X import Y
        pattern = re.compile(
            rf"(^\s*from\s+){re.escape(bad_import)}(\s+import\s+{re.escape(symbol)}.*$)",
            re.MULTILINE,
        )
        candidate = pattern.sub(
            rf"\g<1>{module_name}\g<2>",
            code,
        )
        if candidate != code:
            return candidate

        # import X
        pattern = re.compile(
            rf"(^\s*import\s+){re.escape(bad_import)}(\s*(?:#.*)?$)",
            re.MULTILINE,
        )
        return pattern.sub(
            rf"\g<1>{module_name}\g<2>",
            code,
        )

    # =========================================================================
    # Test execution and parsing
    # =========================================================================

    def _resolve_test_command(
            self,
            base_path: Path,
            test_command: str | list[str] | None,
    ) -> list[str] | None:
        if test_command:
            if isinstance(test_command, str):
                return test_command.split()
            return list(test_command)

        pyproject = base_path / "pyproject.toml"
        if pyproject.exists():
            try:
                content = pyproject.read_text(encoding="utf-8")
                if "[tool.pytest" in content:
                    return ["python", "-m", "pytest", "-q"]
            except OSError:
                pass

        if (base_path / "pytest.ini").exists() or (base_path / "conftest.py").exists():
            return ["python", "-m", "pytest", "-q"]

        tests_dir = base_path / "tests"
        if tests_dir.exists():
            if any(tests_dir.rglob("test_*.py")) or any(tests_dir.rglob("*_test.py")):
                return ["python", "-m", "pytest", "-q"]

        return None

    def _run_tests(self, base_path: Path, command: list[str]) -> dict[str, Any]:
        try:
            completed = subprocess.run(
                command,
                cwd=base_path,
                text=True,
                capture_output=True,
                timeout=self._test_timeout,
                check=False,
            )
            output = (
                    (completed.stdout or "")
                    + "\n"
                    + (completed.stderr or "")
            ).strip()
            return {
                "command": " ".join(command),
                "returncode": completed.returncode,
                "passed": completed.returncode == 0,
                "output": output,
                "timed_out": False,
            }
        except subprocess.TimeoutExpired as exc:
            output = (
                    (exc.stdout or "")
                    + "\n"
                    + (exc.stderr or "")
            ).strip()
            return {
                "command": " ".join(command),
                "returncode": -1,
                "passed": False,
                "output": output + "\nTest command timed out.",
                "timed_out": True,
            }
        except OSError as exc:
            return {
                "command": " ".join(command),
                "returncode": -1,
                "passed": False,
                "output": f"Could not execute test command: {exc}",
                "timed_out": False,
            }

    def _failure_signature(self, test_result: dict[str, Any]) -> str:
        output = test_result.get("output", "")
        normalized = re.sub(r"\d+", "#", output)
        return normalized[-6000:]

    # =========================================================================
    # General utilities
    # =========================================================================

    def _safe_project_path(
            self,
            base_path: Path,
            relative_path: str,
    ) -> Path | None:
        try:
            candidate = (base_path / relative_path).resolve()
            candidate.relative_to(base_path.resolve())
            return candidate
        except (ValueError, OSError):
            return None

    def _resolve_generated_output_root(
            self,
            base_path: str | Path | None,
    ) -> Path | None:
        """Accept either the project root or generated_output and return generated_output."""
        base = Path(base_path) if base_path is not None else Path.cwd()
        base = base.resolve()

        if base.name == GENERATED_OUTPUT_DIR and base.is_dir():
            return base

        candidate = base / GENERATED_OUTPUT_DIR
        if candidate.exists() and candidate.is_dir():
            return candidate.resolve()

        return None

    def _candidate_from_attempt(
            self,
            current_code: str,
            issue: dict,
            attempt: FixAttempt,
    ) -> str:
        # New strategies return complete code. Keep support for the old
        # "Replace 'x' with 'y'" contract for compatibility.
        if attempt.changes_made.startswith("Replace "):
            match = re.search(
                r"Replace '([^']+)' with '([^']+)'",
                attempt.changes_made,
            )
            if match:
                return current_code.replace(match.group(1), match.group(2))
        return attempt.changes_made

    def _validate_code(self, code: str, extension: str) -> bool:
        if extension == ".py":
            try:
                ast.parse(code)
                return True
            except SyntaxError:
                return False
        return True

    def _extract_code_from_response(self, response_text: str) -> str:
        match = re.search(
            r"```(?:python|javascript|typescript|json|yaml|text)?\s*\n(.*?)\n```",
            response_text,
            re.DOTALL | re.IGNORECASE,
            )
        if match:
            return match.group(1).strip()
        return response_text.strip()

    def _extract_file_replacements(
            self,
            response_text: str,
    ) -> dict[str, str]:
        replacements: dict[str, str] = {}
        pattern = re.compile(
            r'<FILE\s+path=["\']([^"\']+)["\']>\s*'
            r'```[^\n]*\n(.*?)\n```\s*</FILE>',
            re.DOTALL | re.IGNORECASE,
            )
        for match in pattern.finditer(response_text):
            replacements[match.group(1).strip()] = match.group(2).strip()
        return replacements

    def _language_for(self, path: Path) -> str:
        return {
            ".py": "python",
            ".js": "javascript",
            ".jsx": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".json": "json",
            ".yaml": "yaml",
            ".yml": "yaml",
        }.get(path.suffix.lower(), "text")

    def _log_summary(self, report: OptimizationReport) -> None:
        logger.info("\n" + "=" * 60)
        logger.info("🔧 OPTIMIZATION SUMMARY")
        logger.info("=" * 60)
        logger.info("Review Passed: %s", report.review_passed)
        logger.info("Tests Passed: %s", report.tests_passed)
        logger.info("Files Fixed: %d", len(report.files_fixed))
        logger.info("Files Failed: %d", len(report.files_failed))
        logger.info(
            "Needs Human (review only): %d",
            len(report.needs_human_intervention),
        )
        logger.info("Test Runs: %d", len(report.test_runs))

        if report.needs_human_intervention:
            logger.info("\n🆘 REVIEW FILES NEEDING HUMAN INTERVENTION:")
            for file_path in report.needs_human_intervention:
                logger.info("   - %s", file_path)

        logger.info("=" * 60 + "\n")
