# Implementation Planning

`app.developer` can produce deterministic implementation plans without writing code or changing a repository. Create a `DeveloperAgent` with a repository root and call `plan_feature()` with a Pydantic v2 `FeatureRequest`.

```python
from app.developer import DeveloperAgent, FeatureRequest

agent = DeveloperAgent(".")
plan = agent.plan_feature(
    FeatureRequest(
        feature_name="Goal activity endpoint",
        description="Expose an API endpoint that returns goal activity.",
        requirements=("Return a Pydantic response model.",),
    )
)
```

The agent loads repository metadata and performs architecture analysis on the first request. `ImplementationPlanner` combines that architecture context, repository root, and feature request into ordered `ImplementationStep` entries. Each step identifies proposed files to create or modify, priority, dependencies, and estimated complexity. `ImplementationPlan` also provides deduplicated plan-wide file and dependency lists plus an overall complexity estimate.

The planner follows the existing API, service, repository, model, and schema boundaries. Its output is advisory only: it does not generate source code, read mutable application state, run commands, or write files.
