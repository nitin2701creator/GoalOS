# GoalOS Architecture

GoalOS is a FastAPI application organized around clear application layers. The application entry point is `app/main.py`, which creates the FastAPI application and mounts the versioned API router under `/api`.

API endpoints live in `app/api/v1`. Routers accept and return Pydantic request and response schemas from `app/schemas`, and delegate application behavior to services in `app/services`.

Services coordinate business operations and use repository classes in `app/repositories` for persistence. Repositories use SQLAlchemy sessions from `app/db/session.py` and SQLAlchemy models defined in `app/db/models`. Database metadata is collected in `app/db/base.py` and tables are created during application startup.

The planning subsystem in `app/planning` provides deterministic planning artifacts and generators. The agent and tool foundations live in `app/agents` and `app/tools`; LLM providers and planner support are isolated in `app/llm` and `app/ai`.

Tests are kept in `tests` and exercise API behavior, planning foundations, and agent/tool primitives. This separation keeps HTTP concerns, business rules, and persistence concerns independently testable.
