from fastapi import APIRouter, Depends, HTTPException, status
from typing import Optional
from api.middleware.authMiddleware import extractTenantContext
from api.models.requests import RegisterToolRequest
from schemas import TenantContext, ToolDefinition, ToolPermission
from tools.registry.toolRegistry import toolRegistry
from utils.logger import getLogger
from utils.exceptions import ToolNotFound

logger = getLogger(__name__)
router = APIRouter(prefix="/tools", tags=["tools"])


@router.post("/register")
async def registerTool(
    request: RegisterToolRequest,
    tenantContext: TenantContext = Depends(extractTenantContext)
):
    tool = ToolDefinition(
        name=request.name,
        version=request.version,
        description=request.description,
        inputSchema=request.inputSchema,
        outputSchema=request.outputSchema,
        permission=request.permission,
        tenantId=tenantContext.tenantId,
        codeS3Key=request.codeS3Key,
        yamlConfig=request.yamlConfig,
        requiresAuth=request.requiresAuth
    )

    toolId = await toolRegistry.register(tool)

    return {
        "toolId": toolId,
        "name": tool.name,
        "version": tool.version,
        "message": "Tool registered successfully"
    }


@router.get("/list")
async def listTools(
    permission: Optional[str] = None,
    tenantContext: TenantContext = Depends(extractTenantContext)
):
    permissionEnum = ToolPermission(permission) if permission else None

    tools = await toolRegistry.list(tenantContext, permissionEnum)

    return {
        "tools": [
            {
                "id": tool.id,
                "name": tool.name,
                "version": tool.version,
                "description": tool.description,
                "permission": tool.permission.value,
                "isActive": tool.isActive,
                "createdAt": tool.createdAt.isoformat()
            }
            for tool in tools
        ]
    }


@router.get("/{toolName}")
async def getTool(
    toolName: str,
    version: str = "1.0.0",
    tenantContext: TenantContext = Depends(extractTenantContext)
):
    try:
        tool = await toolRegistry.get(toolName, tenantContext, version)
    except ToolNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool {toolName} (v{version}) not found"
        )

    return {
        "id": tool.id,
        "name": tool.name,
        "version": tool.version,
        "description": tool.description,
        "inputSchema": tool.inputSchema,
        "outputSchema": tool.outputSchema,
        "permission": tool.permission.value,
        "isActive": tool.isActive,
        "requiresAuth": tool.requiresAuth,
        "createdAt": tool.createdAt.isoformat(),
        "updatedAt": tool.updatedAt.isoformat()
    }


@router.post("/{toolName}/deactivate")
async def deactivateTool(
    toolName: str,
    version: str = "1.0.0",
    tenantContext: TenantContext = Depends(extractTenantContext)
):
    success = await toolRegistry.deactivate(toolName, tenantContext, version)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to deactivate tool"
        )

    return {
        "toolName": toolName,
        "version": version,
        "message": "Tool deactivated successfully"
    }


@router.get("/{toolName}/versions")
async def getToolVersions(
    toolName: str,
    includePublic: bool = True,
    includeInactive: bool = True,
    tenantContext: TenantContext = Depends(extractTenantContext)
):
    history = await toolRegistry.getVersionHistory(
        toolName,
        tenantContext,
        includePublic=includePublic,
        includeInactive=includeInactive
    )

    return history


@router.get("/{toolName}/next-version")
async def getNextToolVersion(
    toolName: str,
    releaseType: str = "patch",
    includePublic: bool = True,
    tenantContext: TenantContext = Depends(extractTenantContext)
):
    result = await toolRegistry.getNextVersion(
        toolName,
        tenantContext,
        releaseType=releaseType,
        includePublic=includePublic
    )

    return result
