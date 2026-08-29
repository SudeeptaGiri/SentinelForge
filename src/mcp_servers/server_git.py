"""MCP Server: Git workspace repository manager.

Description: MCP tool server exposing Git operations (clone, branch, diff,
             commit) used by the Code Generation Agent.
Need: The Code Gen Agent must read/write source files and produce reviewable
      diffs for the Gate 2 HITL check without shelling out ad-hoc.
Motive: Standardize Git interactions (branching, diffing, committing) behind
        MCP so code changes are always tracked and reviewable.
"""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

server = None  # Server("git-mcp") — placeholder until MCP SDK is wired in.


class GitOperations:
    """Git operations wrapper for code generation and self-healing workflows."""
    
    def __init__(self, repo_path: str):
        """Initialize git operations for a repository.
        
        Args:
            repo_path: Path to the git repository root
        """
        self.repo_path = Path(repo_path)
        if not (self.repo_path / ".git").exists():
            raise ValueError(f"Not a git repository: {repo_path}")
    
    def create_branch(self, branch_name: str) -> bool:
        """Create and checkout a new git branch.
        
        Args:
            branch_name: Name of the branch to create
            
        Returns:
            True if successful, False otherwise
        """
        try:
            result = subprocess.run(
                ["git", "checkout", "-b", branch_name],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            logger.info(f"Created branch: {branch_name}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to create branch {branch_name}: {e.stderr}")
            return False
    
    def commit_changes(self, files: list[str], message: str) -> str:
        """Stage and commit changes to specified files.
        
        Args:
            files: List of file paths relative to repo root
            message: Commit message
            
        Returns:
            Commit SHA if successful, empty string otherwise
        """
        try:
            # Stage files
            subprocess.run(
                ["git", "add"] + files,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            
            # Commit
            result = subprocess.run(
                ["git", "commit", "-m", message],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            
            # Get commit SHA
            sha_result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            commit_sha = sha_result.stdout.strip()
            logger.info(f"Committed changes: {commit_sha[:8]} - {message}")
            return commit_sha
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to commit changes: {e.stderr}")
            return ""
    
    def get_diff(self, base_branch: str = "master") -> str:
        """Get git diff between current branch and base branch.
        
        Args:
            base_branch: Base branch to compare against (default: master)
            
        Returns:
            Git diff output as string
        """
        try:
            result = subprocess.run(
                ["git", "diff", base_branch],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to get diff: {e.stderr}")
            return ""
    
    def get_current_branch(self) -> str:
        """Get the name of the current branch.
        
        Returns:
            Current branch name
        """
        try:
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return "master"
    
    def apply_patch(self, patch_content: str) -> bool:
        """Apply a patch to the repository.
        
        Args:
            patch_content: Git patch content as string
            
        Returns:
            True if successful, False otherwise
        """
        try:
            result = subprocess.run(
                ["git", "apply"],
                input=patch_content,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            logger.info("Patch applied successfully")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to apply patch: {e.stderr}")
            return False
    
    def checkout(self, branch_name: str) -> bool:
        """Checkout an existing branch.
        
        Args:
            branch_name: Branch to checkout
            
        Returns:
            True if successful, False otherwise
        """
        try:
            subprocess.run(
                ["git", "checkout", branch_name],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            logger.info(f"Checked out branch: {branch_name}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to checkout {branch_name}: {e.stderr}")
            return False


def create_branch_and_diff(repo_path: str, branch_name: str) -> str:
    """Creates a working branch and returns the generated diff for review.
    
    Legacy function for backward compatibility.
    """
    git = GitOperations(repo_path)
    if git.create_branch(branch_name):
        return git.get_diff()
    return ""
