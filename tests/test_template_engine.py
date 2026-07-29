"""Tests for the GoalOS code-generation template engine."""

from __future__ import annotations

import pytest

from app.developer.template_engine import (
    TemplateEngine,
    TemplateNotFoundError,
    UnresolvedPlaceholderError,
)


def test_load_template_reads_text_from_configured_directory(tmp_path) -> None:
    """Templates are loaded as UTF-8 text from the configured directory."""

    (tmp_path / "module.py.tmpl").write_text("class Example:\n    pass\n", encoding="utf-8")

    engine = TemplateEngine(tmp_path)

    assert engine.load_template("module.py.tmpl") == "class Example:\n    pass\n"


def test_render_substitutes_all_placeholder_values(tmp_path) -> None:
    """Rendering replaces each declared placeholder and preserves code braces."""

    (tmp_path / "service.py.tmpl").write_text(
        "def {{ function_name }}():\n    return {'name': '{{ value }}'}\n",
        encoding="utf-8",
    )

    result = TemplateEngine(tmp_path).render(
        "service.py.tmpl", {"function_name": "build", "value": "GoalOS"}
    )

    assert result == "def build():\n    return {'name': 'GoalOS'}\n"


def test_render_rejects_unresolved_placeholders(tmp_path) -> None:
    """Rendering fails clearly instead of returning incomplete generated code."""

    (tmp_path / "incomplete.tmpl").write_text("class {{ class_name }}:\n    {{ body }}\n")

    with pytest.raises(UnresolvedPlaceholderError, match="body"):
        TemplateEngine(tmp_path).render("incomplete.tmpl", {"class_name": "Goal"})


def test_load_template_raises_clear_error_when_template_is_missing(tmp_path) -> None:
    """A missing template reports the requested template name."""

    with pytest.raises(TemplateNotFoundError, match="missing.tmpl"):
        TemplateEngine(tmp_path).load_template("missing.tmpl")
