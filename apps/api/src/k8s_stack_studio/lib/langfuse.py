"""Bounded, owner-checked reads of LLM exchanges from Langfuse v4."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Literal

import httpx
from pydantic import AwareDatetime, BaseModel, Field, StrictStr


class LangfuseReadError(Exception):
    """An upstream read or ownership validation failed."""


class Exchange(BaseModel):
    """Only the fields needed to display one sent request and received response."""

    id: StrictStr
    user_id: StrictStr = Field(alias="userId")
    type: Literal["GENERATION"]
    start_time: AwareDatetime = Field(alias="startTime")
    name: str | None = None
    model: str | None = None
    level: str | None = None
    input: str | None = None
    output: str | None = None


class _Page(BaseModel):
    """Langfuse observation page; metadata is deliberately discarded."""

    data: list[Exchange]


class LangfuseClient:
    """Never allow browser-provided filters or identities into upstream queries."""

    def __init__(
        self, base_url: str, public_key: str, secret_key: str, client: httpx.AsyncClient
    ) -> None:
        """Keep project credentials exclusively inside the API process."""
        self._url = f"{base_url.rstrip('/')}/api/public/v2/observations"
        self._auth = httpx.BasicAuth(public_key, secret_key)
        self._client = client

    async def _page(
        self, user_id: str, start: datetime, end: datetime, column: str | None, query: str
    ) -> list[Exchange]:
        """Create *all* upstream conditions on the server, including the owner."""
        params: dict[str, str | int] = {
            "fields": "core,basic,io,model",
            "limit": 10,
        }
        if column is None:
            params.update(
                userId=user_id,
                type="GENERATION",
                fromStartTime=start.isoformat(),
                toStartTime=end.isoformat(),
            )
        else:
            # Langfuse's advanced filter overrides ALL first-class query filters.
            # Include the verified owner, type and time in every search request.
            params["filter"] = json.dumps(
                [
                    {"type": "string", "column": "userId", "operator": "=", "value": user_id},
                    {
                        "type": "stringOptions",
                        "column": "type",
                        "operator": "any of",
                        "value": ["GENERATION"],
                    },
                    {
                        "type": "datetime",
                        "column": "startTime",
                        "operator": ">=",
                        "value": start.isoformat(),
                    },
                    {
                        "type": "datetime",
                        "column": "startTime",
                        "operator": "<",
                        "value": end.isoformat(),
                    },
                    {"type": "string", "column": column, "operator": "matches", "value": query},
                ]
            )
        try:
            response = await self._client.get(
                self._url, params=params, auth=self._auth, timeout=10.0
            )
            response.raise_for_status()
            page = _Page.model_validate(response.json())
        except (httpx.HTTPError, ValueError) as exc:
            raise LangfuseReadError from exc
        if len(page.data) > 10:
            raise LangfuseReadError
        for row in page.data:
            if (
                not row.id
                or row.user_id != user_id
                or not start <= row.start_time.astimezone(UTC) < end
            ):
                raise LangfuseReadError
        return page.data

    async def recent(
        self, user_id: str, start: datetime, end: datetime, query: str | None
    ) -> list[Exchange]:
        """Return the ten newest matching generations, with complete recorded I/O."""
        if not query:
            return await self._page(user_id, start, end, None, "")
        # Langfuse's filters combine with AND. Separate searches implement
        # input OR output without ever dropping the enforced owner condition.
        incoming = await self._page(user_id, start, end, "input", query)
        outgoing = await self._page(user_id, start, end, "output", query)
        unique = {row.id: row for row in [*incoming, *outgoing]}
        return sorted(unique.values(), key=lambda item: item.start_time, reverse=True)[:10]
