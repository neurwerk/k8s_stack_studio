"""Bounded, owner-checked reads of LLM and MCP activity from Langfuse v4."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from pydantic import AwareDatetime, BaseModel, Field, StrictStr

ActivityType = Literal["all", "llm", "mcp"]
ObservationType = Literal["GENERATION", "TOOL"]


class LangfuseReadError(Exception):
    """An upstream read or ownership validation failed."""


class Observation(BaseModel):
    """Typed Langfuse observation; metadata stays inside the API process."""

    id: StrictStr
    user_id: StrictStr = Field(alias="userId")
    type: ObservationType
    start_time: AwareDatetime = Field(alias="startTime")
    end_time: AwareDatetime | None = Field(default=None, alias="endTime")
    session_id: str | None = Field(default=None, alias="sessionId")
    name: str | None = None
    model: str | None = None
    level: str | None = None
    status_message: str | None = Field(default=None, alias="statusMessage")
    input: str | None = None
    output: str | None = None
    input_usage: int | None = Field(default=None, alias="inputUsage")
    output_usage: int | None = Field(default=None, alias="outputUsage")
    total_usage: int | None = Field(default=None, alias="totalUsage")
    total_cost: float | None = Field(default=None, alias="totalCost")
    metadata: dict[str, Any] = Field(default_factory=dict)


class Exchange(BaseModel):
    """A model request and response."""

    id: str
    user_id: str = Field(alias="userId")
    type: Literal["GENERATION"] = "GENERATION"
    start_time: AwareDatetime = Field(alias="startTime")
    duration_ms: int | None = Field(default=None, alias="durationMs")
    session_id: str | None = Field(default=None, alias="sessionId")
    name: str | None = None
    model: str | None = None
    level: str | None = None
    input: str | None = None
    output: str | None = None
    tokens: int | None = None
    cost_usd: float | None = Field(default=None, alias="costUsd")
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolCall(BaseModel):
    """Only the recorded MCP fields needed for a person's activity view."""

    id: str
    user_id: str = Field(alias="userId")
    type: Literal["TOOL"] = "TOOL"
    start_time: AwareDatetime = Field(alias="startTime")
    duration_ms: int | None = Field(default=None, alias="durationMs")
    session_id: str | None = Field(default=None, alias="sessionId")
    server: str | None = None
    tool: str
    parameters: str | None = None
    result: str | None = None
    status: str | None = None
    tokens: int | None = None
    cost_usd: float | None = Field(default=None, alias="costUsd")
    metadata: dict[str, Any] = Field(default_factory=dict)


Activity = Exchange | ToolCall

_SECRET_KEY = re.compile(
    r"(?:^|[._-])(?:authorization|cookie|password|secret|credential|apikey|api[._-]?key|"
    r"access[_-]?token|refresh[_-]?token|id[_-]?token|jwt[._-]sub)(?:$|[._-])",
    re.IGNORECASE,
)
_BEARER = re.compile(r"\bBearer\s+\S+", re.IGNORECASE)
_URL_USERINFO = re.compile(r"([a-z][a-z0-9+.-]*://)[^/@\s]+:[^/@\s]+@", re.IGNORECASE)
_SECRET_PARAM = re.compile(
    r"([?&](?:token|access_token|api_key|key|secret|password)=)[^&#\s]+", re.IGNORECASE
)
_VISIBLE_METADATA = frozenset(
    {
        "requested_model",
        "attributes.gen_ai.request.model",
        "attributes.gen_ai.response.model",
        "attributes.gen_ai.provider.name",
        "attributes.gen_ai.operation.name",
        "attributes.http.method",
        "attributes.http.status",
        "attributes.langfuse.session.id",
        "resourceAttributes.service.name",
        "mcp.server",
        "mcp.tool",
        "attributes.mcp.target",
        "attributes.gen_ai.tool.name",
    }
)


def _redact_text(value: str) -> str:
    """Mask credentials in recorded text before returning it to a browser."""
    value = _URL_USERINFO.sub(r"\1******@", value)
    value = _SECRET_PARAM.sub(r"\1******", value)
    return _BEARER.sub("Bearer ******", value)


