"""Code Review Agent with Normal and Epic Review Modes.

Description: Reviews generated code for best practices, flaws, and security issues.
Need: Automated code review before testing to catch issues early.
Motive: Ensure code quality and security without manual review overhead.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

from src.utils.genai_client import build_genai_client

logger = logging.getLogger(__name__)


class ReviewIssue:
    """Represents a single code review issue."""
    
    def __init__(self, severity: str, category: str, message: str, file_path: str, line: int = 0):
        self.severity = severity  # "info", "warning", "critical"
        self.category = category  # "best_practice", "security", "logic", "performance"
        self.message = message
        self.file_path = file_path
        self.line = line


class ReviewReport:
    """Contains all review findings."""
    
    def __init__(self):
        self.normal_issues: list[ReviewIssue] = []
        self.epic_issues: list[ReviewIssue] = []
    
    def has_issues(self) -> bool:
        return len(self.normal_issues) > 0 or len(self.epic_issues) > 0
    
    def critical_count(self) -> int:
        return sum(1 for i in self.normal_issues + self.epic_issues if i.severity == "critical")


class ReviewAgent:
    """Reviews generated code using Gemini AI with two modes: Normal and Epic."""
    
    def __init__(self, model: str = "gemini-2.5-pro"):
        self._model = model
        self._client = None
        self._auth_mode = None
        
        # Load config
        config_path = Path(__file__).parents[2] / "config" / "agent_config.yaml"
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f)
                agent_config = config.get("agents", {}).get("review_agent", {})
                self._model = agent_config.get("model", self._model)
        
        # Initialize Gemini client
        self._client, self._auth_mode, _ = build_genai_client()
        if self._auth_mode != "adc":
            self._client = None
        
        if self._client:
            logger.info(f"ReviewAgent initialized with {self._model} using {self._auth_mode} auth")
    
    @property
    def enabled(self) -> bool:
        return self._client is not None
    
    def review_code(self, code_path: str | Path, mode: str = "both") -> ReviewReport:
        """Review code with normal and/or epic reviewer.
        
        Args:
            code_path: Path to the code directory
            mode: "normal", "epic", or "both"
            
        Returns:
            ReviewReport with all findings
        """
        code_path = Path(code_path)
        report = ReviewReport()
        
        if not self.enabled:
            logger.warning("ReviewAgent disabled - ADC auth required")
            return report
        
        logger.info(f"Starting code review in '{mode}' mode...")
        
        # Collect code files
        code_files = self._collect_code_files(code_path)
        
        if mode in ("normal", "both"):
            report.normal_issues = self._normal_review(code_files)
            logger.info(f"Normal review found {len(report.normal_issues)} issues")
        
        if mode in ("epic", "both"):
            report.epic_issues = self._epic_review(code_files)
            logger.info(f"Epic review found {len(report.epic_issues)} issues")
        
        # Save review report to file
        self._save_review_report(report, code_path)
        
        return report
    
    def _save_review_report(self, report: ReviewReport, code_path: Path) -> None:
        """Save review report to a text file for audit trail."""
        report_file = code_path / "REVIEW_REPORT.txt"
        
        lines = ["CODE REVIEW REPORT", "=" * 70, ""]
        
        if report.normal_issues:
            lines.append(f"NORMAL REVIEW - {len(report.normal_issues)} issues found:")
            lines.append("-" * 70)
            for i, issue in enumerate(report.normal_issues, 1):
                lines.append(f"\n{i}. [{issue.severity.upper()}] {issue.category}")
                lines.append(f"   File: {issue.file_path}")
                if issue.line:
                    lines.append(f"   Line: {issue.line}")
                lines.append(f"   Issue: {issue.message}")
            lines.append("")
        
        if report.epic_issues:
            lines.append(f"\nEPIC REVIEW - {len(report.epic_issues)} issues found:")
            lines.append("-" * 70)
            for i, issue in enumerate(report.epic_issues, 1):
                lines.append(f"\n{i}. [{issue.severity.upper()}] {issue.category}")
                lines.append(f"   File: {issue.file_path}")
                if issue.line:
                    lines.append(f"   Line: {issue.line}")
                lines.append(f"   Issue: {issue.message}")
            lines.append("")
        
        lines.append("\n" + "=" * 70)
        lines.append(f"Total Issues: {len(report.normal_issues) + len(report.epic_issues)}")
        lines.append(f"Critical Issues: {report.critical_count()}")
        lines.append("=" * 70)
        
        report_file.write_text("\n".join(lines))
        logger.info(f"✅ Review report saved to {report_file}")
    
    def _collect_code_files(self, code_path: Path) -> dict[str, str]:
        """Collect all Python files for review."""
        code_files = {}
        for py_file in code_path.rglob("*.py"):
            if "__pycache__" not in str(py_file):
                relative_path = py_file.relative_to(code_path)
                code_files[str(relative_path)] = py_file.read_text()
        return code_files
    
    def _normal_review(self, code_files: dict[str, str]) -> list[ReviewIssue]:
        """Normal reviewer: Check code quality and best practices."""
        issues = []
        
        for file_path, code in code_files.items():
            prompt = f"""You are a code reviewer. Review this Python code for:
