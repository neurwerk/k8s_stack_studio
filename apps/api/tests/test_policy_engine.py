"""Tests for the PII Engine client and Studio policy routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.routing import APIRoute
from neurwerk_request_segments.models import EngineChatRequest as OpenAIChatRequest
from neurwerk_request_segments.models import EngineMessage as ChatMessage
from pydantic import ValidationError
from starlette.requests import Request

from k8s_stack_studio.controllers.policy_engine import evaluate, router
from k8s_stack_studio.lib.auth import StudioPrincipal
from k8s_stack_studio.lib.dependencies import get_pii_engine_client
from k8s_stack_studio.lib.exceptions import (
    PiiEngineRequestError,
    PiiEngineTimeoutError,
    PiiEngineUnavailableError,
)
from k8s_stack_studio.lib.pii_engine import PiiEngineClient
from k8s_stack_studio.models.policy_engine import (
    StudioAnalyzeRequest,
    StudioPolicyEvaluationRequest,
    StudioPolicyEvaluationValidResponse,
)


def request_model() -> StudioAnalyzeRequest:
    """Build a valid versioned Studio request."""
    return StudioAnalyzeRequest(
        request=OpenAIChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="email a@example.com")],
        ),
        policy={"pii": {"defaultAction": "mask"}},
    )


def studio_response() -> dict[str, object]:
    """Build a response without reversal material."""
    return {
        "api_version": "v2",
        "decision": "apply_actions",
        "entities": ["EMAIL_ADDRESS"],
        "entity_counts": {"EMAIL_ADDRESS": 1},
        "applied_actions": ["mask"],
        "remote_allowed": True,
        "segments": [{"id": "s0", "text": "email *************"}],
        "analysis": {
            "source": "current_request",
            "scan_performed": True,
            "duration_ms": 3200,
            "overlap_count": 0,
            "overlap_resolution": "strictest_action",
            "policy_version": "test",
            "text_leaf_count": 1,
            "cached_decision_applied": False,
        },
        "notices": {"request": [], "response": []},
    }


def evaluation_request_model() -> StudioPolicyEvaluationRequest:
    """Build a valid deterministic evaluation request."""
    return StudioPolicyEvaluationRequest(
        request=request_model().request,
        policy=request_model().policy,
    )


def evaluation_response() -> dict[str, object]:
    """Build a valid detailed evaluation response."""
    return studio_response() | {
        "valid": True,
        "issues": [],
        "issues_truncated": False,
        "report": {
            "rows": [
                {
                    "entity_type": "EMAIL_ADDRESS",
                    "action": "mask",
                    "detected_count": 1,
                    "transformed_count": 1,
                    "unique_transformed_count": 1,
                }
            ]
        },
        "diagnostics": {
            "logical_detections": [
                {
                    "segment_id": "s0",
                    "start": 6,
                    "end": 19,
                    "entity_type": "EMAIL_ADDRESS",
                    "score": 0.99,
                    "source": "deterministic",
                    "configured_action": "mask",
                    "resolved_action": "mask",
                }
            ],
            "effective_regions": [
                {
                    "segment_id": "s0",
                    "start": 6,
                    "end": 19,
                    "entity_type": "EMAIL_ADDRESS",
                    "action": "mask",
                    "source": "deterministic",
                    "score": 0.99,
                    "member_entity_types": ["EMAIL_ADDRESS"],
                    "overlap": False,
                }
            ],
            "truncated": False,
        },
        "simulation": {
            "type": "deterministic_echo",
            "status": "completed",
            "reason": None,
            "model_called": False,
            "model_response": "[SIMULATED - NO MODEL CALLED]\nemail *************",
            "user_response": "[SIMULATED - NO MODEL CALLED]\nemail *************",
            "restored_entity_counts": {},
        },
    }


@pytest.fixture
def mock_http_client() -> MagicMock:
    """Return a mocked async HTTP client."""
    return MagicMock(spec=httpx.AsyncClient)


@pytest.fixture
def client(mock_http_client: MagicMock) -> PiiEngineClient:
    """Return a PII Engine client with no network access."""
    return PiiEngineClient(
        "https://monitor-pii-engine-service.monitor-pii-engine.svc.cluster.local:443",
        mock_http_client,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["analyze", "evaluate"])
async def test_client_analyze_uses_studio_contract(
    client: PiiEngineClient, mock_http_client: MagicMock, endpoint: str
) -> None:
    """HTTP transformations preserve provider omissions, nulls, and false values."""
    response = httpx.Response(
        200, json=studio_response() if endpoint == "analyze" else evaluation_response()
    )
    mock_http_client.request = AsyncMock(return_value=response)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_pii_engine_client] = lambda: client

    @app.middleware("http")
    async def authenticate(request, call_next):
        request.scope["user"] = StudioPrincipal(
            "user-1", frozenset({"studio-user", "pii-admin"}), frozenset(), {}
        )
        return await call_next(request)

    provider_request = {
        "model": "test-model",
        "messages": [{"role": "user", "content": "email a@example.com"}],
        "temperature": None,
        "stream": False,
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as browser:
        response = await browser.post(
            f"/api/policy-engine/{endpoint}",
            json={"request": provider_request, "policy": {"pii": {"defaultAction": "mask"}}},
        )
    assert response.status_code == 200
    result = response.json()
    assert result["entities"] == ["EMAIL_ADDRESS"]
    assert result["request"] == provider_request | {
        "messages": [{"role": "user", "content": "email *************"}]
    }
    assert result["route_class"] is None
    assert result["safety_rule"] is None
    assert "reversal" not in result
    call = mock_http_client.request.await_args
    assert call is not None
    path = "analyze-segments" if endpoint == "analyze" else "evaluate-policy"
    assert call.args[:2] == (
        "POST",
        f"https://monitor-pii-engine-service.monitor-pii-engine.svc.cluster.local:443/v2/studio/{path}",
    )
    assert "headers" not in call.kwargs
    assert call.kwargs["json"]["policy"]["pii"]["defaultAction"] == "mask"


@pytest.mark.asyncio
async def test_client_actions_and_policy(
    client: PiiEngineClient, mock_http_client: MagicMock
) -> None:
    """Actions and policy use the versioned engine paths."""
    actions = MagicMock(spec=httpx.Response)
    actions.status_code = 200
    actions.json.return_value = [
        {
            "name": "mask",
            "decision": "apply_actions",
            "reversible": False,
            "severity": "info",
            "strictness": 2,
            "params": [],
            "notes": "safe",
        }
    ]
    policy = MagicMock(spec=httpx.Response)
    policy.status_code = 200
    policy.json.return_value = {
        "api_version": "v1",
        "version": "test",
        "default_action": "pass",
        "entities": ["EMAIL_ADDRESS"],
        "safety_rules": ["promptInjection"],
    }
    mock_http_client.request = AsyncMock(side_effect=[actions, policy])

    assert (await client.get_actions())[0].name == "mask"
    assert (await client.get_policy()).entities == ["EMAIL_ADDRESS"]


@pytest.mark.asyncio
@pytest.mark.parametrize("include_usage", [None, False, True])
async def test_client_evaluate_uses_dedicated_studio_path_without_headers(
    client: PiiEngineClient, mock_http_client: MagicMock, include_usage: bool | None
) -> None:
    """Evaluation preserves serialized Engine stream options without human headers."""
    options = None if include_usage is None else {"include_usage": include_usage}
    payload = evaluation_response()
    response = httpx.Response(200, json=payload)
    mock_http_client.request = AsyncMock(return_value=response)
    request = evaluation_request_model().model_dump(mode="json")
    if options is not None:
        request["request"].update({"stream": True, "stream_options": options})

    result = await client.evaluate(StudioPolicyEvaluationRequest.model_validate(request))

    assert result.valid is True
    assert isinstance(result, StudioPolicyEvaluationValidResponse)
    assert result.api_version == "v1"
    assert result.diagnostics.logical_detections[0].path == ["messages", 0, "content"]
    assert result.model_dump(mode="json")["request"]["stream_options"] == options
    call = mock_http_client.request.await_args
    assert call is not None
    assert call.args[:2] == (
        "POST",
        "https://monitor-pii-engine-service.monitor-pii-engine.svc.cluster.local:443/v2/studio/evaluate-policy",
    )
    assert "headers" not in call.kwargs
    assert call.kwargs["json"] == {
        "request": {
            "api_version": "v2",
            "request_kind": "chat",
            "scope": "request",
            "segments": [{"id": "s0", "text": "email a@example.com"}],
            "text_pii_enabled": True,
            "attachments_present": False,
            "visual_findings": None,
        },
        "policy": {"pii": {"defaultAction": "mask"}},
        "simulation": "deterministic_echo",
    }


@pytest.mark.parametrize(
    "update",
    [
        {"stream": True, "stream_options": {"include_usage": "true"}},
        {"stream": True, "stream_options": {"include_usage": 1}},
        {"stream": True, "stream_options": {"include_usage": True, "unknown": True}},
        {"stream_options": {"include_usage": True}},
        {"stream": False, "stream_options": {"include_usage": False}},
        {"stream": True, "stream_options": {"include_usage": True}, "unknown": True},
    ],
)
def test_chat_request_rejects_invalid_stream_options(update: dict[str, object]) -> None:
    with pytest.raises((ValidationError, PiiEngineRequestError)):
        StudioAnalyzeRequest.model_validate(
            {
                "request": {
                    "model": "test-model",
                    "messages": [{"role": "user", "content": "hello"}],
                }
                | update
            }
        )


@pytest.mark.asyncio
async def test_client_accepts_invalid_candidate_as_a_normal_response(
    client: PiiEngineClient, mock_http_client: MagicMock
) -> None:
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json.return_value = {
        "api_version": "v2",
        "valid": False,
        "issues": [
            {
                "stage": "schema",
                "path": ["pii", "defaultAction"],
                "code": "literal_error",
                "message": "Input should be a supported action.",
            }
        ],
        "issues_truncated": False,
    }
    mock_http_client.request = AsyncMock(return_value=response)

    result = await client.evaluate(evaluation_request_model())

    assert result.valid is False
    assert result.issues[0].code == "literal_error"


@pytest.mark.asyncio
async def test_client_rejects_extra_fields_on_invalid_evaluation_response(
    client: PiiEngineClient, mock_http_client: MagicMock
) -> None:
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json.return_value = {
        "api_version": "v2",
        "valid": False,
        "issues": [
            {
                "stage": "compile",
                "path": [],
                "code": "policy_compile_failed",
                "message": "Policy compilation failed.",
            }
        ],
        "issues_truncated": False,
        "reversal": {"placeholder": "private"},
    }
    mock_http_client.request = AsyncMock(return_value=response)

    with pytest.raises(PiiEngineRequestError) as error:
        await client.evaluate(evaluation_request_model())

    assert error.value.status_code == 502
    assert "private" not in str(error.value)


@pytest.mark.asyncio
async def test_evaluate_controller_proxies_typed_request() -> None:
    """The Studio route delegates without adding human identity material."""
    client = AsyncMock(spec=PiiEngineClient)
    response = MagicMock()
    client.evaluate.return_value = response
    request = evaluation_request_model()

    result = await evaluate(request, "user-1", None, client)

    assert result is response
    client.evaluate.assert_awaited_once_with(request)


def test_evaluate_route_requires_pii_admin() -> None:
    """The evaluate route retains the focused pii-admin authorization gate."""
    route = next(
        item
        for item in router.routes
        if isinstance(item, APIRoute) and item.path == "/api/policy-engine/evaluate"
    )
    role_check = next(
        dependency.call
        for dependency in route.dependant.dependencies
        if dependency.call is not None
        and getattr(dependency.call, "__name__", None) == "_check_role"
    )
    request = Request(
        {
            "type": "http",
            "headers": [],
            "user": StudioPrincipal("user-1", frozenset({"studio-user"}), frozenset(), {}),
        }
    )

    with pytest.raises(HTTPException) as error:
        role_check(request)

    assert error.value.status_code == 403
    request.scope["user"] = StudioPrincipal(
        "user-1", frozenset({"studio-user", "pii-admin"}), frozenset(), {}
    )
    assert role_check(request) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update({"reversal": {"placeholder": "private"}}),
        lambda payload: cast(dict[str, object], payload["simulation"]).update(
            {"reversal": {"placeholder": "private"}}
        ),
        lambda payload: cast(dict[str, object], payload["simulation"]).update(
            {"model_called": True}
        ),
        lambda payload: payload.update(
            {
                "issues": [
                    {
                        "stage": "compile",
                        "path": [],
                        "code": "unexpected_issue",
                        "message": "A valid response cannot contain issues.",
                    }
                ]
            }
        ),
        lambda payload: cast(
            list[dict[str, object]],
            cast(dict[str, object], payload["report"])["rows"],
        )[0].update({"unique_transformed_count": 2}),
    ],
)
async def test_client_strictly_rejects_malformed_evaluation_responses(
    client: PiiEngineClient,
    mock_http_client: MagicMock,
    mutate: Callable[[dict[str, object]], None],
) -> None:
    payload = evaluation_response()
    mutate(payload)
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json.return_value = payload
    mock_http_client.request = AsyncMock(return_value=response)

    with pytest.raises(PiiEngineRequestError) as error:
        await client.evaluate(evaluation_request_model())

    assert error.value.status_code == 502
    assert "private" not in str(error.value)


@pytest.mark.asyncio
async def test_client_omits_policy_when_preview_is_not_requested(
    client: PiiEngineClient, mock_http_client: MagicMock
) -> None:
    """Normal Studio analysis uses the engine's deployed policy."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json.return_value = studio_response()
    mock_http_client.request = AsyncMock(return_value=response)
    request = StudioAnalyzeRequest(request=request_model().request)

    await client.analyze(request)

    call = mock_http_client.request.await_args
    assert call is not None
    assert "policy" not in call.kwargs["json"]


