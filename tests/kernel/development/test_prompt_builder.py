"""Tests for Autonomous Development System prompt construction."""

from __future__ import annotations

from pathlib import Path

from app.kernel.development.models import DevelopmentTask
from app.kernel.development.prompt_builder import PromptBuilder


def test_build_minimal_task_prompt() -> None:
    """A minimal task includes its title, tests, and closing instructions."""

    task = DevelopmentTask(title="Add backlog", description="")

    prompt = PromptBuilder().build(task)

    assert "Task: Add backlog" in prompt
    assert "Description:" not in prompt
    assert "Modify ONLY:" not in prompt
    assert "Run ONLY:\n\npython -m pytest" in prompt
    assert prompt.endswith("- If tests fail, fix them before stopping.")


def test_build_includes_description() -> None:
    """A task description is included when it is present."""

    task = DevelopmentTask(title="Add prompt builder", description="Build deterministic prompts.")

    prompt = PromptBuilder().build(task)

    assert "Description:\nBuild deterministic prompts." in prompt


def test_build_includes_multiple_files() -> None:
    """Every requested file is listed in the modification section."""

    task = DevelopmentTask(
        title="Update ADS",
        description="Update the task modules.",
        files=[Path("app/kernel/development/models.py"), Path("tests/kernel/test_models.py")],
    )

    prompt = PromptBuilder().build(task)

    assert "Modify ONLY:\n\n- app/kernel/development/models.py\n- tests/kernel/test_models.py" in prompt


def test_build_omits_file_section_without_files() -> None:
    """Tasks without files omit the modification section."""

    task = DevelopmentTask(title="Document ADS", description="Update documentation.")

    assert "Modify ONLY:" not in PromptBuilder().build(task)


def test_build_uses_custom_test_command() -> None:
    """A custom task test command is preserved in the prompt."""

    task = DevelopmentTask(
        title="Test backlog",
        description="Test backlog behavior.",
        test_command="python -m pytest tests/kernel/development/test_backlog.py -q",
    )

    prompt = PromptBuilder().build(task)

    assert "Run ONLY:\n\npython -m pytest tests/kernel/development/test_backlog.py -q" in prompt


def test_build_is_deterministic() -> None:
    """Building a prompt repeatedly for one task returns the same value."""

    task = DevelopmentTask(
        title="Stable prompt",
        description="Ensure stable output.",
        files=[Path("app/kernel/development/prompt_builder.py")],
    )
    builder = PromptBuilder()

    assert builder.build(task) == builder.build(task)
