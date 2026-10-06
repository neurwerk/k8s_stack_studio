"""Operator-approved MCP catalog; native destinations stay on the backend."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


class McpRegistration(BaseModel):
    """Fixed mapping to an operator-owned native registration and virtual server."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=100)
    authentication_model: AuthenticationModel
    gateway_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    server_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    oauth_authorization_origin: str = ""

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


ConnectionStatus = Literal["connected", "refresh pending", "connect required", "status unavailable"]


class McpConnectionStatus(BaseModel):
    """Personal metadata only; expiry does not prove refresh is unavailable."""

    status: ConnectionStatus


class McpConnectResponse(BaseModel):
    """A provider authorization URL and the approved native popup callback origin."""

    authorization_url: str
    callback_origin: str
