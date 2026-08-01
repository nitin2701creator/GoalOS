"""Run one development task through the Autonomous Development System."""

from app.kernel.development.models import DevelopmentTask
from app.kernel.development.orchestrator import DevelopmentOrchestrator


def main() -> None:
    """Execute one sample task using the default local ADS components."""

    orchestrator = DevelopmentOrchestrator()
    orchestrator.backlog.add(
        DevelopmentTask(
            title="ADS runner check",
            description="Execute one ADS orchestration cycle.",
        )
    )
    result = orchestrator.run()
    print(f"{result.status}: {result.message}")


if __name__ == "__main__":
    main()
