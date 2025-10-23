import asyncpg
from typing import List, Dict, Any, Optional
from config.settings import settings
from utils.logger import getLogger
from schemas import TenantContext

logger = getLogger(__name__)


class KnowledgeGraph:
    def __init__(self):
        self._pool = None

    async def _getPool(self):
        if not self._pool:
            self._pool = await asyncpg.create_pool(
                host=settings.rds.host,
                port=settings.rds.port,
                database=settings.rds.database,
                user=settings.rds.username,
                password=settings.rds.password,
                min_size=2,
                max_size=10
            )
        return self._pool

    async def initialize(self):
        pool = await self._getPool()

        createTablesSql = """
        CREATE EXTENSION IF NOT EXISTS vector;

        CREATE TABLE IF NOT EXISTS kg_entities (
            id VARCHAR(255) PRIMARY KEY,
            tenant_id VARCHAR(255) NOT NULL,
            user_id VARCHAR(255) NOT NULL,
            entity_type VARCHAR(100) NOT NULL,
            entity_name VARCHAR(500) NOT NULL,
            properties JSONB,
            embedding vector(384),
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_tenant_user ON kg_entities (tenant_id, user_id);
        CREATE INDEX IF NOT EXISTS idx_entity_type ON kg_entities (entity_type);
        CREATE INDEX IF NOT EXISTS idx_entity_name ON kg_entities (entity_name);

        CREATE TABLE IF NOT EXISTS kg_relationships (
            id VARCHAR(255) PRIMARY KEY,
            tenant_id VARCHAR(255) NOT NULL,
            from_entity_id VARCHAR(255) NOT NULL,
            to_entity_id VARCHAR(255) NOT NULL,
            relationship_type VARCHAR(100) NOT NULL,
            properties JSONB,
            weight FLOAT DEFAULT 1.0,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            is_active BOOLEAN DEFAULT TRUE,
            FOREIGN KEY (from_entity_id) REFERENCES kg_entities(id) ON DELETE CASCADE,
            FOREIGN KEY (to_entity_id) REFERENCES kg_entities(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_from_entity ON kg_relationships (from_entity_id);
        CREATE INDEX IF NOT EXISTS idx_to_entity ON kg_relationships (to_entity_id);
        CREATE INDEX IF NOT EXISTS idx_relationship_type ON kg_relationships (relationship_type);
        """

        async with pool.acquire() as conn:
            try:
                await conn.execute(createTablesSql)
                logger.info("knowledge_graph_initialized")
            except Exception as e:
                logger.error("kg_initialization_error", error=str(e))

    async def addEntity(
        self,
        tenantContext: TenantContext,
        entityId: str,
        entityType: str,
        entityName: str,
        properties: Optional[Dict[str, Any]] = None,
        embedding: Optional[List[float]] = None
    ) -> bool:
        pool = await self._getPool()

        insertSql = """
        INSERT INTO kg_entities (id, tenant_id, user_id, entity_type, entity_name, properties, embedding)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (id) DO UPDATE SET
            entity_name = $5,
            properties = $6,
            embedding = $7,
            updated_at = NOW()
        """

        async with pool.acquire() as conn:
            try:
                await conn.execute(
                    insertSql,
                    entityId,
                    tenantContext.tenantId,
                    tenantContext.userId,
                    entityType,
                    entityName,
                    properties or {},
                    embedding
                )
                logger.info("kg_entity_added", entityId=entityId, entityType=entityType)
                return True

            except Exception as e:
                logger.error("kg_add_entity_error", error=str(e), entityId=entityId)
                return False

    async def addRelationship(
        self,
        tenantContext: TenantContext,
        relationshipId: str,
        fromEntityId: str,
        toEntityId: str,
        relationshipType: str,
        properties: Optional[Dict[str, Any]] = None,
        weight: float = 1.0
    ) -> bool:
        pool = await self._getPool()

        insertSql = """
        INSERT INTO kg_relationships (id, tenant_id, from_entity_id, to_entity_id, relationship_type, properties, weight)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (id) DO UPDATE SET
            properties = $6,
            weight = $7,
            updated_at = NOW()
        """

        async with pool.acquire() as conn:
            try:
                await conn.execute(
                    insertSql,
                    relationshipId,
                    tenantContext.tenantId,
                    fromEntityId,
                    toEntityId,
                    relationshipType,
                    properties or {},
                    weight
                )
                logger.info("kg_relationship_added", relationshipId=relationshipId, type=relationshipType)
                return True

            except Exception as e:
                logger.error("kg_add_relationship_error", error=str(e))
                return False

    async def getEntity(self, entityId: str, tenantContext: TenantContext) -> Optional[Dict[str, Any]]:
        pool = await self._getPool()

        selectSql = """
        SELECT id, entity_type, entity_name, properties, created_at, updated_at
        FROM kg_entities
        WHERE id = $1 AND tenant_id = $2
        """

        async with pool.acquire() as conn:
            try:
                row = await conn.fetchrow(selectSql, entityId, tenantContext.tenantId)
                if row:
                    return dict(row)
                return None

            except Exception as e:
                logger.error("kg_get_entity_error", error=str(e), entityId=entityId)
                return None

    async def findRelatedEntities(
        self,
        entityId: str,
        tenantContext: TenantContext,
        relationshipType: Optional[str] = None,
        maxDepth: int = 2
    ) -> List[Dict[str, Any]]:
        pool = await self._getPool()

        if maxDepth == 1:
            sql = """
            SELECT DISTINCT e.id, e.entity_type, e.entity_name, e.properties, r.relationship_type, r.weight
            FROM kg_entities e
            JOIN kg_relationships r ON (r.to_entity_id = e.id OR r.from_entity_id = e.id)
            WHERE (r.from_entity_id = $1 OR r.to_entity_id = $1)
              AND e.id != $1
              AND e.tenant_id = $2
              AND r.is_active = TRUE
            """

            params = [entityId, tenantContext.tenantId]

            if relationshipType:
                sql += " AND r.relationship_type = $3"
                params.append(relationshipType)

            sql += " ORDER BY r.weight DESC LIMIT 20"

        else:
            sql = """
            WITH RECURSIVE entity_graph AS (
                SELECT e.id, e.entity_type, e.entity_name, e.properties, r.relationship_type, r.weight, 1 as depth
                FROM kg_entities e
                JOIN kg_relationships r ON (r.to_entity_id = e.id OR r.from_entity_id = e.id)
                WHERE (r.from_entity_id = $1 OR r.to_entity_id = $1)
                  AND e.id != $1
                  AND e.tenant_id = $2
                  AND r.is_active = TRUE

                UNION

                SELECT e.id, e.entity_type, e.entity_name, e.properties, r.relationship_type, r.weight, eg.depth + 1
                FROM kg_entities e
                JOIN kg_relationships r ON (r.to_entity_id = e.id OR r.from_entity_id = e.id)
                JOIN entity_graph eg ON (r.from_entity_id = eg.id OR r.to_entity_id = eg.id)
                WHERE e.id != eg.id
                  AND e.tenant_id = $2
                  AND r.is_active = TRUE
                  AND eg.depth < $3
            )
            SELECT DISTINCT id, entity_type, entity_name, properties, relationship_type, weight
            FROM entity_graph
            ORDER BY weight DESC
            LIMIT 50
            """

            params = [entityId, tenantContext.tenantId, maxDepth]

        async with pool.acquire() as conn:
            try:
                rows = await conn.fetch(sql, *params)
                return [dict(row) for row in rows]

            except Exception as e:
                logger.error("kg_find_related_error", error=str(e), entityId=entityId)
                return []

    async def searchEntities(
        self,
        tenantContext: TenantContext,
        entityType: Optional[str] = None,
        namePattern: Optional[str] = None,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        pool = await self._getPool()

        sql = "SELECT id, entity_type, entity_name, properties FROM kg_entities WHERE tenant_id = $1"
        params = [tenantContext.tenantId]
        paramCount = 1

        if entityType:
            paramCount += 1
            sql += f" AND entity_type = ${paramCount}"
            params.append(entityType)

        if namePattern:
            paramCount += 1
            sql += f" AND entity_name ILIKE ${paramCount}"
            params.append(f"%{namePattern}%")

        sql += f" ORDER BY created_at DESC LIMIT {limit}"

        async with pool.acquire() as conn:
            try:
                rows = await conn.fetch(sql, *params)
                return [dict(row) for row in rows]

            except Exception as e:
                logger.error("kg_search_entities_error", error=str(e))
                return []

    async def deleteEntity(self, entityId: str, tenantContext: TenantContext) -> bool:
        pool = await self._getPool()

        deleteSql = "DELETE FROM kg_entities WHERE id = $1 AND tenant_id = $2"

        async with pool.acquire() as conn:
            try:
                await conn.execute(deleteSql, entityId, tenantContext.tenantId)
                logger.info("kg_entity_deleted", entityId=entityId)
                return True

            except Exception as e:
                logger.error("kg_delete_entity_error", error=str(e), entityId=entityId)
                return False

    async def invalidateRelationship(self, relationshipId: str, tenantContext: TenantContext) -> bool:
        pool = await self._getPool()

        updateSql = "UPDATE kg_relationships SET is_active = FALSE WHERE id = $1 AND tenant_id = $2"

        async with pool.acquire() as conn:
            try:
                await conn.execute(updateSql, relationshipId, tenantContext.tenantId)
                logger.info("kg_relationship_invalidated", relationshipId=relationshipId)
                return True

            except Exception as e:
                logger.error("kg_invalidate_relationship_error", error=str(e))
                return False


knowledgeGraph = KnowledgeGraph()
