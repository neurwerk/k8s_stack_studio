"""Strict Pydantic v2 models for the versioned PII Engine Studio contract."""

from __future__ import annotations

from typing import Annotated, Literal

from neurwerk_request_segments import SupportedRequest, UnsupportedFeatureError, parse_request
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_serializer,
    model_validator,
)

from k8s_stack_studio.lib.exceptions import PiiEngineRequestError

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


def _parse_sample(value: object) -> SupportedRequest:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", by_alias=True, exclude_unset=True)
    if not isinstance(value, dict):
        raise PiiEngineRequestError(400, "The sample request must be an object.")
    try:
        return parse_request(value)
    except UnsupportedFeatureError:
        raise PiiEngineRequestError(
            400, "The sample contains an unsupported request feature."
        ) from None


type StudioRequest = Annotated[SupportedRequest, BeforeValidator(_parse_sample)]


class StrictModel(BaseModel):
    """Reject undocumented fields at the Studio/engine boundary."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class EngineLimitDetail(StrictModel):
    """Accept only content-free, bounded Engine limit measurements."""

    model_config = ConfigDict(extra="forbid", strict=True)

    component: Literal["pii_engine", "extproc", "request_segments"]
    stage: Literal[
        "admission",
        "json",
        "inspection",
        "engine_request",
        "engine_response",
        "provider_response",
        "output",
    ]
    reason: Literal[
        "bytes",
        "declared_bytes",
        "encoded_bytes",
        "decoded_bytes",
        "transformed_bytes",
        "depth",
        "tokens",
        "nodes",
        "text_characters",
        "segments",
        "text_leaves",
        "empty_chunks",
    ]
    measured: int = Field(ge=0, le=10**18)
    maximum: int = Field(ge=0, le=10**18)
    unit: Literal["bytes", "characters", "items", "levels"]
    exact: bool


class EngineLimitError(StrictModel):
    """Validate a fixed Engine rejection message before displaying it."""

    code: Literal["request_too_large"]
    message: Literal["The analysis request exceeds the configured size limit."]
    retryable: Literal[False]
    limit: EngineLimitDetail


class EngineLimitResponse(StrictModel):
    """Accept the Engine's versioned limit error envelope."""

    api_version: Literal["v2"]
    error: EngineLimitError


class StudioAnalyzeRequest(StrictModel):
    """Wrap a supported request and optional engine-validated policy preview."""

    request: StudioRequest
    policy: dict[str, JsonValue] | None = Field(default=None, max_length=16)


class StudioPolicyEvaluationRequest(StrictModel):
    """Accept a request sample and an unvalidated bounded policy candidate."""

    request: StudioRequest
    policy: dict[str, JsonValue] | None = Field(default=None, max_length=16)
    simulation: Literal["deterministic_echo"] = "deterministic_echo"


class AnalysisMetadata(StrictModel):
    """Describe bounded analysis facts without exposing prompt values."""

    source: Literal["current_request", "cached_decision"]
    scan_performed: bool
    duration_ms: int | None = Field(ge=0, le=120_000)
    overlap_count: int = Field(ge=0, le=10_000_000)
    overlap_resolution: Literal["strictest_action"]
    policy_version: str = Field(min_length=1, max_length=64)
    text_leaf_count: int = Field(ge=0, le=2_048)
    cached_decision_applied: bool

    @model_validator(mode="after")
    def validate_provenance(self) -> AnalysisMetadata:
        """Require scan timing and cache provenance to agree."""
        if self.scan_performed != (self.duration_ms is not None):
            raise ValueError(  # noqa: TRY003
                "scan duration must exist exactly when a scan was performed"
            )
        if self.scan_performed and self.source != "current_request":
            raise ValueError("performed scans must describe the current request")  # noqa: TRY003
        if self.source == "cached_decision" and not self.cached_decision_applied:
            raise ValueError(  # noqa: TRY003
                "cached analysis metadata must apply a cached decision"
            )
        if not self.scan_performed and self.source == "current_request" and self.overlap_count:
            raise ValueError("unscanned current requests cannot report overlaps")  # noqa: TRY003
        return self


