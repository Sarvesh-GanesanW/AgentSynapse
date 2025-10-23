import pytest
from schemas import TenantContext, MemorySource
from memory.memoryManager import memoryManager


@pytest.fixture
def tenantContext():
    return TenantContext(
        tenantId="test-tenant",
        userId="test-user"
    )


@pytest.mark.asyncio
async def testStoreInteraction(tenantContext):
    recordId = await memoryManager.storeInteraction(
        tenantContext,
        "session-1",
        "agent-1",
        "What is 2+2?",
        "2+2 equals 4",
        toolsUsed=["calculator"],
        outcome="success",
        importance=0.6
    )

    assert recordId is not None
    assert isinstance(recordId, str)


@pytest.mark.asyncio
async def testStoreFact(tenantContext):
    factId = await memoryManager.storeFact(
        tenantContext,
        "session-1",
        "User prefers Python over JavaScript",
        source=MemorySource.USER_STATED,
        importance=0.8,
        tags=["preference", "programming"]
    )

    assert factId is not None


@pytest.mark.asyncio
async def testRetrieveContext(tenantContext):
    context = await memoryManager.retrieveContext(
        tenantContext,
        "session-1",
        "programming preferences",
        maxTokens=5000
    )

    assert "working" in context
    assert "episodic" in context
    assert "semantic" in context
    assert "totalTokens" in context
    assert context["totalTokens"] <= 5000


def testRecencyScoreCalculation():
    from datetime import datetime, timedelta

    now = datetime.utcnow()
    recentDate = now - timedelta(days=1)
    oldDate = now - timedelta(days=30)

    recentScore = memoryManager._calculateRecencyScore(recentDate, now)
    oldScore = memoryManager._calculateRecencyScore(oldDate, now)

    assert recentScore > oldScore
    assert 0 <= recentScore <= 1.0
    assert 0 <= oldScore <= 1.0


@pytest.mark.asyncio
async def testWorkingMemoryOperations(tenantContext):
    await memoryManager.storeWorkingContext(
        tenantContext,
        "session-2",
        "user_preference",
        {"theme": "dark", "language": "en"}
    )

    value = await memoryManager.getWorkingContext(
        tenantContext,
        "session-2",
        "user_preference"
    )

    assert value is not None
    assert value["theme"] == "dark"
    assert value["language"] == "en"
