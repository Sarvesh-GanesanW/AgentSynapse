import traceback
from typing import Callable, Dict, Any, List

import jwt
from fastapi import Request, HTTPException, status

from schemas import TenantContext
from utils.logger import getLogger

logger = getLogger(__name__)


async def getUserAndRole(request: Request) -> Dict[str, Any]:
    """
    Decode the incoming Cognito JWT and derive the primary role and all groups.
    """
    try:
        token = request.headers.get("Authorization")
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized: Missing Authorization header"
            )

        decoded = jwt.decode(token, options={"verify_signature": False})
        username = decoded.get("cognito:username")
        groups: List[str] = decoded.get("cognito:groups", []) or []

        if not username:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized: Token missing username"
            )

        group = ""
        if "Admin" in groups:
            group = "ADMIN"
        elif "Modify" in groups:
            group = "MODIFY"
        elif "Readonly" in groups:
            group = "READONLY"

        return {
            "user": username,
            "group": group,
            "allGroups": groups
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("jwt_decode_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized"
        )


def getSubdomain(request: Request) -> str:
    """
    Extract the tenant subdomain from Origin/Referer headers or gz-site fallback.
    """
    methodName = "middleware.getSubdomain"
    try:
        origin = request.headers.get("origin")
        if origin is None:
            referer = request.headers.get("referer")
            if referer:
                origin = referer
            else:
                return request.headers.get("gz-site", "")

        origin = origin.replace("http://", "").replace("https://", "")
        origin = origin.split("/")[0]
        parts = origin.split(".")

        if len(parts) == 4:
            return parts[0]

        return ""
    except Exception as exc:
        stack = traceback.format_exc()
        logger.error(
            "subdomain_parse_failed",
            error=str(exc),
            stackTrace=stack,
            method=methodName
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized"
        )


async def extractTenantContext(request: Request) -> TenantContext:
    user_info = await getUserAndRole(request)
    subdomain = getSubdomain(request)

    if not subdomain:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to determine tenant subdomain"
        )

    roles = user_info["allGroups"]
    permissions: List[str] = []

    tenantContext = TenantContext(
        tenantId=subdomain,
        userId=user_info["user"],
        orgId=None,
        roles=[role for role in roles if role],
        permissions=permissions
    )

    # Store useful attributes on request.state for downstream handlers
    request.state.subdomain = subdomain
    request.state.username = user_info["user"]
    request.state.group = user_info["group"]
    request.state.groups = user_info["allGroups"]

    logger.info("tenant_context_extracted", tenantId=subdomain, userId=user_info["user"])
    return tenantContext


def requirePermission(permission: str) -> Callable:
    async def permissionChecker(request: Request):
        tenantContext = await extractTenantContext(request)

        if permission not in tenantContext.permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission: {permission}"
            )

        return tenantContext

    return permissionChecker
