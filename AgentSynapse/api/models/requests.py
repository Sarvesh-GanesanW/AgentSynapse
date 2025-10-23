from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from schemas import AgentType, ToolPermission


class ExecuteAgentRequest(BaseModel):
    agentId: str
    userMessage: str
    sessionId: str
    stream: bool = False


class CreateAgentRequest(BaseModel):
    name: str
    type: AgentType
    description: str
    systemPrompt: str
    temperature: float = Field(default=0.7, ge=0.0, le=1.0)
    maxTokens: int = Field(default=4096, gt=0)
    toolIds: List[str] = Field(default_factory=list)
    isAsync: bool = False
    timeoutSeconds: int = 300
    customSettings: Dict[str, Any] = Field(default_factory=dict)


class UpdateAgentRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    systemPrompt: Optional[str] = None
    temperature: Optional[float] = None
    maxTokens: Optional[int] = None
    toolIds: Optional[List[str]] = None
    timeoutSeconds: Optional[int] = None
    customSettings: Optional[Dict[str, Any]] = None


class RegisterToolRequest(BaseModel):
    name: str
    version: str = "1.0.0"
    description: str
    inputSchema: Dict[str, Any]
    outputSchema: Optional[Dict[str, Any]] = None
    permission: ToolPermission = ToolPermission.PRIVATE
    codeS3Key: Optional[str] = None
    yamlConfig: Optional[Dict[str, Any]] = None
    requiresAuth: bool = True


class OrchestrateRequest(BaseModel):
    userRequest: str
    sessionId: str


class AsyncTaskRequest(BaseModel):
    agentId: str
    userMessage: str
    sessionId: str
    callbackUrl: Optional[str] = None


class StoreFactRequest(BaseModel):
    fact: str
    sessionId: str
    importance: float = 0.7
    tags: Optional[List[str]] = None
    relatedEntities: Optional[List[str]] = None


class SearchMemoryRequest(BaseModel):
    query: str
    sessionId: Optional[str] = None
    limit: int = 10
    memoryType: str = "semantic"
