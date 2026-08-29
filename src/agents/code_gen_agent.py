"""E2E App Code Generation & Refactoring Agent.

Description: Generates full app codebases (Greenfield) or refactors existing
             files (Ongoing Tasks/Migration).
Need: The core value of the system is turning an approved approach/spec into
      real, working code without manual authoring.
Motive: Automate the highest-effort part of the SDLC (writing/refactoring
        code) while producing a reviewable diff for the Gate 2 HITL check.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import yaml
from google.adk.agents import Agent

from src.mcp_servers.server_git import GitOperations
from src.models.schemas import CodeDiff, CostEstimate, MigrationPlan
from src.utils.genai_client import build_genai_client

logger = logging.getLogger(__name__)


class CodeGeneratorAgent:
    """Generates or refactors application code based on the approved spec/plan.

    Uses Gemini (via ADK patterns) to intelligently generate code changes
    that align with migration plans and infrastructure requirements.
    All generation is fully dynamic and driven by the plan specification.
    """

    def __init__(self, model: str = "gemini-2.5-pro", api_key: str | None = None):
        """Initialize the code generator agent.

        Args:
            model: Gemini model to use (default from agent_config.yaml)
            api_key: Deprecated for code-gen flow (ADC is required)
        """
        self._model = model
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self._client = None
        self._auth_mode = None
        self._project = None

        # Track last generation for integration with other agents
        self._last_code_diff: CodeDiff | None = None
        self._last_files_changed: list[str] = []
        self._last_branch: str | None = None
        self._last_diff: str | None = None

        # Load config
        config_path = Path(__file__).parents[2] / "config" / "agent_config.yaml"
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f)
                agent_config = config.get("agents", {}).get("code_gen_agent", {})
                self._model = agent_config.get("model", self._model)
                self.max_retries = agent_config.get("max_retries", 3)
        else:
            self.max_retries = 3

        # Initialize Gemini client and enforce ADC-only mode
        self._client, self._auth_mode, self._project = build_genai_client(api_key=self._api_key)
        if self._auth_mode != "adc":
            if self._api_key:
                logger.warning(
                    "CodeGeneratorAgent ignores API key auth; configure ADC instead"
                )
            self._client = None
            self._auth_mode = None
        if self._client:
            logger.info(
                "CodeGeneratorAgent initialized with %s using %s auth",
                self._model,
                self._auth_mode,
            )

        self._init_adk_agent()

    def _init_adk_agent(self) -> None:
        """Initializes the Google ADK Agent representation."""
        self.adk_agent = Agent(
            name="code_gen_agent",
            description="Generates or refactors application code files from an approved migration plan or concept.",
            model=self._model,
            instruction=(
                "You are the SentinelForge Code Generation Agent. "
                "Given an approved migration plan or feature request, generate complete, production-ready "
                "file contents (Dockerfile, application code, infra manifests) for human review.\n\n"
                "When asked to generate or refactor code for a migration, "
                "call `generate_migration_code_files(repo_path=..., target_platform=..., rationale=...)` directly "
                "and present the proposed files for review."
            ),
            tools=[generate_migration_code_files],
        )

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def enabled(self) -> bool:
        """Check if Gemini client is available."""
        return self._client is not None

    # =========================================================================
    # Public Interface - Main Entry Points
    # =========================================================================

    def generate_from_plan_file(
            self,
            plan_file_path: str,
            output_dir: str = "generated_output"
    ) -> dict:
        """Generate code from any Plan file - fully driven by plan contents.

        This is the main entry point for plan-based code generation.
        The plan determines what files to generate, what framework to use,
        and all implementation details.

        Args:
            plan_file_path: Path to plan file (YAML, JSON, or text)
            output_dir: Output directory for generated code

        Returns:
            Dictionary with:
                - output_path: Path to generated code
                - files_generated: List of generated filenames
                - plan_source: Original plan file path
                - deployable: Boolean indicating if generation succeeded
        """
        plan_path = Path(plan_file_path)

        if not plan_path.exists():
            raise FileNotFoundError(f"Plan file not found: {plan_file_path}")

        logger.info(f"📋 Generating code from plan: {plan_path.name}")

        # Read plan file based on extension
        plan_data = self._load_plan_file(plan_path)

        # Create output directory
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Generate all artifacts based on plan
        files_generated = self._generate_from_plan(plan_data, output_path)

        # Track for other agents
        self._last_files_changed = files_generated

        logger.info(f"✅ Generated {len(files_generated)} files in {output_dir}")

        return {
            "output_path": str(output_path),
            "files_generated": files_generated,
            "plan_source": str(plan_path),
            "deployable": len(files_generated) > 0
        }

    def generate_code_changes(
            self,
            plan: MigrationPlan,
            repo_path: str,
            branch_name: str | None = None,
    ) -> CodeDiff:
        """Generate code changes based on the approved migration plan.

        This method works with existing repositories and creates changes
        on a feature branch.

        Args:
            plan: Approved migration plan with target platform details
            repo_path: Path to the application repository
            branch_name: Optional branch name for the feature branch

        Returns:
            CodeDiff object with branch name, changed files, and diff text
        """
        logger.info(f"🔄 Generating code changes for migration to {plan.target_platform}")

        if not self.enabled:
            raise RuntimeError(
                "Code generation requires ADC-authenticated Gemini client; "
                "fallback generation is disabled"
            )

        repo_path = Path(repo_path)
        git = GitOperations(str(repo_path))
        resolved_branch_name = branch_name or self._derive_branch_name(plan)

        # Create feature branch
        if not git.create_branch(resolved_branch_name):
            raise RuntimeError(f"Failed to create branch: {resolved_branch_name}")

        # Convert plan to text for dynamic generation
        plan_dict = {
            "target_platform": plan.target_platform,
            "source_platform": getattr(plan, "source_platform", "unknown"),
            "migration_steps": getattr(plan, "steps", []),
            "requirements": getattr(plan, "requirements", []),
        }
        plan_text = yaml.dump(plan_dict, default_flow_style=False)

        # Determine what files need to be generated/modified
        files_to_generate = self._determine_migration_files(plan_text, repo_path)
        files_changed = []

        for file_info in files_to_generate:
            file_name = file_info["name"]
            file_purpose = file_info.get("purpose", "")
            action = file_info.get("action", "create")

            file_path = repo_path / file_name

            if action == "modify" and file_path.exists():
                # Modify existing file
                current_content = file_path.read_text()
                new_content = self._modify_file_for_migration(
                    plan_text, file_name, file_purpose, current_content
                )
            else:
                # Create new file
                new_content = self._generate_single_file(plan_text, file_name, file_purpose)

            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(new_content, encoding='utf-8')
            files_changed.append(file_name)
            logger.info(f"  📄 {'Modified' if action == 'modify' else 'Created'}: {file_name}")

        # Commit changes
        target_platform = getattr(plan, "target_platform", "target")
        commit_msg = f"feat: {target_platform} migration - {', '.join(files_changed)}"
        commit_sha = git.commit_changes(files_changed, commit_msg)

        if not commit_sha:
            raise RuntimeError("Failed to commit changes")

        # Get diff against repository default branch
        diff_text = git.get_diff(self._resolve_base_branch(repo_path))

        # Track for other agents
        self._last_branch = resolved_branch_name
        self._last_files_changed = files_changed
        self._last_diff = diff_text

        code_diff = CodeDiff(
            branch_name=resolved_branch_name,
            files_changed=files_changed,
            diff_text=diff_text or f"Added {len(files_changed)} file(s) for migration",
            unit_tests_added=[]
        )

        self._last_code_diff = code_diff
        return code_diff

    def generate_review_diff(
            self,
            plan: MigrationPlan,
            repo_path: str,
            feedback: str | None = None,
    ) -> CodeDiff:
        """Generates in-memory file changes for the HITL review UI (no git required).

        Unlike `generate_code_changes`, this does not require the target
        directory to be a git repository or write files to disk — it returns
        proposed `file_contents` for the reviewer to inspect/edit in the
        browser before anything is committed. Used by the web pipeline's
        Code Review gate (Step 3) instead of the mocked file generation.

        Args:
            plan: Approved migration plan with target platform details.
            repo_path: Path to the application repository (read-only).
            feedback: Optional reviewer feedback from a previous rejection,
                appended to the generation prompt for regeneration.

        Returns:
            CodeDiff with `file_contents` populated (no branch/commit yet).
        """
        if not self.enabled:
            raise RuntimeError(
                "Code generation requires ADC-authenticated Gemini client"
            )

        repo_dir = Path(repo_path)
        plan_dict = {
            "target_platform": plan.target_platform,
            "baseline_platform": plan.baseline.platform,
            "monthly_savings_usd": plan.monthly_savings_usd,
            "rationale": plan.rationale,
        }
        plan_text = yaml.dump(plan_dict, default_flow_style=False)
        if feedback:
            plan_text += f"\nREVISION REQUESTED BY REVIEWER: {feedback}\n"

        files_to_generate = self._determine_migration_files(plan_text, repo_dir)
        file_contents: dict[str, str] = {}

        for file_info in files_to_generate:
            file_name = file_info["name"]
            file_purpose = file_info.get("purpose", "")
            action = file_info.get("action", "create")
            existing_path = repo_dir / file_name

            if action == "modify" and existing_path.exists():
                current_content = existing_path.read_text(encoding="utf-8")
                new_content = self._modify_file_for_migration(
                    plan_text, file_name, file_purpose, current_content
                )
            else:
                new_content = self._generate_single_file(plan_text, file_name, file_purpose)

            file_contents[file_name] = new_content

        branch_name = self._derive_branch_name(plan)
        diff = CodeDiff(
            branch_name=branch_name,
            files_changed=list(file_contents.keys()),
            diff_text=f"Proposed {len(file_contents)} file(s) for {plan.target_platform} migration.",
            unit_tests_added=[],
            file_contents=file_contents,
        )
        self._last_branch = branch_name
        self._last_files_changed = diff.files_changed
        self._last_code_diff = diff
        return diff

    # =========================================================================
    # Integration Interface - For Other Agents
    # =========================================================================

    def get_generated_artifacts(self) -> dict:
        """Return artifacts for review agent consumption.

        Returns:
            Dictionary with generation results for downstream agents
        """
        return {
            "files_changed": self._last_files_changed,
            "diff_text": self._last_diff,
            "branch_name": self._last_branch,
            "ready_for_review": len(self._last_files_changed) > 0,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    def apply_review_fixes(
            self,
            review_feedback: dict,
            repo_path: str | None = None
    ) -> dict:
        """Apply fixes based on review agent feedback.

        Args:
            review_feedback: Dictionary containing:
                - normal_review: Best practices issues
                - epic_review: Flaws and edge cases
                - files_to_fix: List of files needing changes
            repo_path: Optional path to repository (for git operations)

        Returns:
            Dictionary with fix results
        """
        if not review_feedback.get("files_to_fix"):
            logger.info("✅ No fixes required from review")
            return {
                "status": "no_fixes_needed",
                "files_fixed": []
            }

        files_fixed = []

        for file_info in review_feedback["files_to_fix"]:
            file_path = Path(file_info["path"])
            issues = file_info.get("issues", [])

            if not file_path.exists():
                logger.warning(f"File not found for fixing: {file_path}")
                continue

            current_content = file_path.read_text()
            fixed_content = self._apply_fixes_to_file(
                file_path=str(file_path),
                current_content=current_content,
                issues=issues,
                preserve_functionality=True
            )

            # Validate before writing
            if file_path.suffix == '.py':
                is_valid, error = self._validate_python_code(fixed_content)
                if not is_valid:
                    logger.error(f"Fixed code invalid for {file_path}: {error}")
                    continue

            file_path.write_text(fixed_content, encoding='utf-8')
            files_fixed.append(str(file_path))
            logger.info(f"  🔧 Fixed: {file_path}")

        return {
            "status": "fixes_applied",
            "files_fixed": files_fixed
        }

    def signal_ready_for_tests(self) -> dict:
        """Signal that code is ready for test agent.

        Returns:
            Dictionary with readiness information for test agent
        """
        return {
            "status": "GREEN_CHECK",
            "branch": self._last_branch,
            "files": self._last_files_changed,
            "entry_point": self._detect_entry_point(),
            "test_command": self._detect_test_command(),
            "ready_at": datetime.now(timezone.utc).isoformat()
        }

    # =========================================================================
    # Plan Loading
    # =========================================================================

    def _load_plan_file(self, plan_path: Path) -> dict | str:
        """Load plan file in any supported format.

        Args:
            plan_path: Path to the plan file

        Returns:
            Parsed plan data (dict for YAML/JSON, str for text)
        """
        suffix = plan_path.suffix.lower()

        with open(plan_path) as f:
            if suffix in (".yaml", ".yml"):
                return yaml.safe_load(f)
            elif suffix == ".json":
                return json.load(f)
            else:
                # Plain text or other formats
                return f.read()

    # =========================================================================
    # Dynamic File Structure Detection
    # =========================================================================

    def _generate_from_plan(self, plan_data: dict | str, output_path: Path) -> list[str]:
        """Generate all code artifacts based on plan specification.

        The plan itself determines what files to generate.

        Args:
            plan_data: Parsed plan data
            output_path: Directory to write generated files

        Returns:
            List of generated filenames
        """
        if not self.enabled:
            raise RuntimeError("Gemini client required for code generation")

        # Convert to string for prompt
        if isinstance(plan_data, dict):
            plan_text = yaml.dump(plan_data, default_flow_style=False, indent=2)
        else:
            plan_text = str(plan_data)

        # Step 1: Ask LLM to determine what files need to be generated
        logger.info("🔍 Analyzing plan to determine file structure...")
        file_structure = self._determine_file_structure(plan_text)

        logger.info(f"📁 Will generate {len(file_structure)} files")

        # Step 2: Generate each file
        files_generated = []
        for file_info in file_structure:
            file_name = file_info["name"]
            file_purpose = file_info.get("purpose", "")

            logger.info(f"  ⚙️  Generating: {file_name}")

            code = self._generate_single_file(plan_text, file_name, file_purpose)

            # Validate Python files
            if file_name.endswith('.py'):
                is_valid, error = self._validate_python_code(code)
                if not is_valid:
                    logger.warning(f"Validation failed for {file_name}: {error}")
                    # Retry with error context
                    code = self._regenerate_with_error(plan_text, file_name, file_purpose, error)

            # Write file
            file_path = output_path / file_name
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(code, encoding='utf-8')
            files_generated.append(file_name)

            logger.info(f"  ✅ Generated: {file_name}")

        return files_generated

    def _determine_file_structure(self, plan_text: str) -> list[dict]:
        """Ask LLM to determine what files need to be generated based on plan.

        Args:
            plan_text: Plan specification as text

        Returns:
            List of file info dicts with 'name' and 'purpose' keys
        """
        prompt = f"""<role>
