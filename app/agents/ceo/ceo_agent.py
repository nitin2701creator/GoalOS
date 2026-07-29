"""Digital CEO agent that coordinates specialized executive agents."""

from __future__ import annotations

import inspect
from typing import Any

from app.agents.base_agent import AgentContext, AgentResult, BaseAgent
from app.agents.ceo.executive_registry import ExecutiveAgent, ExecutiveRegistry
from app.agents.ceo.executive_summary import ExecutiveBrief, ExecutiveSummary, PriorityAction


class CEOAgent(BaseAgent):
    """Coordinate executives while leaving department execution to them."""

    agent_name = "ceo"
    _RISK_TERMS = ("risk", "overdue", "blocked", "decline", "shortfall", "urgent")

    def __init__(self, executive_registry: ExecutiveRegistry | None = None) -> None:
        super().__init__(name="CEO Agent", description="Coordinates GoalOS executive agents.")
        self.executive_registry = executive_registry or ExecutiveRegistry()

    def discover_executives(self) -> tuple[str, ...]:
        """Return currently registered department names without instantiating integrations."""

        return self.executive_registry.list_executives()

    def request_department_summaries(self) -> tuple[ExecutiveSummary, ...]:
        """Collect normalized reports from all available executive agents."""

        return tuple(
            self._summary_for(name, executive)
            for name, executive in self.executive_registry.snapshot().items()
        )

    def prioritize_actions(self, summaries: tuple[ExecutiveSummary, ...]) -> tuple[PriorityAction, ...]:
        """Deterministically rank all stated department priorities."""

        actions = [
            PriorityAction(summary.department, action, rank=0)
            for summary in summaries for action in summary.priorities
        ]
        ranked = sorted(actions, key=lambda item: (item.department.casefold(), item.action.casefold()))
        return tuple(
            PriorityAction(item.department, item.action, rank=index)
            for index, item in enumerate(ranked, start=1)
        )

    def generate_executive_briefing(self) -> ExecutiveBrief:
        """Merge department reports into a deterministic executive briefing."""

        summaries = self.request_department_summaries()
        recommendations = tuple(
            recommendation for summary in summaries for recommendation in summary.recommendations
        )
        risks = tuple(item for item in recommendations if self._is_risk(item))
        opportunities = tuple(item for item in recommendations if not self._is_risk(item))
        return ExecutiveBrief(
            department_summaries=summaries,
            top_risks=risks,
            top_opportunities=opportunities,
            today_priorities=self.prioritize_actions(summaries),
            ai_recommendations=recommendations,
        )

    def assign_objective(self, executive_name: str, objective: str) -> Any:
        """Delegate an objective assignment to the named department executive."""

        return self.delegate_work(executive_name, {"type": "objective", "objective": objective})

    def delegate_work(self, executive_name: str, action: Any) -> Any:
        """Ask one executive to execute work; the CEO never calls integrations directly."""

        executive = self.executive_registry.get_executive(executive_name)
        if executive is None:
            return None
        return executive.execute(action)

    async def plan(self, context: AgentContext) -> AgentResult:
        brief = self.generate_executive_briefing()
        return self._result(
            summary=f"Prepared executive plan for: {self._require_text(context.goal, 'goal')}",
            actions=tuple(item.action for item in brief.today_priorities),
            metadata={"phase": "plan", "executive_count": len(brief.department_summaries)},
        )

    async def execute(self, context: AgentContext) -> AgentResult:
        action = context.metadata.get("action")
        executive_name = context.metadata.get("executive")
        delegated_result = None
        if isinstance(executive_name, str) and action is not None:
            delegated_result = self.delegate_work(executive_name, action)
            if inspect.isawaitable(delegated_result):
                delegated_result = await delegated_result
        return self._result(
            summary=f"Coordinated executive work for: {self._require_text(context.goal, 'goal')}",
            metadata={"phase": "execute", "delegated": delegated_result is not None},
        )

    async def report(self, context: AgentContext) -> AgentResult:
        brief = self.generate_executive_briefing()
        return self._result(
            summary=f"Executive briefing prepared for: {self._require_text(context.goal, 'goal')}",
            actions=tuple(item.action for item in brief.today_priorities),
            metadata={
                "phase": "report",
                "executive_count": len(brief.department_summaries),
                "risk_count": len(brief.top_risks),
            },
        )

    @staticmethod
    def _summary_for(name: str, executive: ExecutiveAgent) -> ExecutiveSummary:
        return ExecutiveSummary(
            department=name,
            status=executive.get_status(),
            kpis=executive.get_kpis(),
            priorities=tuple(executive.get_priorities()),
            recommendations=tuple(executive.get_recommendations()),
        )

    @classmethod
    def _is_risk(cls, recommendation: str) -> bool:
        normalized = recommendation.casefold()
        return any(term in normalized for term in cls._RISK_TERMS)
