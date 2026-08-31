"""Strict request models for user-managed API keys."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from k8s_stack_studio.models.policy_engine import StrictModel


class CreateApiKeyRequest(StrictModel):
    """Create an immutable, expiring API key grant."""

    name: str = Field(min_length=1, max_length=128)
    permissions: list[Annotated[str, Field(min_length=1, max_length=256)]] = Field(min_length=1)
    expires_in_days: int = Field(ge=1, le=365)
