import pytest
from schemas import AgentConfig, AgentType, TenantContext
from core.agentEngine import agentEngine


@pytest.fixture
def tenantContext():
    return TenantContext(
        tenantId="test-tenant",
        userId="test-user",
        roles=["admin"],
        permissions=["agent:execute"]
    )


@pytest.fixture
def agentConfig(tenantContext):
    return AgentConfig(
        name="Test Agent",
        type=AgentType.CUSTOM,
        description="Test agent for unit tests",
        systemPrompt="You are a helpful test assistant.",
        tenantContext=tenantContext,
        temperature=0.7,
        maxTokens=1000,
        toolIds=[]
    )


@pytest.mark.asyncio
async def testAgentExecutionBasic(agentConfig):
    execution = await agentEngine.execute(
        agentConfig,
        "Hello, how are you?",
        "test-session-1"
    )

    assert execution is not None
    assert execution.agentId == agentConfig.id
    assert execution.status.value in ["completed", "failed"]
    assert execution.tokensUsed > 0


@pytest.mark.asyncio
async def testAgentRecursionLimit(agentConfig):
    with pytest.raises(Exception):
        await agentEngine.execute(
            agentConfig,
            "Test message",
            "test-session-2",
            depth=10
        )


def testSystemPromptBuilding(agentConfig):
    context = {
        "semantic": [
            {"content": "User prefers dark mode"},
            {"content": "User is based in California"}
        ],
        "procedural": ["data-analysis-workflow", "dashboard-creation"]
    }

    prompt = agentEngine._buildSystemPrompt(agentConfig, context)

    assert "helpful test assistant" in prompt
    assert "dark mode" in prompt
    assert "data-analysis-workflow" in prompt