@pytest.mark.asyncio
async def test_client_rejects_unversioned_analysis_response(
    client: PiiEngineClient, mock_http_client: MagicMock
) -> None:
    """Studio cannot silently assume a contract version for an engine reply."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    payload = studio_response()
    del payload["api_version"]
    response.json.return_value = payload
    mock_http_client.request = AsyncMock(return_value=response)

    with pytest.raises(PiiEngineRequestError) as error:
        await client.analyze(request_model())
    assert error.value.status_code == 502


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (httpx.RequestError("connection refused"), PiiEngineUnavailableError),
        (httpx.TimeoutException("timed out"), PiiEngineTimeoutError),
    ],
)
async def test_client_translates_transport_errors(
    client: PiiEngineClient,
    mock_http_client: MagicMock,
    error: Exception,
    expected: type[Exception],
) -> None:
    """Transport failures become stable Studio domain errors."""
    mock_http_client.request = AsyncMock(side_effect=error)
    with pytest.raises(expected):
        await client.analyze(request_model())


@pytest.mark.asyncio
async def test_client_translates_engine_error(
    client: PiiEngineClient, mock_http_client: MagicMock
) -> None:
    """Non-success engine responses preserve their status code."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = 422
    response.text = "invalid request"
    mock_http_client.request = AsyncMock(return_value=response)
    with pytest.raises(PiiEngineRequestError) as error:
        await client.analyze(request_model())
    assert error.value.status_code == 422
    assert "invalid request" not in str(error.value)

    limit_error = {
        "api_version": "v2",
        "error": {
            "code": "request_too_large",
            "message": "The analysis request exceeds the configured size limit.",
            "retryable": False,
            "limit": {
                "component": "pii_engine",
                "stage": "inspection",
                "reason": "depth",
                "measured": 33,
                "maximum": 32,
                "unit": "levels",
                "exact": False,
            },
        },
    }
    mock_http_client.request = AsyncMock(
        return_value=httpx.Response(
            413, json=limit_error, headers={"x-correlation-id": "sample-request-1"}
        )
    )
    with pytest.raises(PiiEngineRequestError) as error:
        await client.analyze(request_model())
    assert error.value.status_code == 413
    assert "depth, at least 33 levels, maximum 32" in str(error.value.detail)
    assert "Request ID: sample-request-1" in str(error.value.detail)
    limit_error["error"]["message"] = "private rejected content"
    mock_http_client.request = AsyncMock(return_value=httpx.Response(413, json=limit_error))
    with pytest.raises(PiiEngineRequestError) as error:
        await client.analyze(request_model())
    assert error.value.detail == "PII Engine request failed."


