"""Tests for the lightweight idempotent schema-additions helper.

``Base.metadata.create_all`` never adds columns to existing tables, so
GoalOS databases created before a schema addition (e.g. the workflow
``plan`` column) must be upgraded idempotently on startup. These tests
prove a legacy database gains the missing column, that re-running is a
no-op, and that a fresh database is unaffected.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models.workflow import Workflow  # noqa: F401 - registers the model on Base.metadata
from app.db.schema import ensure_schema


def _columns(engine, table: str) -> set[str]:
    with engine.connect() as connection:
        return {
            row[1]
            for row in connection.execute(text(f"PRAGMA table_info({table})"))
        }


def test_ensure_schema_adds_missing_column_to_legacy_database(tmp_path: Path) -> None:
    """A database created before the plan column gains it on startup."""
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    # Simulate the pre-plan schema: create the workflows table without plan.
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE workflows ("
                "id VARCHAR(36) NOT NULL, "
                "project_id VARCHAR(36) NOT NULL, "
                "name VARCHAR(200) NOT NULL, "
                "status VARCHAR(20) NOT NULL DEFAULT 'Pending', "
                "progress_percentage INTEGER NOT NULL DEFAULT 0, "
                "requirement TEXT, "
                "steps JSON, "
                "results JSON, "
                "PRIMARY KEY (id))"
            )
        )
    assert "plan" not in _columns(engine, "workflows")

    ensure_schema(engine)
    assert "plan" in _columns(engine, "workflows")

    # Re-running is a no-op (idempotent).
    ensure_schema(engine)
    assert "plan" in _columns(engine, "workflows")


def test_ensure_schema_does_not_touch_fresh_databases(tmp_path: Path) -> None:
    """A database created from the current metadata needs no additions."""
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    Base.metadata.create_all(engine)
    before = _columns(engine, "workflows")
    assert "plan" in before

    ensure_schema(engine)
    assert _columns(engine, "workflows") == before


def test_workflow_plan_column_is_persisted_end_to_end(tmp_path: Path) -> None:
    """The plan column round-trips through the ORM repository."""
    from app.repositories.project_repository import ProjectRepository
    from app.repositories.workflow_repository import WorkflowRepository
    from app.schemas.project import ProjectCreateRequest
    from app.schemas.workflow import WorkflowCreateRequest

    engine = create_engine(
        f"sqlite:///{tmp_path / 'plan_col.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    ensure_schema(engine)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False)()

    project = ProjectRepository(db).create(
        ProjectCreateRequest(
            title="Schema test",
            description="plan column round trip",
            owner="GoalOS",
            department="Autonomous",
            priority="High",
        )
    )
    workflow = WorkflowRepository(db).create(
        WorkflowCreateRequest(project_id=project.id, name="Plan round trip")
    )
    plan = [{"capability": "web_research", "goal": "g", "inputs": {}}]
    updated = WorkflowRepository(db).update(workflow, {"plan": plan})
    assert updated.plan == plan

    fetched = WorkflowRepository(db).get(updated.id)
    assert fetched is not None
    assert fetched.plan == plan
    db.close()
