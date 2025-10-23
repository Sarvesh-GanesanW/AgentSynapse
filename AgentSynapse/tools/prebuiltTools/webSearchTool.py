"""
Asynchronous web search tool backed by DuckDuckGo's instant answer API.

Required toolInput fields:
    - query (str): Search keywords.
    - regions (list[str], optional): Region codes to include in the response.

Optional tuning in toolInput:
    - format (str): API response format, defaults to JSON.
    - safeSearch (bool): Enable safe search filtering (default True).

Environment prerequisites:
    - None (DuckDuckGo API is public), but consider adding a caching layer for production.
"""

import httpx


async def execute(toolInput: dict, context: dict) -> dict:
    query = toolInput.get("query")
    if not query:
        return {
            "success": False,
            "error": "Missing required field 'query'"
        }

    safeSearch = toolInput.get("safeSearch", True)
    formatType = toolInput.get("format", "json")
    regions = toolInput.get("regions", [])

    params = {
        "q": query,
        "format": formatType,
        "no_redirect": 1,
        "no_html": 1,
        "safe": "active" if safeSearch else "off"
    }

    if regions:
        params["kl"] = ",".join(regions)

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get("https://api.duckduckgo.com/", params=params)
        response.raise_for_status()
        data = response.json()

    return {
        "success": True,
        "query": query,
        "source": "DuckDuckGo",
        "abstractText": data.get("AbstractText"),
        "abstractURL": data.get("AbstractURL"),
        "answer": data.get("Answer"),
        "relatedTopics": data.get("RelatedTopics", []),
        "raw": data
    }
