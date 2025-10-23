from typing import List, Dict, Any, Optional
from opensearchpy import AsyncOpenSearch, RequestsHttpConnection
from sentence_transformers import SentenceTransformer
from config.settings import settings
from utils.logger import getLogger
from utils.exceptions import MemoryError
from schemas import SemanticMemoryRecord, TenantContext, MemorySource, MemoryType
from datetime import datetime

logger = getLogger(__name__)


class VectorStore:
    def __init__(self):
        self._client = None
        self._encoder = None
        self.indexName = settings.opensearch.indexSemantic

    def _getClient(self) -> AsyncOpenSearch:
        if not self._client:
            endpoint = settings.opensearch.endpoint
            use_ssl = endpoint.startswith("https")
            self._client = AsyncOpenSearch(
                hosts=[endpoint],
                use_ssl=use_ssl,
                verify_certs=use_ssl,
                connection_class=RequestsHttpConnection
            )
        return self._client

    def _getEncoder(self) -> SentenceTransformer:
        if not self._encoder:
            self._encoder = SentenceTransformer('all-MiniLM-L6-v2')
        return self._encoder

    async def _ensureIndex(self):
        client = self._getClient()

        indexBody = {
            "settings": {
                "index": {
                    "knn": True,
                    "knn.algo_param.ef_search": 100
                }
            },
            "mappings": {
                "properties": {
                    "id": {"type": "keyword"},
                    "tenantId": {"type": "keyword"},
                    "userId": {"type": "keyword"},
                    "sessionId": {"type": "keyword"},
                    "content": {"type": "text"},
                    "embedding": {
                        "type": "knn_vector",
                        "dimension": 384,
                        "method": {
                            "name": "hnsw",
                            "space_type": "cosinesimil",
                            "engine": "nmslib"
                        }
                    },
                    "source": {"type": "keyword"},
                    "confidenceScore": {"type": "float"},
                    "importance": {"type": "float"},
                    "tags": {"type": "keyword"},
                    "relatedEntities": {"type": "keyword"},
                    "knowledgeGraphId": {"type": "keyword"},
                    "createdAt": {"type": "date"},
                    "updatedAt": {"type": "date"}
                }
            }
        }

        try:
            exists = await client.indices.exists(index=self.indexName)
            if not exists:
                await client.indices.create(index=self.indexName, body=indexBody)
                logger.info("opensearch_index_created", index=self.indexName)
        except Exception as e:
            logger.error("opensearch_index_creation_error", error=str(e))

    def _generateEmbedding(self, text: str) -> List[float]:
        encoder = self._getEncoder()
        return encoder.encode(text).tolist()

    async def store(self, record: SemanticMemoryRecord) -> str:
        await self._ensureIndex()
        client = self._getClient()

        if not record.embedding:
            record.embedding = self._generateEmbedding(record.content)

        doc = {
            "id": record.id,
            "tenantId": record.tenantId,
            "userId": record.userId,
            "sessionId": record.sessionId,
            "content": record.content,
            "embedding": record.embedding,
            "source": record.source.value,
            "confidenceScore": record.confidenceScore,
            "importance": record.importance,
            "tags": record.tags,
            "relatedEntities": record.relatedEntities,
            "knowledgeGraphId": record.knowledgeGraphId,
            "contextData": record.contextData,
            "createdAt": record.createdAt.isoformat(),
            "updatedAt": record.updatedAt.isoformat()
        }

        try:
            await client.index(
                index=self.indexName,
                id=record.id,
                body=doc
            )
            logger.info("semantic_memory_stored", recordId=record.id)
            return record.id

        except Exception as e:
            logger.error("semantic_store_error", error=str(e), recordId=record.id)
            raise MemoryError(f"Failed to store semantic memory: {str(e)}", "semantic")

    async def search(
        self,
        tenantContext: TenantContext,
        query: str,
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[SemanticMemoryRecord]:
        client = self._getClient()
        queryEmbedding = self._generateEmbedding(query)

        must = [
            {"term": {"tenantId": tenantContext.tenantId}},
            {"term": {"userId": tenantContext.userId}}
        ]

        if filters:
            if filters.get("tags"):
                must.append({"terms": {"tags": filters["tags"]}})

            if filters.get("minImportance"):
                must.append({"range": {"importance": {"gte": filters["minImportance"]}}})

            if filters.get("sessionId"):
                must.append({"term": {"sessionId": filters["sessionId"]}})

        searchBody = {
            "size": limit,
            "query": {
                "script_score": {
                    "query": {
                        "bool": {
                            "must": must
                        }
                    },
                    "script": {
                        "source": "knn_score",
                        "lang": "knn",
                        "params": {
                            "field": "embedding",
                            "query_value": queryEmbedding,
                            "space_type": "cosinesimil"
                        }
                    }
                }
            }
        }

        try:
            response = await client.search(
                index=self.indexName,
                body=searchBody
            )

            hits = response["hits"]["hits"]
            records = []

            for hit in hits:
                source = hit["_source"]
                record = SemanticMemoryRecord(
                    id=source["id"],
                    tenantId=source["tenantId"],
                    userId=source["userId"],
                    sessionId=source["sessionId"],
                    memoryType=MemoryType.SEMANTIC,
                    content=source["content"],
                    embedding=source["embedding"],
                    source=MemorySource(source["source"]),
                    confidenceScore=source["confidenceScore"],
                    importance=source["importance"],
                    tags=source.get("tags", []),
                    relatedEntities=source.get("relatedEntities", []),
                    knowledgeGraphId=source.get("knowledgeGraphId"),
                    contextData=source.get("contextData", {}),
                    createdAt=datetime.fromisoformat(source["createdAt"]),
                    updatedAt=datetime.fromisoformat(source["updatedAt"])
                )
                records.append(record)

            return records

        except Exception as e:
            logger.error("semantic_search_error", error=str(e), query=query)
            return []

    async def delete(self, recordId: str, tenantContext: TenantContext) -> bool:
        client = self._getClient()

        try:
            await client.delete(index=self.indexName, id=recordId)
            logger.info("semantic_memory_deleted", recordId=recordId)
            return True

        except Exception as e:
            logger.error("semantic_delete_error", error=str(e), recordId=recordId)
            return False

    async def bulkStore(self, records: List[SemanticMemoryRecord]) -> int:
        await self._ensureIndex()
        client = self._getClient()

        actions = []
        for record in records:
            if not record.embedding:
                record.embedding = self._generateEmbedding(record.content)

            action = {
                "index": {
                    "_index": self.indexName,
                    "_id": record.id
                }
            }

            doc = {
                "id": record.id,
                "tenantId": record.tenantId,
                "userId": record.userId,
                "sessionId": record.sessionId,
                "content": record.content,
                "embedding": record.embedding,
                "source": record.source.value,
                "confidenceScore": record.confidenceScore,
                "importance": record.importance,
                "tags": record.tags,
                "relatedEntities": record.relatedEntities,
                "knowledgeGraphId": record.knowledgeGraphId,
                "contextData": record.contextData,
                "createdAt": record.createdAt.isoformat(),
                "updatedAt": record.updatedAt.isoformat()
            }

            actions.append(action)
            actions.append(doc)

        try:
            from opensearchpy.helpers import async_bulk
            success, failed = await async_bulk(client, actions)
            logger.info("semantic_bulk_store", success=success, failed=len(failed))
            return success

        except Exception as e:
            logger.error("semantic_bulk_store_error", error=str(e))
            return 0


vectorStore = VectorStore()
