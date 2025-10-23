# ACE Framework (Agentic Context Engineering)

A production-ready AI agent framework built from scratch using Python and AWS Bedrock Claude models.

## Features

### Multi-Tiered Memory System
- **Working Memory**: Redis-based session memory with automatic expiration
- **Episodic Memory**: DynamoDB time-series storage for conversation history
- **Semantic Memory**: OpenSearch vector store for knowledge retrieval
- **Knowledge Graph**: PostgreSQL with pg_vector for entity relationships
- **Procedural Memory**: S3-based workflow pattern storage

### Advanced Memory Management
- Intelligent memory decay and consolidation
- Context-aware retrieval with relevance ranking
- Memory attribution and confidence scoring
- Multi-tenant isolation

### Multi-Agent Coordination
- Dynamic task decomposition
- Parallel and sequential agent execution
- Bounded autonomy with safety controls
- Inter-agent communication

### Tool System
- YAML-based tool definitions
- Code-based tools (Python S3 storage)
- HTTP and Lambda tool execution
- Tool versioning and permissions
- Access control integration

### Agent Types
- **Orchestrator**: Coordinates multiple specialized agents
- **SQL Agent**: Database queries and lakehouse operations
- **BI Agent**: Dashboard and visualization creation
- **ETL Agent**: Pipeline debugging and log analysis
- **Analytics Agent**: Data analysis and insights
- **Custom Agents**: User-defined agents

### Production Features
- Multi-tenant architecture
- Async agent execution via SQS
- Streaming responses
- Cost and token limits
- Comprehensive audit logging
- AWS X-Ray tracing

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     API Gateway (FastAPI)                    │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────┴────────────────────────────────────┐
│              Agent Engine & Orchestrator                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │ Agent Engine │  │ Orchestrator │  │ Tool Manager │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└────────────────────────┬────────────────────────────────────┘
                         │
         ┌───────────────┼───────────────┐
         │               │               │
    ┌────▼────┐    ┌────▼────┐    ┌────▼────┐
    │Bedrock  │    │ Memory  │    │  Tool   │
    │ Claude  │    │ System  │    │Executor │
    └─────────┘    └─────────┘    └─────────┘
                        │
         ┌──────────────┼──────────────┐
         │              │              │
    ┌────▼────┐    ┌───▼────┐    ┌───▼────┐
    │DynamoDB │    │OpenSearch│   │  RDS   │
    └─────────┘    └─────────┘    └────────┘
```

## Installation

### Prerequisites
- Python 3.11+
- AWS Account with Bedrock access
- Redis (for working memory)
- PostgreSQL (for knowledge graph)
- AWS Services: DynamoDB, OpenSearch, S3, SQS

### Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Configure environment:
```bash
cp .env.example .env
# Edit .env with your AWS credentials and endpoints
```

3. Initialize databases:
```bash
python -m aceFramework.scripts.initializeDatabases
```

4. Start the API server:
```bash
python -m api.main
```

The API will be available at `http://localhost:8000`

## Quick Start

### 1. Create an Agent

```bash
curl -X POST http://localhost:8000/api/v1/agents/create \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "X-Tenant-ID: tenant123" \
  -H "X-User-ID: user123" \
  -d '{
    "name": "My SQL Agent",
    "type": "sql_agent",
    "description": "Helps with database queries",
    "systemPrompt": "You are a SQL expert...",
    "toolIds": ["sql-query:1.0.0"]
  }'
```

### 2. Execute an Agent

```bash
curl -X POST http://localhost:8000/api/v1/agents/execute \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "X-Tenant-ID: tenant123" \
  -H "X-User-ID: user123" \
  -d '{
    "agentId": "agent-id-from-step-1",
    "userMessage": "Show me sales data from last month",
    "sessionId": "session123"
  }'
```

### 3. Register a Tool

```bash
curl -X POST http://localhost:8000/api/v1/tools/register \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "X-Tenant-ID: tenant123" \
  -H "X-User-ID: user123" \
  -d '{
    "name": "sql-query",
    "description": "Execute SQL queries",
    "inputSchema": {
      "type": "object",
      "properties": {
        "query": {"type": "string"}
      }
    },
    "yamlConfig": {
      "type": "lambda",
      "functionName": "your-sql-lambda"
    }
  }'
```

## API Documentation

Once the server is running, visit:
- Interactive API docs: `http://localhost:8000/docs`
- OpenAPI schema: `http://localhost:8000/openapi.json`

## Key Endpoints

### Agents
- `POST /api/v1/agents/create` - Create new agent
- `POST /api/v1/agents/execute` - Execute agent (sync)
- `POST /api/v1/agents/orchestrate` - Multi-agent orchestration
- `POST /api/v1/agents/async/submit` - Submit async task
- `GET /api/v1/agents/async/status/{taskId}` - Check async status
- `GET /api/v1/agents/list` - List all agents
- `GET /api/v1/agents/{agentId}` - Get agent details
- `PUT /api/v1/agents/{agentId}` - Update agent
- `DELETE /api/v1/agents/{agentId}` - Delete agent

### Tools
- `POST /api/v1/tools/register` - Register new tool
- `GET /api/v1/tools/list` - List all tools
- `GET /api/v1/tools/{toolName}` - Get tool details
- `POST /api/v1/tools/{toolName}/deactivate` - Deactivate tool

### Memory
- `POST /api/v1/memory/fact/store` - Store a fact
- `POST /api/v1/memory/search` - Search memories
- `GET /api/v1/memory/context/{sessionId}` - Get session context
- `POST /api/v1/memory/consolidate/{sessionId}` - Consolidate memories
- `DELETE /api/v1/memory/session/{sessionId}` - Clear session

## Configuration

All configuration is managed via environment variables. See `.env.example` for complete list.

Key settings:
- `AWS_BEDROCK_MODEL_ID`: Claude model to use
- `MAX_AGENT_RECURSION_DEPTH`: Max nested agent calls
- `MAX_PARALLEL_AGENTS`: Max concurrent agents
- `EPISODIC_RETENTION_DAYS`: How long to keep episodic memories
- `MAX_CONTEXT_TOKENS`: Max tokens for context retrieval

## Multi-Tenant Usage

Every request must include:
- `X-Tenant-ID`: Unique tenant identifier
- `X-User-ID`: User identifier
- `Authorization`: Bearer token

Data is automatically isolated by tenant.

## Testing

Run tests:
```bash
pytest tests/ -v
```

With coverage:
```bash
pytest tests/ --cov=aceFramework --cov-report=html
```

## Deployment

### AWS Lambda
The framework is designed to run on AWS Lambda with FastAPI Lambda adapter.

### Docker
```bash
docker build -t ace-framework .
docker run -p 8000:8000 --env-file .env ace-framework
```

## License

Proprietary - Internal Use Only

## Support

For issues and questions, contact the development team.