@pytest.mark.asyncio
async def test_client_keeps_evaluation_engine_errors_safe(
    client: PiiEngineClient, mock_http_client: MagicMock
) -> None:
    """Evaluation failures do not expose an upstream body or policy values."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = 503
    response.text = "private rejected candidate"
    mock_http_client.request = AsyncMock(return_value=response)

    with pytest.raises(PiiEngineRequestError) as error:
        await client.evaluate(evaluation_request_model())

    assert error.value.status_code == 503
    assert "private rejected candidate" not in str(error.value)


@pytest.mark.asyncio
async def test_client_rejects_reversal_data_in_studio_response(
    client: PiiEngineClient, mock_http_client: MagicMock
) -> None:
    """Studio never accepts a response containing adapter-only reversal data."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json.return_value = studio_response() | {"reversal": {"<EMAIL>": "secret@example.com"}}
    mock_http_client.request = AsyncMock(return_value=response)

    with pytest.raises(PiiEngineRequestError) as error:
        await client.analyze(request_model())
    assert error.value.status_code == 502
    assert "secret@example.com" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "update",
    [
        {"duration_ms": None},
        {"scan_performed": False},
        {"duration_ms": -1},
        {"overlap_count": -1},
        {"overlap_resolution": "first_match"},
        {"source": "cached_decision"},
        {"unexpected": True},
    ],
)
async def test_client_rejects_malformed_analysis_metadata(
    client: PiiEngineClient,
    mock_http_client: MagicMock,
    update: dict[str, object],
) -> None:
    payload = studio_response()
    analysis = cast(dict[str, object], payload["analysis"])
    analysis.update(update)
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json.return_value = payload
    mock_http_client.request = AsyncMock(return_value=response)

    with pytest.raises(PiiEngineRequestError) as error:
        await client.analyze(request_model())
    assert error.value.status_code == 502


