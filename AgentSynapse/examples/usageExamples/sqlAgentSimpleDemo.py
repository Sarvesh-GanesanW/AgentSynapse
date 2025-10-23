"""
Simple SQL Agent example.

Prerequisites:
  1. `lakehouseQueryTool` (version 1.0.0) is already registered for your tenant.
     The prebuilt implementation lives at `tools/prebuiltTools/lakehouseQueryTool.py`.
  2. Environment variables (AWS credentials, tool registry tables, etc.) are already configured.
  3. You have a valid bearer token for the Lakehouse endpoints in `ACE_DEMO_AUTH_TOKEN`.

This script focuses on the SQL Agent prompt + single execution flow so you can see how
little wiring is required once the tool exists.
"""

import asyncio
import os

# Minimal placeholders so settings validation passes during imports.
os.environ.setdefault("OPENSEARCH_ENDPOINT", "https://example.com")
os.environ.setdefault("AWS_REGION", "ap-south-1")

from AgentSynapse import agentEngine
from AgentSynapse.schemas import AgentConfig, AgentType, TenantContext
from AgentSynapse.tools.registry.toolRegistry import toolRegistry
from AgentSynapse.utils.exceptions import ToolNotFound

LAKEHOUSE_TOOL_VERSION = "1.0.0"
LAKEHOUSE_TOOL_ID = f"lakehouseQueryTool:{LAKEHOUSE_TOOL_VERSION}"

SQL_AGENT_PROMPT = """
You are the ACE SQL Agent. Turn natural language questions into safe SparkSQL queries
and execute them with `lakehouseQueryTool`.

Guidelines:
- Produce a single SELECT statement; never use DROP/DELETE/INSERT/UPDATE/ALTER.
- Strip comments before executing.
- After the tool returns rows, summarise the key findings in plain English.
- If the task is impossible, explain why and do not call any tools.

One-shot example
----------------
User: "Show the number of orders per country in 2024."
Assistant tool call:
{
  "tool": "lakehouseQueryTool",
  "input": {
    "host": "<tenant-host>",
    "stage": "dev",
    "submitQuery": {
      "catalog": "gz_catalog",
      "query": "SELECT country, COUNT(*) AS total_orders FROM sales.orders WHERE order_year = 2024 GROUP BY country"
    }
  }
}
Assistant: Summarise the grouped results and highlight the top country.
""".strip()


async def main():
    tenant_context = TenantContext(
        tenantId="demo-tenant",
        userId="demo-user",
        orgId="demo-org",
        roles=["analyst"],
        permissions=["agent:execute"],
        costLimit=50.0,
    )

    # Quick sanity check: make sure the tool exists for this tenant.
    try:
        await toolRegistry.get("lakehouseQueryTool", tenant_context, LAKEHOUSE_TOOL_VERSION)
    except ToolNotFound as exc:
        raise SystemExit(
            "lakehouseQueryTool v1.0.0 is not registered for this tenant. "
            "Run the standard tool registration flow before using this demo."
        ) from exc

    agent_config = AgentConfig(
        name="SQL Agent Demo",
        type=AgentType.SQL_AGENT,
        description="Minimal SQL agent powered by lakehouseQueryTool.",
        systemPrompt=SQL_AGENT_PROMPT,
        temperature=0.2,
        maxTokens=2048,
        toolIds=[LAKEHOUSE_TOOL_ID],
        tenantContext=tenant_context,
        timeoutSeconds=120,
    )

    auth_token = os.environ.get("ACE_DEMO_AUTH_TOKEN")
    if not auth_token:
        raise SystemExit("Set ACE_DEMO_AUTH_TOKEN with a valid bearer token before running this demo.")

    user_message = (
        "List the last 5 transactions from finance.transactions showing transaction_id, amount, and transaction_date."
    )

    print("Running SQL agent demo...\n")
    try:
        execution = await agentEngine.execute(
            agent_config,
            user_message,
            sessionId="sql-agent-simple-session",
            authToken=auth_token,
        )

        print("Status:", execution.status.value)
        print("Response:\n", execution.agentResponse)
        print("\nTool Calls:")
        for call in execution.toolCalls:
            print(call)
    finally:
        await agentEngine.toolExecutor.close()


if __name__ == "__main__":
    asyncio.run(main())
