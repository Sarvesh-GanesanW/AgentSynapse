"""
ACE Framework Configuration Settings
Centralized configuration management using Pydantic Settings
"""

from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AWSSettings(BaseSettings):
    """AWS Service Configuration"""

    region: str = Field(default="us-east-1", alias="AWS_REGION")
    accessKeyId: Optional[str] = Field(default=None, alias="AWS_ACCESS_KEY_ID")
    secretAccessKey: Optional[str] = Field(default=None, alias="AWS_SECRET_ACCESS_KEY")
    bedrockModelId: str = Field(
        default="arn:aws:bedrock:us-east-1::inference-profile/us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        alias="AWS_BEDROCK_MODEL_ID"
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class RedisSettings(BaseSettings):
    """Redis Configuration for Working Memory"""

    host: str = Field(default="localhost", alias="REDIS_HOST")
    port: int = Field(default=6379, alias="REDIS_PORT")
    db: int = Field(default=0, alias="REDIS_DB")
    password: Optional[str] = Field(default=None, alias="REDIS_PASSWORD")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class DynamoDBSettings(BaseSettings):
    """DynamoDB Configuration for Episodic Memory"""

    tableEpisodic: str = Field(default="aceEpisodicMemory", alias="DYNAMODB_TABLE_EPISODIC")
    tableAgentConfig: str = Field(default="aceAgentConfig", alias="DYNAMODB_TABLE_AGENT_CONFIG")
    tableToolRegistry: str = Field(default="aceToolRegistry", alias="DYNAMODB_TABLE_TOOL_REGISTRY")
    tableSessions: str = Field(default="aceAgentSessions", alias="DYNAMODB_TABLE_SESSIONS")
    endpointUrl: Optional[str] = Field(default=None, alias="DYNAMODB_ENDPOINT_URL")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class OpenSearchSettings(BaseSettings):
    """OpenSearch Configuration for Semantic Memory (Vectors)"""

    endpoint: str = Field(alias="OPENSEARCH_ENDPOINT")
    indexSemantic: str = Field(default="ace-semantic-memory", alias="OPENSEARCH_INDEX_SEMANTIC")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class RDSSettings(BaseSettings):
    """RDS PostgreSQL Configuration for Knowledge Graph"""

    host: str = Field(alias="RDS_HOST")
    port: int = Field(default=5432, alias="RDS_PORT")
    database: str = Field(default="ace_knowledge_graph", alias="RDS_DATABASE")
    username: str = Field(alias="RDS_USERNAME")
    password: str = Field(alias="RDS_PASSWORD")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class S3Settings(BaseSettings):
    """S3 Configuration for Procedural Memory"""

    bucketProcedural: str = Field(default="ace-procedural-memory", alias="S3_BUCKET_PROCEDURAL")
    bucketToolCode: str = Field(default="ace-tool-code", alias="S3_BUCKET_TOOL_CODE")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class AgentSettings(BaseSettings):
    """Agent Execution Configuration"""

    maxRecursionDepth: int = Field(default=5, alias="MAX_AGENT_RECURSION_DEPTH")
    maxParallelAgents: int = Field(default=10, alias="MAX_PARALLEL_AGENTS")
    timeoutSeconds: int = Field(default=300, alias="AGENT_TIMEOUT_SECONDS")
    maxTokenLimit: int = Field(default=100000, alias="MAX_TOKEN_LIMIT")
    defaultTemperature: float = Field(default=0.7, alias="DEFAULT_TEMPERATURE")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class MemorySettings(BaseSettings):
    """Memory Management Configuration"""

    workingMemoryTtl: int = Field(default=3600, alias="WORKING_MEMORY_TTL_SECONDS")
    episodicRetentionDays: int = Field(default=90, alias="EPISODIC_RETENTION_DAYS")
    decayThresholdDays: int = Field(default=7, alias="MEMORY_DECAY_THRESHOLD_DAYS")
    maxContextTokens: int = Field(default=200000, alias="MAX_CONTEXT_TOKENS")
    topKSemanticRetrieval: int = Field(default=10, alias="TOP_K_SEMANTIC_RETRIEVAL")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class MultiTenantSettings(BaseSettings):
    """Multi-Tenant Configuration"""

    enableTenantIsolation: bool = Field(default=True, alias="ENABLE_TENANT_ISOLATION")
    defaultCostLimit: float = Field(default=100.0, alias="DEFAULT_COST_LIMIT_USD")
    enableAuditLogging: bool = Field(default=True, alias="ENABLE_AUDIT_LOGGING")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class AsyncAgentSettings(BaseSettings):
    """Async Agent Execution Configuration"""

    sqsQueue: str = Field(default="ace-async-agents", alias="SQS_QUEUE_ASYNC_AGENTS")
    visibilityTimeout: int = Field(default=900, alias="SQS_VISIBILITY_TIMEOUT")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class AppSettings(BaseSettings):
    """Application Configuration"""

    name: str = Field(default="ACE Framework", alias="APP_NAME")
    version: str = Field(default="1.0.0", alias="APP_VERSION")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    logLevel: str = Field(default="INFO", alias="LOG_LEVEL")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class MonitoringSettings(BaseSettings):
    """Monitoring and Observability Configuration"""

    enableXRayTracing: bool = Field(default=True, alias="ENABLE_XRAY_TRACING")
    enableCloudWatchMetrics: bool = Field(default=True, alias="ENABLE_CLOUDWATCH_METRICS")
    metricsNamespace: str = Field(default="ACE/Agents", alias="METRICS_NAMESPACE")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class Settings:
    """Main Settings Class - Aggregates all configuration"""

    def __init__(self):
        self.app = AppSettings()
        self.aws = AWSSettings()
        self.redis = RedisSettings()
        self.dynamodb = DynamoDBSettings()
        self.opensearch = OpenSearchSettings()
        self.rds = RDSSettings()
        self.s3 = S3Settings()
        self.agent = AgentSettings()
        self.memory = MemorySettings()
        self.multiTenant = MultiTenantSettings()
        self.asyncAgent = AsyncAgentSettings()
        self.monitoring = MonitoringSettings()


# Global settings instance
settings = Settings()