@pytest.mark.asyncio
async def test_client_accepts_cached_analysis_without_a_duration(
    client: PiiEngineClient, mock_http_client: MagicMock
) -> None:
    payload = studio_response()
    analysis = cast(dict[str, object], payload["analysis"])
    analysis.update(
        {
            "source": "cached_decision",
            "scan_performed": False,
            "duration_ms": None,
            "overlap_count": 2,
            "text_leaf_count": 0,
            "cached_decision_applied": True,
        }
    )
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json.return_value = payload
    mock_http_client.request = AsyncMock(return_value=response)

    result = await client.analyze(request_model())
    assert result.analysis.duration_ms is None
    assert result.analysis.overlap_count == 2


@pytest.mark.parametrize(
    "update",
    [
        {"segments": []},
        {"segments": [{"id": "s1", "text": "changed"}]},
        {"segments": [{"id": "s0", "text": "changed"}] * 2},
        {"segments": None},
        {"decision": "pass"},
        {"applied_actions": []},
        {"applied_actions": ["pass"]},
        {"decision": "block"},
        {"request": {"model": "unauthorized"}},
    ],
)
async def test_client_rejects_invalid_segment_replacements(client, mock_http_client, update):
    mock_http_client.request = AsyncMock(
        return_value=httpx.Response(200, json=studio_response() | update)
    )
    with pytest.raises(PiiEngineRequestError) as error:
        await client.analyze(request_model())
    assert error.value.status_code == 502


