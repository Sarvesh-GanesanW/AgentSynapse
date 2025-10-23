from typing import List, Dict, Any, Optional
from datetime import datetime
from config.settings import settings
from utils.logger import getLogger
from schemas import (
    TenantContext,
    MemoryType,
    MemorySource,
    EpisodicMemoryRecord,
    SemanticMemoryRecord
)
from memory.workingMemory.redisMemory import redisWorkingMemory
from memory.episodicMemory.dynamodbMemory import dynamodbEpisodicMemory
from memory.semanticMemory.vectorStore import vectorStore
from memory.semanticMemory.knowledgeGraph import knowledgeGraph
from memory.proceduralMemory.s3Storage import s3ProceduralMemory
from core.bedrockClient import bedrockClient

logger = getLogger(__name__)


class MemoryManager:
    def __init__(self):
        self.workingMemory = redisWorkingMemory
        self.episodicMemory = dynamodbEpisodicMemory
        self.semanticMemory = vectorStore
        self.knowledgeGraph = knowledgeGraph
        self.proceduralMemory = s3ProceduralMemory

    async def storeInteraction(
        self,
        tenantContext: TenantContext,
        sessionId: str,
        agentId: str,
        userMessage: str,
        agentResponse: str,
        toolsUsed: List[str],
        outcome: str,
        importance: float = 0.5
    ) -> str:
        record = EpisodicMemoryRecord(
            tenantId=tenantContext.tenantId,
            userId=tenantContext.userId,
            sessionId=sessionId,
            agentId=agentId,
            memoryType=MemoryType.EPISODIC,
            content=f"User: {userMessage}\nAgent: {agentResponse}",
            outcome=outcome,
            source=MemorySource.SYSTEM_DERIVED,
            importance=importance,
            toolsUsed=toolsUsed,
            confidenceScore=1.0
        )

        return await self.episodicMemory.store(record)

    async def storeFact(
        self,
        tenantContext: TenantContext,
        sessionId: str,
        fact: str,
        source: MemorySource = MemorySource.AGENT_INFERRED,
        importance: float = 0.7,
        tags: Optional[List[str]] = None,
        relatedEntities: Optional[List[str]] = None
    ) -> str:
        record = SemanticMemoryRecord(
            tenantId=tenantContext.tenantId,
            userId=tenantContext.userId,
            sessionId=sessionId,
            memoryType=MemoryType.SEMANTIC,
            content=fact,
            source=source,
            importance=importance,
            confidenceScore=0.8 if source == MemorySource.AGENT_INFERRED else 1.0,
            tags=tags or [],
            relatedEntities=relatedEntities or []
        )

        return await self.semanticMemory.store(record)

    async def retrieveContext(
        self,
        tenantContext: TenantContext,
        sessionId: str,
        query: str,
        maxTokens: int = 10000
    ) -> Dict[str, Any]:
        context = {
            "working": {},
            "episodic": [],
            "semantic": [],
            "procedural": [],
            "totalTokens": 0
        }

        workingCtx = await self.workingMemory.getAll(tenantContext, sessionId)
        context["working"] = workingCtx
        context["totalTokens"] += bedrockClient.countTokens(str(workingCtx))

        if context["totalTokens"] < maxTokens:
            recentEpisodic = await self.episodicMemory.retrieveBySession(
                tenantContext,
                sessionId,
                limit=10
            )
            for memory in recentEpisodic:
                tokens = bedrockClient.countTokens(memory.content)
                if context["totalTokens"] + tokens < maxTokens:
                    context["episodic"].append(memory.dict())
                    context["totalTokens"] += tokens
                else:
                    break

        if context["totalTokens"] < maxTokens * 0.7:
            semanticMemories = await self.semanticMemory.search(
                tenantContext,
                query,
                limit=settings.memory.topKSemanticRetrieval
            )

            rankedMemories = self._rankMemories(semanticMemories, query)

            for memory in rankedMemories:
                tokens = bedrockClient.countTokens(memory.content)
                if context["totalTokens"] + tokens < maxTokens:
                    context["semantic"].append(memory.dict())
                    context["totalTokens"] += tokens
                else:
                    break

        proceduralPatterns = await self.proceduralMemory.search(
            tenantContext,
            limit=5
        )
        context["procedural"] = [p.name for p in proceduralPatterns[:3]]

        return context

    def _rankMemories(
        self,
        memories: List[SemanticMemoryRecord],
        query: str
    ) -> List[SemanticMemoryRecord]:
        now = datetime.utcnow()

        for memory in memories:
            recencyScore = self._calculateRecencyScore(memory.createdAt, now)
            importanceScore = memory.importance
            confidenceScore = memory.confidenceScore

            memory.contextData["relevanceScore"] = (
                recencyScore * 0.3 +
                importanceScore * 0.4 +
                confidenceScore * 0.3
            )

        return sorted(
            memories,
            key=lambda m: m.contextData.get("relevanceScore", 0),
            reverse=True
        )

    def _calculateRecencyScore(self, createdAt: datetime, now: datetime) -> float:
        age = (now - createdAt).total_seconds() / 86400
        decayThreshold = settings.memory.decayThresholdDays

        if age < decayThreshold:
            return 1.0
        elif age < decayThreshold * 4:
            return 1.0 - ((age - decayThreshold) / (decayThreshold * 3)) * 0.5
        else:
            return 0.5 - ((age - decayThreshold * 4) / (decayThreshold * 10)) * 0.4

    async def consolidateMemories(
        self,
        tenantContext: TenantContext,
        sessionId: str
    ) -> Dict[str, int]:
        episodicMemories = await self.episodicMemory.retrieveBySession(
            tenantContext,
            sessionId,
            limit=100
        )

        if len(episodicMemories) < 10:
            return {"consolidated": 0, "facts_extracted": 0}

        summaryPrompt = f"""
Analyze these conversation interactions and extract key facts and insights:

{[m.content for m in episodicMemories[:20]]}

Extract:
1. User preferences
2. Important facts mentioned
3. Recurring patterns
4. Key entities and relationships

Format as JSON list of facts.
"""

        messages = bedrockClient.formatMessages(summaryPrompt)
        response = bedrockClient.invokeModel(
            messages=messages,
            systemPrompt="You are a memory consolidation expert. Extract factual knowledge from conversations.",
            temperature=0.3,
            maxTokens=2000
        )

        extractedText = bedrockClient.extractTextResponse(response)

        import json
        try:
            facts = json.loads(extractedText)
            factsStored = 0

            for fact in facts:
                if isinstance(fact, dict):
                    await self.storeFact(
                        tenantContext,
                        sessionId,
                        fact.get("fact", str(fact)),
                        source=MemorySource.AGENT_INFERRED,
                        importance=fact.get("importance", 0.7),
                        tags=fact.get("tags", [])
                    )
                    factsStored += 1

            return {"consolidated": len(episodicMemories), "facts_extracted": factsStored}

        except json.JSONDecodeError:
            logger.error("memory_consolidation_parse_error", response=extractedText)
            return {"consolidated": 0, "facts_extracted": 0}

    async def performDecay(self, tenantContext: TenantContext) -> int:
        decayedCount = await self.episodicMemory.cleanup(
            tenantContext,
            olderThanDays=settings.memory.episodicRetentionDays
        )

        logger.info("memory_decay_completed", decayedCount=decayedCount, tenantId=tenantContext.tenantId)
        return decayedCount

    async def storeWorkingContext(
        self,
        tenantContext: TenantContext,
        sessionId: str,
        key: str,
        value: Any
    ) -> bool:
        return await self.workingMemory.set(
            tenantContext,
            sessionId,
            key,
            value,
            ttl=settings.memory.workingMemoryTtl
        )

    async def getWorkingContext(
        self,
        tenantContext: TenantContext,
        sessionId: str,
        key: str
    ) -> Optional[Any]:
        return await self.workingMemory.get(tenantContext, sessionId, key)

    async def appendToConversation(
        self,
        tenantContext: TenantContext,
        sessionId: str,
        message: Dict[str, Any]
    ) -> int:
        return await self.workingMemory.appendToList(
            tenantContext,
            sessionId,
            "conversation_history",
            message
        )

    async def getConversationHistory(
        self,
        tenantContext: TenantContext,
        sessionId: str,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        messages = await self.workingMemory.getList(
            tenantContext,
            sessionId,
            "conversation_history",
            start=-limit
        )
        return messages

    async def clearSession(
        self,
        tenantContext: TenantContext,
        sessionId: str
    ) -> int:
        return await self.workingMemory.clearSession(tenantContext, sessionId)


memoryManager = MemoryManager()
