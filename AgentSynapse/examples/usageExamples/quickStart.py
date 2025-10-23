"""
Quick start walkthrough for the packaged ACE Framework.

This script shows how to wire up the core engine once the package is installed:

    pip install ace-framework

The example assumes supporting services (AWS credentials, Redis, databases, etc.)
are configured via environment variables as described in README.md.
"""

import asyncio
from AgentSynapse import agentEngine, settings
from AgentSynapse.schemas import AgentConfig, AgentType, TenantContext


async def runQuickStart():
    tenantContext = TenantContext(
        tenantId="demo-tenant",
        userId="demo-user",
        roles=["admin"],
        permissions=["agent:execute"],
        costLimit=50.0
    )

    agentConfig = AgentConfig(
        name="Quick Start Agent",
        type=AgentType.CUSTOM,
        description="Lightweight demo agent for ACE Framework quick start.",
        systemPrompt="You are a helpful assistant that keeps responses short.",
        temperature=settings.agent.defaultTemperature,
        maxTokens=2048,
        toolIds=[],
        tenantContext=tenantContext,
        isAsync=False,
        timeoutSeconds=120,
        customSettings={}
    )

    try:
        execution = await agentEngine.execute(
            agentConfig,
            userMessage="Give me one fun fact about ACE Framework packaging.",
            sessionId="demo-session-1"
        )
        print("Agent response:", execution.agentResponse)
        print("Tokens used:", execution.tokensUsed)
    finally:
        # Prevent lingering HTTP clients
        await agentEngine.toolExecutor.close()


if __name__ == "__main__":
    asyncio.run(runQuickStart())
