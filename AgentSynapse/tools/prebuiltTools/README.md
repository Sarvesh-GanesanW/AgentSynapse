# Prebuilt Tools

This directory contains ready-to-use tool definitions that align with the ACE Framework
tooling model. Each tool follows the camelCase naming convention and can be registered
through the Tool Registry API or directly with `toolRegistry.register`.

## Included Tools

| Tool                      | Type          | Use Case                                                           |
| ------------------------- | ------------- | ------------------------------------------------------------------ |
| `awsLambdaTool.yaml`    | YAML (lambda) | Invoke serverless compute with tenant context encapsulation.       |
| `webSearchTool.py`      | Code          | Perform live web searches against DuckDuckGo's instant answer API. |
| `biDashboardTool.yaml`  | YAML (http)   | Create/refresh BI dashboards via a RESTful analytics service.      |
| `lakehouseQueryTool.py` | Code          | Drive SparkSQL on the custom Lakehouse API (start, submit, stop).  |
| `etlLogInspector.py`    | Code          | Retrieve ETL pipeline logs from CloudWatch for rapid triage.       |

## Usage

1. Upload code-based tools to your tool code bucket (`settings.s3.bucketToolCode`) or mount them
   in a code registry. YAML tools may be stored directly in DynamoDB along with the tool definition.
2. Register the tool using the Tool Registry API (see `README.md` in the project root) or the
   `toolRegistry.register` method.
3. Provide any required environment variables (API keys, AWS credentials) before execution.

Each script contains documentation for necessary permissions and configuration.

### Lakehouse SparkSQL Tool

`lakehouseQueryTool.py` expects inputs that mirror the SparkSQL Lambda facade:

```json
{
  "host": "pfxdz14aii.execute-api.ap-south-1.amazonaws.com",
  "stage": "dev",
  "startSessionPayload": {
    "computeId": 6,
    "warehouseId": "wh-123",
    "connectionConfig": {
      "warehouseName": "gz_catalog",
      "databaseName": "default"
    }
  },
  "submitQuery": {
    "catalog": "gz_catalog",
    "query": "SELECT * FROM testdbnewone.invalid_masking"
  },
  "stopSession": true
}
```

If an existing session is supplied (`submitQuery.sessionId`), the tool skips the start call. The
auth token handed to `toolExecutor.execute` is forwarded as a Bearer token to all three endpoints:
`startsession`, `submitquery`, and (optionally) `stopsession`.