You are a software architect analyzing a project specification to determine the required file structure.
</role>

<task>
Analyze the plan below and determine what files need to be generated to fully implement it.
</task>

<plan>
{plan_text}
</plan>

<instructions>
1. Identify the type of application (web app, CLI, library, API, etc.)
2. Determine the programming language and framework from the plan context
3. List ALL files needed for a complete, deployable application including:
   - Main application code
   - Configuration files
   - Dependency files (requirements.txt, package.json, etc.)
   - Infrastructure files if needed (Dockerfile, etc.)
   - Test files if testing is mentioned
4. Use appropriate file extensions based on the detected language
5. Order files logically (main files first, then configs, then infrastructure)
</instructions>

<output_format>
Return a JSON array of objects. Each object must have:
- "name": filename with path if nested (e.g., "src/app.py", "requirements.txt")
- "purpose": brief description of the file's role

Return ONLY the JSON array. No markdown fences, no explanations.
</output_format>"""

        response = self._generate_with_retry(prompt, self._extract_json)

        try:
            return json.loads(response)
        except json.JSONDecodeError:
            logger.warning("Failed to parse file structure JSON, attempting extraction")
            return self._extract_json_array(response)

    def _determine_migration_files(self, plan_text: str, repo_path: Path) -> list[dict]:
        """Determine what files need to be created/modified for migration.

        Args:
            plan_text: Migration plan as text
            repo_path: Path to existing repository

        Returns:
            List of file info dicts with 'name', 'purpose', and 'action' keys
        """
        # Get existing files for context
        existing_files = []
        for f in repo_path.rglob("*"):
            if f.is_file() and not any(p in str(f) for p in ['.git', '__pycache__', '.pyc']):
                existing_files.append(str(f.relative_to(repo_path)))

        prompt = f"""<role>
