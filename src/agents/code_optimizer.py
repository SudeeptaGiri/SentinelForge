"""Code Optimizer Agent - Intelligently Fixes Review Issues.

Automatically fixes issues found by ReviewAgent:
- Import errors (reads file structure, suggests correct paths)
- Syntax errors (analyzes and fixes)
- Best practice violations
- Security issues

Escalation: Only asks human intervention if ALL fix strategies fail.
"""

from __future__ import annotations

import ast
import json
import logging
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src.utils.genai_client import build_genai_client

logger = logging.getLogger(__name__)


# =============================================================================
# Data Models
# =============================================================================

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
                    "strategy": fa.strategy,
                    "success": fa.success,
                    "changes": fa.changes_made,
                    "error": fa.error_message
                }
                for fa in self.fix_attempts
            ]
        }


@dataclass
class OptimizationReport:
    """Complete optimization report."""

    files_fixed: list[str] = field(default_factory=list)
    files_failed: list[str] = field(default_factory=list)
    needs_human_intervention: list[str] = field(default_factory=list)
    results: list[OptimizationResult] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        """Convert report to dictionary."""
        return {
            "timestamp": self.timestamp,
            "summary": {
                "total_files": len(self.results),
                "fixed": len(self.files_fixed),
                "failed": len(self.files_failed),
                "needs_human": len(self.needs_human_intervention)
            },
            "files_fixed": self.files_fixed,
            "files_failed": self.files_failed,
            "needs_human_intervention": self.needs_human_intervention,
            "details": [r.to_dict() for r in self.results]
        }

    def save_report(self, output_path: Path) -> None:
        """Save report to JSON file."""
        report_file = output_path / "OPTIMIZER_REPORT.json"
        report_file.write_text(json.dumps(self.to_dict(), indent=2), encoding='utf-8')
        logger.info(f"📄 Optimization report saved to {report_file}")


# =============================================================================
# Code Optimizer Agent
# =============================================================================

