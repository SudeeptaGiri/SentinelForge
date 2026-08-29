"""Unit tests for repository loader, Git URL validation, and SSRF security."""

import os
import pytest
from src.utils.repo_loader import (
    is_git_url,
    validate_git_url,
    get_repo_name_from_url,
    resolve_repository,
    get_allowed_hosts,
)


def test_is_git_url_detection():
    # Valid Git URLs
    assert is_git_url("https://github.com/SudeeptaGiri/spill-the-tea.git") is True
    assert is_git_url("https://gitlab.com/group/repo.git") is True
    assert is_git_url("github.com/user/project") is True
    assert is_git_url("gitlab.com/user/project.git") is True

    # Local Paths (Not Git URLs)
    assert is_git_url("fixtures/sample_legacy_app") is False
    assert is_git_url("C:\\Users\\SudeeptaGiri\\project") is False
    assert is_git_url("/var/data/project") is False
    assert is_git_url("./local_dir") is False


def test_ssrf_host_allowlist_validation():
    # Approved hosts with HTTPS
    assert validate_git_url("https://github.com/org/repo.git") == "https://github.com/org/repo.git"
    assert validate_git_url("https://gitlab.com/team/app") == "https://gitlab.com/team/app"
    assert validate_git_url("https://bitbucket.org/team/app.git") == "https://bitbucket.org/team/app.git"
    assert validate_git_url("github.com/org/repo") == "https://github.com/org/repo"

    # SSRF: Block unauthorized hosts
    with pytest.raises(ValueError, match="not authorized"):
        validate_git_url("https://169.254.169.254/latest/meta-data")

    with pytest.raises(ValueError, match="not authorized"):
        validate_git_url("https://internal-server.corp/repo.git")

    with pytest.raises(ValueError, match="not authorized"):
        validate_git_url("https://malicious-site.com/exploit.git")

    # Insecure scheme (non-HTTPS)
    with pytest.raises(ValueError, match="Only 'https://' is permitted"):
        validate_git_url("http://github.com/org/repo.git")


def test_custom_allowed_git_hosts(monkeypatch):
    monkeypatch.setenv("ALLOWED_GIT_HOSTS", "gitlab.mycorp.internal,git.internal-cloud.io")
    allowed = get_allowed_hosts()
    assert "gitlab.mycorp.internal" in allowed
    assert "git.internal-cloud.io" in allowed

    # Now this internal host is valid
    url = validate_git_url("https://gitlab.mycorp.internal/dept/service.git")
    assert url == "https://gitlab.mycorp.internal/dept/service.git"


def test_get_repo_name_from_url():
    assert get_repo_name_from_url("https://github.com/SudeeptaGiri/spill-the-tea.git") == "spill-the-tea"
    assert get_repo_name_from_url("https://github.com/org/service-api/") == "service-api"
    assert get_repo_name_from_url("https://gitlab.com/team/core-engine.git") == "core-engine"


def test_resolve_local_repository():
    local_path, was_cloned, pull_warn = resolve_repository("fixtures/sample_legacy_app")
    assert os.path.exists(local_path)
    assert was_cloned is False
    assert pull_warn is None
    assert "sample_legacy_app" in local_path


def test_resolve_nonexistent_local_path():
    with pytest.raises(FileNotFoundError):
        resolve_repository("nonexistent/invalid/directory/path")
