"""Operator-approved MCP catalog; native destinations stay on the backend."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AuthenticationModel = Literal[
    "no-authentication", "shared-authentication", "individual-authentication"
]


class McpRegistration(BaseModel):
    """Fixed mapping to an operator-owned native registration and virtual server."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=100)
    authentication_model: AuthenticationModel
    gateway_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    server_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")


class McpCatalogEntry(BaseModel):
    """Publishable catalog information, not connection credentials or destinations."""

    id: str
    name: str
    authentication_model: AuthenticationModel
    permitted: bool
    connection_status: Literal["status unavailable"] | None
