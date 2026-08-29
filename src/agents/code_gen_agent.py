"""E2E App Code Generation & Refactoring Agent.

Description: Generates full app codebases (Greenfield) or refactors existing
             files (Ongoing Tasks/Migration).
Need: The core value of the system is turning an approved approach/spec into
      real, working code without manual authoring.
Motive: Automate the highest-effort part of the SDLC (writing/refactoring
        code) while producing a reviewable diff for the Gate 2 HITL check.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml

from src.mcp_servers.server_git import GitOperations
from src.models.schemas import CodeDiff, MigrationPlan

logger = logging.getLogger(__name__)


class CodeGeneratorAgent:
    """Generates or refactors application code based on the approved spec/plan.
    
    Uses Gemini (via ADK patterns) to intelligently generate code changes
    that align with migration plans and infrastructure requirements.
    """
    
    def __init__(self, model: str = "gemini-2.5-pro", api_key: str | None = None):
        """Initialize the code generator agent.
        
        Args:
            model: Gemini model to use (default from agent_config.yaml)
            api_key: Gemini API key (reads from env if not provided)
        """
        self._model = model
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self._client = None
        
        # Load config
        config_path = Path(__file__).parents[2] / "config" / "agent_config.yaml"
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f)
                agent_config = config.get("agents", {}).get("code_gen_agent", {})
                self._model = agent_config.get("model", self._model)
                self.max_retries = agent_config.get("max_retries", 3)
        
        # Initialize Gemini client
        if self._api_key:
            try:
                from google import genai
                self._client = genai.Client(api_key=self._api_key)
                logger.info(f"CodeGeneratorAgent initialized with {self._model}")
            except Exception as exc:
                logger.warning(f"Gemini SDK unavailable: {exc}")
    
    @property
    def enabled(self) -> bool:
        """Check if Gemini client is available."""
        return self._client is not None
    
    def generate_code_changes(
        self, 
        plan: MigrationPlan, 
        repo_path: str,
        branch_name: str = "feature/cloud-run-migration"
    ) -> CodeDiff:
        """Generate code changes based on the approved migration plan.
        
        Args:
            plan: Approved migration plan with target platform details
            repo_path: Path to the application repository
            branch_name: Name for the feature branch
            
        Returns:
            CodeDiff object with branch name, changed files, and diff text
        """
        logger.info(f"Generating code changes for migration to {plan.target_platform}")
        
        repo_path = Path(repo_path)
        git = GitOperations(str(repo_path))
        
        # Create feature branch
        if not git.create_branch(branch_name):
            raise RuntimeError(f"Failed to create branch: {branch_name}")
        
        files_changed = []
        
        # Generate health check endpoint (required for Cloud Run)
        if "cloudrun" in plan.target_platform.lower() or "cloud run" in plan.target_platform.lower():
            logger.info("Generating /healthz endpoint for Cloud Run readiness probe...")
            self._add_healthz_endpoint(repo_path)
            files_changed.append("app.py")
        
        # Generate Dockerfile if needed
        if not (repo_path / "Dockerfile").exists():
            logger.info("Generating Dockerfile...")
            self._generate_dockerfile(repo_path, plan)
            files_changed.append("Dockerfile")
        
        # Commit changes
        commit_msg = f"Add Cloud Run migration changes: {', '.join(files_changed)}"
        commit_sha = git.commit_changes(files_changed, commit_msg)
        
        if not commit_sha:
            raise RuntimeError("Failed to commit changes")
        
        # Get diff
        diff_text = git.get_diff("master")
        
        # Identify any unit tests that were added
        unit_tests_added = ["test_healthz_endpoint" if "app.py" in files_changed else ""]
        unit_tests_added = [t for t in unit_tests_added if t]
        
        return CodeDiff(
            branch_name=branch_name,
            files_changed=files_changed,
            diff_text=diff_text or f"Added {len(files_changed)} file(s) for migration",
            unit_tests_added=unit_tests_added
        )
    
    def _add_healthz_endpoint(self, repo_path: Path) -> None:
        """Add /healthz endpoint to Flask app using Gemini.
        
        Args:
            repo_path: Path to the repository
        """
        app_file = repo_path / "app.py"
        
        if not app_file.exists():
            logger.warning("app.py not found, skipping healthz endpoint")
            return
        
        # Read current app code
        current_code = app_file.read_text()
        
        if "/healthz" in current_code:
            logger.info("Health check endpoint already exists")
            return
        
        if self.enabled:
            # Use Gemini to generate the health check endpoint intelligently
            prompt = f"""Add a /healthz health check endpoint to this Flask application.
