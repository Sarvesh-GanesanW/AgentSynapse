"""
Lakehouse query tool that integrates with the custom SparkSQL Lakehouse service.

The tool orchestrates the lifecycle:
1. Start a session (unless an existing `sessionId` is supplied).
2. Submit Spark SQL via the `/iceberg/submitquery` endpoint.
3. Optionally stop the session.

Required toolInput fields:
    - host (str): API Gateway host serving the Lakehouse Lambda (e.g. pfxdz14aii.execute-api.ap-south-1.amazonaws.com).
    - stage (str): API stage prefix (e.g. "dev").
    - submitQuery (dict):
        * catalog (str)
        * query (str)
        * Optional sessionId (str) – skip start session if provided.

Optional toolInput fields:
    - startSessionPayload (dict): Payload for `/iceberg/startsession` when creating a new session.
    - stopSession (bool): Whether to stop the session after query execution (default True when the tool created the session).
    - stopSessionPayload (dict): Extra fields to include when stopping the session.

Authentication:
    - Requires `authToken` in the tool execution context; it is propagated as a Bearer token.
"""

from typing import Any, Dict, Optional
import httpx


def _build_url(host: str, stage: str, path: str) -> str:
    normalized_stage = stage.strip("/")
    normalized_path = path.lstrip("/")
    return f"https://{host}/{normalized_stage}/{normalized_path}"


async def _post_json(
    client: httpx.AsyncClient,
    url: str,
    payload: Dict[str, Any],
    headers: Dict[str, str]
) -> Dict[str, Any]:
    response = await client.post(url, json=payload, headers=headers)
    response.raise_for_status()
    return response.json()


async def execute(toolInput: dict, context: dict) -> dict:
    authToken = context.get("authToken")
    if not authToken:
        return {
            "success": False,
            "error": "Missing authToken in execution context"
        }

    host = toolInput.get("host")
    stage = toolInput.get("stage", "dev")
    submitConfig = toolInput.get("submitQuery", {})

    if not host:
        return {
            "success": False,
            "error": "Tool input must include 'host'"
        }

    if not submitConfig or "query" not in submitConfig or "catalog" not in submitConfig:
        return {
            "success": False,
            "error": "submitQuery must include 'catalog' and 'query'"
        }

    sessionId: Optional[str] = submitConfig.get("sessionId")
    startPayload = toolInput.get("startSessionPayload")
    stopAfter = toolInput.get("stopSession", True)
    stopPayloadOverrides = toolInput.get("stopSessionPayload", {})

    headers = {
        "Authorization": f"Bearer {authToken}",
        "Content-Type": "application/json"
    }

    returnPayload: Dict[str, Any] = {}
    startResponsePayload: Optional[Dict[str, Any]] = None

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            if not sessionId:
                if not startPayload:
                    return {
                        "success": False,
                        "error": "startSessionPayload is required when sessionId is not provided"
                    }

                startUrl = _build_url(host, stage, "iceberg/startsession")
                startResponse = await _post_json(client, startUrl, startPayload, headers)

                sessionId = (
                    startResponse.get("response", {}).get("sessionId")
                    or startResponse.get("sessionId")
                )

                if not sessionId:
                    return {
                        "success": False,
                        "error": "Failed to obtain sessionId from start session response",
                        "rawResponse": startResponse
                    }

                startResponsePayload = startResponse

            submitPayload = {
                **submitConfig,
                "sessionId": sessionId
            }

            submitUrl = _build_url(host, stage, "iceberg/submitquery")
            submitResponse = await _post_json(client, submitUrl, submitPayload, headers)

            returnPayload.update(
                {
                    "success": True,
                    "sessionId": sessionId,
                    "response": submitResponse,
                    "startSession": startResponsePayload
                }
            )

            return returnPayload

        except httpx.HTTPStatusError as statusError:
            return {
                "success": False,
                "error": f"HTTP status error: {statusError}",
                "statusCode": statusError.response.status_code,
                "details": statusError.response.text,
                "sessionId": sessionId
            }
        except httpx.HTTPError as httpError:
            return {
                "success": False,
                "error": f"HTTP error: {httpError}",
                "sessionId": sessionId
            }
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "sessionId": sessionId
            }
        finally:
            if sessionId and stopAfter:
                stopUrl = _build_url(host, stage, "iceberg/stopsession")
                stopPayload = {"sessionId": sessionId, **stopPayloadOverrides}
                try:
                    await _post_json(client, stopUrl, stopPayload, headers)
                except Exception as stopError:
                    if returnPayload:
                        returnPayload.setdefault("warnings", []).append(
                            f"Failed to stop session {sessionId}: {stopError}"
                        )
