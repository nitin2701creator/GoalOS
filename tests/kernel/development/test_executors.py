"""Tests for the ADS coding executors.

The native executor is tested against a real temporary repository: the
deterministic provider returns real edit plans, and the executor must
actually apply them to disk, reject unsafe paths, and fail honestly on
garbage responses. The Aider adapter is tested for availability and
delegation without requiring Aider to be installed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.kernel.development.executors import (
    AiderCodingExecutor,
    EditPlanParser,
    NativeGoalOSCodingExecutor,
    SafeFileEditor,
    create_coding_executor,
)
from app.kernel.development.models import DevelopmentTask
from tests.kernel.development.helpers import (
    DeterministicEditProvider,
    calculator_plan,
    make_calculator_repo,
)

OBJECTIVE = "Make calculator.add return the sum of its arguments."


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repository with a stub calculator and a failing test."""
    return make_calculator_repo(tmp_path / "repo")


def _task(files: tuple[Path, ...] = ()) -> DevelopmentTask:
    """A development task scoped to the calculator repository."""
    return DevelopmentTask(
        title=OBJECTIVE,
        description=OBJECTIVE,
        files=list(files),
    )


def _scope(repo: Path) -> tuple[Path, ...]:
    """The default whole-repo scope of the calculator fixture."""
    return (Path("calculator.py"), Path("test_calculator.py"))


class TestEditPlanParser:
    def test_parses_plain_json(self) -> None:
        plan = EditPlanParser.parse('{"files": [{"path": "a.py", "content": "x"}]}')
        assert plan.files[0].path == "a.py"
        assert plan.files[0].content == "x"

    def test_parses_fenced_json(self) -> None:
        text = '```json\n{"files": [{"path": "a.py", "content": "x"}]}\n```'
        plan = EditPlanParser.parse(text)
        assert plan.files[0].path == "a.py"

    def test_rejects_non_json(self) -> None:
        with pytest.raises(ValueError, match="not valid JSON"):
            EditPlanParser.parse("free-llm-provider-ready")

    def test_rejects_empty_plan(self) -> None:
        with pytest.raises(ValueError, match="at least one file"):
            EditPlanParser.parse('{"files": []}')


class TestSafeFileEditor:
    def test_rejects_paths_outside_workspace(self, repo: Path) -> None:
        from app.kernel.development.executors import EditPlan, PlannedFile

        editor = SafeFileEditor()
        plan = EditPlan(
            files=(
                PlannedFile(path="../outside.py", content="x"),
                PlannedFile(path="/etc/evil.py", content="x"),
            )
        )

        changed, rejected = editor.apply(plan, repo)

        assert changed == []
        assert len(rejected) == 2
        assert not (repo.parent / "outside.py").exists()
        assert not Path("/etc/evil.py").exists()

    def test_rejects_credential_and_env_files(self, repo: Path) -> None:
        from app.kernel.development.executors import EditPlan, PlannedFile

        editor = SafeFileEditor()
        plan = EditPlan(
            files=(
                PlannedFile(path=".env", content="SECRET=1"),
                PlannedFile(path="config/.env.local", content="SECRET=1"),
                PlannedFile(path="keys/id_rsa", content="PRIVATE"),
                PlannedFile(path="service.pem", content="PRIVATE"),
            )
        )

        changed, rejected = editor.apply(plan, repo)

        assert changed == []
        assert len(rejected) == 4
        assert not (repo / ".env").exists()

    def test_writes_only_planned_files(self, repo: Path) -> None:
        from app.kernel.development.executors import EditPlan, PlannedFile

        editor = SafeFileEditor()
        plan = EditPlan(
            files=(
                PlannedFile(path="calculator.py", content="def add(a, b):\n    return a + b\n"),
            )
        )

        changed, rejected = editor.apply(plan, repo)

        assert rejected == []
        assert changed == [Path("calculator.py")]
        assert "return a + b" in (repo / "calculator.py").read_text()
        # The unrelated test file is untouched.
        assert "assert add(2, 3) == 5" in (repo / "test_calculator.py").read_text()