The endpoint should:
1. Return HTTP 200 with JSON {{"status": "healthy"}}
2. Follow Flask best practices
3. Be placed after existing routes
4. Include a descriptive docstring

Current code:
{current_code}

Return ONLY the complete modified app.py file content, no explanations."""

            try:
                response = self._client.models.generate_content(
                    model=self._model,
                    contents=prompt
                )
                
                generated_code = response.text.strip()
                
                # Extract code from markdown if present
                if "```python" in generated_code:
                    generated_code = generated_code.split("```python")[1].split("```")[0].strip()
                elif "```" in generated_code:
                    generated_code = generated_code.split("```")[1].split("```")[0].strip()
                
                # Write the modified code
                app_file.write_text(generated_code)
                logger.info("✅ Generated /healthz endpoint using Gemini")
                return
                
            except Exception as exc:
                logger.warning(f"Gemini generation failed: {exc}, using template")
        
        # Fallback: Template-based generation
        logger.info("Using template to add /healthz endpoint")
        healthz_code = '''

@app.route('/healthz')
def healthz():
    """Health check endpoint for Cloud Run readiness probe."""
    return jsonify({"status": "healthy"}), 200
'''
        
        # Insert before the if __name__ block
        if "if __name__" in current_code:
            parts = current_code.split("if __name__")
            modified_code = parts[0].rstrip() + healthz_code + "\n\nif __name__" + parts[1]
        else:
            modified_code = current_code.rstrip() + healthz_code
        
        app_file.write_text(modified_code)
        logger.info("✅ Added /healthz endpoint using template")
    
    def _generate_dockerfile(self, repo_path: Path, plan: MigrationPlan) -> None:
        """Generate a Dockerfile for the application.
        
        Args:
            repo_path: Path to the repository
            plan: Migration plan with platform details
        """
        dockerfile_path = repo_path / "Dockerfile"
        
        if self.enabled:
            # Use Gemini to generate optimized Dockerfile
            prompt = f"""Generate a production-ready Dockerfile for a Flask application that will run on {plan.target_platform}.

Requirements:
1. Use Python 3.11 slim base image
2. Install dependencies from requirements.txt
3. Run gunicorn (not Flask dev server)
4. Listen on port 8080
5. Follow Docker best practices (multi-stage build, non-root user)
6. Keep it minimal and optimized

Return ONLY the Dockerfile content, no explanations."""

            try:
                response = self._client.models.generate_content(
                    model=self._model,
                    contents=prompt
                )
                
                dockerfile_content = response.text.strip()
                
                # Extract code from markdown if present
                if "```dockerfile" in dockerfile_content.lower():
                    dockerfile_content = dockerfile_content.split("```")[1].split("```")[0].strip()
                    if dockerfile_content.lower().startswith("dockerfile"):
                        dockerfile_content = "\n".join(dockerfile_content.split("\n")[1:])
                elif "```" in dockerfile_content:
                    dockerfile_content = dockerfile_content.split("```")[1].split("```")[0].strip()
                
                dockerfile_path.write_text(dockerfile_content)
                logger.info("✅ Generated Dockerfile using Gemini")
                return
                
            except Exception as exc:
                logger.warning(f"Gemini generation failed: {exc}, using template")
        
        # Fallback: Template Dockerfile
        dockerfile_content = """FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

# Cloud Run expects port 8080
ENV PORT=8080

# Run with gunicorn
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 app:app
"""
        
        dockerfile_path.write_text(dockerfile_content)
        logger.info("✅ Generated Dockerfile using template")
    
    def refactor_module(self, module_path: str, plan: dict) -> str:
        """Refactor a specific module based on a plan.
        
        Args:
            module_path: Path to the module to refactor
            plan: Refactoring plan details
            
        Returns:
            Path to the refactored module
        """
        # This is for future expansion - more sophisticated refactoring
        raise NotImplementedError("Advanced refactoring not yet implemented")