def _safe_metadata(value: object, key: str = "") -> object:
    """Keep recorded context while withholding credentials before it reaches the browser."""
    if _SECRET_KEY.search(key):
        return "******"
    if isinstance(value, dict):
        return {str(name): _safe_metadata(part, str(name)) for name, part in value.items()}
    if isinstance(value, list):
        return [_safe_metadata(part) for part in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


class _Page(BaseModel):
    """Langfuse observation page; discard pagination after a bounded read."""

    data: list[Observation]


def _recorded_content(value: str | None, metadata: dict[str, Any], prefix: str) -> str | None:
    """Prefer direct I/O; v4 MCP traces can store flattened I/O only in metadata."""
    if value:
        return _redact_text(value)
    fields = {
        key.removeprefix(prefix): content
        for key, content in metadata.items()
        if key.startswith(prefix) and key != f"{prefix}isError"
    }
    return json.dumps(fields, ensure_ascii=False) if fields else None


def _activity(row: Observation) -> Activity:
    duration_ms = (
        max(0, round((row.end_time - row.start_time).total_seconds() * 1000))
        if row.end_time is not None
        else None
    )
    metadata = {
        name: _safe_metadata(value, name)
        for name, value in row.metadata.items()
        if name in _VISIBLE_METADATA
    }
    content_metadata = {
        name: _safe_metadata(value, name)
        for name, value in row.metadata.items()
        if name.startswith("attributes.langfuse.observation.input.")
        or name.startswith("attributes.langfuse.observation.output.")
    }
    recorded_session = row.session_id or row.metadata.get("attributes.langfuse.session.id")
    session_id = (
        recorded_session if isinstance(recorded_session, str) and recorded_session else None
    )
    tokens = row.total_usage
    if tokens is None and (row.input_usage is not None or row.output_usage is not None):
        tokens = (row.input_usage or 0) + (row.output_usage or 0)
    if row.type == "GENERATION":
        recorded = row.model_dump(by_alias=True)
        recorded["input"] = _redact_text(row.input) if row.input else row.input
        recorded["output"] = _redact_text(row.output) if row.output else row.output
        recorded["durationMs"] = duration_ms
        recorded["sessionId"] = session_id
        recorded["tokens"] = tokens
        recorded["costUsd"] = row.total_cost
        recorded["metadata"] = metadata
        response_model = row.metadata.get("attributes.gen_ai.response.model")
        if isinstance(response_model, str) and response_model:
            recorded["model"] = response_model
        return Exchange.model_validate(recorded)
    tool = metadata.get("mcp.tool") or metadata.get("attributes.gen_ai.tool.name") or row.name
    server = metadata.get("mcp.server") or metadata.get("attributes.mcp.target")
    error = metadata.get("attributes.langfuse.observation.output.isError")
    status = (
        "Error"
        if error is True or error == "true"
        else "Completed"
        if error is False or error == "false"
        else row.status_message or (row.level if row.level not in (None, "DEFAULT") else None)
    )
    return ToolCall(
        id=row.id,
        userId=row.user_id,
        startTime=row.start_time,
        durationMs=duration_ms,
        sessionId=session_id,
        server=server if isinstance(server, str) else None,
        tool=tool if isinstance(tool, str) else "MCP tool",
        parameters=_recorded_content(
            row.input,
            content_metadata,
            "attributes.langfuse.observation.input.",
        ),
        result=_recorded_content(
            row.output,
            content_metadata,
            "attributes.langfuse.observation.output.",
        ),
        status=status,
        tokens=tokens,
        costUsd=row.total_cost,
        metadata=metadata,
    )


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
        self,
        user_id: str,
        start: datetime,
        end: datetime,
        types: list[str],
        column: str | None,
        query: str,
    ) -> list[Observation]:
        """Create *all* upstream conditions on the server, including the owner."""
        params: dict[str, str | int] = {
            "fields": "core,basic,io,model,metadata,usage",
            "limit": 10,
        }
        if column is None and len(types) == 1:
            params.update(
                userId=user_id,
                type=types[0],
                fromStartTime=start.isoformat(),
                toStartTime=end.isoformat(),
            )
        else:
            # An advanced filter overrides ALL first-class filters.
            conditions: list[dict[str, Any]] = [
                {"type": "string", "column": "userId", "operator": "=", "value": user_id},
                {"type": "stringOptions", "column": "type", "operator": "any of", "value": types},
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
            ]
            if column is not None:
                if column == "metadata":
                    conditions.append(
                        {
                            "type": "stringObject",
                            "column": "metadata",
                            "key": "attributes.langfuse.observation.input.query",
                            "operator": "matches",
                            "value": query,
                        }
                    )
                else:
                    conditions.append(
                        {"type": "string", "column": column, "operator": "matches", "value": query}
                    )
            params["filter"] = json.dumps(conditions)
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
                or row.type not in types
                or not start <= row.start_time.astimezone(UTC) < end
            ):
                raise LangfuseReadError
        return page.data

    async def recent(
        self,
        user_id: str,
        start: datetime,
        end: datetime,
        query: str | None,
        activity_type: ActivityType = "all",
    ) -> list[Activity]:
        """Return ten newest matching, owner-checked generations and/or MCP calls."""
        types = {"all": ["GENERATION", "TOOL"], "llm": ["GENERATION"], "mcp": ["TOOL"]}[
            activity_type
        ]
        if not query:
            rows = await self._page(user_id, start, end, types, None, "")
        else:
            # Langfuse combines filters with AND. Search each content field separately.
            rows = []
            for column in ("input", "output", "metadata"):
                if column == "metadata" and activity_type == "llm":
                    continue
                search_types = ["TOOL"] if column == "metadata" else types
                rows.extend(await self._page(user_id, start, end, search_types, column, query))
            rows = list({row.id: row for row in rows}.values())
        return [
            _activity(row)
            for row in sorted(rows, key=lambda item: item.start_time, reverse=True)[:10]
        ]
