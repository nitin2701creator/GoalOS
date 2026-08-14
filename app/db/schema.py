"""Lightweight idempotent schema additions for existing GoalOS databases.

``Base.metadata.create_all`` creates missing tables but never adds columns
to tables that already exist. GoalOS runs SQLite in development (and by
default on the KVM volume), where ``ALTER TABLE ... ADD COLUMN`` guarded
by a ``PRAGMA table_info`` check is the standard way to evolve an
existing database. This helper applies exactly the columns GoalOS has
added since the first release, in order, and is safe to run on every
startup: each addition is a no-op once the column is present.

Run from the application startup right after ``create_all``.
"""

from __future__ import annotations

import logging

from sqlalchemy import Engine, text

logger = logging.getLogger(__name__)

#: (table, column, ALTER TABLE DDL) additions applied idempotently.
_ADDITIONS: tuple[tuple[str, str, str], ...] = (
    (
        "workflows",
        "plan",
        "ALTER TABLE workflows ADD COLUMN plan JSON",
    ),
)


def ensure_schema(engine: Engine) -> None:
    """Add any missing columns to existing tables (idempotent)."""
    for table, column, ddl in _ADDITIONS:
        try:
            with engine.begin() as connection:
                existing = {
                    row[1]
                    for row in connection.execute(text(f"PRAGMA table_info({table})"))
                }
                if column in existing:
                    continue
                connection.execute(text(ddl))
                logger.info(
                    "schema addition: added column '%s' to table '%s'",
                    column,
                    table,
                )
        except Exception as exc:  # noqa: BLE001 - a failed addition must not block startup
            logger.warning(
                "schema addition for %s.%s failed: %s",
                table,
                column,
                exc,
            )
