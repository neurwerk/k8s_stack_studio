"""Operator-approved MCP catalog; native destinations stay on the backend."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

AuthenticationModel = Literal[
    "no-authentication", "shared-authentication", "individual-authentication"
]


def https_origin(value: str) -> str:
    """Project HTTPS metadata to the canonical origin used by the Base catalog."""
    url = urlsplit(value)
    if url.scheme != "https" or not url.hostname:
        raise ValueError("OAuth URL must use HTTPS")  # noqa: TRY003
    host = url.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    port = "" if url.port in {None, 443} else f":{url.port}"
    return f"https://{host}{port}"


class McpCheckDisplay(BaseModel):
    """An optional plain-text label and dot-separated JSON field, never a template."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str = Field(min_length=1, max_length=100)
    field: str = Field(min_length=1, max_length=200, pattern=r"^[a-zA-Z0-9_-]+(\.[a-zA-Z0-9_-]+)*$")


class McpCheck(BaseModel):
    """Operator approval to execute one read-only tool with fixed non-secret arguments."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=100)
    tool: str = Field(min_length=1, max_length=200)
    arguments: dict[str, JsonValue] = Field(default_factory=dict)
    display: McpCheckDisplay | None = None

    @field_validator("arguments")
    @classmethod
    def bounded_arguments(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """Keep configured check payloads small and JSON-only."""
        if len(json.dumps(value, allow_nan=False).encode()) > 8192:
            raise ValueError("MCP check arguments exceed 8192 bytes")  # noqa: TRY003
        return value


class McpRegistration(BaseModel):
    """Fixed mapping to an operator-owned native registration and virtual server."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=100)
    authentication_model: AuthenticationModel
    gateway_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    server_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    oauth_authorization_origin: str = ""
    approved_tools: list[str] = Field(default_factory=list, max_length=100)
    # Setup resolves original approved names to their exact gateway-visible names.
    tool_names: dict[str, str] = Field(default_factory=dict, max_length=100)
    checks: list[McpCheck] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def validate_checks(self) -> Self:
        """Reject checks outside the approved tool mapping and ambiguous mappings."""
        if (
            any(check.tool not in self.approved_tools for check in self.checks)
            or not set(self.tool_names) <= set(self.approved_tools)
            or len(set(self.tool_names.values())) != len(self.tool_names)
            or any(not name or not wire for name, wire in self.tool_names.items())
        ):
            raise ValueError("MCP checks require unique approved tool mappings")  # noqa: TRY003
        return self

    @field_validator("oauth_authorization_origin")
    @classmethod
    def validate_authorization_origin(cls, value: str) -> str:
        """Allow only a fixed HTTPS origin, never a browser-selected destination."""
        if not value:
            return value
        try:
            url = urlsplit(value)
            _ = url.port
            if (
                url.scheme == "https"
                and url.hostname
                and url.username is None
                and url.password is None
                and not url.path
                and not url.query
                and not url.fragment
                and url.geturl() == value
                and not any(character.isspace() or character == "\\" for character in value)
            ):
                return https_origin(value)
        except ValueError:
            pass
        raise ValueError("OAuth authorization policy must be an HTTPS origin")  # noqa: TRY003


class McpCatalogEntry(BaseModel):
    """Publishable catalog information, not connection credentials or destinations."""

    id: str
    name: str
    authentication_model: AuthenticationModel
    permitted: bool
    connection_status: Literal["status unavailable"] | None
    can_discover: bool = False
    publication: McpPublicationStatus | None = None


class McpPublicationStatus(BaseModel):
    """Safe publication metadata; discovery and saved connections are separate."""

    state: Literal["pending-discovery", "published", "error", "unavailable"]
    checked_at: datetime | None = None
    error_code: str | None = None


class McpDiscoverResponse(BaseModel):
    """Native discovery completion is not proof of setup publication."""

    discovered_at: datetime


ConnectionStatus = Literal["connected", "refresh pending", "connect required", "status unavailable"]


class McpConnectionStatus(BaseModel):
    """Personal metadata only; expiry does not prove refresh is unavailable."""

    status: ConnectionStatus
    checked_at: datetime | None = None
    retry_after: int | None = None
    message: str | None = None


class McpConnectResponse(BaseModel):
    """A provider authorization URL and the approved native popup callback origin."""

    authorization_url: str
    callback_origin: str


class McpTool(BaseModel):
    """Only an approved tool's name, description and configured checks."""

    name: str
    description: str
    checks: dict[str, McpCheck] = Field(default_factory=dict)


class McpCheckResult(BaseModel):
    """A caller-owned result; kept out of shared caches and application logs."""

    status: Literal["passed", "failed"]
    checked_at: datetime
    result: str = ""
    display_label: str | None = None
    display_value: str | None = None
