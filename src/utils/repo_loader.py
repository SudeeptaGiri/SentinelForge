"""Repository loader & Git URL resolver for SentinelForge.

Description: Resolves local repository paths and securely clones remote Git repositories
             (GitHub, GitLab, Bitbucket, or approved enterprise hosts) to a local cache.
Need: The pipeline accepts both local filesystem directories and remote public/private
      Git URLs for automated codebase analysis and modernizations.
Motive: Provide uniform, secure filesystem access to Graphify GraphRAG and AnalysisAgent,
        enforcing SSRF host allowlists and explicit pull failure reporting.
"""

import os
import re
import shutil
import urllib.parse
from typing import Optional, Set, Tuple
import git

DEFAULT_ALLOWED_HOSTS: Set[str] = {
    "github.com",
    "gitlab.com",
    "bitbucket.org",
}


def get_allowed_hosts() -> Set[str]:
    """Returns the set of approved Git hostnames from defaults and environment config."""
    hosts = set(DEFAULT_ALLOWED_HOSTS)
    env_hosts = os.getenv("ALLOWED_GIT_HOSTS", "")
    if env_hosts:
        for h in env_hosts.split(","):
            cleaned = h.strip().lower()
            if cleaned:
                hosts.add(cleaned)
    return hosts


def is_git_url(url_or_path: str) -> bool:
    """Checks if a string is a remote Git repository URL."""
    if not isinstance(url_or_path, str):
        return False

    clean = url_or_path.strip()

    # Match HTTP/HTTPS Git URLs
    if re.match(r'^https?://', clean, re.IGNORECASE):
        return True

    # Match common git hosts without protocol prefix (e.g. github.com/owner/repo)
    if any(clean.lower().startswith(f"{h}/") for h in get_allowed_hosts()):
        return True

    return False


def validate_git_url(git_url: str) -> str:
    """Validates that a Git URL uses HTTPS and points to an allowlisted host (SSRF Protection).

    Args:
        git_url: The target repository URL.

    Returns:
        Normalized HTTPS URL.

    Raises:
        ValueError: If scheme is not HTTPS or host is not on the allowlist.
    """
    clean = git_url.strip()

    # Prepend https:// if protocol is omitted
    if not re.match(r'^[a-zA-Z]+://', clean):
        clean = f"https://{clean}"

    parsed = urllib.parse.urlparse(clean)

    if parsed.scheme.lower() != "https":
        raise ValueError(
            f"Insecure or invalid Git scheme '{parsed.scheme}'. Only 'https://' is permitted for remote repositories."
        )

    hostname = (parsed.hostname or "").lower()
    allowed_hosts = get_allowed_hosts()

    if hostname not in allowed_hosts:
        raise ValueError(
            f"Git host '{hostname}' is not authorized. Allowed hosts: {sorted(list(allowed_hosts))}. "
            f"Set ALLOWED_GIT_HOSTS to authorize custom enterprise hosts."
        )

    return clean


def get_repo_name_from_url(git_url: str) -> str:
    """Extracts a sanitized repository folder name from a Git URL."""
    clean = git_url.strip().rstrip("/")
    if clean.endswith(".git"):
        clean = clean[:-4]

    parts = clean.replace("\\", "/").split("/")
    repo_name = parts[-1] if parts else "cloned_repo"
    sanitized = re.sub(r'[^a-zA-Z0-9_-]', '_', repo_name)
    return sanitized or "cloned_repo"


def resolve_repository(
    repo_path_or_url: str,
    cache_dir: Optional[str] = None,
    force_clone: bool = False
) -> Tuple[str, bool, Optional[str]]:
    """Resolves a local path or remote Git URL into an absolute local directory path.

    Args:
        repo_path_or_url: Local filesystem path or remote Git URL.
        cache_dir: Optional custom cache directory. Defaults to '.repos_cache'.
        force_clone: Whether to delete existing cache and re-clone.

    Returns:
        Tuple of (local_absolute_path, was_cloned, pull_warning)
    """
    clean_target = repo_path_or_url.strip()

    # If it is NOT a Git URL, verify local filesystem existence
    if not is_git_url(clean_target):
        abs_path = os.path.abspath(clean_target)
        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"Local repository path does not exist: {abs_path}")
        return abs_path, False, None

    # Validate against SSRF and host allowlist
    validated_url = validate_git_url(clean_target)
    repo_name = get_repo_name_from_url(validated_url)

    if cache_dir is None:
        cache_dir = os.path.join(os.getcwd(), ".repos_cache")

    os.makedirs(cache_dir, exist_ok=True)
    target_local_path = os.path.join(cache_dir, repo_name)
    pull_warning: Optional[str] = None

    # If already cloned and not force_clone, reuse or pull latest
    if os.path.exists(target_local_path):
        if force_clone:
            shutil.rmtree(target_local_path, ignore_errors=True)
        else:
            try:
                repo = git.Repo(target_local_path)
                repo.remotes.origin.pull()
            except Exception as e:
                pull_warning = f"Git pull failed ({e}); using existing cached repository."
            return os.path.abspath(target_local_path), True, pull_warning

    # Clone repository (shallow depth=1 for speed)
    try:
        git.Repo.clone_from(
            url=validated_url,
            to_path=target_local_path,
            depth=1,
            single_branch=True
        )
    except Exception as e:
        raise RuntimeError(f"Failed to clone remote Git repository '{validated_url}': {e}") from e

    return os.path.abspath(target_local_path), True, None
