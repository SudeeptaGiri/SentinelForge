"""Code Review Agent with Normal and Epic Review Modes + Import Validation.

Reviews generated code in generated_output/src AND generated_output/tests.
Validates imports and catches ModuleNotFoundError issues.

Normal Mode: Tech Lead with 10 years experience - best practices, SOLID principles, no duplication
Epic Mode: Senior Architect - architectural flaws, security vulnerabilities, design issues
Import Check: Validates all imports resolve correctly

Returns empty report if no issues found (0 issues is valid).
"""

from __future__ import annotations

import ast
import importlib.util
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src.utils.genai_client import build_genai_client

logger = logging.getLogger(__name__)

# Configuration
REVIEW_TARGET_DIRS = [
    "generated_output/src",    # Source code
    "generated_output/tests"   # Test files for import validation
]


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class ReviewIssue:
    """Single code review issue."""
    
    severity: str  # "info", "warning", "critical"
    category: str  # "best_practice", "solid", "security", "architecture", "duplication"
    message: str
    file_path: str
    line: int = 0
    suggestion: str = ""

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "category": self.category,
            "message": self.message,
            "file_path": self.file_path,
            "line": self.line,
            "suggestion": self.suggestion
        }


@dataclass
class ReviewReport:
    """Review findings from Normal and Epic modes."""
    
    normal_issues: list[ReviewIssue] = field(default_factory=list)
    epic_issues: list[ReviewIssue] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def all_issues(self) -> list[ReviewIssue]:
        return self.normal_issues + self.epic_issues

    def critical_count(self) -> int:
        return sum(1 for i in self.all_issues if i.severity == "critical")

    def warning_count(self) -> int:
        return sum(1 for i in self.all_issues if i.severity == "warning")

    def passes_quality_gate(self, max_critical: int = 0, max_warnings: int = 5) -> bool:
        """Check if code passes quality gate."""
        return self.critical_count() <= max_critical and self.warning_count() <= max_warnings

    def to_dict(self) -> dict:
        """Export report as dictionary."""
        return {
            "timestamp": self.timestamp,
            "summary": {
                "total_issues": len(self.all_issues),
                "critical": self.critical_count(),
                "warnings": self.warning_count(),
                "passed": self.passes_quality_gate()
            },
            "normal_review": {
                "count": len(self.normal_issues),
                "issues": [i.to_dict() for i in self.normal_issues]
            },
            "epic_review": {
                "count": len(self.epic_issues),
                "issues": [i.to_dict() for i in self.epic_issues]
            }
        }


# =============================================================================
# Review Agent
# =============================================================================