You are a software architect planning a migration.
</role>

<task>
Analyze the migration plan and existing repository to determine what files need to be created or modified.
</task>

<migration_plan>
{plan_text}
</migration_plan>

<existing_files>
{yaml.dump(existing_files[:50])}  # Limit to first 50 files
</existing_files>

<instructions>
1. Identify files that need to be CREATED (don't exist yet)
2. Identify files that need to be MODIFIED (exist and need changes)
3. Focus on files required for the migration target platform
4. Include any necessary configuration or infrastructure files
</instructions>

<output_format>
Return a JSON array. Each object must have:
- "name": filename
- "purpose": what this file does
- "action": "create" or "modify"

Return ONLY the JSON array.
</output_format>"""

        response = self._generate_with_retry(prompt, self._extract_json)

        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return self._extract_json_array(response)

    # =========================================================================
    # Code Generation
    # =========================================================================

    def _generate_single_file(
            self,
            plan_text: str,
            file_name: str,
            file_purpose: str
    ) -> str:
        """Generate a single file based on plan and file context.

        Args:
            plan_text: Full plan specification
            file_name: Name of the file to generate
            file_purpose: Description of the file's purpose

        Returns:
            Generated file contents
        """
        prompt = f"""<role>
You are an expert software engineer generating production-ready code.
</role>

<task>
Generate the complete contents of the file "{file_name}" based on the plan below.
</task>

<file_info>
- Filename: {file_name}
- Purpose: {file_purpose}
</file_info>

<plan>
{plan_text}
</plan>

<instructions>
1. Generate ONLY the contents for "{file_name}"
2. Ensure the code fully implements what the plan specifies for this file
3. Make it production-ready with proper error handling where appropriate
4. Follow best practices and conventions for this file type
5. If this is a dependency file, include all necessary dependencies with versions
6. If this is an infrastructure file, make it deployment-ready
7. Ensure compatibility with other files that would be generated from this plan
</instructions>

<constraints>
- Generate COMPLETE, working code - no placeholders or TODOs
- No comments explaining obvious code
- No unnecessary imports or dependencies
- Follow the language/framework conventions
</constraints>

<output_format>
Return ONLY the file contents.
- NO markdown code fences
- NO explanations before or after
- NO filename headers
- ONLY the raw, complete file contents
</output_format>"""

        extractor = self._get_extractor_for_file(file_name)
        return self._generate_with_retry(prompt, extractor)

    def _regenerate_with_error(
            self,
            plan_text: str,
            file_name: str,
            file_purpose: str,
            error: str
    ) -> str:
        """Regenerate a file with error context from previous attempt.

        Args:
            plan_text: Full plan specification
            file_name: Name of the file to generate
            file_purpose: Description of the file's purpose
            error: Error message from previous attempt

        Returns:
            Regenerated file contents
        """
        prompt = f"""<role>
You are an expert software engineer fixing code generation errors.
</role>

<task>
Generate the file "{file_name}" - the previous attempt had errors.
</task>

<file_info>
- Filename: {file_name}
- Purpose: {file_purpose}
</file_info>

<plan>
{plan_text}
</plan>

<previous_error>
{error}
</previous_error>

<instructions>
1. Generate valid, syntactically correct code
2. Fix the error mentioned above
3. Ensure the code is complete and production-ready
</instructions>

<output_format>
Return ONLY the corrected file contents. No markdown, no explanations.
</output_format>"""

        extractor = self._get_extractor_for_file(file_name)
        return self._generate_with_retry(prompt, extractor)

    def _modify_file_for_migration(
            self,
            plan_text: str,
            file_name: str,
            file_purpose: str,
            current_content: str
    ) -> str:
        """Modify an existing file based on migration plan.

        Args:
            plan_text: Migration plan specification
            file_name: Name of the file to modify
            file_purpose: Why this file needs modification
            current_content: Current file contents

        Returns:
            Modified file contents
        """
        prompt = f"""<role>
You are an expert software engineer performing a code migration.
</role>

<task>
Modify the file "{file_name}" according to the migration plan.
</task>

<file_info>
- Filename: {file_name}
- Modification purpose: {file_purpose}
</file_info>

<migration_plan>
{plan_text}
</migration_plan>

<current_file_contents>
{current_content}
</current_file_contents>

<instructions>
1. Apply ONLY the changes required by the migration plan
2. PRESERVE all existing functionality that is not being migrated
3. Maintain code style consistency with the existing code
4. Add necessary imports for new functionality
5. Update configurations as needed for the target platform
</instructions>

<constraints>
- DO NOT remove functionality unless explicitly required
- DO NOT change code style unnecessarily  
- DO NOT add features not mentioned in the plan
- PRESERVE all existing tests and their behavior
</constraints>

<output_format>
Return the COMPLETE modified file contents.
- NO markdown code fences
- NO explanations
- ONLY the full file contents with changes applied
</output_format>"""

        extractor = self._get_extractor_for_file(file_name)
        return self._generate_with_retry(prompt, extractor)

    def _apply_fixes_to_file(
            self,
            file_path: str,
            current_content: str,
            issues: list[dict],
            preserve_functionality: bool = True
    ) -> str:
        """Apply review fixes to a file without breaking functionality.

        Args:
            file_path: Path to the file
            current_content: Current file contents
            issues: List of issues to fix
            preserve_functionality: Whether to preserve existing behavior

        Returns:
            Fixed file contents
        """
        issues_text = yaml.dump(issues, default_flow_style=False)

        prompt = f"""<role>
You are a senior software engineer applying code review fixes.
</role>

<task>
Fix the issues in "{file_path}" identified during code review.
</task>

<current_code>
{current_content}
</current_code>

<issues_to_fix>
{issues_text}
</issues_to_fix>

<instructions>
1. Address each issue listed above
2. {"PRESERVE all existing functionality" if preserve_functionality else "Refactor as needed"}
3. Maintain code style consistency
4. Ensure the code remains production-ready
</instructions>

<constraints>
- Fix ONLY the issues listed - no other changes
- DO NOT change function signatures unless required
- DO NOT remove existing features
- Keep backwards compatibility
</constraints>

<output_format>
Return the COMPLETE fixed file contents. No markdown, no explanations.
</output_format>"""

        extractor = self._get_extractor_for_file(Path(file_path).name)
        return self._generate_with_retry(prompt, extractor)

    # =========================================================================
    # Retry Logic
    # =========================================================================

    def _generate_with_retry(
            self,
            prompt: str,
            extractor: Callable[[str], str] | None = None
    ) -> str:
        """Generate content with retry logic.

        Args:
            prompt: The prompt to send to LLM
            extractor: Optional function to extract/clean the response

        Returns:
            Generated content (extracted if extractor provided)

        Raises:
            RuntimeError: If generation fails after all retries
        """
        last_error = None
        current_prompt = prompt

        for attempt in range(self.max_retries):
            try:
                response = self._client.models.generate_content(
                    model=self._model,
                    contents=current_prompt
                )

                content = response.text.strip()

                if extractor:
                    content = extractor(content)

                if not content:
                    raise ValueError("Empty response from LLM")

                logger.debug(f"Generation successful on attempt {attempt + 1}")
                return content

            except Exception as e:
                last_error = e
                logger.warning(
                    f"Generation attempt {attempt + 1}/{self.max_retries} failed: {e}"
                )

                if attempt < self.max_retries - 1:
                    # Add error context to prompt for next attempt
                    current_prompt = prompt + f"""

<previous_attempt_error>
Attempt {attempt + 1} failed with error: {str(e)}
Please fix this issue and try again.
</previous_attempt_error>"""

        raise RuntimeError(
            f"Generation failed after {self.max_retries} attempts. Last error: {last_error}"
        )

    # =========================================================================
    # Content Extractors
    # =========================================================================

    def _get_extractor_for_file(self, file_name: str) -> Callable[[str], str]:
        """Get appropriate content extractor based on file type.

        Args:
            file_name: Name of the file

        Returns:
            Extractor function for this file type
        """
        lower_name = file_name.lower()

        if lower_name.endswith('.py'):
            return self._extract_python_code
        elif lower_name == 'dockerfile':
            return self._extract_dockerfile
        elif lower_name.endswith('.json'):
            return self._extract_json
        else:
            return self._extract_raw_content

    def _extract_python_code(self, text: str) -> str:
        """Extract Python code from LLM response.

        Args:
            text: Raw LLM response

        Returns:
            Extracted Python code
        """
        text = text.strip()

        # Try python fence first
        if "```python" in text:
            return text.split("```python")[1].split("```")[0].strip()

        # Try generic fence
        if "```" in text:
            parts = text.split("```")
            if len(parts) >= 2:
                return parts[1].split("```")[0].strip()

        # Return as-is if no fences
        return text

    def _extract_dockerfile(self, text: str) -> str:
        """Extract Dockerfile content from LLM response.

        Args:
            text: Raw LLM response

        Returns:
            Extracted Dockerfile content
        """
        text = text.strip()

        if "```dockerfile" in text.lower():
            content = text.split("```")[1].split("```")[0].strip()
            # Remove 'dockerfile' language marker if present
            lines = content.split("\n")
            if lines[0].lower() == "dockerfile":
                return "\n".join(lines[1:])
            return content

        if "```" in text:
            return text.split("```")[1].split("```")[0].strip()

        return text

    def _extract_json(self, text: str) -> str:
        """Extract JSON from LLM response.

        Args:
            text: Raw LLM response

        Returns:
            Extracted JSON string
        """
        text = text.strip()

        # Remove markdown fences
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        # Find JSON array or object bounds
        start_array = text.find('[')
        start_obj = text.find('{')

        if start_array != -1 and (start_obj == -1 or start_array < start_obj):
            end = text.rfind(']') + 1
            if end > start_array:
                return text[start_array:end]
        elif start_obj != -1:
            end = text.rfind('}') + 1
            if end > start_obj:
                return text[start_obj:end]

        return text

    def _extract_json_array(self, text: str) -> list[dict]:
        """Fallback JSON array extraction.

        Args:
            text: Text potentially containing JSON array

        Returns:
            Extracted list of dicts, or minimal fallback
        """
        try:
            # Try to find and parse any JSON array in text
            match = re.search(r'\[.*\]', text, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception:
            pass

        # Ultimate fallback - return minimal structure
        logger.warning("Could not extract file structure, using minimal default")
        return [{"name": "main.py", "purpose": "Main application"}]

    def _extract_raw_content(self, text: str) -> str:
        """Extract raw content, removing any markdown fences.

        Args:
            text: Raw LLM response

        Returns:
            Extracted content
        """
        text = text.strip()

        if "```" in text:
            parts = text.split("```")
            if len(parts) >= 2:
                content = parts[1]
                # Remove language identifier if present (first line)
                lines = content.split('\n')
                if lines:
                    first_line = lines[0].strip()
                    # Check if first line is just a language identifier
                    if (len(first_line) < 20 and
                            ' ' not in first_line and
                            not first_line.startswith(('#', '//', 'FROM', 'import', 'package', '{', '['))):
                        content = '\n'.join(lines[1:])
                return content.strip()

        return text

    # =========================================================================
    # Validation
    # =========================================================================

    def _validate_python_code(self, code: str) -> tuple[bool, str]:
        """Validate Python code syntax.

        Args:
            code: Python code string

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            ast.parse(code)
            return True, ""
        except SyntaxError as e:
            return False, f"Syntax error at line {e.lineno}: {e.msg}"

    def _validate_dockerfile(self, content: str) -> tuple[bool, str]:
        """Basic Dockerfile validation.

        Args:
            content: Dockerfile content

        Returns:
            Tuple of (is_valid, error_message)
        """
        lines = content.strip().split("\n")

        if not any(line.strip().upper().startswith("FROM") for line in lines):
            return False, "Dockerfile must have FROM instruction"

        if not any(line.strip().upper().startswith(("CMD", "ENTRYPOINT")) for line in lines):
            return False, "Dockerfile should have CMD or ENTRYPOINT"

        return True, ""

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def _derive_branch_name(self, plan: MigrationPlan) -> str:
        """Create a deterministic branch name from the plan.

        Args:
            plan: Migration plan object

        Returns:
            Branch name string
        """
        platform = getattr(plan, "target_platform", "migration") or "migration"
        slug = re.sub(r"[^a-z0-9]+", "-", str(platform).lower()).strip("-") or "migration"
        return f"feature/{slug}-migration"

    def _resolve_base_branch(self, repo_path: Path) -> str:
        """Resolve the branch used as the diff base.

        Tries origin HEAD, main, then master.

        Args:
            repo_path: Path to the repository

        Returns:
            Base branch name
        """
        try:
            result = subprocess.run(
                ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip().split("/")[-1]
        except Exception:
            pass

        for candidate in ("main", "master"):
            probe = subprocess.run(
                ["git", "rev-parse", "--verify", candidate],
                cwd=repo_path,
                capture_output=True,
                text=True,
            )
            if probe.returncode == 0:
                return candidate

        return "master"

    def _detect_entry_point(self) -> str:
        """Detect the main entry point from generated files.

        Returns:
            Entry point filename
        """
        for f in self._last_files_changed:
            if f in ("app.py", "main.py", "server.py", "index.py"):
                return f
        return self._last_files_changed[0] if self._last_files_changed else "main.py"

    def _detect_test_command(self) -> str:
        """Detect the appropriate test command.

        Returns:
            Test command string
        """
        for f in self._last_files_changed:
            if f == "requirements.txt":
                return "pytest"
            elif f == "package.json":
                return "npm test"
            elif f == "go.mod":
                return "go test ./..."
        return "pytest"

    # =========================================================================
    # Advanced Refactoring (Future)
    # =========================================================================

    def refactor_module(self, module_path: str, plan: dict) -> str:
        """Refactor a specific module based on a plan.

        Args:
            module_path: Path to the module to refactor
            plan: Refactoring plan details

        Returns:
            Path to the refactored module

        Raises:
            NotImplementedError: Advanced refactoring not yet implemented
        """
        raise NotImplementedError("Advanced refactoring not yet implemented")


# ADK tool function exposed to the agent / adk web
def generate_migration_code_files(
    repo_path: str,
    target_platform: str,
    baseline_platform: str = "GCE",
    monthly_savings_usd: float = 0.0,
    rationale: str = "",
) -> dict:
    """Generates proposed file changes (Dockerfile, app code, infra manifests) for a migration plan.

    Args:
        repo_path: Path to the application repository to migrate (read-only; no files are written).
        target_platform: Target GCP platform, e.g. 'CloudRun'.
        baseline_platform: Current hosting platform, e.g. 'GCE'.
        monthly_savings_usd: Estimated monthly savings from the migration plan.
        rationale: Human-readable rationale for the migration approach.

    Returns:
        Dictionary with branch_name, files_changed, diff_text, and file_contents (path -> proposed content).
    """
    plan = MigrationPlan(
        baseline=CostEstimate(platform=baseline_platform, monthly_cost_usd=0.0),
        target=CostEstimate(platform=target_platform, monthly_cost_usd=0.0),
        target_platform=target_platform,
        monthly_savings_usd=monthly_savings_usd,
        savings_pct=0.0,
        rationale=rationale or f"Migrate from {baseline_platform} to {target_platform}.",
    )
    agent = CodeGeneratorAgent()
    diff = agent.generate_review_diff(plan, repo_path)
    return diff.model_dump()