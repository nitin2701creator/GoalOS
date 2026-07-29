"""Deterministic prompt construction for Autonomous Development System tasks."""

from __future__ import annotations

from app.kernel.development.models import DevelopmentTask


class PromptBuilder:
    """Build concise coding-agent prompts from development tasks."""

    def build(self, task: DevelopmentTask) -> str:
        """Build a deterministic prompt for ``task``."""

        lines = [f"Task: {task.title}"]

        if task.description:
            lines.extend(("", "Description:", task.description))

        if task.files:
            lines.extend(("", "Modify ONLY:", ""))
            lines.extend(f"- {file_path.as_posix()}" for file_path in task.files)

        lines.extend(
            (
                "",
                "Run ONLY:",
                "",
                task.test_command,
                "",
                "- Stop after completion.",
                "- Do not modify unrelated files.",
                "- If tests fail, fix them before stopping.",
            )
        )
        return "\n".join(lines)
