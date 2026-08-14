"""Chat service bridging OpenWebUI requests to the GoalOS autonomous system.

The service turns an OpenWebUI conversation message into a GoalOS action
using only the existing architecture:

- ``create_agent`` intent: capability resolution → AgentFactory
  (reuse or create agent/skills) → persisted, ACTIVE agent.
- ``run_workflow`` intent: capability resolution → goal/project/workflow
  chain → ``WorkflowService.run_agent_workflow`` → persisted results and
  evaluation.

No second orchestration system is introduced, and dangerous permissions
are never auto-authorized from chat: capabilities that require
``EXECUTE_CODE``, ``SEND_EMAIL``, ``WRITE_WEBSITE``, ``MODIFY_ADS`` or
``SCHEDULE_WORKFLOWS`` are refused with an explicit message pointing at
the agents API.

The final response is a deterministic summary of the persisted workflow
result. When an LLM provider is configured (and only then) the summary is
polished by the LLM; without one the deterministic text is returned —
never fabricated data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.agents.capabilities import capability_spec
from app.agents.permissions import DANGEROUS_PERMISSIONS
from app.ai.llm_gateway import LLMGateway
from app.ai.planner_service import PlannerService
from app.compat import StrEnum
from app.db.models.workflow import WorkflowStatus
from app.integrations.factory import build_default_registry
from app.llm.base_provider import BaseProvider, provider_configured
from app.repositories.capability_repository import CapabilityRepository
from app.services.capability_service import CapabilityService

#: Backwards-compatible alias for the provider credential gate.
llm_configured = provider_configured
from app.repositories.agent_repository import AgentRepository
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.goal_repository import GoalRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.runtime_execution_repository import RuntimeExecutionRepository
from app.repositories.skill_repository import SkillRepository
from app.repositories.workflow_repository import WorkflowRepository
from app.schemas.agent import AgentCreateRequest, AgentResponse
from app.schemas.chat import ChatCompletionRequest, ChatMessage
from app.schemas.goal import GoalCreateRequest
from app.schemas.project import ProjectCreateRequest
from app.schemas.workflow import WorkflowCreateRequest, WorkflowResponse
from app.services.agent_factory import AgentFactoryService
from app.services.execution_runtime import ExecutionRuntimeService
from app.services.goal_service import GoalService
from app.services.project_service import ProjectService
from app.services.workflow_service import WorkflowService

logger = logging.getLogger(__name__)

#: Phrases that mark an agent-creation intent in a chat message. Matching
#: is deterministic and case-insensitive — general, not special-cased.
_CREATE_AGENT_MARKERS = (
    "create an agent",
    "create a new agent",
    "create agent",
    "make an agent",
    "build an agent",
    "add an agent",
    "set up an agent",
)

#: How many prior conversation messages to carry into the requirement.
_CONTEXT_WINDOW = 8

class ChatIntent(StrEnum):
    """The two GoalOS actions an OpenWebUI message can trigger."""

    CREATE_AGENT = "create_agent"
    RUN_WORKFLOW = "run_workflow"


@dataclass(frozen=True)
class ChatResult:
    """Outcome of handling one chat message.

    Attributes:
        content: The assistant content returned to OpenWebUI.
        intent: Which GoalOS action ran.
        agent: The created/reused agent, when applicable.
        workflow: The persisted workflow run, when applicable.
        blocked: Whether the request was refused (dangerous action or
            missing integration).
    """

    content: str
    intent: ChatIntent
    agent: AgentResponse | None = None
    workflow: WorkflowResponse | None = None
    blocked: bool = False


def detect_intent(message: str) -> ChatIntent:
    """Classify a user message into a GoalOS chat intent.

    Creation markers win; anything else is a workflow execution request.
    """
    text = message.casefold()
    if any(marker in text for marker in _CREATE_AGENT_MARKERS):
        return ChatIntent.CREATE_AGENT
    return ChatIntent.RUN_WORKFLOW


def last_user_message(messages: list[ChatMessage]) -> str:
    """Return the most recent user message from the conversation."""
    for message in reversed(messages):
        if message.role == "user":
            return message.content
    return messages[-1].content


def build_requirement(messages: list[ChatMessage], *, window: int = _CONTEXT_WINDOW) -> str:
    """Combine the current request with relevant prior conversation context.

    The context window is passed to the workflow as the persisted
    ``requirement`` (conversation history is preserved through the
    existing workflow persistence, not a separate conversation store).
    """
    recent = messages[-window:]
    if len(recent) == 1:
        return recent[0].content
    context = "\n".join(f"[{message.role}] {message.content}" for message in recent[:-1])
    return f"Conversation context:\n{context}\n\nCurrent request: {recent[-1].content}"


class ChatService:
    """Execute OpenWebUI chat messages through the GoalOS autonomous system."""

    def __init__(
        self,
        db: Any,
        *,
        agent_factory: AgentFactoryService | None = None,
        workflow_service: WorkflowService | None = None,
        goal_service: GoalService | None = None,
        project_service: ProjectService | None = None,
        llm_provider: BaseProvider | None = None,
    ) -> None:
        self.db = db
        self.agent_factory = agent_factory or AgentFactoryService(
            AgentRepository(db), SkillRepository(db)
        )
        self.workflow_service = workflow_service or WorkflowService(
            WorkflowRepository(db), ExecutionRepository(db)
        )
        self.goal_service = goal_service or GoalService(GoalRepository(db))
        self.project_service = project_service or ProjectService(ProjectRepository(db))
        self.llm_provider = llm_provider
        self.integration_registry = build_default_registry(session=db)
        self.capability_service = CapabilityService(
            CapabilityRepository(db),
            integration_registry=self.integration_registry,
            llm_provider=llm_provider,
        )
        # Goal planner: LLM-first decomposition into an ordered capability
        # plan, with the deterministic capability resolver as fallback (no
        # LLM configured → behavior identical to the pre-planner path).
        self.planner_service = PlannerService(self.capability_service, llm_provider)

    def handle(self, request: ChatCompletionRequest) -> ChatResult:
        """Route a chat request through the GoalOS autonomous system."""
        message = last_user_message(request.messages)
        intent = detect_intent(message)
        if intent is ChatIntent.CREATE_AGENT:
            return self._handle_create_agent(message)
        return self._handle_run_workflow(request, message)

    def _resolve_execution_capabilities(self, message: str) -> list[str]:
        """Resolve a message to execution capabilities via the engine."""
        resolution = self.capability_service.resolve_for_goal(message)
        return list(resolution.execution_capabilities)

    # ------------------------------------------------------------------
    # Agent creation intent
    # ------------------------------------------------------------------
    def _handle_create_agent(self, message: str) -> ChatResult:
        capabilities = tuple(self._resolve_execution_capabilities(message))
        if not capabilities:
            return ChatResult(
                content=(
                    "GoalOS could not resolve any capability from that request. "
                    "Try describing the work, e.g. \"analyze the Organigram website SEO\"."
                ),
                intent=ChatIntent.CREATE_AGENT,
            )
        dangerous = self._dangerous_capabilities(capabilities)
        if dangerous:
            return ChatResult(
                content=self._dangerous_refusal("create this agent", dangerous),
                intent=ChatIntent.CREATE_AGENT,
                blocked=True,
            )
        try:
            resolved = self.agent_factory.resolve_for_capabilities(message, capabilities)
        except ValueError as exc:
            return ChatResult(content=str(exc), intent=ChatIntent.CREATE_AGENT)
        if resolved.agent is not None:
            agent = resolved.agent
            created = False
        else:
            spec = resolved.specification
            assert spec is not None
            try:
                agent = self.agent_factory.create_agent(
                    AgentCreateRequest(
                        name=spec.name,
                        purpose=spec.purpose,
                        required_capabilities=list(spec.capabilities),
                    )
                )
            except ValueError as exc:
                return ChatResult(content=str(exc), intent=ChatIntent.CREATE_AGENT)
            created = True
        content = (
            f"Agent {agent.name} is {'ready' if created else 'already available'} "
            f"(status: {agent.status.value}). "
            f"Capabilities: {', '.join(agent.capabilities)}. "
            f"Skills: {', '.join(agent.skills)}. "
            f"Integrations: {', '.join(agent.integrations) or 'none required'}. "
            f"Permissions: {', '.join(permission.value for permission in agent.permissions)}."
        )
        return ChatResult(
            content=self._polish(content),
            intent=ChatIntent.CREATE_AGENT,
            agent=agent,
        )

    # ------------------------------------------------------------------
    # Workflow execution intent
    # ------------------------------------------------------------------
    def _handle_run_workflow(
        self, request: ChatCompletionRequest, message: str
    ) -> ChatResult:
        # Goal plan first: an LLM-driven ordered capability plan when a
        # provider is configured, else the deterministic resolver (identical
        # to the pre-planner behavior). Explicit user restrictions are
        # applied inside the planner AND re-enforced by the runtime, so a
        # prohibited capability is never planned, executed, or persisted.
        plan = self.planner_service.plan_for_goal(message)
        capabilities = tuple(plan.capabilities)
        resolution = self.capability_service.resolve_for_goal(message)
        if not capabilities:
            return ChatResult(
                content=(
                    "GoalOS could not resolve any capability from that request. "
                    "Try describing the task, e.g. \"run the SEO analysis\"."
                ),
                intent=ChatIntent.RUN_WORKFLOW,
            )
        dangerous = self._dangerous_capabilities(capabilities)
        if dangerous:
            return ChatResult(
                content=self._dangerous_refusal("run this task", dangerous),
                intent=ChatIntent.RUN_WORKFLOW,
                blocked=True,
            )

        requirement = build_requirement(request.messages)
        workflow = self._create_goal_chain(message)
        try:
            # Approve the workflow with the persisted goal plan, then run it
            # through the execution runtime. The runtime executes the plan's
            # ordered steps sequentially (chaining each step's output into
            # the next step's input), resolves each capability through the
            # capability engine, reuses/creates the executing agent (whose
            # declared permissions are granted — never escalated), dispatches
            # through the existing connectors/skills, and persists one
            # runtime execution record per step.
            self.workflow_service.approve(
                workflow.id,
                requirement,
                capabilities=capabilities,
                resolved_capabilities=list(resolution.capabilities),
                capability_service=self.capability_service,
                plan=PlannerService.plan_to_dict(plan),
            )
            runtime = ExecutionRuntimeService(
                RuntimeExecutionRepository(self.db),
                self.capability_service,
                workflow_repository=WorkflowRepository(self.db),
            )
            result = runtime.run_workflow(
                workflow.id,
                requirement=requirement,
                capabilities=capabilities,
                agent_factory=self.agent_factory,
            )
        except ValueError as exc:
            return ChatResult(content=str(exc), intent=ChatIntent.RUN_WORKFLOW)
        workflow_result = result.workflow
        return ChatResult(
            content=self._format_workflow_result(workflow_result),
            intent=ChatIntent.RUN_WORKFLOW,
            workflow=workflow_result,
            blocked=workflow_result.status == WorkflowStatus.FAILED.value,
        )

    def _create_goal_chain(self, message: str) -> WorkflowResponse:
        """Persist the goal → project → workflow chain for a chat run.

        Reuses the existing GoalOS persistence exactly as the API does;
        every run leaves a traceable goal, project, and workflow.
        """
        title = message.strip()[:120] or "OpenWebUI request"
        goal = self.goal_service.create(
            GoalCreateRequest(
                title=title,
                description=message,
                executive_owner="OpenWebUI",
                department="Autonomous",
                priority="High",
            )
        )
        project = self.project_service.create(
            ProjectCreateRequest(
                goal_id=goal.id,
                title=f"{title} — project",
                description=message,
                owner="GoalOS",
                department="Autonomous",
                priority="High",
            )
        )
        return self.workflow_service.create(
            WorkflowCreateRequest(project_id=project.id, name=f"{title} — workflow")
        )

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------
    @staticmethod
    def _dangerous_capabilities(capabilities: tuple[str, ...]) -> tuple[str, ...]:
        """Return the capabilities that require dangerous permissions."""
        dangerous: list[str] = []
        for capability in capabilities:
            try:
                spec = capability_spec(capability)
            except ValueError:
                continue
            if set(spec.permissions) & DANGEROUS_PERMISSIONS:
                dangerous.append(capability)
        return tuple(dangerous)

    def _dangerous_refusal(self, action: str, capabilities: tuple[str, ...]) -> str:
        """Compose the honest refusal for dangerous chat requests."""
        permission_names: list[str] = []
        for capability in capabilities:
            try:
                spec = capability_spec(capability)
            except ValueError:
                continue
            for permission in set(spec.permissions) & DANGEROUS_PERMISSIONS:
                if permission.value not in permission_names:
                    permission_names.append(permission.value)
        return (
            f"GoalOS will not auto-authorize dangerous actions from chat, so it "
            f"cannot {action}. The request resolves to capabilities that require "
            f"explicit permission(s): {', '.join(permission_names)}. "
            "Create the agent through POST /api/v1/agents with an explicit "
            "permissions list instead."
        )

    def _format_workflow_result(self, workflow: WorkflowResponse) -> str:
        """Build the deterministic chat response from the persisted workflow."""
        status = workflow.status
        error = workflow.error_message or ""
        if status == WorkflowStatus.FAILED.value:
            if _is_configuration_failure(error):
                content = (
                    "INTEGRATION_NOT_CONFIGURED: GoalOS could not execute this "
                    f"request because a required integration is not configured.\n{error}"
                )
            else:
                content = f"GoalOS could not complete the request.\n{error}"
        else:
            evaluation = workflow.evaluation or {}
            step_lines = "\n".join(
                f"- {step['capability']}: {step['status']}"
                for step in workflow.steps or []
            )
            content = (
                f"GoalOS executed the request through the autonomous workflow "
                f"'{workflow.name}' (status: {status}).\n"
                f"Evaluation: {evaluation.get('summary', '')}\n{step_lines}"
            )
        return self._polish(content)

    def _polish(self, content: str) -> str:
        """Polished response when an LLM provider is configured; else as-is."""
        provider = self.llm_provider
        if not llm_configured(provider):
            return content
        try:
            payload = provider.request(
                "Summarize this GoalOS result for the user in 2-3 sentences "
                "without inventing details:\n\n" + content
            )
            polished = LLMGateway._response_text(payload).strip()
            if polished:
                return polished
        except Exception:  # noqa: BLE001 - LLM polish must never break chat
            logger.warning("LLM polish failed; returning deterministic result")
        return content


def _is_configuration_failure(error: str) -> bool:
    """Detect integration-configuration failure messages."""
    markers = (
        "not configured",
        "not registered",
        "unavailable",
        "missing environment configuration",
        "authentication required",
    )
    return any(marker in error.casefold() for marker in markers)
