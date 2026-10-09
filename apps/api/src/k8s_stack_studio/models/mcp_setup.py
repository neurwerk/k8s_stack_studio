"""Administrator setup requests and secret-free status responses."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from k8s_stack_studio.models.mcp import McpCredential


class McpChange(BaseModel):
    """A revision and idempotency key bind each explicit administrator action."""

    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=0)
    operation_id: UUID


class McpPublish(McpChange):
    """Blank replacement keeps the key; removal is always explicit."""

    selected_tools: list[str] = Field(max_length=500)
    key_action: Literal["keep", "replace", "remove"] = "keep"
    api_key: SecretStr = Field(default=SecretStr(""), max_length=16384, repr=False)


class McpOperation(BaseModel):
    """Progress is durable; errors never contain provider responses or secrets."""

    id: UUID
    kind: Literal["publish", "disable", "refresh"]
    state: Literal["queued", "applying", "succeeded", "failed"]
    phase: str
    error_code: str | None = None
    started_at: datetime
    updated_at: datetime
    actor: str


class McpSetupTool(BaseModel):
    """A discovered tool, addressed by its original upstream name."""

    name: str
    description: str


class McpSetupStatus(BaseModel):
    """Safe setup data for every installed integration, including unconfigured ones."""

    id: str
    name: str
    url: str
    credential: McpCredential
    revision: int = 0
    selected_tools: list[str] = Field(default_factory=list)
    published_tools: list[str] = Field(default_factory=list)
    enabled: bool = False
    publication_uncertain: bool = False
    published_at: datetime | None = None
    key_configured: bool = False
    refreshed_at: datetime | None = None
    updated_at: datetime | None = None
    operation: McpOperation | None = None
    available: bool = True
    tools: list[McpSetupTool] = Field(default_factory=list)
