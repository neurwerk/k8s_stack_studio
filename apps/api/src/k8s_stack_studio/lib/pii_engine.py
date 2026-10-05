"""Typed HTTP client for the versioned PII Engine Studio contract."""

from __future__ import annotations

import logging
import re

import httpx
from neurwerk_request_segments import (
    ExtractedRequest,
    ExtractionLimitError,
    SupportedRequest,
    TextSegment,
    extract_request,
)
from pydantic import TypeAdapter, ValidationError

from k8s_stack_studio.lib.exceptions import (
    PiiEngineRequestError,
    PiiEngineTimeoutError,
    PiiEngineUnavailableError,
)
from k8s_stack_studio.models.policy_engine import (
    ActionDescription,
    EngineLimitResponse,
    PolicyResponse,
    StudioAnalyzeRequest,
    StudioAnalyzeResponse,
    StudioPolicyEvaluationRequest,
    StudioPolicyEvaluationResponse,
)

_logger = logging.getLogger(__name__)
_evaluation_response_adapter = TypeAdapter(StudioPolicyEvaluationResponse)
_segments_adapter = TypeAdapter(list[TextSegment])


def _extract_sample(request: SupportedRequest) -> ExtractedRequest:
    try:
        extracted = extract_request(request)
    except ExtractionLimitError as error:
        raise PiiEngineRequestError(
            413,
            f"The sample exceeds the extraction {error.reason} limit "
            f"(at least {error.measured} {error.unit}; maximum {error.maximum}).",
        ) from None
    except ValueError:
        # Extraction uses ValueError for malformed encoded arguments and unsupported content.
        raise PiiEngineRequestError(
            400, "The sample contains invalid or unsupported content."
        ) from None
    if any(len(segment.text) > 100_000 for segment in extracted.segments):
        raise PiiEngineRequestError(413, "Studio text fields cannot exceed 100000 characters.")
    return extracted


def _engine_error_detail(response: httpx.Response) -> str:
    if response.status_code != 413 or len(response.content) > 16_384:
        return "PII Engine request failed."
    try:
        error = EngineLimitResponse.model_validate_json(response.content).error
    except ValidationError:
        return "PII Engine request failed."
    limit = error.limit
    detail = (
        f"{error.message} {limit.component}/{limit.stage}: {limit.reason}, "
        f"{'measured' if limit.exact else 'at least'} {limit.measured} {limit.unit}, "
        f"maximum {limit.maximum}."
    )
    request_id = response.headers.get("x-correlation-id", "")
    if re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", request_id):
        detail += f" Request ID: {request_id}."
    return detail


def _segment_payload(extracted: ExtractedRequest) -> dict[str, object]:
    return {
        "api_version": "v2",
        "request_kind": extracted.request_kind,
        "scope": "request",
        "segments": [segment.model_dump() for segment in extracted.segments],
        "text_pii_enabled": True,
        "attachments_present": extracted.attachments_present,
        "visual_findings": None,
    }


def _restore_response(data: object, extracted: ExtractedRequest) -> dict[str, object]:
    if not isinstance(data, dict) or data.get("api_version") != "v2":
        raise ValueError("Invalid segment response")  # noqa: TRY003
    result = dict(data)
    result["api_version"] = "v1"
    if result.get("valid") is False:
        return result
    if "request" in result or "segments" not in result:
        raise ValueError("Expected segment response")  # noqa: TRY003
    segments = result.pop("segments")
    if result.get("decision") == "block":
        if segments is not None:
            raise ValueError("Blocked response contains segments")  # noqa: TRY003
        result["request"] = None
    else:
        replacements = _segments_adapter.validate_python(segments)
        if [segment.id for segment in replacements] != [
            segment.id for segment in extracted.segments
        ]:
            raise ValueError("Segment IDs or order changed")  # noqa: TRY003
        if replacements != extracted.segments and (
            result.get("decision") not in {"apply_actions", "reroute"}
            or not _allows_replacement(result.get("applied_actions"))
        ):
            raise ValueError("Unauthorized segment replacement")  # noqa: TRY003
        result["request"] = extracted.rebuild(replacements)
    if "diagnostics" in result:
        result["diagnostics"] = _restore_diagnostics(result["diagnostics"], extracted)
    return result


def _allows_replacement(actions: object) -> bool:
    return isinstance(actions, list) and any(
        action in {"mask", "replace", "redact", "hash", "encrypt", "reversible_replace"}
        for action in actions
        if isinstance(action, str)
    )


def _restore_diagnostics(data: object, extracted: ExtractedRequest) -> dict[str, object]:
    if not isinstance(data, dict):
        raise TypeError("Invalid diagnostics")  # noqa: TRY003
    result = dict(data)
    lengths = {segment.id: len(segment.text) for segment in extracted.segments}
    for name in ("logical_detections", "effective_regions"):
        entries = data.get(name)
        if not isinstance(entries, list):
            raise TypeError("Invalid diagnostics list")  # noqa: TRY003
        rows = []
        for row in entries:
            if not isinstance(row, dict) or "path" in row:
                raise ValueError("Invalid segment diagnostic")  # noqa: TRY003
            item = dict(row)
            segment_id = item.pop("segment_id", None)
            if not isinstance(segment_id, str) or segment_id not in lengths:
                raise ValueError("Unknown diagnostic segment")  # noqa: TRY003
            if not isinstance(item.get("end"), int) or item["end"] > lengths[segment_id]:
                raise ValueError("Diagnostic exceeds segment")  # noqa: TRY003
            path = extracted.diagnostic_path(segment_id)
            bounded_path = tuple(
                min(part, 10_000_000) if isinstance(part, int) else part[:128] for part in path[:64]
            )
            if bounded_path != path:
                result["truncated"] = True
            item["path"] = list(bounded_path)
            rows.append(item)
        result[name] = rows
    return result


class PiiEngineClient:
    """Call PII Engine with a dedicated mTLS-configured httpx client."""

    def __init__(self, base_url: str, client: httpx.AsyncClient) -> None:
        """Store the engine URL and lifespan-managed HTTP client."""
        self._base = base_url.rstrip("/")
        self._client = client

    async def analyze(self, request: StudioAnalyzeRequest) -> StudioAnalyzeResponse:
        """Analyze a supported request and optional request-local policy preview."""
        extracted = _extract_sample(request.request)
        payload: dict[str, object] = {"request": _segment_payload(extracted)}
        if request.policy is not None:
            payload["policy"] = request.policy
        data = await self._post("/v2/studio/analyze-segments", payload)
        try:
            return StudioAnalyzeResponse.model_validate(_restore_response(data, extracted))
        except (ValueError, TypeError, KeyError) as error:
            raise PiiEngineRequestError(502, "Invalid PII Engine response") from error

    async def evaluate(
        self, request: StudioPolicyEvaluationRequest
    ) -> StudioPolicyEvaluationResponse:
        """Evaluate a policy candidate and parse strict model-free evidence."""
        extracted = _extract_sample(request.request)
        payload: dict[str, object] = {
            "request": _segment_payload(extracted),
            "simulation": request.simulation,
        }
        if request.policy is not None:
            payload["policy"] = request.policy
        data = await self._post("/v2/studio/evaluate-policy", payload)
        try:
            return _evaluation_response_adapter.validate_python(_restore_response(data, extracted))
        except (ValueError, TypeError, KeyError) as error:
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
            raise PiiEngineRequestError(response.status_code, _engine_error_detail(response))
        try:
            return response.json()
        except ValueError as error:
            raise PiiEngineRequestError(502, "PII Engine returned invalid JSON.") from error