1. Code quality and readability
2. Best practices (PEP 8, naming conventions)
3. Error handling
4. Documentation
5. Maintainability

Code file: {file_path}
```python
{code}
```

Return findings as JSON array:
[{{"severity": "info|warning|critical", "category": "best_practice|performance", "message": "description", "line": 0}}]

Return empty array [] if no issues found. Return ONLY the JSON, no explanations."""
            
            try:
                response = self._client.models.generate_content(model=self._model, contents=prompt)
                issues.extend(self._parse_review_response(response.text, file_path))
            except Exception as e:
                logger.error(f"Normal review failed for {file_path}: {e}")
        
        return issues
    
    def _epic_review(self, code_files: dict[str, str]) -> list[ReviewIssue]:
        """Epic reviewer: Deep analysis for security flaws and logic errors."""
        issues = []
        
        for file_path, code in code_files.items():
            prompt = f"""You are an expert security and logic reviewer. Deep analyze this code for:
1. Security vulnerabilities (injection, XSS, CSRF, etc.)
2. Logic errors and edge cases
3. Race conditions
4. Input validation issues
5. Hidden flaws and anti-patterns

Code file: {file_path}
```python
{code}
```

Return findings as JSON array:
[{{"severity": "info|warning|critical", "category": "security|logic", "message": "description", "line": 0}}]

Return empty array [] if no issues found. Return ONLY the JSON, no explanations."""
            
            try:
                response = self._client.models.generate_content(model=self._model, contents=prompt)
                issues.extend(self._parse_review_response(response.text, file_path))
            except Exception as e:
                logger.error(f"Epic review failed for {file_path}: {e}")
        
        return issues
    
    def _parse_review_response(self, response: str, file_path: str) -> list[ReviewIssue]:
        """Parse Gemini response into ReviewIssue objects."""
        import json
        import re
        
        # Extract JSON from response
        response = response.strip()
        if "```json" in response:
            response = response.split("```json")[1].split("```")[0].strip()
        elif "```" in response:
            response = response.split("```")[1].split("```")[0].strip()
        
        # Remove potential markdown
        response = re.sub(r'^json\s*', '', response, flags=re.IGNORECASE)
        
        try:
            findings = json.loads(response)
            if not isinstance(findings, list):
                return []
            
            issues = []
            for finding in findings:
                if isinstance(finding, dict):
                    issues.append(ReviewIssue(
                        severity=finding.get("severity", "info"),
                        category=finding.get("category", "unknown"),
                        message=finding.get("message", ""),
                        file_path=file_path,
                        line=finding.get("line", 0)
                    ))
            return issues
        except json.JSONDecodeError:
            logger.warning(f"Could not parse review response for {file_path}")
            return []
    
    def generate_fix_suggestions(self, report: ReviewReport, code_path: Path) -> dict[str, str]:
        """Generate fix suggestions for critical issues."""
        if not report.has_issues():
            return {}
        
        critical_issues = [i for i in report.normal_issues + report.epic_issues if i.severity == "critical"]
        
        if not critical_issues:
            return {}
        
        fixes = {}
        for issue in critical_issues:
            file_path = code_path / issue.file_path
            if not file_path.exists():
                continue
            
            code = file_path.read_text()
            prompt = f"""Fix this critical issue in the code:

Issue: {issue.message}
Category: {issue.category}
File: {issue.file_path}

Current code:
```python
{code}
```

Return the COMPLETE fixed code. No explanations."""
            
            try:
                response = self._client.models.generate_content(model=self._model, contents=prompt)
                fixed_code = response.text.strip()
                
                if "```python" in fixed_code:
                    fixed_code = fixed_code.split("```python")[1].split("```")[0].strip()
                elif "```" in fixed_code:
                    fixed_code = fixed_code.split("```")[1].split("```")[0].strip()
                
                fixes[issue.file_path] = fixed_code
                logger.info(f"Generated fix for {issue.file_path}")
            except Exception as e:
                logger.error(f"Failed to generate fix for {issue.file_path}: {e}")
        
        return fixes
