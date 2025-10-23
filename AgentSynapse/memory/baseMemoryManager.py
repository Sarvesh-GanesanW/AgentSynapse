from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from schemas import MemoryRecord, TenantContext


class BaseMemoryManager(ABC):
    @abstractmethod
    async def store(self, record: MemoryRecord) -> str:
        pass

    @abstractmethod
    async def retrieve(
        self,
        tenantContext: TenantContext,
        query: str,
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[MemoryRecord]:
        pass

    @abstractmethod
    async def delete(self, recordId: str, tenantContext: TenantContext) -> bool:
        pass

    @abstractmethod
    async def update(self, recordId: str, record: MemoryRecord, tenantContext: TenantContext) -> bool:
        pass

    async def cleanup(self, tenantContext: TenantContext, olderThanDays: int) -> int:
        pass