class ReviewAgent:
    """Reviews code in generated_output/src with Normal and Epic modes.
    
    Normal Mode: Tech Lead review (10 years exp)
      - Best practices
      - SOLID principles
      - Code duplication
      - Clean code principles
    
    Epic Mode: Senior Architect review
      - Architectural flaws
      - Security vulnerabilities
      - Design issues
      - Scalability concerns
    """

    SUPPORTED_EXTENSIONS = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".java": "java",
        ".go": "go",
    }

    def __init__(self, model: str = "gemini-2.0-flash-exp"):
        """Initialize review agent."""
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
            logger.info(f"ReviewAgent initialized with {self._model}")

    @property
    def enabled(self) -> bool:
        """Check if agent is enabled."""
        return self._client is not None

    # =========================================================================
    # Public Interface
    # =========================================================================

    def review_code(
            self,
            base_path: str | Path = None,
            mode: str = "both",
            check_imports: bool = True
    ) -> ReviewReport:
        """Review code in generated_output directories.
        
        Args:
            base_path: Base project path (defaults to current directory)
            mode: "normal", "epic", or "both"
            check_imports: Whether to validate imports
            
        Returns:
            ReviewReport (can be empty if no issues found)
        """
        if not self.enabled:
            logger.warning("ReviewAgent disabled - ADC auth required")
            return ReviewReport()

        # Determine base path
        if base_path is None:
            base_path = Path.cwd()
        else:
            base_path = Path(base_path)
        
        report = ReviewReport()
        all_code_files = {}
        
        # Collect files from all review directories
        for target_dir in REVIEW_TARGET_DIRS:
            review_dir = base_path / target_dir
            if review_dir.exists():
                logger.info(f"🔍 Scanning: {review_dir}")
                files = self._collect_code_files(review_dir)
                # Store with full relative path from base
                for file_path, content in files.items():
                    full_path = str(Path(target_dir) / file_path)
                    all_code_files[full_path] = content
        
        if not all_code_files:
            logger.info("No code files to review")
            return ReviewReport()

        logger.info(f"📁 Found {len(all_code_files)} files total")

        # Check imports first (catches critical issues)
        if check_imports:
            logger.info("🔍 Validating imports...")
            import_issues = self._validate_imports(all_code_files, base_path)
            if import_issues:
                report.epic_issues.extend(import_issues)
                logger.info(f"   Found {len(import_issues)} import issues")

        # Normal review
        if mode in ("normal", "both"):
            logger.info("📋 Running Normal Review (Tech Lead mode)...")
            report.normal_issues = self._normal_review(all_code_files)
            logger.info(f"   Found {len(report.normal_issues)} issues")

        # Epic review
        if mode in ("epic", "both"):
            logger.info("🔒 Running Epic Review (Architect mode)...")
            epic_issues = self._epic_review(all_code_files)
            report.epic_issues.extend(epic_issues)
            logger.info(f"   Found {len(epic_issues)} security/architecture issues")

        # Save report
        self._save_report(report, base_path / "generated_output")
        self._log_summary(report)

        return report

    # =========================================================================
    # File Collection
    # =========================================================================

    def _collect_code_files(self, review_dir: Path) -> dict[str, str]:
        """Collect code files from review directory."""
        code_files = {}
        
        for file_path in review_dir.rglob("*"):
            if file_path.is_file() and file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                try:
                    relative_path = file_path.relative_to(review_dir)
                    code_files[str(relative_path)] = file_path.read_text(encoding='utf-8')
                except Exception as e:
                    logger.warning(f"Could not read {file_path}: {e}")
        
        return code_files

    # =========================================================================
    # Import Validation
    # =========================================================================

    def _validate_imports(self, code_files: dict[str, str], base_path: Path) -> list[ReviewIssue]:
        """Validate that all imports can be resolved."""
        issues = []
        
        for file_path, content in code_files.items():
            if not file_path.endswith('.py'):
                continue
            
            try:
                # Parse imports from file
                tree = ast.parse(content, filename=file_path)
                imports = self._extract_imports(tree)
                
                # Check each import
                for import_line, module_name in imports:
                    if not self._can_resolve_import(module_name, file_path, base_path):
                        # Try to suggest correct import
                        suggestion = self._suggest_import_fix(module_name, file_path, base_path)
                        
                        issues.append(ReviewIssue(
                            severity="critical",
                            category="import_error",
                            message=f"Cannot import '{module_name}' - module not found",
                            file_path=file_path,
                            line=import_line,
                            suggestion=suggestion
                        ))
                        
            except SyntaxError as e:
                issues.append(ReviewIssue(
                    severity="critical",
                    category="syntax_error",
                    message=f"Syntax error: {str(e)}",
                    file_path=file_path,
                    line=e.lineno or 0,
                    suggestion="Fix syntax error before proceeding"
                ))
            except Exception as e:
                logger.warning(f"Could not validate imports in {file_path}: {e}")
        
        return issues

    def _extract_imports(self, tree: ast.AST) -> list[tuple[int, str]]:
        """Extract all import statements from AST."""
        imports = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append((node.lineno, alias.name))
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append((node.lineno, node.module))
        
        return imports

    def _can_resolve_import(self, module_name: str, file_path: str, base_path: Path) -> bool:
        """Check if an import can be resolved."""
        # Skip standard library and third-party packages
        if module_name.split('.')[0] in ['pytest', 'flask', 'os', 'sys', 'json', 'pathlib', 'datetime']:
            return True
        
        # Check if it's a relative import within generated_output
        if module_name.startswith('src.') or module_name.startswith('app.'):
            # Try to find the actual file
            possible_paths = [
                base_path / "generated_output" / module_name.replace('.', '/') + '.py',
                base_path / "generated_output" / module_name.replace('.', '/') / '__init__.py',
            ]
            
            return any(p.exists() for p in possible_paths)
        
        return True  # Assume other imports are okay

    def _suggest_import_fix(self, module_name: str, file_path: str, base_path: Path) -> str:
        """Suggest correct import based on file structure."""
        # Common fixes
        if module_name.startswith('app.'):
            # Check if src.app exists
            app_file = base_path / "generated_output" / "src" / "app.py"
            if app_file.exists():
                fixed_import = module_name.replace('app.', 'src.app.')
                return f"Change import to: from {fixed_import} OR from src.app import ..."
        
        # Look for similar files
        gen_output = base_path / "generated_output"
        if gen_output.exists():
            src_files = list(gen_output.rglob("*.py"))
            module_parts = module_name.split('.')
            target = module_parts[-1]
            
            # Find files with matching names
            matches = [f for f in src_files if f.stem == target]
            if matches:
                # Suggest first match
                rel_path = matches[0].relative_to(gen_output)
                suggested = str(rel_path).replace('/', '.').replace('.py', '')
                return f"Try: from {suggested} import ..."
        
        return "Check file structure and ensure module exists"

    # =========================================================================
    # Normal Review (Tech Lead)
    # =========================================================================

    def _normal_review(self, code_files: dict[str, str]) -> list[ReviewIssue]:
        """Normal review: Tech Lead with 10 years experience."""
        all_issues = []

        for file_path, code in code_files.items():
            language = self._get_language(file_path)

            prompt = f"""You are a Tech Lead with 10 years of experience reviewing code.

Review this {language} file and identify issues related to:
1. Best practices violations
2. SOLID principles violations
3. Code duplication
4. Poor naming/structure
5. Missing error handling

File: {file_path}

```{language}
{code}
```

Return ONLY a JSON array of issues (or empty array [] if no issues):
[
  {{
    "severity": "info|warning|critical",
    "category": "best_practice|solid|duplication|naming|error_handling",
    "message": "Clear description",
    "line": line_number,
    "suggestion": "How to fix"
  }}
]

If code is perfect, return: []
"""

            try:
                response = self._client.models.generate_content(
                    model=self._model,
                    contents=prompt
                )
                
                issues_json = self._extract_json(response.text)
                
                for issue_data in issues_json:
                    all_issues.append(ReviewIssue(
                        severity=issue_data.get("severity", "info"),
                        category=issue_data.get("category", "best_practice"),
                        message=issue_data.get("message", ""),
                        file_path=file_path,
                        line=issue_data.get("line", 0),
                        suggestion=issue_data.get("suggestion", "")
                    ))
                    
            except Exception as e:
                logger.error(f"Error in normal review of {file_path}: {e}")
                
        return all_issues

    # =========================================================================
    # Epic Review (Architect)
    # =========================================================================

    def _epic_review(self, code_files: dict[str, str]) -> list[ReviewIssue]:
        """Epic review: Senior Architect security and design analysis."""
        all_issues = []

        for file_path, code in code_files.items():
            language = self._get_language(file_path)

            prompt = f"""You are a Senior Architect reviewing code for security and design flaws.

Review this {language} file and identify:
1. Security vulnerabilities (SQL injection, XSS, secrets in code, etc.)
2. Architectural flaws
3. Design pattern violations
4. Scalability concerns
5. Critical logic errors

File: {file_path}

```{language}
{code}
```

Return ONLY a JSON array of issues (or empty array [] if no issues):
[
  {{
    "severity": "warning|critical",
    "category": "security|architecture|design|scalability|logic",
    "message": "Clear description of the flaw",
    "line": line_number,
    "suggestion": "How to fix"
  }}
]

If no security or architectural issues, return: []
"""

            try:
                response = self._client.models.generate_content(
                    model=self._model,
                    contents=prompt
                )
                
                issues_json = self._extract_json(response.text)
                
                for issue_data in issues_json:
                    all_issues.append(ReviewIssue(
                        severity=issue_data.get("severity", "warning"),
                        category=issue_data.get("category", "security"),
                        message=issue_data.get("message", ""),
                        file_path=file_path,
                        line=issue_data.get("line", 0),
                        suggestion=issue_data.get("suggestion", "")
                    ))
                    
            except Exception as e:
                logger.error(f"Error in epic review of {file_path}: {e}")
                
        return all_issues

    # =========================================================================
    # Utilities
    # =========================================================================

    def _get_language(self, file_path: str) -> str:
        """Get language from file extension."""
        return self.SUPPORTED_EXTENSIONS.get(Path(file_path).suffix.lower(), "text")

    def _extract_json(self, text: str) -> list[dict]:
        """Extract JSON array from response."""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            import re
            # Try to find JSON in markdown
            match = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', text, re.DOTALL)
            if match:
                return json.loads(match.group(1))
            # Try to find raw array
            match = re.search(r'\[.*?\]', text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except:
                    pass
            return []

    def _save_report(self, report: ReviewReport, review_dir: Path) -> None:
        """Save review report."""
        report_file = review_dir.parent / "REVIEW_REPORT.json"
        report_file.write_text(json.dumps(report.to_dict(), indent=2), encoding='utf-8')
        logger.info(f"📄 Report saved: {report_file}")

    def _log_summary(self, report: ReviewReport) -> None:
        """Log review summary."""
        logger.info("\n" + "="*60)
        logger.info("📊 REVIEW SUMMARY")
        logger.info("="*60)
        logger.info(f"Total Issues: {len(report.all_issues)}")
        logger.info(f"  🔴 Critical: {report.critical_count()}")
        logger.info(f"  🟡 Warnings: {report.warning_count()}")
        logger.info(f"\nQuality Gate: {'✅ PASS' if report.passes_quality_gate() else '⚠️ FAIL'}")
        logger.info("="*60 + "\n")
