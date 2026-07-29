"""Template rendering utilities for GoalOS code generation."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import re


class TemplateNotFoundError(FileNotFoundError):
    """Raised when a requested template cannot be found in the template directory."""


class UnresolvedPlaceholderError(ValueError):
    """Raised when a template contains placeholders without supplied values."""


class TemplateEngine:
    """Load and render text templates used by the GoalOS code generator.

    Templates use ``{{ placeholder_name }}`` markers. Values from the supplied
    mapping replace markers with matching names; all remaining markers cause an
    :class:`UnresolvedPlaceholderError` so incomplete code is never returned.
    """

    _placeholder_pattern = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")

    def __init__(self, templates_directory: str | Path | None = None) -> None:
        """Create an engine rooted at a template directory.

        Args:
            templates_directory: Directory containing text templates. When omitted,
                the ``templates`` directory beside this module is used.
        """

        default_directory = Path(__file__).with_name("templates")
        self.templates_directory = Path(templates_directory or default_directory)

    def load_template(self, template_name: str) -> str:
        """Load a UTF-8 text template by name.

        Args:
            template_name: Relative filename within ``templates_directory``.

        Raises:
            TemplateNotFoundError: If the template does not exist, is not a file,
                or resolves outside the configured template directory.
        """

        template_path = self._template_path(template_name)
        if not template_path.is_file():
            raise TemplateNotFoundError(
                f"Template '{template_name}' was not found in "
                f"'{self.templates_directory}'."
            )
        return template_path.read_text(encoding="utf-8")

    def render(self, template_name: str, values: Mapping[str, object]) -> str:
        """Render a template using placeholder values and return generated code.

        Args:
            template_name: Relative filename of the template to render.
            values: Placeholder names mapped to replacement values.

        Raises:
            TemplateNotFoundError: If ``template_name`` cannot be loaded.
            UnresolvedPlaceholderError: If a template placeholder has no value.
        """

        template = self.load_template(template_name)
        unresolved = sorted(
            set(self._placeholder_pattern.findall(template)).difference(values)
        )
        if unresolved:
            names = ", ".join(unresolved)
            raise UnresolvedPlaceholderError(
                f"Template '{template_name}' has unresolved placeholders: {names}."
            )

        return self._placeholder_pattern.sub(
            lambda match: str(values[match.group(1)]), template
        )

    def _template_path(self, template_name: str) -> Path:
        """Return a validated absolute path for a template filename."""

        directory = self.templates_directory.resolve()
        path = (directory / template_name).resolve()
        if directory not in path.parents:
            raise TemplateNotFoundError(
                f"Template '{template_name}' is outside '{self.templates_directory}'."
            )
        return path