class Notices(StrictModel):
    """Carry policy-owned request and response messages."""

    request: list[Annotated[str, Field(max_length=4_000)]] = Field(max_length=16)
    response: list[Annotated[str, Field(max_length=4_000)]] = Field(max_length=16)


Decision = Literal["pass", "block", "apply_actions", "reroute"]


class StudioAnalyzeResponse(StrictModel):
    """Return sanitized request data without reversal mappings."""

    api_version: Literal["v1"]
    decision: Decision
    entities: list[str] = Field(default_factory=list, max_length=64)
    entity_counts: dict[str, int] = Field(default_factory=dict, max_length=64)
    applied_actions: list[str] = Field(default_factory=list, max_length=16)
    remote_allowed: bool
    route_class: str | None = Field(default=None, max_length=128)
    request: SupportedRequest | None = None
    analysis: AnalysisMetadata
    notices: Notices
    safety_rule: str | None = Field(default=None, max_length=128)

    @field_serializer("request")
    def serialize_request(self, request: SupportedRequest | None) -> dict[str, object] | None:
        """Preserve provider omissions without dropping Studio response defaults."""
        if request is None:
            return None
        return request.model_dump(mode="json", by_alias=True, exclude_unset=True)


type EvaluationPathPart = (
    Annotated[str, Field(min_length=1, max_length=128)] | Annotated[int, Field(ge=0, le=10_000_000)]
)
type PIIAction = Literal[
    "pass",
    "block",
    "reroute",
    "mask",
    "replace",
    "redact",
    "hash",
    "encrypt",
    "reversible_replace",
]
type DetectionSource = Literal["deterministic", "spacy", "transformer", "policy_regex"]


class PolicyEvaluationIssue(StrictModel):
    """Describe one sanitized policy-candidate failure."""

    stage: Literal["schema", "merge", "compile"]
    path: list[EvaluationPathPart] = Field(max_length=16)
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    message: str = Field(min_length=1, max_length=256)


class StudioPolicyEvaluationInvalidResponse(StrictModel):
    """Return candidate issues as a normal evaluation result."""

    api_version: Literal["v1"]
    valid: Literal[False]
    issues: list[PolicyEvaluationIssue] = Field(min_length=1, max_length=128)
    issues_truncated: bool


class PIIReportRow(StrictModel):
    """Summarize one entity action without detected values."""

    entity_type: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    action: PIIAction
    detected_count: int = Field(ge=1, le=10_000_000)
    transformed_count: int = Field(ge=0, le=10_000_000)
    unique_transformed_count: int = Field(ge=0, le=10_000_000)

    @model_validator(mode="after")
    def validate_counts(self) -> PIIReportRow:
        """Require transformation totals to describe possible executions."""
        if self.transformed_count > self.detected_count:
            raise ValueError("transformed_count cannot exceed detected_count")  # noqa: TRY003
        if self.unique_transformed_count > self.transformed_count:
            raise ValueError(  # noqa: TRY003
                "unique_transformed_count cannot exceed transformed_count"
            )
        if self.action in {"pass", "block"} and self.transformed_count:
            raise ValueError("pass and block rows cannot claim transformations")  # noqa: TRY003
        return self


class PIIReport(StrictModel):
    """Return aggregate PII details safe for Studio."""

    rows: list[PIIReportRow] = Field(max_length=64)

    @model_validator(mode="after")
    def validate_rows(self) -> PIIReport:
        """Require one deterministically ordered row per entity."""
        entity_types = [row.entity_type for row in self.rows]
        if len(entity_types) != len(set(entity_types)):
            raise ValueError("report rows must contain unique entity types")  # noqa: TRY003
        if entity_types != sorted(entity_types):
            raise ValueError("report rows must be sorted by entity_type")  # noqa: TRY003
        return self


class LogicalDetection(StrictModel):
    """Describe one leaf-local logical detection without matched content."""

    path: list[EvaluationPathPart] = Field(max_length=64)
    start: int = Field(ge=0, le=4_000_000)
    end: int = Field(gt=0, le=4_000_000)
    entity_type: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    score: float = Field(ge=0, le=1, allow_inf_nan=False)
    source: DetectionSource
    configured_action: PIIAction
    resolved_action: PIIAction

    @model_validator(mode="after")
    def validate_span(self) -> LogicalDetection:
        """Require a non-empty code-point span."""
        if self.end <= self.start:
            raise ValueError("detection end must follow start")  # noqa: TRY003
        return self


