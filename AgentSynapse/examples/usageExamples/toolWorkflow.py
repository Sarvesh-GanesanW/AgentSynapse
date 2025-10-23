"""
End-to-end tool workflow using the packaged ACE Framework.

Highlights:
    * Register a YAML-based HTTP tool.
    * Inspect semantic version history.
    * Resolve the latest version for agent consumption.

The example assumes DynamoDB, S3, and other dependencies are available and that
environment variables are configured before execution.
"""

import asyncio
from uuid import uuid4

from AgentSynapse.schemas import TenantContext, ToolDefinition, ToolPermission
from AgentSynapse.tools.registry.toolRegistry import toolRegistry


async def runToolWorkflow():
    tenantContext = TenantContext(
        tenantId="demo-tenant",
        userId="demo-user",
        roles=["admin"],
        permissions=["tool:manage"]
    )

    toolName = "demo-http-tool"

    httpTool = ToolDefinition(
        id=str(uuid4()),
        name=toolName,
        version="1.0.0",
        description="Demo HTTP POST tool registered through the ACE Framework package.",
        inputSchema={
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "priority": {"type": "integer"}
            },
            "required": ["message"]
        },
        outputSchema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "echo": {"type": "string"}
            }
        },
        permission=ToolPermission.PRIVATE,
        tenantId=tenantContext.tenantId,
        yamlConfig={
            "type": "http",
            "url": "https://example.com/api/demo",
            "method": "POST",
            "headers": {"Content-Type": "application/json"}
        },
        requiresAuth=False
    )

    toolId = await toolRegistry.register(httpTool)
    print(f"Registered tool {toolName} with id {toolId}")

    versionInfo = await toolRegistry.getVersionHistory(toolName, tenantContext)
    print("Version history:", versionInfo)

    latestTool = await toolRegistry.get(toolName, tenantContext, version="latest")
    print(f"Resolved latest version {latestTool.version} for tool {latestTool.name}")


if __name__ == "__main__":
    asyncio.run(runToolWorkflow())
