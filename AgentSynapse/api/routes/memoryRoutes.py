from fastapi import APIRouter, Depends, HTTPException, status
from api.middleware.authMiddleware import extractTenantContext
from api.models.requests import StoreFactRequest, SearchMemoryRequest
from schemas import TenantContext, MemorySource
from memory.memoryManager import memoryManager
from utils.logger import getLogger

logger = getLogger(__name__)
router = APIRouter(prefix="/memory", tags=["memory"])


@router.post("/fact/store")
async def storeFact(
    request: StoreFactRequest,
    tenantContext: TenantContext = Depends(extractTenantContext)
):
    factId = await memoryManager.storeFact(
        tenantContext,
        request.sessionId,
        request.fact,
        source=MemorySource.USER_STATED,
        importance=request.importance,
        tags=request.tags,
        relatedEntities=request.relatedEntities
    )

    return {
        "factId": factId,
        "message": "Fact stored successfully"
    }


@router.post("/search")
async def searchMemory(
    request: SearchMemoryRequest,
    tenantContext: TenantContext = Depends(extractTenantContext)
):
    if request.memoryType == "semantic":
        filters = {}
        if request.sessionId:
            filters["sessionId"] = request.sessionId

        memories = await memoryManager.semanticMemory.search(
            tenantContext,
            request.query,
            limit=request.limit,
            filters=filters
        )

        return {
            "memories": [
                {
                    "id": mem.id,
                    "content": mem.content,
                    "importance": mem.importance,
                    "confidenceScore": mem.confidenceScore,
                    "tags": mem.tags,
                    "createdAt": mem.createdAt.isoformat()
                }
                for mem in memories
            ]
        }

    elif request.memoryType == "episodic":
        filters = {}
        if request.sessionId:
            filters["sessionId"] = request.sessionId

        memories = await memoryManager.episodicMemory.retrieve(
            tenantContext,
            query=request.query,
            limit=request.limit,
            filters=filters
        )

        return {
            "memories": [
                {
                    "id": mem.id,
                    "content": mem.content,
                    "outcome": mem.outcome,
                    "toolsUsed": mem.toolsUsed,
                    "importance": mem.importance,
                    "createdAt": mem.createdAt.isoformat()
                }
                for mem in memories
            ]
        }

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid memory type: {request.memoryType}"
        )


@router.get("/context/{sessionId}")
async def getContext(
    sessionId: str,
    query: str = "",
    maxTokens: int = 10000,
    tenantContext: TenantContext = Depends(extractTenantContext)
):
    context = await memoryManager.retrieveContext(
        tenantContext,
        sessionId,
        query,
        maxTokens=maxTokens
    )

    return {
        "context": context,
        "totalTokens": context["totalTokens"]
    }


@router.post("/consolidate/{sessionId}")
async def consolidateMemories(
    sessionId: str,
    tenantContext: TenantContext = Depends(extractTenantContext)
):
    result = await memoryManager.consolidateMemories(
        tenantContext,
        sessionId
    )

    return {
        "consolidated": result["consolidated"],
        "factsExtracted": result["facts_extracted"],
        "message": "Memory consolidation completed"
    }


@router.delete("/session/{sessionId}")
async def clearSession(
    sessionId: str,
    tenantContext: TenantContext = Depends(extractTenantContext)
):
    deletedCount = await memoryManager.clearSession(
        tenantContext,
        sessionId
    )

    return {
        "sessionId": sessionId,
        "deletedCount": deletedCount,
        "message": "Session cleared successfully"
    }
