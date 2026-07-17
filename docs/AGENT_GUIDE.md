# GoalOS Developer Agent Guide

The Developer Agent is a deterministic repository-analysis foundation for future autonomous software engineering workflows. It is not a chatbot and does not modify files, run commands, or create commits in its current form.

Its current capabilities are repository discovery and architecture classification. `RepositoryReader` lists Python modules and Markdown documentation while excluding `.git`, `__pycache__`, and `.venv`. `ArchitectureAnalyzer` identifies models, schemas, services, repositories, API routers, and tests. `DeveloperAgent` coordinates these components and retains the results in `DeveloperContext`.

Future work can build on this stable context to read coding standards and documentation, plan changes, generate modules and tests, run pytest, interpret failures, and propose fixes. A later, separately authorized capability may prepare Git commits after verification.

Future AI-enabled modules should consume the repository and architecture context rather than rediscovering project structure independently. They should preserve the existing API, repository, and service boundaries, apply the coding standards, and keep file modification and command execution as explicit capabilities with their own safety controls.