async def test_client_preserves_block_without_rebuilding(client, mock_http_client):
    payload = studio_response() | {"decision": "block", "segments": None, "remote_allowed": False}
    mock_http_client.request = AsyncMock(return_value=httpx.Response(200, json=payload))
    result = await client.analyze(request_model())
    assert result.request is None
    assert result.decision == "block"


@pytest.mark.parametrize("key", ["contact", "k" * 129])
async def test_evaluation_rebuilds_nested_mcp_and_maps_diagnostics(client, mock_http_client, key):
    request = StudioPolicyEvaluationRequest.model_validate(
        {
            "request": {
                "jsonrpc": "2.0",
                "id": "call-1",
                "method": "tools/call",
                "params": {"name": "lookup", "arguments": {key: ["email a@example.com"]}},
            }
        }
    )
    mock_http_client.request = AsyncMock(
        return_value=httpx.Response(200, json=evaluation_response())
    )
    result = await client.evaluate(request)
    assert result.valid
    assert result.request.model_dump()["params"]["arguments"] == {key: ["email *************"]}
    assert result.request.model_dump()["params"]["name"] == "lookup"
    assert result.diagnostics.logical_detections[0].path == ["params", "arguments", key[:128], 0]
    assert result.diagnostics.effective_regions[0].path == ["params", "arguments", key[:128], 0]
    assert result.diagnostics.truncated == (len(key) > 128)
    call = mock_http_client.request.await_args
    assert call is not None
    sent = call.kwargs["json"]["request"]
    assert sent["request_kind"] == "mcp"
    assert sent["segments"] == [{"id": "s0", "text": "email a@example.com"}]
    assert "params" not in sent


