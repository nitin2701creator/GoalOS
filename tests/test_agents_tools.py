from __future__ import annotations

import pytest

from app.agents import AgentContext, AgentLoader, AgentRegistry, BaseAgent, DeveloperAgent
from app.skills import BaseSkill, SkillLoader, SkillRegistry
from app.tools import BaseTool, FileSystemTool, LLMTool, ToolContext, ToolRegistry


class ExampleSkill(BaseSkill):
    """Concrete test skill used to validate the skills runtime."""

    def __init__(self) -> None:
        super().__init__(name="example", description="Example test skill")
        self.initialized = False
        self.stopped = False

    def initialize(self) -> None:
        self.initialized = True

    def shutdown(self) -> None:
        self.stopped = True

    async def execute(self, context: object) -> object:
        return context


def test_base_agent_is_abstract() -> None:
    with pytest.raises(TypeError):
        BaseAgent(name="Base", description="Abstract")


@pytest.mark.asyncio
async def test_developer_agent_implements_async_lifecycle() -> None:
    agent = DeveloperAgent()
    context = AgentContext(goal="Ship Sprint 6A foundation")

    plan = await agent.plan(context)
    execution = await agent.execute(context)
    report = await agent.report(context)

    assert plan.agent_name == "Developer Agent"
    assert plan.metadata["phase"] == "plan"
    assert execution.metadata["phase"] == "execute"
    assert report.metadata["phase"] == "report"


@pytest.mark.asyncio
async def test_developer_agent_loads_runtime_resources_before_execution() -> None:
    agent = DeveloperAgent()

    assert agent.is_initialized is False

    result = await agent.execute(AgentContext(goal="Prepare a runtime"))

    assert agent.is_initialized is True
    assert set(agent.skills) == set()
    assert set(agent.tools) == {"filesystem", "llm"}
    assert agent.llm_gateway is not None
    assert result.metadata["tool_count"] == 2


def test_skill_registry_and_loader_manage_skill_lifecycle() -> None:
    registry = SkillRegistry()
    loader = SkillLoader(registry)
    skill = ExampleSkill()

    registry.register(skill)
    loaded_skills = loader.load_skills()

    assert registry.list_skills() == ("example",)
    assert registry.get_skill(" example ") is skill
    assert loaded_skills["example"].initialized is True

    loader.shutdown_skills()

    assert skill.stopped is True
    assert registry.unregister("example") is skill


def test_skill_loader_discovers_concrete_skill_classes() -> None:
    import types

    module = types.ModuleType("test_skills")

    class DiscoveredSkill(ExampleSkill):
        pass

    DiscoveredSkill.__module__ = module.__name__
    module.DiscoveredSkill = DiscoveredSkill

    loader = SkillLoader()

    assert loader.discover_skills(module) == ("DiscoveredSkill",)
    assert set(loader.load_skills()) == {"example"}


def test_agent_registry_and_loader_discover_initialized_agents() -> None:
    registry = AgentRegistry()
    loader = AgentLoader(registry)

    assert loader.discover_agents() == ("developer",)
    loaded_agents = loader.load_agents()

    assert registry.get_agent("developer") is DeveloperAgent
    assert registry.list_agents() == ("developer",)
    assert loaded_agents["developer"].is_initialized is True
    assert loader.get_agent("developer") is loaded_agents["developer"]
    assert registry.unregister("developer") is DeveloperAgent


def test_base_tool_is_abstract() -> None:
    with pytest.raises(TypeError):
        BaseTool(name="base", description="Abstract")


def test_tool_registry_is_singleton_with_required_operations() -> None:
    registry = ToolRegistry()
    same_registry = ToolRegistry()
    tool = LLMTool()

    registry.unregister(tool.name)
    registry.register(tool)

    assert registry is same_registry
    assert registry.get("llm") is tool
    assert "llm" in registry.list()
    assert registry.unregister("llm") is tool
    assert registry.get("llm") is None


@pytest.mark.asyncio
async def test_tool_stubs_return_unimplemented_success_results() -> None:
    llm_tool = LLMTool()
    filesystem_tool = FileSystemTool()

    llm_result = await llm_tool.execute(ToolContext(command="generate"))
    filesystem_result = await filesystem_tool.execute(ToolContext(command="list"))

    assert llm_result.success is True
    assert llm_result.output["implemented"] is False
    assert filesystem_result.success is True
    assert filesystem_result.output["implemented"] is False
