class ACEException(Exception):
    def __init__(self, message: str, code: str = "ACE_ERROR", details: dict = None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(self.message)


class AgentExecutionError(ACEException):
    def __init__(self, message: str, agentId: str = None, details: dict = None):
        super().__init__(message, "AGENT_EXECUTION_ERROR", details)
        self.agentId = agentId


class ToolExecutionError(ACEException):
    def __init__(self, message: str, toolName: str = None, details: dict = None):
        super().__init__(message, "TOOL_EXECUTION_ERROR", details)
        self.toolName = toolName


class MemoryError(ACEException):
    def __init__(self, message: str, memoryType: str = None, details: dict = None):
        super().__init__(message, "MEMORY_ERROR", details)
        self.memoryType = memoryType


class TenantIsolationError(ACEException):
    def __init__(self, message: str, tenantId: str = None, details: dict = None):
        super().__init__(message, "TENANT_ISOLATION_ERROR", details)
        self.tenantId = tenantId


class RecursionDepthExceeded(ACEException):
    def __init__(self, currentDepth: int, maxDepth: int):
        message = f"Max recursion depth exceeded: {currentDepth}/{maxDepth}"
        super().__init__(message, "RECURSION_DEPTH_EXCEEDED")
        self.currentDepth = currentDepth
        self.maxDepth = maxDepth


class TokenLimitExceeded(ACEException):
    def __init__(self, tokensUsed: int, tokenLimit: int):
        message = f"Token limit exceeded: {tokensUsed}/{tokenLimit}"
        super().__init__(message, "TOKEN_LIMIT_EXCEEDED")
        self.tokensUsed = tokensUsed
        self.tokenLimit = tokenLimit


class CostLimitExceeded(ACEException):
    def __init__(self, currentCost: float, costLimit: float):
        message = f"Cost limit exceeded: ${currentCost:.2f}/${costLimit:.2f}"
        super().__init__(message, "COST_LIMIT_EXCEEDED")
        self.currentCost = currentCost
        self.costLimit = costLimit


class InvalidToolDefinition(ACEException):
    def __init__(self, message: str, toolName: str = None):
        super().__init__(message, "INVALID_TOOL_DEFINITION")
        self.toolName = toolName


class AgentNotFound(ACEException):
    def __init__(self, agentId: str):
        super().__init__(f"Agent not found: {agentId}", "AGENT_NOT_FOUND")
        self.agentId = agentId


class ToolNotFound(ACEException):
    def __init__(self, toolName: str):
        super().__init__(f"Tool not found: {toolName}", "TOOL_NOT_FOUND")
        self.toolName = toolName


class UnauthorizedAccess(ACEException):
    def __init__(self, message: str, resource: str = None):
        super().__init__(message, "UNAUTHORIZED_ACCESS")
        self.resource = resource
