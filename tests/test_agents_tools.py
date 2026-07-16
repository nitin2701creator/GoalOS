from __future__ import annotations

import pytest

from app.agents import AgentContext, BaseAgent, DeveloperAgent
from app.tools import BaseTool, FileSystemTool, LLMTool, ToolContext, ToolRegistry


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
