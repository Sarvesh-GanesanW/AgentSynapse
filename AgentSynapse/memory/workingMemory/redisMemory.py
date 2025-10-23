import json
import redis.asyncio as redis
from typing import Dict, Any, Optional, List
from config.settings import settings
from utils.logger import getLogger
from utils.exceptions import MemoryError
from utils.serialization import DecimalEncoder
from schemas import TenantContext

logger = getLogger(__name__)


class RedisWorkingMemory:
    def __init__(self):
        self._pool = None
        self._redis = None

    async def _getClient(self):
        if not self._redis:
            self._pool = redis.ConnectionPool(
                host=settings.redis.host,
                port=settings.redis.port,
                db=settings.redis.db,
                password=settings.redis.password,
                decode_responses=True
            )
            self._redis = redis.Redis(connection_pool=self._pool)
        return self._redis

    def _buildKey(self, tenantId: str, userId: str, sessionId: str, key: str) -> str:
        return f"{tenantId}:{userId}:{sessionId}:{key}"

    async def set(
        self,
        tenantContext: TenantContext,
        sessionId: str,
        key: str,
        value: Any,
        ttl: Optional[int] = None
    ) -> bool:
        client = await self._getClient()
        fullKey = self._buildKey(tenantContext.tenantId, tenantContext.userId, sessionId, key)

        try:
            serializedValue = json.dumps(value, cls=DecimalEncoder) if not isinstance(value, str) else value
            if ttl:
                await client.setex(fullKey, ttl, serializedValue)
            else:
                await client.set(fullKey, serializedValue)
            return True

        except Exception as e:
            logger.error("redis_set_error", key=fullKey, error=str(e))
            raise MemoryError(f"Failed to set working memory: {str(e)}", "working")

    async def get(
        self,
        tenantContext: TenantContext,
        sessionId: str,
        key: str
    ) -> Optional[Any]:
        client = await self._getClient()
        fullKey = self._buildKey(tenantContext.tenantId, tenantContext.userId, sessionId, key)

        try:
            value = await client.get(fullKey)
            if value:
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return value
            return None

        except Exception as e:
            logger.error("redis_get_error", key=fullKey, error=str(e))
            raise MemoryError(f"Failed to get working memory: {str(e)}", "working")

    async def delete(
        self,
        tenantContext: TenantContext,
        sessionId: str,
        key: str
    ) -> bool:
        client = await self._getClient()
        fullKey = self._buildKey(tenantContext.tenantId, tenantContext.userId, sessionId, key)

        try:
            deleted = await client.delete(fullKey)
            return deleted > 0

        except Exception as e:
            logger.error("redis_delete_error", key=fullKey, error=str(e))
            return False

    async def getAll(
        self,
        tenantContext: TenantContext,
        sessionId: str
    ) -> Dict[str, Any]:
        client = await self._getClient()
        pattern = self._buildKey(tenantContext.tenantId, tenantContext.userId, sessionId, "*")

        try:
            keys = []
            async for key in client.scan_iter(match=pattern):
                keys.append(key)

            if not keys:
                return {}

            values = await client.mget(keys)
            result = {}

            for key, value in zip(keys, values):
                shortKey = key.split(":")[-1]
                if value:
                    try:
                        result[shortKey] = json.loads(value)
                    except json.JSONDecodeError:
                        result[shortKey] = value

            return result

        except Exception as e:
            logger.error("redis_getall_error", pattern=pattern, error=str(e))
            return {}

    async def clearSession(
        self,
        tenantContext: TenantContext,
        sessionId: str
    ) -> int:
        client = await self._getClient()
        pattern = self._buildKey(tenantContext.tenantId, tenantContext.userId, sessionId, "*")

        try:
            keys = []
            async for key in client.scan_iter(match=pattern):
                keys.append(key)

            if keys:
                return await client.delete(*keys)
            return 0

        except Exception as e:
            logger.error("redis_clear_session_error", pattern=pattern, error=str(e))
            return 0

    async def appendToList(
        self,
        tenantContext: TenantContext,
        sessionId: str,
        key: str,
        value: Any
    ) -> int:
        client = await self._getClient()
        fullKey = self._buildKey(tenantContext.tenantId, tenantContext.userId, sessionId, key)

        try:
            serializedValue = json.dumps(value, cls=DecimalEncoder) if not isinstance(value, str) else value
            return await client.rpush(fullKey, serializedValue)

        except Exception as e:
            logger.error("redis_append_error", key=fullKey, error=str(e))
            raise MemoryError(f"Failed to append to list: {str(e)}", "working")

    async def getList(
        self,
        tenantContext: TenantContext,
        sessionId: str,
        key: str,
        start: int = 0,
        end: int = -1
    ) -> List[Any]:
        client = await self._getClient()
        fullKey = self._buildKey(tenantContext.tenantId, tenantContext.userId, sessionId, key)

        try:
            values = await client.lrange(fullKey, start, end)
            result = []

            for value in values:
                try:
                    result.append(json.loads(value))
                except json.JSONDecodeError:
                    result.append(value)

            return result

        except Exception as e:
            logger.error("redis_getlist_error", key=fullKey, error=str(e))
            return []

    async def close(self):
        if self._redis:
            await self._redis.close()
            await self._pool.disconnect()


redisWorkingMemory = RedisWorkingMemory()
