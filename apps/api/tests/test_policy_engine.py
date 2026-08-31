"""Tests for the PII Engine client and Studio policy routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from starlette.requests import Request

from k8s_stack_studio.controllers.policy_engine import evaluate, router
from k8s_stack_studio.lib.auth import StudioPrincipal
from k8s_stack_studio.lib.exceptions import (
    PiiEngineRequestError,
    PiiEngineTimeoutError,
    PiiEngineUnavailableError,
)
from k8s_stack_studio.lib.pii_engine import PiiEngineClient
from k8s_stack_studio.models.policy_engine import (
    ChatMessage,
    OpenAIChatRequest,
    StudioAnalyzeRequest,
    StudioPolicyEvaluationRequest,
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
        "api_version": "v1",
        "decision": "apply_actions",
        "entities": ["EMAIL_ADDRESS"],
        "entity_counts": {"EMAIL_ADDRESS": 1},
        "applied_actions": ["mask"],
        "remote_allowed": True,
        "request": {
            "model": "test-model",
            "messages": [{"role": "user", "content": "email *************"}],
        },
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
                    "path": ["messages", 0, "content"],
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
                    "path": ["messages", 0, "content"],
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
async def test_client_analyze_uses_studio_contract(
    client: PiiEngineClient, mock_http_client: MagicMock
) -> None:
    """Analyze posts the strict request and parses the no-reversal response."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json.return_value = studio_response()
    mock_http_client.request = AsyncMock(return_value=response)

    result = await client.analyze(request_model())

    assert result.entities == ["EMAIL_ADDRESS"]
    assert "reversal" not in result.model_dump()
    call = mock_http_client.request.await_args
    assert call is not None
    assert call.args[:2] == (
        "POST",
        "https://monitor-pii-engine-service.monitor-pii-engine.svc.cluster.local:443/v1/studio/analyze-request",
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
async def test_client_evaluate_uses_dedicated_studio_path_without_headers(
    client: PiiEngineClient, mock_http_client: MagicMock
) -> None:
    """Evaluation sends the exact body through the existing isolated client."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json.return_value = evaluation_response()
    mock_http_client.request = AsyncMock(return_value=response)

    result = await client.evaluate(evaluation_request_model())

    assert result.valid is True
    call = mock_http_client.request.await_args
    assert call is not None
    assert call.args[:2] == (
        "POST",
        "https://monitor-pii-engine-service.monitor-pii-engine.svc.cluster.local:443/v1/studio/evaluate-policy",
    )
    assert "headers" not in call.kwargs
    assert call.kwargs["json"] == {
        "request": {
            "model": "test-model",
            "messages": [
                {
                    "role": "user",
                    "content": "email a@example.com",
                    "tool_calls": [],
                }
            ],
            "stream": False,
            "tools": [],
        },
        "policy": {"pii": {"defaultAction": "mask"}},
        "simulation": "deterministic_echo",
    }


@pytest.mark.asyncio
async def test_client_accepts_invalid_candidate_as_a_normal_response(
    client: PiiEngineClient, mock_http_client: MagicMock
) -> None:
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json.return_value = {
        "api_version": "v1",
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
        "api_version": "v1",
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
