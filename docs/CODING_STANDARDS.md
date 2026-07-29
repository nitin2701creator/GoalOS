# GoalOS Coding Standards

GoalOS uses a layered architecture. API routers should remain focused on HTTP concerns. Business operations belong in services, while repositories contain SQLAlchemy queries and persistence operations. Services should not duplicate repository query logic, and routers should not access database models directly.

Use Pydantic v2 models for API contracts and SQLAlchemy models for persistence. Primary and relationship identifiers use `uuid.UUID`; do not introduce integer identifiers for new domain entities.

Use descriptive `snake_case` names for modules, functions, variables, and fields. Use `PascalCase` names for classes, including Pydantic schemas and SQLAlchemy models. Prefer specific request and response schema names such as `GoalCreateRequest` and `GoalResponse`.

All new public classes and non-obvious functions should include concise docstrings. Add type hints to function inputs and outputs. Keep dependencies directed from routers to services to repositories, rather than bypassing layers.

Tests use pytest. New behavior should have focused tests that cover the expected result and important invalid or boundary inputs without relying on test order. Preserve existing tests whenever extending a module.

Format and lint Python code with Ruff before handoff. Keep imports organized, remove unused code, and make formatting changes only where needed for the work being delivered.
