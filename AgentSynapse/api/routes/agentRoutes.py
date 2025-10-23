from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
import json
from api.middleware.authMiddleware import extractTenantContext
from api.models.requests import (
    ExecuteAgentRequest,
    CreateAgentRequest,
    UpdateAgentRequest,
    OrchestrateRequest,
    AsyncTaskRequest
)
from schemas import TenantContext, AgentConfig, AgentType
from core.agentEngine import agentEngine
from agents.registry.agentRegistry import agentRegistry
from agents.orchestrator.agentOrchestrator import agentOrchestrator
from core.asyncAgentExecutor import asyncAgentExecutor
from utils.exceptions import AgentNotFound
from utils.logger import getLogger

logger = getLogger(__name__)
router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/execute")
async def executeAgent(
    request: ExecuteAgentRequest,
    tenantContext: TenantContext = Depends(extractTenantContext)
):
    try:
        agent = await agentRegistry.get(request.agentId, tenantContext)
    except AgentNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {request.agentId} not found"
        )

    authToken = None

    if request.stream:
        async def generateStream():
            async for chunk in agentEngine.executeStreaming(
                agent,
                request.userMessage,
                request.sessionId,
                authToken
            ):
                yield f"data: {json.dumps(chunk)}\n\n"

        return StreamingResponse(generateStream(), media_type="text/event-stream")

    execution = await agentEngine.execute(
        agent,
        request.userMessage,
        request.sessionId,
        authToken
    )

    return {
        "executionId": execution.id,
        "status": execution.status.value,
        "response": execution.agentResponse,
        "toolCalls": execution.toolCalls,
        "tokensUsed": execution.tokensUsed,
        "executionTimeMs": execution.executionTimeMs
    }


@router.post("/orchestrate")
async def orchestrate(
    request: OrchestrateRequest,
    tenantContext: TenantContext = Depends(extractTenantContext)
):
    result = await agentOrchestrator.orchestrate(
        request.userRequest,
        request.sessionId,
        tenantContext
    )

    return result


@router.post("/async/submit")
async def submitAsyncTask(
    request: AsyncTaskRequest,
    tenantContext: TenantContext = Depends(extractTenantContext)
):
    taskId = await asyncAgentExecutor.submitAsyncTask(
        request.agentId,
        request.userMessage,
        request.sessionId,
        tenantContext,
        callbackUrl=request.callbackUrl
    )

    return {
        "taskId": taskId,
        "status": "submitted",
        "message": "Task submitted for async processing"
    }


@router.get("/async/status/{taskId}")
async def getAsyncTaskStatus(
    taskId: str,
    sessionId: str,
    tenantContext: TenantContext = Depends(extractTenantContext)
):
    taskStatus = await asyncAgentExecutor.getTaskStatus(
        taskId,
        sessionId,
        tenantContext
    )

    if not taskStatus:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {taskId} not found"
        )

    return taskStatus


@router.post("/create")
async def createAgent(
    request: CreateAgentRequest,
    tenantContext: TenantContext = Depends(extractTenantContext)
):
    agent = AgentConfig(
        name=request.name,
        type=request.type,
        description=request.description,
        systemPrompt=request.systemPrompt,
        temperature=request.temperature,
        maxTokens=request.maxTokens,
        toolIds=request.toolIds,
        tenantContext=tenantContext,
        isAsync=request.isAsync,
        timeoutSeconds=request.timeoutSeconds,
        customSettings=request.customSettings
    )

    agentId = await agentRegistry.register(agent)

    return {
        "agentId": agentId,
        "message": "Agent created successfully"
    }


@router.get("/list")
async def listAgents(
    agentType: str = None,
    tenantContext: TenantContext = Depends(extractTenantContext)
):
    agentTypeEnum = AgentType(agentType) if agentType else None

    agents = await agentRegistry.list(tenantContext, agentTypeEnum)

    return {
        "agents": [
            {
                "id": agent.id,
                "name": agent.name,
                "type": agent.type.value,
                "description": agent.description,
                "isAsync": agent.isAsync,
                "createdAt": agent.createdAt.isoformat()
            }
            for agent in agents
        ]
    }


@router.get("/{agentId}")
async def getAgent(
    agentId: str,
    tenantContext: TenantContext = Depends(extractTenantContext)
):
    try:
        agent = await agentRegistry.get(agentId, tenantContext)
    except AgentNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agentId} not found"
        )

    return {
        "id": agent.id,
        "name": agent.name,
        "type": agent.type.value,
        "description": agent.description,
        "systemPrompt": agent.systemPrompt,
        "temperature": agent.temperature,
        "maxTokens": agent.maxTokens,
        "toolIds": agent.toolIds,
        "isAsync": agent.isAsync,
        "timeoutSeconds": agent.timeoutSeconds,
        "customSettings": agent.customSettings,
        "createdAt": agent.createdAt.isoformat(),
        "updatedAt": agent.updatedAt.isoformat()
    }


@router.put("/{agentId}")
async def updateAgent(
    agentId: str,
    request: UpdateAgentRequest,
    tenantContext: TenantContext = Depends(extractTenantContext)
):
    updates = request.dict(exclude_unset=True)

    success = await agentRegistry.update(agentId, updates, tenantContext)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update agent"
        )

    return {
        "agentId": agentId,
        "message": "Agent updated successfully"
    }


@router.delete("/{agentId}")
async def deleteAgent(
    agentId: str,
    tenantContext: TenantContext = Depends(extractTenantContext)
):
    success = await agentRegistry.delete(agentId, tenantContext)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete agent"
        )

    return {
        "agentId": agentId,
        "message": "Agent deleted successfully"
    }