@pytest.mark.parametrize("update", [{"segment_id": "unknown"}, {"end": 1000}, {"path": []}])
async def test_client_rejects_unmapped_diagnostics(client, mock_http_client, update):
    payload = evaluation_response()
    diagnostics = cast(dict[str, list[dict[str, object]]], payload["diagnostics"])
    diagnostics["logical_detections"][0].update(update)
    mock_http_client.request = AsyncMock(return_value=httpx.Response(200, json=payload))
    with pytest.raises(PiiEngineRequestError):
        await client.evaluate(evaluation_request_model())


async def test_studio_rejects_invalid_samples_without_sending_content(client, mock_http_client):
    oversized = StudioAnalyzeRequest.model_validate(
        {"request": {"model": "sample", "input": "x" * 100_001}}
    )
    with pytest.raises(PiiEngineRequestError) as error:
        await client.analyze(oversized)
    assert error.value.status_code == 413
    malformed = StudioPolicyEvaluationRequest.model_validate(
        {
            "request": {
                "model": "sample",
                "messages": [
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {"name": "lookup", "arguments": '{"private-input"'},
                            }
                        ],
                    }
                ],
            }
        }
    )
    with pytest.raises(PiiEngineRequestError) as error:
        await client.evaluate(malformed)
    assert error.value.status_code == 400
    assert "private-input" not in str(error.value)
    assert error.value.__suppress_context__
    deep_arguments: object = "private-input"
    for _ in range(34):
        deep_arguments = [deep_arguments]
    deep = StudioAnalyzeRequest.model_validate(
        {
            "request": {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "lookup", "arguments": {"nested": deep_arguments}},
            }
        }
    )
    with pytest.raises(PiiEngineRequestError) as error:
        await client.analyze(deep)
    assert error.value.status_code == 413
    assert "private-input" not in str(error.value)
    encoded = malformed.model_dump(mode="json", exclude_unset=True)
    encoded["request"]["messages"][0]["tool_calls"][0]["function"]["arguments"] = (
        "[" * 1500 + '"private-input"' + "]" * 1500
    )
    with pytest.raises(PiiEngineRequestError) as error:
        await client.evaluate(StudioPolicyEvaluationRequest.model_validate(encoded))
    assert error.value.status_code == 413
    assert "private-input" not in str(error.value)
    mock_http_client.request.assert_not_called()


async def test_responses_preserves_controls_and_rejects_reordered_segments(
    client, mock_http_client
):
    sample = {
        "model": "sample-model",
        "instructions": "answer briefly",
        "input": "email a@example.com",
        "previous_response_id": None,
        "stream": False,
    }
    request = StudioAnalyzeRequest.model_validate({"request": sample})
    payload = studio_response() | {
        "segments": [
            {"id": "s0", "text": "answer briefly"},
            {"id": "s1", "text": "email *************"},
        ]
    }
    mock_http_client.request = AsyncMock(return_value=httpx.Response(200, json=payload))
    result = await client.analyze(request)
    assert result.request is not None
    assert result.request.model_dump(exclude_unset=True) == sample | {
        "input": "email *************"
    }
    cast(list[dict[str, str]], payload["segments"]).reverse()
    mock_http_client.request = AsyncMock(return_value=httpx.Response(200, json=payload))
    with pytest.raises(PiiEngineRequestError):
        await client.analyze(request)
    with pytest.raises(PiiEngineRequestError) as error:
        StudioAnalyzeRequest.model_validate(
            {"request": sample | {"previous_response_id": "response-1"}}
        )
    assert error.value.status_code == 400
