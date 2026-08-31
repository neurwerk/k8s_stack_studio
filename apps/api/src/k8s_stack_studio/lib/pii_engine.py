"""Typed HTTP client for the versioned PII Engine Studio contract."""

from __future__ import annotations

import logging

import httpx
from pydantic import TypeAdapter, ValidationError

from k8s_stack_studio.lib.exceptions import (
    PiiEngineRequestError,
    PiiEngineTimeoutError,
    PiiEngineUnavailableError,
)
from k8s_stack_studio.models.policy_engine import (
    ActionDescription,
    PolicyResponse,
    StudioAnalyzeRequest,
    StudioAnalyzeResponse,
    StudioPolicyEvaluationRequest,
    StudioPolicyEvaluationResponse,
)

_logger = logging.getLogger(__name__)
_evaluation_response_adapter = TypeAdapter(StudioPolicyEvaluationResponse)


class PiiEngineClient:
    """Call PII Engine with a dedicated mTLS-configured httpx client."""

    def __init__(self, base_url: str, client: httpx.AsyncClient) -> None:
        """Store the engine URL and lifespan-managed HTTP client."""
        self._base = base_url.rstrip("/")
        self._client = client

    async def analyze(self, request: StudioAnalyzeRequest) -> StudioAnalyzeResponse:
        """Analyze a supported request and optional request-local policy preview."""
        data = await self._post(
            "/v1/studio/analyze-request",
            request.model_dump(mode="json", exclude_none=True),
        )
        try:
            return StudioAnalyzeResponse.model_validate(data)
        except ValidationError as error:
            raise PiiEngineRequestError(502, "Invalid PII Engine response") from error

    async def evaluate(
        self, request: StudioPolicyEvaluationRequest
    ) -> StudioPolicyEvaluationResponse:
        """Evaluate a policy candidate and parse strict model-free evidence."""
        data = await self._post(
            "/v1/studio/evaluate-policy",
            request.model_dump(mode="json", exclude_none=True),
        )
        try:
            return _evaluation_response_adapter.validate_python(data)
        except ValidationError as error:
            raise PiiEngineRequestError(502, "Invalid PII Engine response") from error

    async def get_actions(self) -> list[ActionDescription]:
        """Return the shared PII action registry."""
        data = await self._get("/v1/actions")
        if not isinstance(data, list):
            raise PiiEngineRequestError(502, "Invalid action registry response")
        try:
            return [ActionDescription.model_validate(item) for item in data]
        except ValidationError as error:
            raise PiiEngineRequestError(502, "Invalid PII Engine action registry") from error

    async def get_policy(self) -> PolicyResponse:
        """Return shared policy metadata and the normalized entity catalog."""
        data = await self._get("/v1/policy")
        try:
            return PolicyResponse.model_validate(data)
        except ValidationError as error:
            raise PiiEngineRequestError(502, "Invalid PII Engine policy response") from error

    async def _post(self, path: str, payload: object) -> object:
        """POST a typed payload and translate transport failures."""
        return await self._request("POST", path, payload)

    async def _get(self, path: str) -> object:
        """GET a typed engine resource and translate transport failures."""
        return await self._request("GET", path, None)

    async def _request(self, method: str, path: str, payload: object | None) -> object:
        """Execute one request through the dedicated client."""
        url = f"{self._base}{path}"
        try:
            if payload is None:
                response = await self._client.request(method, url)
            else:
                response = await self._client.request(method, url, json=payload)
        except httpx.TimeoutException:
            raise PiiEngineTimeoutError("PII Engine request timed out.") from None  # noqa: TRY003
        except httpx.RequestError as error:
            _logger.exception("PII Engine unreachable at %s", url)
            raise PiiEngineUnavailableError("PII Engine unreachable.") from error  # noqa: TRY003
        if response.status_code >= 400:
            raise PiiEngineRequestError(response.status_code, "PII Engine request failed.")
        try:
            return response.json()
        except ValueError as error:
            raise PiiEngineRequestError(502, "PII Engine returned invalid JSON.") from error
