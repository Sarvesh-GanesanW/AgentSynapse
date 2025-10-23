from typing import Dict, Any, List, Optional
from datetime import datetime
from config.settings import settings
from utils.logger import getLogger
from utils.exceptions import (
    AgentExecutionError,
    RecursionDepthExceeded,
    TokenLimitExceeded
)
from schemas import (
    AgentConfig,
    AgentExecution,
    AgentStatus
)
from core.bedrockClient import bedrockClient
from memory.memoryManager import memoryManager
from tools.registry.toolRegistry import toolRegistry
from tools.executor.toolExecutor import toolExecutor

logger = getLogger(__name__)


class AgentEngine:
    def __init__(self):
        self.bedrock = bedrockClient
        self.memory = memoryManager
        self.toolRegistry = toolRegistry
        self.toolExecutor = toolExecutor
        self._activeExecutions = {}

    async def execute(
        self,
        agentConfig: AgentConfig,
        userMessage: str,
        sessionId: str,
        authToken: Optional[str] = None,
        parentExecutionId: Optional[str] = None,
        depth: int = 0
    ) -> AgentExecution:
        if depth >= settings.agent.maxRecursionDepth:
            raise RecursionDepthExceeded(depth, settings.agent.maxRecursionDepth)

        execution = AgentExecution.model_construct(
            agentId=agentConfig.id,
            sessionId=sessionId,
            tenantContext=agentConfig.tenantContext,
            userMessage=userMessage,
            status=AgentStatus.RUNNING,
            parentExecutionId=parentExecutionId,
            depth=depth
        )

        self._activeExecutions[execution.id] = execution
        startTime = datetime.utcnow()

        try:
            tools = await self.toolRegistry.getToolsForAgent(
                agentConfig.toolIds,
                agentConfig.tenantContext
            )

            logger.info(
                "tools_loaded_for_agent",
                agentId=agentConfig.id,
                toolCount=len(tools),
                toolNames=[t.name for t in tools]
            )

            bedrockTools = [self.toolExecutor.formatForBedrock(t) for t in tools]

            if bedrockTools:
                logger.info(
                    "tools_formatted_for_bedrock",
                    toolCount=len(bedrockTools),
                    toolNames=[t['name'] for t in bedrockTools]
                )

            context = await self.memory.retrieveContext(
                agentConfig.tenantContext,
                sessionId,
                userMessage,
                maxTokens=settings.memory.maxContextTokens
            )

            conversationHistory = await self.memory.getConversationHistory(
                agentConfig.tenantContext,
                sessionId
            )

            systemPrompt = self._buildSystemPrompt(agentConfig, context)

            messages = conversationHistory + [{
                "role": "user",
                "content": userMessage
            }]

            totalTokens = 0
            maxIterations = 10
            iterations = 0

            while iterations < maxIterations:
                iterations += 1

                response = self.bedrock.invokeModel(
                    messages=messages,
                    systemPrompt=systemPrompt,
                    temperature=agentConfig.temperature,
                    maxTokens=agentConfig.maxTokens,
                    tools=bedrockTools if tools else None
                )

                totalTokens += response.get("usage", {}).get("total_tokens", 0)

                if totalTokens > settings.agent.maxTokenLimit:
                    raise TokenLimitExceeded(totalTokens, settings.agent.maxTokenLimit)

                toolCalls = self.bedrock.extractToolCalls(response)

                if toolCalls:
                    logger.info(
                        "tool_calls_detected",
                        agentId=agentConfig.id,
                        toolCallCount=len(toolCalls),
                        toolNames=[tc.get('name') for tc in toolCalls]
                    )
                else:
                    logger.info(
                        "no_tool_calls_in_response",
                        agentId=agentConfig.id,
                        hasTools=bool(bedrockTools)
                    )

                if not toolCalls:
                    textResponse = self.bedrock.extractTextResponse(response)
                    execution.agentResponse = textResponse
                    execution.status = AgentStatus.COMPLETED
                    execution.tokensUsed = totalTokens
                    break

                messages.append({
                    "role": "assistant",
                    "content": response.get("content", [])
                })

                for toolCall in toolCalls:
                    tool = next((t for t in tools if t.name == toolCall["name"]), None)

                    logger.info(
                        "executing_tool",
                        toolName=toolCall["name"],
                        toolId=toolCall.get("id"),
                        toolInput=str(toolCall["input"])[:200]
                    )

                    if not tool:
                        toolResult = {"error": f"Tool {toolCall['name']} not found"}
                        logger.error(
                            "tool_not_found_in_loaded_tools",
                            toolName=toolCall["name"],
                            loadedTools=[t.name for t in tools]
                        )
                    else:
                        try:
                            toolResult = await self.toolExecutor.execute(
                                tool,
                                toolCall["input"],
                                agentConfig.tenantContext,
                                authToken
                            )
                            logger.info(
                                "tool_execution_completed",
                                toolName=toolCall["name"],
                                success=isinstance(toolResult, dict) and toolResult.get("success", True),
                                resultPreview=str(toolResult)[:200]
                            )
                        except Exception as e:
                            toolResult = {"error": str(e)}
                            logger.error(
                                "tool_execution_error",
                                toolName=toolCall["name"],
                                error=str(e)
                            )

                    execution.toolCalls.append({
                        "id": toolCall["id"],
                        "name": toolCall["name"],
                        "input": toolCall["input"],
                        "result": toolResult
                    })

                    messages.append(
                        self.bedrock.formatToolResult(toolCall["id"], toolResult)
                    )

            if iterations >= maxIterations:
                execution.status = AgentStatus.FAILED
                execution.errorMessage = "Max iterations exceeded"

            endTime = datetime.utcnow()
            execution.executionTimeMs = int((endTime - startTime).total_seconds() * 1000)

            await self.memory.appendToConversation(
                agentConfig.tenantContext,
                sessionId,
                {"role": "user", "content": userMessage}
            )

            if execution.agentResponse:
                await self.memory.appendToConversation(
                    agentConfig.tenantContext,
                    sessionId,
                    {"role": "assistant", "content": execution.agentResponse}
                )

                await self.memory.storeInteraction(
                    agentConfig.tenantContext,
                    sessionId,
                    agentConfig.id,
                    userMessage,
                    execution.agentResponse,
                    [tc["name"] for tc in execution.toolCalls],
                    "success" if execution.status == AgentStatus.COMPLETED else "failed",
                    importance=0.6 if depth == 0 else 0.4
                )

            logger.info(
                "agent_execution_completed",
                executionId=execution.id,
                status=execution.status,
                tokensUsed=totalTokens,
                executionTime=execution.executionTimeMs
            )

            return execution

        except Exception as e:
            execution.status = AgentStatus.FAILED
            execution.errorMessage = str(e)
            logger.error("agent_execution_failed", error=str(e), executionId=execution.id)
            raise AgentExecutionError(
                f"Agent execution failed: {str(e)}",
                agentId=agentConfig.id,
                details={"executionId": execution.id}
            )

        finally:
            if execution.id in self._activeExecutions:
                del self._activeExecutions[execution.id]

    def _buildSystemPrompt(
        self,
        agentConfig: AgentConfig,
        context: Dict[str, Any]
    ) -> str:
        systemPrompt = agentConfig.systemPrompt

        if context.get("semantic"):
            semanticFacts = "\n".join([
                f"- {mem['content']}"
                for mem in context["semantic"][:5]
            ])
            systemPrompt += f"\n\nRelevant knowledge:\n{semanticFacts}"

        if context.get("procedural"):
            patterns = ", ".join(context["procedural"])
            systemPrompt += f"\n\nAvailable patterns: {patterns}"

        return systemPrompt

    async def executeStreaming(
        self,
        agentConfig: AgentConfig,
        userMessage: str,
        sessionId: str,
        authToken: Optional[str] = None
    ):
        tools = await self.toolRegistry.getToolsForAgent(
            agentConfig.toolIds,
            agentConfig.tenantContext
        )

        bedrockTools = [self.toolExecutor.formatForBedrock(t) for t in tools]

        context = await self.memory.retrieveContext(
            agentConfig.tenantContext,
            sessionId,
            userMessage,
            maxTokens=settings.memory.maxContextTokens
        )

        conversationHistory = await self.memory.getConversationHistory(
            agentConfig.tenantContext,
            sessionId
        )

        systemPrompt = self._buildSystemPrompt(agentConfig, context)

        messages = conversationHistory + [{
            "role": "user",
            "content": userMessage
        }]

        async for chunk in self.bedrock.invokeModelStream(
            messages=messages,
            systemPrompt=systemPrompt,
            temperature=agentConfig.temperature,
            maxTokens=agentConfig.maxTokens,
            tools=bedrockTools if tools else None
        ):
            yield chunk

    def getActiveExecutions(self, tenantId: str) -> List[AgentExecution]:
        return [
            exec for exec in self._activeExecutions.values()
            if exec.tenantContext.tenantId == tenantId
        ]

    async def cancelExecution(self, executionId: str) -> bool:
        if executionId in self._activeExecutions:
            execution = self._activeExecutions[executionId]
            execution.status = AgentStatus.CANCELLED
            del self._activeExecutions[executionId]
            logger.info("agent_execution_cancelled", executionId=executionId)
            return True
        return False


agentEngine = AgentEngine()
