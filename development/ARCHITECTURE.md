# Autonomous Development System Architecture

## Workflow

```text
Roadmap -> Backlog -> Planner -> Scheduler -> Prompt Builder -> Worker
                                                        |
Memory <- Git Manager <- Reviewer <- Verifier <--------+
                                |
                          Orchestrator -> Service
```

## Component Responsibilities

- `models`: Shared ADS value types and lifecycle statuses.
- `roadmap` and `backlog`: Planning artifact access boundaries.
- `planner` and `scheduler`: Task preparation and ordering boundaries.
- `prompt_builder` and `worker`: Execution request construction and execution boundaries.
- `verifier` and `reviewer`: Independent validation and review boundaries.
- `git_manager`: Repository safety boundary.
- `memory`: Session and learning context boundary.
- `orchestrator` and `service`: ADS workflow coordination and application-facing access.

Implementations must remain explicit about approval, safety, and auditability.