class EffectiveRegion(StrictModel):
    """Describe one non-overlapping region selected for execution."""

    path: list[EvaluationPathPart] = Field(max_length=64)
    start: int = Field(ge=0, le=4_000_000)
    end: int = Field(gt=0, le=4_000_000)
    entity_type: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    action: PIIAction
    source: DetectionSource
    score: float = Field(ge=0, le=1, allow_inf_nan=False)
    member_entity_types: list[str] = Field(min_length=1, max_length=64)
    overlap: bool

    @model_validator(mode="after")
    def validate_region(self) -> EffectiveRegion:
        """Require a valid span and deterministic member names."""
        if self.end <= self.start:
            raise ValueError("region end must follow start")  # noqa: TRY003
        if self.member_entity_types != sorted(set(self.member_entity_types)):
            raise ValueError("region members must be sorted and unique")  # noqa: TRY003
        if self.entity_type not in self.member_entity_types:
            raise ValueError("winning entity must be a region member")  # noqa: TRY003
        return self


class EvaluationDiagnostics(StrictModel):
    """Carry bounded logical and effective policy evidence."""

    logical_detections: list[LogicalDetection] = Field(max_length=2_048)
    effective_regions: list[EffectiveRegion] = Field(max_length=2_048)
    truncated: bool


class EvaluationSimulation(StrictModel):
    """Describe a local deterministic echo without model transport."""

    type: Literal["deterministic_echo"]
    status: Literal["completed", "skipped"]
    reason: Literal["request_blocked"] | None
    model_called: Literal[False]
    model_response: str | None = Field(max_length=10_485_760)
    user_response: str | None = Field(max_length=10_485_760)
    restored_entity_counts: dict[str, int] = Field(max_length=64)

    @model_validator(mode="after")
    def validate_status(self) -> EvaluationSimulation:
        """Keep skipped and completed simulation fields unambiguous."""
        if self.status == "skipped":
            if self.reason != "request_blocked" or self.model_response or self.user_response:
                raise ValueError(  # noqa: TRY003
                    "skipped simulations require only a block reason"
                )
        elif self.reason is not None or self.model_response is None or self.user_response is None:
            raise ValueError(  # noqa: TRY003
                "completed simulations require both response texts"
            )
        if any(count <= 0 or count > 10_000_000 for count in self.restored_entity_counts.values()):
            raise ValueError("restored entity counts are invalid")  # noqa: TRY003
        return self


class StudioPolicyEvaluationValidResponse(StudioAnalyzeResponse):
    """Return detailed model-free evidence for one valid candidate."""

    valid: Literal[True]
    issues: list[PolicyEvaluationIssue] = Field(max_length=0)
    issues_truncated: Literal[False]
    report: PIIReport
    diagnostics: EvaluationDiagnostics
    simulation: EvaluationSimulation


type StudioPolicyEvaluationResponse = Annotated[
    StudioPolicyEvaluationValidResponse | StudioPolicyEvaluationInvalidResponse,
    Field(discriminator="valid"),
]


class ActionParam(StrictModel):
    """Describe one action parameter from the shared registry."""

    name: str
    type: str
    default: str
    description: str
    options: list[str] = Field(default_factory=list)


class ActionDescription(StrictModel):
    """Describe one Studio-visible PII action."""

    name: str
    decision: str
    reversible: bool
    severity: Literal["pass", "info", "warn", "fail"]
    strictness: int = Field(ge=1, le=9)
    params: list[ActionParam] = Field(default_factory=list)
    notes: str


class PolicyResponse(StrictModel):
    """Expose deterministic policy metadata and normalized entity names."""

    api_version: Literal["v1"]
    version: str
    default_action: str
    entities: list[str]
    safety_rules: list[str]


AnalyzeRequest = StudioAnalyzeRequest
AnalyzeResponse = StudioAnalyzeResponse
EvaluateRequest = StudioPolicyEvaluationRequest
EvaluateResponse = StudioPolicyEvaluationResponse
