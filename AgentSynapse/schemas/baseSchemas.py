"""
Base Schema Definitions for ACE Framework
Core data models used across the framework
"""

from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field
from uuid import uuid4


class AgentStatus(str, Enum):
    """Agent execution status"""
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class AgentType(str, Enum):
    """Types of agents in the system"""
    ORCHESTRATOR = "orchestrator"
    SQL_AGENT = "sql_agent"
    BI_AGENT = "bi_agent"
    ETL_AGENT = "etl_agent"
    ANALYTICS_AGENT = "analytics_agent"
    CUSTOM = "custom"


class MemoryType(str, Enum):
    """Types of memory in the system"""
    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


class MemorySource(str, Enum):
    """Source of memory/knowledge"""
    USER_STATED = "user_stated"
    AGENT_INFERRED = "agent_inferred"
    SYSTEM_DERIVED = "system_derived"
    TOOL_RESULT = "tool_result"


class ToolPermission(str, Enum):
    """Tool access permissions"""
    PUBLIC = "public"
    PRIVATE = "private"
    ORG_SHARED = "org_shared"


class ExecutionMode(str, Enum):
    """Agent execution modes"""
    SYNC = "sync"
    ASYNC = "async"


class BaseSchema(BaseModel):
    """Base schema with common fields"""
    id: str = Field(default_factory=lambda: str(uuid4()))
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    updatedAt: datetime = Field(default_factory=datetime.utcnow)

    model_config = {
        "json_encoders": {
            datetime: lambda v: v.isoformat()
        },
        "arbitrary_types_allowed": True
    }


class TenantContext(BaseModel):
    """Multi-tenant context information"""
    tenantId: str
    userId: str
    orgId: Optional[str] = None
    roles: List[str] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)
    costLimit: Optional[float] = None


class AgentConfig(BaseSchema):
    """Agent configuration"""
    name: str
    type: AgentType
    description: str
    systemPrompt: str
    temperature: float = 0.7
    maxTokens: int = 4096
    toolIds: List[str] = Field(default_factory=list)
    tenantContext: TenantContext
    isAsync: bool = False
    timeoutSeconds: int = 300
    customSettings: Dict[str, Any] = Field(default_factory=dict)


class ToolDefinition(BaseSchema):
    """Tool definition schema"""
    name: str
    version: str = "1.0.0"
    description: str
    inputSchema: Dict[str, Any]
    outputSchema: Optional[Dict[str, Any]] = None
    permission: ToolPermission = ToolPermission.PRIVATE
    tenantId: str
    codeS3Key: Optional[str] = None
    yamlConfig: Optional[Dict[str, Any]] = None
    isActive: bool = True
    requiresAuth: bool = True


class AgentExecution(BaseSchema):
    """Agent execution record"""
    agentId: str
    sessionId: str
    tenantContext: TenantContext
    userMessage: str
    agentResponse: Optional[str] = None
    status: AgentStatus = AgentStatus.IDLE
    toolCalls: List[Dict[str, Any]] = Field(default_factory=list)
    tokensUsed: int = 0
    executionTimeMs: int = 0
    errorMessage: Optional[str] = None
    parentExecutionId: Optional[str] = None  # For nested agent calls
    depth: int = 0  # Recursion depth


class MemoryRecord(BaseSchema):
    """Base memory record"""
    tenantId: str
    userId: str
    sessionId: str
    memoryType: MemoryType
    content: str
    contextData: Dict[str, Any] = Field(default_factory=dict)
    source: MemorySource
    confidenceScore: float = 1.0
    importance: float = 0.5
    tags: List[str] = Field(default_factory=list)
    expiresAt: Optional[datetime] = None


class EpisodicMemoryRecord(MemoryRecord):
    """Episodic memory - specific events/interactions"""
    agentId: str
    toolsUsed: List[str] = Field(default_factory=list)
    outcome: str
    sentiment: Optional[str] = None


class SemanticMemoryRecord(MemoryRecord):
    """Semantic memory - knowledge and facts"""
    embedding: Optional[List[float]] = None
    relatedEntities: List[str] = Field(default_factory=list)
    knowledgeGraphId: Optional[str] = None


class ProceduralMemoryRecord(BaseSchema):
    """Procedural memory - workflows and patterns"""
    tenantId: str
    name: str
    description: str
    workflow: List[Dict[str, Any]]
    successCount: int = 0
    failureCount: int = 0
    avgExecutionTimeMs: float = 0.0
    s3Key: str
    tags: List[str] = Field(default_factory=list)


class TaskDecomposition(BaseModel):
    """Task decomposition for multi-agent coordination"""
    taskId: str = Field(default_factory=lambda: str(uuid4()))
    description: str
    assignedAgentType: AgentType
    dependencies: List[str] = Field(default_factory=list)
    priority: int = 1
    estimatedTokens: int = 1000
    status: AgentStatus = AgentStatus.IDLE
    result: Optional[Dict[str, Any]] = None


class AgentCommunication(BaseModel):
    """Inter-agent communication message"""
    messageId: str = Field(default_factory=lambda: str(uuid4()))
    fromAgentId: str
    toAgentId: str
    messageType: str  # 'request', 'response', 'notification'
    payload: Dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    correlationId: Optional[str] = None
