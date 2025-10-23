import asyncio
import json
from typing import List, Dict, Any, Optional
from uuid import uuid4
from config.settings import settings
from utils.logger import getLogger
from schemas import (
    AgentConfig,
    AgentType,
    TaskDecomposition,
    AgentStatus,
    TenantContext
)
from core.agentEngine import agentEngine
from core.bedrockClient import bedrockClient
from agents.registry.agentRegistry import agentRegistry

logger = getLogger(__name__)


class AgentOrchestrator:
    def __init__(self):
        self.engine = agentEngine
        self.bedrock = bedrockClient
        self.agentRegistry = agentRegistry
        self._messageQueue = asyncio.Queue()

    async def orchestrate(
        self,
        userRequest: str,
        sessionId: str,
        tenantContext: TenantContext,
        authToken: Optional[str] = None
    ) -> Dict[str, Any]:
        orchestratorAgent = await self._getOrCreateOrchestrator(tenantContext)

        tasks = await self._decomposeTask(userRequest, tenantContext)

        if not tasks:
            return await self._executeSingleAgent(
                orchestratorAgent,
                userRequest,
                sessionId,
                authToken
            )

        executionPlan = self._buildExecutionPlan(tasks)

        results = await self._executeParallelTasks(
            executionPlan,
            sessionId,
            tenantContext,
            authToken
        )

        finalResponse = await self._synthesizeResults(
            orchestratorAgent,
            userRequest,
            results,
            sessionId,
            authToken
        )

        return {
            "response": finalResponse,
            "tasks": tasks,
            "results": results,
            "executionPlan": executionPlan
        }

    async def _decomposeTask(
        self,
        userRequest: str,
        tenantContext: TenantContext
    ) -> List[TaskDecomposition]:
        decompositionPrompt = f"""
Analyze this user request and determine if it requires multiple specialized agents:

Request: {userRequest}

Available agent types:
- SQL_AGENT: Handles database queries, data retrieval from lakehouse
- BI_AGENT: Creates dashboards, datasets, filters, visualizations
- ETL_AGENT: Pipeline debugging, log analysis, data transformation
- ANALYTICS_AGENT: Data analysis, insights, statistical operations

If the task is simple, return an empty list.
If it's complex, break it down into subtasks and assign to appropriate agents.

Return JSON format:
{{
  "tasks": [
    {{
      "description": "task description",
      "agentType": "agent_type",
      "dependencies": ["taskId1", "taskId2"],
      "priority": 1,
      "estimatedTokens": 1000
    }}
  ]
}}
"""

        messages = self.bedrock.formatMessages(decompositionPrompt)
        response = self.bedrock.invokeModel(
            messages=messages,
            systemPrompt="You are a task decomposition expert for multi-agent systems.",
            temperature=0.3,
            maxTokens=2000
        )

        responseText = self.bedrock.extractTextResponse(response)

        try:
            data = json.loads(responseText)
            tasksList = data.get("tasks", [])

            if not tasksList:
                return []

            tasks = []
            for taskData in tasksList:
                task = TaskDecomposition(
                    taskId=str(uuid4()),
                    description=taskData["description"],
                    assignedAgentType=AgentType(taskData["agentType"]),
                    dependencies=taskData.get("dependencies", []),
                    priority=taskData.get("priority", 1),
                    estimatedTokens=taskData.get("estimatedTokens", 1000)
                )
                tasks.append(task)

            logger.info("task_decomposition_completed", taskCount=len(tasks))
            return tasks

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.error("task_decomposition_error", error=str(e), response=responseText)
            return []

    def _buildExecutionPlan(
        self,
        tasks: List[TaskDecomposition]
    ) -> Dict[str, List[TaskDecomposition]]:
        plan = {
            "sequential": [],
            "parallel": []
        }

        taskMap = {task.taskId: task for task in tasks}
        completed = set()
        remaining = set(task.taskId for task in tasks)

        waves = []
        while remaining:
            currentWave = []

            for taskId in list(remaining):
                task = taskMap[taskId]
                if all(dep in completed for dep in task.dependencies):
                    currentWave.append(task)
                    remaining.remove(taskId)

            if not currentWave:
                logger.warning("circular_dependency_detected")
                break

            waves.append(currentWave)
            completed.update(task.taskId for task in currentWave)

        for wave in waves:
            if len(wave) > 1:
                plan["parallel"].extend(wave)
            else:
                plan["sequential"].extend(wave)

        return plan

    async def _executeParallelTasks(
        self,
        executionPlan: Dict[str, List[TaskDecomposition]],
        sessionId: str,
        tenantContext: TenantContext,
        authToken: Optional[str] = None
    ) -> Dict[str, Any]:
        results = {}

        for task in executionPlan.get("sequential", []):
            result = await self._executeTask(task, sessionId, tenantContext, authToken)
            results[task.taskId] = result
            task.result = result
            task.status = AgentStatus.COMPLETED

        parallelTasks = executionPlan.get("parallel", [])

        if parallelTasks:
            parallelLimit = min(len(parallelTasks), settings.agent.maxParallelAgents)

            semaphore = asyncio.Semaphore(parallelLimit)

            async def executeWithSemaphore(task):
                async with semaphore:
                    return await self._executeTask(task, sessionId, tenantContext, authToken)

            parallelResults = await asyncio.gather(
                *[executeWithSemaphore(task) for task in parallelTasks],
                return_exceptions=True
            )

            for task, result in zip(parallelTasks, parallelResults):
                if isinstance(result, Exception):
                    results[task.taskId] = {"error": str(result)}
                    task.status = AgentStatus.FAILED
                else:
                    results[task.taskId] = result
                    task.result = result
                    task.status = AgentStatus.COMPLETED

        return results

    async def _executeTask(
        self,
        task: TaskDecomposition,
        sessionId: str,
        tenantContext: TenantContext,
        authToken: Optional[str] = None
    ) -> Any:
        agent = await self.agentRegistry.getByType(task.assignedAgentType, tenantContext)

        if not agent:
            agent = await self._createDefaultAgent(task.assignedAgentType, tenantContext)

        execution = await self.engine.execute(
            agent,
            task.description,
            sessionId,
            authToken,
            depth=1
        )

        logger.info(
            "task_executed",
            taskId=task.taskId,
            agentType=task.assignedAgentType.value,
            status=execution.status
        )

        return {
            "response": execution.agentResponse,
            "toolCalls": execution.toolCalls,
            "status": execution.status.value
        }

    async def _synthesizeResults(
        self,
        orchestratorAgent: AgentConfig,
        originalRequest: str,
        results: Dict[str, Any],
        sessionId: str,
        authToken: Optional[str] = None
    ) -> str:
        synthesisPrompt = f"""
Original user request: {originalRequest}

Results from specialized agents:
{json.dumps(results, indent=2)}

Synthesize these results into a cohesive response for the user.
"""

        execution = await self.engine.execute(
            orchestratorAgent,
            synthesisPrompt,
            sessionId,
            authToken,
            depth=1
        )

        return execution.agentResponse or "Unable to synthesize results"

    async def _executeSingleAgent(
        self,
        agent: AgentConfig,
        userRequest: str,
        sessionId: str,
        authToken: Optional[str] = None
    ) -> Dict[str, Any]:
        execution = await self.engine.execute(
            agent,
            userRequest,
            sessionId,
            authToken
        )

        return {
            "response": execution.agentResponse,
            "tasks": [],
            "results": {},
            "executionPlan": {}
        }

    async def _getOrCreateOrchestrator(
        self,
        tenantContext: TenantContext
    ) -> AgentConfig:
        agent = await self.agentRegistry.getByType(AgentType.ORCHESTRATOR, tenantContext)

        if agent:
            return agent

        return await self._createDefaultAgent(AgentType.ORCHESTRATOR, tenantContext)

    async def _createDefaultAgent(
        self,
        agentType: AgentType,
        tenantContext: TenantContext
    ) -> AgentConfig:
        systemPrompts = {
            AgentType.ORCHESTRATOR: "You are an orchestrator agent coordinating multiple specialized agents.",
            AgentType.SQL_AGENT: "You are a SQL expert helping with database queries and lakehouse operations.",
            AgentType.BI_AGENT: "You are a BI specialist creating dashboards, datasets, and visualizations.",
            AgentType.ETL_AGENT: "You are an ETL expert helping with pipelines, logs, and data transformation.",
            AgentType.ANALYTICS_AGENT: "You are a data analyst providing insights and statistical analysis."
        }

        agent = AgentConfig(
            name=f"Default {agentType.value}",
            type=agentType,
            description=f"Auto-created {agentType.value}",
            systemPrompt=systemPrompts.get(agentType, "You are a helpful AI assistant."),
            tenantContext=tenantContext,
            temperature=0.7,
            maxTokens=4096,
            toolIds=[]
        )

        await self.agentRegistry.register(agent)
        return agent


agentOrchestrator = AgentOrchestrator()
