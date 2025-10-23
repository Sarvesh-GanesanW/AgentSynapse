import re
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import boto3
from boto3.dynamodb.conditions import Attr, Key

from config.settings import settings
from utils.exceptions import InvalidToolDefinition
from utils.logger import getLogger
from schemas import ToolPermission

logger = getLogger(__name__)


class ToolReleaseType(str, Enum):
    MAJOR = "major"
    MINOR = "minor"
    PATCH = "patch"


class ToolVersioning:
    def __init__(self):
        self._dynamodb = None
        self._table = None
        self._versionPattern = re.compile(r"^\d+\.\d+\.\d+$")
        self._tenantCache: Dict[str, List[Dict[str, Any]]] = {}
        self._publicCache: Dict[str, List[Dict[str, Any]]] = {}

    def _getTable(self):
        if not self._table:
            resourceArgs = {
                "region_name": settings.aws.region,
                "aws_access_key_id": settings.aws.accessKeyId,
                "aws_secret_access_key": settings.aws.secretAccessKey
            }
            if settings.dynamodb.endpointUrl:
                resourceArgs["endpoint_url"] = settings.dynamodb.endpointUrl

            self._dynamodb = boto3.resource("dynamodb", **resourceArgs)
            self._table = self._dynamodb.Table(settings.dynamodb.tableToolRegistry)
        return self._table

    def _cacheKey(self, tenantId: str, toolName: str) -> str:
        return f"{tenantId}:{toolName}"

    def clearCache(self):
        self._tenantCache.clear()
        self._publicCache.clear()
        logger.info("tool_version_cache_cleared")

    def invalidateCache(self, tenantId: Optional[str] = None, toolName: Optional[str] = None):
        if tenantId and toolName:
            key = self._cacheKey(tenantId, toolName)
            self._tenantCache.pop(key, None)
        elif tenantId:
            for key in list(self._tenantCache.keys()):
                if key.startswith(f"{tenantId}:"):
                    self._tenantCache.pop(key, None)
        elif toolName:
            for key in list(self._tenantCache.keys()):
                if key.endswith(f":{toolName}"):
                    self._tenantCache.pop(key, None)

        if toolName:
            self._publicCache.pop(toolName, None)

    def validateVersion(self, version: str) -> bool:
        return bool(self._versionPattern.match(version))

    def ensureValidVersion(self, version: str):
        if not self.validateVersion(version):
            raise InvalidToolDefinition(
                f"Invalid tool version '{version}'. Expected semantic versioning (major.minor.patch)."
            )

    def _parseVersionTuple(self, version: str) -> Tuple[int, int, int]:
        if not self.validateVersion(version):
            return 0, 0, 0
        major, minor, patch = version.split(".")
        return int(major), int(minor), int(patch)

    def _fetchTenantVersions(
        self,
        toolName: str,
        tenantId: str,
        includeInactive: bool = True
    ) -> List[Dict[str, Any]]:
        cacheKey = self._cacheKey(tenantId, toolName)
        if cacheKey in self._tenantCache:
            return self._tenantCache[cacheKey]

        table = self._getTable()
        items: List[Dict[str, Any]] = []
        lastEvaluatedKey = None

        while True:
            queryArgs = {
                "KeyConditionExpression": Key("pk").eq(f"TENANT#{tenantId}") &
                Key("sk").begins_with(f"TOOL#{toolName}#VERSION#")
            }

            if lastEvaluatedKey:
                queryArgs["ExclusiveStartKey"] = lastEvaluatedKey

            response = table.query(**queryArgs)
            items.extend(response.get("Items", []))
            lastEvaluatedKey = response.get("LastEvaluatedKey")

            if not lastEvaluatedKey:
                break

        if not includeInactive:
            items = [item for item in items if item.get("isActive", True)]

        self._tenantCache[cacheKey] = items
        return items

    def _fetchPublicVersions(
        self,
        toolName: str,
        includeInactive: bool = True
    ) -> List[Dict[str, Any]]:
        if toolName in self._publicCache:
            return self._publicCache[toolName]

        table = self._getTable()
        items: List[Dict[str, Any]] = []
        lastEvaluatedKey = None

        while True:
            queryArgs = {
                "IndexName": "ToolNameIndex",
                "KeyConditionExpression": Key("name").eq(toolName),
                "FilterExpression": Attr("permission").eq(ToolPermission.PUBLIC.value)
            }

            if not includeInactive:
                queryArgs["FilterExpression"] = queryArgs["FilterExpression"] & Attr("isActive").eq(True)

            if lastEvaluatedKey:
                queryArgs["ExclusiveStartKey"] = lastEvaluatedKey

            response = table.query(**queryArgs)
            items.extend(response.get("Items", []))
            lastEvaluatedKey = response.get("LastEvaluatedKey")

            if not lastEvaluatedKey:
                break

        self._publicCache[toolName] = items
        return items

    def _toVersionRecord(self, item: Dict[str, Any], source: str) -> Dict[str, Any]:
        return {
            "version": item.get("version"),
            "isActive": item.get("isActive", True),
            "permission": item.get("permission"),
            "tenantId": item.get("tenantId"),
            "createdAt": item.get("createdAt"),
            "updatedAt": item.get("updatedAt"),
            "source": source
        }

    def _sortVersions(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return sorted(
            items,
            key=lambda item: self._parseVersionTuple(item.get("version", "0.0.0")),
            reverse=True
        )

    def getVersionHistory(
        self,
        toolName: str,
        tenantId: str,
        includePublic: bool = True,
        includeInactive: bool = True
    ) -> List[Dict[str, Any]]:
        versions: List[Dict[str, Any]] = []

        tenantItems = self._fetchTenantVersions(toolName, tenantId, includeInactive)
        versions.extend(self._toVersionRecord(item, "tenant") for item in tenantItems)

        if includePublic:
            publicItems = self._fetchPublicVersions(toolName, includeInactive)
            versions.extend(self._toVersionRecord(item, "public") for item in publicItems)

        unique: Dict[str, Dict[str, Any]] = {}
        for record in versions:
            version = record.get("version")
            if not version:
                continue
            if version not in unique:
                unique[version] = record
            elif record["source"] == "tenant":
                unique[version] = record

        sortedVersions = self._sortVersions(list(unique.values()))
        return sortedVersions

    def getLatestVersion(
        self,
        toolName: str,
        tenantId: str,
        includePublic: bool = True
    ) -> Optional[str]:
        history = self.getVersionHistory(
            toolName,
            tenantId,
            includePublic=includePublic,
            includeInactive=False
        )
        if not history:
            return None
        return history[0]["version"]

    def versionExists(
        self,
        toolName: str,
        tenantId: str,
        version: str,
        includeInactive: bool = True
    ) -> bool:
        self.ensureValidVersion(version)
        history = self.getVersionHistory(
            toolName,
            tenantId,
            includePublic=False,
            includeInactive=includeInactive
        )
        return any(record["version"] == version for record in history)

    def ensureVersionAvailable(
        self,
        toolName: str,
        tenantId: str,
        version: str
    ):
        self.ensureValidVersion(version)
        if self.versionExists(toolName, tenantId, version, includeInactive=True):
            raise InvalidToolDefinition(
                f"Tool {toolName} version {version} already exists",
                toolName=toolName
            )

    def calculateNextVersion(
        self,
        currentVersion: str,
        releaseType: ToolReleaseType = ToolReleaseType.PATCH
    ) -> str:
        self.ensureValidVersion(currentVersion)
        major, minor, patch = self._parseVersionTuple(currentVersion)

        if releaseType == ToolReleaseType.MAJOR:
            major += 1
            minor = 0
            patch = 0
        elif releaseType == ToolReleaseType.MINOR:
            minor += 1
            patch = 0
        else:
            patch += 1

        return f"{major}.{minor}.{patch}"

    def getNextVersion(
        self,
        toolName: str,
        tenantId: str,
        releaseType: ToolReleaseType = ToolReleaseType.PATCH,
        includePublic: bool = True
    ) -> str:
        latest = self.getLatestVersion(toolName, tenantId, includePublic=includePublic)
        if not latest:
            return "1.0.0"
        return self.calculateNextVersion(latest, releaseType)

    def recordVersionRegistration(self, tenantId: str, toolName: str):
        self.invalidateCache(tenantId=tenantId, toolName=toolName)

    def recordVersionDeactivation(self, tenantId: str, toolName: str):
        self.invalidateCache(tenantId=tenantId, toolName=toolName)


toolVersioning = ToolVersioning()