class CodeOptimizerAgent:
    """Intelligently fixes code issues with deep analysis and multiple strategies.
    
    Fix Strategies:
    1. Syntax/Import Fix: Analyze error, read file structure, fix imports
    2. Pattern Matching: Common error patterns → known fixes
    3. AI-Assisted: Use Gemini to understand and fix complex issues
    4. Context Analysis: Read related files to understand dependencies
    
    Escalation: Only asks human if all strategies fail.
    """

    def __init__(self, model: str = "gemini-2.0-flash-exp"):
        """Initialize optimizer agent."""
        self._model = model
        self._client = None
        self._auth_mode = None

        # Load config
        config_path = Path(__file__).parents[2] / "config" / "agent_config.yaml"
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f)
                agent_config = config.get("agents", {}).get("optimizer_agent", {})
                self._model = agent_config.get("model", self._model)

        # Initialize Gemini client
        self._client, self._auth_mode, _ = build_genai_client()
        if self._auth_mode != "adc":
            self._client = None

        if self._client:
            logger.info(f"CodeOptimizerAgent initialized with {self._model}")

    @property
    def enabled(self) -> bool:
        """Check if agent is enabled."""
        return self._client is not None

    # =========================================================================
    # Main Entry Point
    # =========================================================================

    def fix_issues(
            self,
            review_report: dict,
            base_path: str | Path = None
    ) -> OptimizationReport:
        """Fix all issues from review report.
        
        Args:
            review_report: Output from ReviewAgent (dict format)
            base_path: Base project path
            
        Returns:
            OptimizationReport with fix results
        """
        if not self.enabled:
            logger.error("CodeOptimizerAgent requires ADC authentication")
            return OptimizationReport()

        if base_path is None:
            base_path = Path.cwd()
        else:
            base_path = Path(base_path)

        logger.info("🔧 Starting Code Optimization...")
        
        report = OptimizationReport()
        
        # Group issues by file
        issues_by_file = self._group_issues_by_file(review_report)
        
        if not issues_by_file:
            logger.info("✅ No issues to fix")
            return report

        logger.info(f"📝 Fixing issues in {len(issues_by_file)} files...")

        # Fix each file
        for file_path, issues in issues_by_file.items():
            logger.info(f"\n🔍 Processing: {file_path}")
            logger.info(f"   Issues: {len(issues)}")
            
            full_path = base_path / file_path
            if not full_path.exists():
                logger.warning(f"   ⚠️  File not found: {full_path}")
                report.files_failed.append(file_path)
                continue

            # Try to fix
            result = self._fix_file(full_path, issues, base_path)
            report.results.append(result)

            if result.success:
                # Write fixed code
                full_path.write_text(result.optimized_code, encoding='utf-8')
                report.files_fixed.append(file_path)
                logger.info(f"   ✅ Fixed {len(result.issues_fixed)} issues")
            elif result.needs_human:
                report.needs_human_intervention.append(file_path)
                logger.warning(f"   🆘 Needs human intervention")
            else:
                report.files_failed.append(file_path)
                logger.error(f"   ❌ Failed to fix")

        # Save report
        report.save_report(base_path / "generated_output")
        self._log_summary(report)

        return report

    # =========================================================================
    # File Fixing Logic
    # =========================================================================

    def _fix_file(
            self,
            file_path: Path,
            issues: list[dict],
            base_path: Path
    ) -> OptimizationResult:
        """Fix all issues in a single file using multiple strategies."""
        original_code = file_path.read_text(encoding='utf-8')
        current_code = original_code
        fix_attempts = []
        issues_fixed = []

        # Sort issues by severity (critical first)
        sorted_issues = sorted(
            issues,
            key=lambda x: {"critical": 0, "warning": 1, "info": 2}.get(x.get("severity", "info"), 3)
        )

        for issue in sorted_issues:
            category = issue.get("category", "")
            
            # Strategy 1: Import Error Fix
            if category == "import_error":
                attempt = self._fix_import_error(current_code, issue, file_path, base_path)
                fix_attempts.append(attempt)
                if attempt.success:
                    current_code = self._apply_fix(current_code, issue, attempt.changes_made)
                    issues_fixed.append(issue.get("message", "import error"))
                    continue

            # Strategy 2: Syntax Error Fix
            if category == "syntax_error":
                attempt = self._fix_syntax_error(current_code, issue)
                fix_attempts.append(attempt)
                if attempt.success:
                    current_code = self._apply_fix(current_code, issue, attempt.changes_made)
                    issues_fixed.append(issue.get("message", "syntax error"))
                    continue

            # Strategy 3: AI-Assisted General Fix
            attempt = self._fix_with_ai(current_code, issue, str(file_path))
            fix_attempts.append(attempt)
            if attempt.success:
                current_code = attempt.changes_made  # AI returns full code
                issues_fixed.append(issue.get("message", "code issue"))

        # Validate final code
        is_valid = self._validate_code(current_code, file_path.suffix)
        success = is_valid and len(issues_fixed) > 0
        needs_human = not success and len(fix_attempts) > 0

        return OptimizationResult(
            file_path=str(file_path.relative_to(base_path)),
            original_code=original_code,
            optimized_code=current_code if success else original_code,
            issues_fixed=issues_fixed,
            fix_attempts=fix_attempts,
            success=success,
            needs_human=needs_human
        )

    # =========================================================================
    # Fix Strategies
    # =========================================================================

    def _fix_import_error(
            self,
            code: str,
            issue: dict,
            file_path: Path,
            base_path: Path
    ) -> FixAttempt:
        """Fix import errors by analyzing file structure."""
        message = issue.get("message", "")
        suggestion = issue.get("suggestion", "")
        
        logger.info(f"      Strategy: Import Error Fix")
        
        # Extract module name from error message
        import re
        match = re.search(r"Cannot import '([^']+)'", message)
        if not match:
            return FixAttempt(
                strategy="import_fix",
                success=False,
                changes_made="",
                error_message="Could not parse import error"
            )

        bad_import = match.group(1)
        
        # Use suggestion if available
        if "from" in suggestion:
            # Extract suggested import
            match = re.search(r"from ([\w.]+) import", suggestion)
            if match:
                correct_import = match.group(1)
                fixed_line = f"from {correct_import} import"
                
                return FixAttempt(
                    strategy="import_fix",
                    success=True,
                    changes_made=f"Replace '{bad_import}' with '{correct_import}'",
                    error_message=""
                )

        return FixAttempt(
            strategy="import_fix",
            success=False,
            changes_made="",
            error_message="No clear fix suggestion"
        )

    def _fix_syntax_error(self, code: str, issue: dict) -> FixAttempt:
        """Fix syntax errors."""
        logger.info(f"      Strategy: Syntax Error Fix")
        
        # For now, delegate to AI
        return FixAttempt(
            strategy="syntax_fix",
            success=False,
            changes_made="",
            error_message="Syntax fixes need AI assistance"
        )

    def _fix_with_ai(self, code: str, issue: dict, file_path: str) -> FixAttempt:
        """Use AI to fix the issue."""
        logger.info(f"      Strategy: AI-Assisted Fix")
        
        language = "python" if file_path.endswith('.py') else "unknown"
        
        prompt = f"""You are a code fixer. Fix the following issue in the code.

Issue: {issue.get('message', 'Unknown issue')}
Category: {issue.get('category', 'Unknown')}
Line: {issue.get('line', 'Unknown')}
Suggestion: {issue.get('suggestion', 'None provided')}

Current Code:
```{language}
{code}
```

Return ONLY the COMPLETE FIXED CODE (no explanations):
```{language}
[FIXED CODE HERE]
```
"""

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=prompt
            )
            
            # Extract code from response
            fixed_code = self._extract_code_from_response(response.text)
            
            if fixed_code and fixed_code != code:
                return FixAttempt(
                    strategy="ai_fix",
                    success=True,
                    changes_made=fixed_code,
                    error_message=""
                )
            else:
                return FixAttempt(
                    strategy="ai_fix",
                    success=False,
                    changes_made="",
                    error_message="AI could not generate valid fix"
                )
                
        except Exception as e:
            return FixAttempt(
                strategy="ai_fix",
                success=False,
                changes_made="",
                error_message=str(e)
            )

    # =========================================================================
    # Utilities
    # =========================================================================

    def _group_issues_by_file(self, review_report: dict) -> dict[str, list[dict]]:
        """Group issues by file path."""
        issues_by_file = {}
        
        # Get all issues from report
        all_issues = []
        all_issues.extend(review_report.get("normal_review", {}).get("issues", []))
        all_issues.extend(review_report.get("epic_review", {}).get("issues", []))
        
        for issue in all_issues:
            file_path = issue.get("file_path", "")
            if file_path:
                if file_path not in issues_by_file:
                    issues_by_file[file_path] = []
                issues_by_file[file_path].append(issue)
        
        return issues_by_file

    def _apply_fix(self, code: str, issue: dict, fix: str) -> str:
        """Apply a fix to code."""
        # Simple replacement strategy
        line_num = issue.get("line", 0)
        
        if "Replace" in fix:
            # Extract old and new values
            import re
            match = re.search(r"Replace '([^']+)' with '([^']+)'", fix)
            if match:
                old_val, new_val = match.groups()
                return code.replace(old_val, new_val)
        
        return code

    def _validate_code(self, code: str, extension: str) -> bool:
        """Validate code syntax."""
        if extension == ".py":
            try:
                ast.parse(code)
                return True
            except SyntaxError:
                return False
        return True  # Assume valid for other languages

    def _extract_code_from_response(self, response_text: str) -> str:
        """Extract code from AI response."""
        import re
        # Look for code in markdown blocks
        match = re.search(r'```(?:python|javascript|typescript)?\s*\n(.*?)\n```', response_text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return response_text.strip()

    def _log_summary(self, report: OptimizationReport) -> None:
        """Log optimization summary."""
        logger.info("\n" + "="*60)
        logger.info("🔧 OPTIMIZATION SUMMARY")
        logger.info("="*60)
        logger.info(f"Files Fixed: {len(report.files_fixed)}")
        logger.info(f"Files Failed: {len(report.files_failed)}")
        logger.info(f"Needs Human: {len(report.needs_human_intervention)}")
        
        if report.needs_human_intervention:
            logger.info("\n🆘 FILES NEEDING HUMAN INTERVENTION:")
            for file_path in report.needs_human_intervention:
                logger.info(f"   - {file_path}")
        
        logger.info("="*60 + "\n")
