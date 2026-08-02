"""Tests for the local Git connector."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.integrations.git.git_connector import GitConnector


def _result(returncode: int = 0, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_connect_succeeds_when_current_directory_is_a_git_repository(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.integrations.git.git_connector.subprocess.run",
        lambda *_args, **_kwargs: _result(stdout="true\n"),
    )

    assert GitConnector().connect() is None


def test_connect_raises_when_current_directory_is_not_a_git_repository(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.integrations.git.git_connector.subprocess.run",
        lambda *_args, **_kwargs: _result(returncode=128),
    )

    with pytest.raises(RuntimeError, match="not inside a Git repository"):
        GitConnector().connect()


def test_disconnect_is_a_no_op() -> None:
    assert GitConnector().disconnect() is None


def test_health_is_true_when_git_is_available_and_directory_is_a_repository(monkeypatch) -> None:
    responses = iter([_result(), _result(stdout="true\n")])
    monkeypatch.setattr(
        "app.integrations.git.git_connector.subprocess.run",
        lambda *_args, **_kwargs: next(responses),
    )

    assert GitConnector().health() is True


def test_health_is_false_when_git_is_unavailable(monkeypatch) -> None:
    def unavailable(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr("app.integrations.git.git_connector.subprocess.run", unavailable)

    assert GitConnector().health() is False


def test_health_is_false_when_directory_is_not_a_git_repository(monkeypatch) -> None:
    responses = iter([_result(), _result(returncode=128)])
    monkeypatch.setattr(
        "app.integrations.git.git_connector.subprocess.run",
        lambda *_args, **_kwargs: next(responses),
    )

    assert GitConnector().health() is False


def test_status_returns_structured_git_output(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.integrations.git.git_connector.subprocess.run",
        lambda *_args, **_kwargs: _result(stdout=" M README.md\n"),
    )

    assert GitConnector().status() == {
        "success": True,
        "returncode": 0,
        "stdout": " M README.md\n",
        "stderr": "",
    }


def test_current_branch_returns_branch_in_structured_result(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.integrations.git.git_connector.subprocess.run",
        lambda *_args, **_kwargs: _result(stdout="main\n"),
    )

    assert GitConnector().current_branch() == {
        "success": True,
        "returncode": 0,
        "stdout": "main\n",
        "stderr": "",
        "branch": "main",
    }


def test_diff_returns_structured_git_error(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.integrations.git.git_connector.subprocess.run",
        lambda *_args, **_kwargs: _result(returncode=128, stderr="not a repository"),
    )

    assert GitConnector().diff() == {
        "success": False,
        "returncode": 128,
        "stdout": "",
        "stderr": "not a repository",
    }


def test_add_stages_each_requested_path(monkeypatch) -> None:
    calls: list[list[str]] = []

    def run(command, **_kwargs):
        calls.append(command)
        return _result()

    monkeypatch.setattr("app.integrations.git.git_connector.subprocess.run", run)

    result = GitConnector().add(["README.md", "src/app.py"])

    assert result["success"] is True
    assert calls == [["git", "add", "--", "README.md", "src/app.py"]]


def test_commit_returns_structured_result_and_handles_missing_git(monkeypatch) -> None:
    def unavailable(*_args, **_kwargs):
        raise FileNotFoundError("git not found")

    monkeypatch.setattr("app.integrations.git.git_connector.subprocess.run", unavailable)

    assert GitConnector().commit("save work") == {
        "success": False,
        "returncode": None,
        "stdout": "",
        "stderr": "git not found",
    }
