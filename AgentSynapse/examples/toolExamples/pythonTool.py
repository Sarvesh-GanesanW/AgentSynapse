async def execute(toolInput: dict, context: dict) -> dict:
    tenantContext = context.get("tenantContext", {})
    query = toolInput.get("query")

    result = {
        "success": True,
        "data": [],
        "rowCount": 0,
        "tenantId": tenantContext.get("tenantId"),
        "queryEcho": query
    }

    return result
