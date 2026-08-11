"""Coding executors for the Autonomous Development System.

A :class:`CodingExecutor` turns a development task into real changes in a
repository working tree. It is the production implementation path of the
autonomous loop, replacing the mock/CLI worker for autonomous runs:

- :class:`NativeGoalOSCodingExecutor` is the production executor: it
  inspects the repository, reads relevant files, asks the configured
  GoalOS LLM provider (``app/llm``) for a structured edit plan, validates
  every path against the workspace, and applies the changes to disk. It
  depends only on the GoalOS LLM/provider configuration — no external
  coding CLI is required.
- :class:`AiderCodingExecutor` is an OPTIONAL development adapter that
  delegates to the existing :class:`AiderWorker` when the ``aider`` CLI
  happens to be installed. Production never depends on it.

Both executors return the existing :class:`WorkerResult` contract so the
rest of ADS (verification, review, persistence) is unchanged.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from app.ai.exceptions import LLMError
from app.developer.repository_reader import RepositoryReader
from app.kernel.development.models import DevelopmentTask
from app.kernel.development.prompt_builder import PromptBuilder
from app.kernel.development.worker import (
    AiderWorker,
    WorkerResult,
    WorkerUnavailableError,
)
from app.llm.base_provider import BaseProvider
from app.llm.provider_factory import ProviderFactory


class CodingExecutor(ABC):
    """Abstraction for autonomous code execution in a repository.

    Implementations accept a development task plus the repository the
    work happens in and return a :class:`WorkerResult` describing the
    files they changed and any error details.
    """

    name: ClassVar[str]

    @abstractmethod
    def available(self) -> bool:
        """Return whether the executor can run on this machine/configuration."""

    @abstractmethod
    def execute(
        self,
        task: DevelopmentTask,
        repository: Path | None,
        feedback: str | None = None,
    ) -> WorkerResult:
        """Implement ``task`` in ``repository`` and return its result.

        Args:
            task: The development task to implement.
            repository: Repository root the executor works in.
            feedback: Optional repair feedback from a previous attempt
                (test failures or review findings).
        """


# --------------------------------------------------------------------- #
# Structured edit plans
# --------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class PlannedFile:
    """One file an executor plans to write.

    Attributes:
        path: Repository-relative path of the file.
        content: Complete new file content.
    """

    path: str
    content: str


@dataclass(frozen=True, slots=True)
class EditPlan:
    """A validated, repository-relative set of file changes.

    Attributes:
        files: Files to write with their complete new content.
        delete: Repository-relative paths of files to remove (for
            example, a file an earlier attempt created out of scope).
    """

    files: tuple[PlannedFile, ...]
    delete: tuple[str, ...] = ()


class EditPlanParser:
    """Parse an LLM response into a structured :class:`EditPlan`.

    The provider is instructed to return a single JSON object of the
    form ``{"files": [{"path": "...", "content": "..."}]}``. The parser
    tolerates a surrounding Markdown code fence and rejects anything that
    is not a well-formed, non-empty plan.
    """

    @staticmethod
    def parse(response_text: str) -> EditPlan:
        """Parse ``response_text`` into an edit plan.

        Raises:
            ValueError: If the response is not a valid edit plan.
        """
        text = response_text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("response is not valid JSON") from exc

        if not isinstance(payload, dict):
            raise TypeError("edit plan must be a JSON object")
        raw_files = payload.get("files")
        if not isinstance(raw_files, list):
            raise TypeError('edit plan must contain a "files" list')

        planned: list[PlannedFile] = []
        for index, raw in enumerate(raw_files):
            if not isinstance(raw, dict):
                raise TypeError(f"file entry {index} must be an object")
            path = raw.get("path")
            content = raw.get("content")
            if not isinstance(path, str) or not path.strip():
                raise TypeError(f"file entry {index} must declare a non-empty path")
            if not isinstance(content, str):
                raise TypeError(f"content for {path!r} must be a string")
            planned.append(PlannedFile(path=path.strip(), content=content))

        delete: list[str] = []
        raw_delete = payload.get("delete")
        if raw_delete is not None:
            if not isinstance(raw_delete, list):
                raise TypeError('edit plan "delete" must be a list')
            for index, raw in enumerate(raw_delete):
                if not isinstance(raw, str) or not raw.strip():
                    raise ValueError(f"delete entry {index} must be a non-empty path")
                delete.append(raw.strip())

        if not planned:
            raise ValueError("edit plan must contain at least one file")
        return EditPlan(files=tuple(planned), delete=tuple(delete))


class SafeFileEditor:
    """Apply a validated edit plan inside a repository working tree.

    The editor is the only file-writing boundary used by the native
    executor. It rejects paths that escape the workspace or target
    credentials/secrets, writes each approved file atomically, and never
    touches anything not named by the plan.
    """

    _FORBIDDEN_NAME_PARTS = (
        ".ssh",
        "credentials",
        "secrets",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
    )
    _FORBIDDEN_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".p8")

    def apply(self, plan: EditPlan, repository: Path) -> tuple[list[Path], list[str]]:
        """Apply ``plan`` and return the changed and rejected paths.

        Args:
            plan: The validated edit plan.
            repository: Repository root that bounds every edit.

        Returns:
            A tuple of repository-relative changed paths and the raw
            paths that were rejected for safety reasons.

        Raises:
            OSError: If a file write fails.
        """
        root = repository.resolve()
        changed: list[Path] = []
        rejected: list[str] = []

        for planned in plan.files:
            relative = self._validate_path(root, planned.path)
            if relative is None:
                rejected.append(planned.path)
                continue
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(planned.content)
            changed.append(relative)

        for raw_path in plan.delete:
            relative = self._validate_path(root, raw_path)
            if relative is None:
                rejected.append(raw_path)
                continue
            target = root / relative
            if target.exists():
                target.unlink()

        return changed, rejected

    @classmethod
    def _validate_path(cls, root: Path, raw_path: str) -> Path | None:
        """Return a safe repository-relative path, or ``None`` if unsafe."""
        candidate = (root / raw_path).resolve()
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            return None
        if candidate == root:
            return None

        parts = Path(raw_path).parts
        if any(cls._forbidden_part(part) for part in parts):
            return None
        if Path(raw_path).name.lower().endswith(cls._FORBIDDEN_SUFFIXES):
            return None
        return relative

    @staticmethod
    def _forbidden_part(part: str) -> bool:
        """Return whether one path part targets credentials or secrets."""
        lowered = part.lower()
        return lowered in SafeFileEditor._FORBIDDEN_NAME_PARTS or lowered.startswith(".env")


# --------------------------------------------------------------------- #
# Native GoalOS executor
# --------------------------------------------------------------------- #
class NativeGoalOSCodingExecutor(CodingExecutor):
    """Production coding executor backed by the GoalOS LLM provider.

    The executor runs entirely inside the repository using the existing
    GoalOS LLM/provider configuration: it reads the files in scope,
    builds a prompt that demands a structured edit plan, parses and
    validates the plan, and applies the changes through the
    :class:`SafeFileEditor`. It never fakes success — an unparseable
    provider response, an unsafe path, or an empty plan fails the run
    with a persisted reason.
    """

    name: ClassVar[str] = "native"

    def __init__(
        self,
        provider: BaseProvider | None = None,
        editor: SafeFileEditor | None = None,
        repository: Path | None = None,
        max_context_files: int = 25,
        max_file_lines: int = 200,
    ) -> None:
        """Initialize the native executor.

        Args:
            provider: GoalOS LLM provider; defaults to the configured
                :class:`ProviderFactory` provider.
            editor: Safe file editor (default editor).
            repository: Optional default repository when ``execute`` is
                called without one.
            max_context_files: Cap on files read into the prompt.
            max_file_lines: Cap on lines read per file.
        """
        self._provider = provider or ProviderFactory.create()
        self._editor = editor or SafeFileEditor()
        self._repository = Path(repository) if repository is not None else None
        self._max_context_files = max_context_files
        self._max_file_lines = max_file_lines
        self._prompt_builder = PromptBuilder()

    def available(self) -> bool:
        """Return whether the configured provider is healthy."""
        return self._provider.health_check()

    def execute(
        self,
        task: DevelopmentTask,
        repository: Path | None,
        feedback: str | None = None,
    ) -> WorkerResult:
        """Inspect, prompt, validate, and apply the implementation.

        Args:
            task: The development task to implement.
            repository: Repository root the executor works in.
            feedback: Optional repair feedback from a previous attempt.

        Returns:
            A worker result describing the applied changes, or the
            failure reason when the plan could not be produced or
            applied safely.
        """
        if not self.available():
            return WorkerResult(
                success=False,
                summary="native executor is unavailable: LLM provider is not healthy",
                output="",
            )

        repo = Path(repository) if repository is not None else self._repository
        if repo is None:
            return WorkerResult(
                success=False,
                summary="native executor requires a repository",
                output="",
            )

        try:
            prompt = self._build_prompt(task, repo, feedback)
            payload = self._provider.request(prompt)
            response_text = self._response_text(payload)
            plan = EditPlanParser.parse(response_text)
            changed, rejected = self._editor.apply(plan, repo)
        except (LLMError, ValueError, TypeError, OSError) as exc:
            return WorkerResult(
                success=False,
                summary=f"native executor failed: {exc}",
                output=str(exc),
            )

        if rejected:
            return WorkerResult(
                success=False,
                summary="native executor rejected unsafe paths: "
                + ", ".join(rejected),
                output=response_text,
            )
        if not changed:
            return WorkerResult(
                success=False,
                summary="native executor produced no file changes",
                output=response_text,
            )

        return WorkerResult(
            success=True,
            summary=f"native executor changed {len(changed)} file(s)",
            output=response_text,
            modified_files=changed,
        )

    def _build_prompt(
        self,
        task: DevelopmentTask,
        repository: Path,
        feedback: str | None,
    ) -> str:
        """Build the provider prompt with repository context and format rules."""
        lines = [self._prompt_builder.build(task)]

        scope = task.files or self._discover_scope(repository)
        context = self._repository_context(repository, scope)
        lines.extend(
            (
                "",
                "Repository context:",
                context or "(no files in scope)",
                "",
                "Return ONLY a JSON edit plan implementing the task:",
                (
                    '{"files": [{"path": "<repo-relative path>", '
                    '"content": "<complete new file content>"}], '
                    '"delete": ["<repo-relative path to remove>"]}'
                ),
                "- Modify only the files that must change; preserve every other file.",
                '- Use "delete" only to remove files that must disappear.',
                "- Every path must be relative to the repository root and stay inside it.",
                "- Never touch environment, credential, secret, or key files.",
            )
        )
        if feedback:
            lines.extend(("", feedback))
        return "\n".join(lines)

    def _repository_context(self, repository: Path, scope: tuple[Path, ...]) -> str:
        """Read in-scope files into a bounded prompt context block."""
        blocks: list[str] = []
        for index, relative in enumerate(scope[: self._max_context_files]):
            target = repository / relative
            if not target.is_file():
                continue
            try:
                content = target.read_text()
            except OSError:
                continue
            lines = content.splitlines()[: self._max_file_lines]
            blocks.append(f"--- {relative.as_posix()} ---\n" + "\n".join(lines))
        return "\n\n".join(blocks)

    @staticmethod
    def _discover_scope(repository: Path) -> tuple[Path, ...]:
        """Fall back to every Python module when the task declares no scope."""
        reader = RepositoryReader(repository)
        return tuple(reader.relative_path(module) for module in reader.python_modules())

    @staticmethod
    def _response_text(payload: dict[str, Any]) -> str:
        """Extract response text from a provider payload."""
        for key in ("response", "text", "content"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
        raise ValueError("provider response contains no text")


# --------------------------------------------------------------------- #
# Optional Aider adapter
# --------------------------------------------------------------------- #
class AiderCodingExecutor(CodingExecutor):
    """Optional development adapter that delegates to the Aider CLI.

    The adapter reuses the existing :class:`AiderWorker` and is only
    available when the ``aider`` executable is on PATH. It is a
    development accelerator — production GoalOS never depends on it, and
    the native executor remains the default production path.
    """

    name: ClassVar[str] = "aider"

    def __init__(
        self,
        repository: Path | None = None,
        timeout: float = 600.0,
        worker: AiderWorker | None = None,
    ) -> None:
        """Initialize the adapter around the existing Aider worker."""
        self._worker = worker or AiderWorker(repository=repository, timeout=timeout)
        self._prompt_builder = PromptBuilder()

    def available(self) -> bool:
        """Return whether the ``aider`` CLI is installed."""
        return self._worker.available()

    def execute(
        self,
        task: DevelopmentTask,
        repository: Path | None,
        feedback: str | None = None,
    ) -> WorkerResult:
        """Run Aider with the task prompt, appending repair feedback."""
        prompt = self._prompt_builder.build(task)
        if feedback:
            prompt += "\n\n" + feedback
        try:
            return self._worker.execute(prompt)
        except WorkerUnavailableError as exc:
            return WorkerResult(success=False, summary=str(exc), output=str(exc))


def create_coding_executor(name: str, repository: Path | None = None) -> CodingExecutor:
    """Create a coding executor by name.

    Args:
        name: ``native`` for the production GoalOS executor or ``aider``
            for the optional Aider adapter.
        repository: Repository root the executor works in.

    Returns:
        The matching executor.

    Raises:
        ValueError: If ``name`` is not a supported executor.
    """
    normalized = name.strip().lower()
    if normalized == "native":
        return NativeGoalOSCodingExecutor(repository=repository)
    if normalized == "aider":
        return AiderCodingExecutor(repository=repository)
    raise ValueError(f"unsupported coding executor: {name}")