class TestNativeGoalOSCodingExecutor:
    def test_applies_real_edit_plan(self, repo: Path) -> None:
        provider = DeterministicEditProvider([calculator_plan()])
        executor = NativeGoalOSCodingExecutor(provider=provider, repository=repo)

        result = executor.execute(_task(_scope(repo)), repo)

        assert result.success
        assert result.modified_files == [Path("calculator.py")]
        assert "return a + b" in (repo / "calculator.py").read_text()
        assert provider.requests  # the provider was actually asked

    def test_prompt_includes_repository_context(self, repo: Path) -> None:
        provider = DeterministicEditProvider([calculator_plan()])
        executor = NativeGoalOSCodingExecutor(provider=provider, repository=repo)

        executor.execute(_task(_scope(repo)), repo)

        prompt = provider.requests[0]
        assert "calculator.py" in prompt
        assert "Repository context" in prompt
        assert "JSON edit plan" in prompt
        assert "def add(a, b)" in prompt  # in-scope file contents are included

    def test_repair_feedback_is_included_in_prompt(self, repo: Path) -> None:
        provider = DeterministicEditProvider([calculator_plan()])
        executor = NativeGoalOSCodingExecutor(provider=provider, repository=repo)

        executor.execute(_task(_scope(repo)), repo, feedback="tests failed: assert -1 == 5")

        assert "tests failed: assert -1 == 5" in provider.requests[0]

    def test_garbage_provider_response_fails_honestly(self, repo: Path) -> None:
        class GarbageProvider(DeterministicEditProvider):
            def request(self, prompt: str, **kwargs):  # type: ignore[override]
                self.requests.append(prompt)
                return {"response": "free-llm-provider-ready"}

        executor = NativeGoalOSCodingExecutor(provider=GarbageProvider([]), repository=repo)

        result = executor.execute(_task(_scope(repo)), repo)

        assert not result.success
        assert "native executor failed" in result.summary
        # The repository is untouched: the stub still returns None.
        assert "return None" in (repo / "calculator.py").read_text()

    def test_unsafe_plan_is_rejected_and_nothing_is_written(self, repo: Path) -> None:
        unsafe_plan = {"files": [{"path": "../escaped.py", "content": "x"}]}
        provider = DeterministicEditProvider([unsafe_plan])
        executor = NativeGoalOSCodingExecutor(provider=provider, repository=repo)

        result = executor.execute(_task(_scope(repo)), repo)

        assert not result.success
        assert "rejected unsafe paths" in result.summary
        assert "escaped.py" in result.summary
        assert not (repo.parent / "escaped.py").exists()

    def test_unavailable_provider_blocks_execution(self, repo: Path) -> None:
        provider = DeterministicEditProvider([calculator_plan()], health=False)
        executor = NativeGoalOSCodingExecutor(provider=provider, repository=repo)

        assert not executor.available()
        # execute still reports a failure instead of crashing
        result = executor.execute(_task(_scope(repo)), repo)
        assert not result.success


class TestAiderCodingExecutor:
    def test_unavailable_when_aider_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.kernel.development.worker as worker_module

        real_which = worker_module.shutil.which
        monkeypatch.setattr(
            worker_module.shutil,
            "which",
            lambda name: None if name == "aider" else real_which(name),
        )

        executor = AiderCodingExecutor()

        assert not executor.available()

    def test_executes_through_existing_aider_worker(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.kernel.development.worker as worker_module

        real_which = worker_module.shutil.which
        real_run = subprocess.run
        monkeypatch.setattr(
            worker_module.shutil,
            "which",
            lambda name: "/usr/bin/aider" if name == "aider" else real_which(name),
        )

        def fake_aider(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            if command and command[0] == "aider":
                cwd = Path(str(kwargs.get("cwd") or "."))
                (cwd / "calculator.py").write_text("def add(a, b):\n    return a + b\n")
                return subprocess.CompletedProcess(command, 0, "applied", "")
            return real_run(command, **kwargs)

        monkeypatch.setattr(worker_module.subprocess, "run", fake_aider)

        executor = AiderCodingExecutor(repository=repo)
        result = executor.execute(_task(_scope(repo)), repo)

        assert executor.available()
        assert result.success
        assert result.modified_files == [Path("calculator.py")]
        assert "return a + b" in (repo / "calculator.py").read_text()


class TestExecutorFactory:
    def test_creates_native_executor(self) -> None:
        executor = create_coding_executor("native")
        assert isinstance(executor, NativeGoalOSCodingExecutor)

    def test_creates_aider_executor(self) -> None:
        executor = create_coding_executor("aider")
        assert isinstance(executor, AiderCodingExecutor)

    def test_rejects_unknown_executor(self) -> None:
        with pytest.raises(ValueError, match="unsupported coding executor"):
            create_coding_executor("bogus")
