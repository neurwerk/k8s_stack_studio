"""Strict Pydantic v2 models for the versioned PII Engine Studio contract."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


class StrictModel(BaseModel):
    """Reject undocumented fields at the Studio/engine boundary."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class TextPart(StrictModel):
    """Represent one supported text content part."""

    type: Literal["text"]
    text: str = Field(min_length=1, max_length=100_000)


class AttachmentPart(BaseModel):
    """Mirror attachment blocks accepted only for engine policy rejection."""

    model_config = ConfigDict(extra="allow", str_strip_whitespace=False)

    type: Literal[
        "image_url",
        "input_audio",
        "file",
        "input_image",
        "input_file",
        "image",
        "audio",
        "resource",
        "resource_link",
    ]


type MessageContent = (
    Annotated[str, Field(max_length=100_000)]
    | Annotated[list[TextPart | AttachmentPart], Field(max_length=64)]
)


class FunctionCall(StrictModel):
    """Represent a supported function call and JSON arguments."""

    name: str = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_.:-]+$")
    arguments: JsonValue = ""


class ToolCall(StrictModel):
    """Represent an assistant tool call."""

    id: str = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_.:-]+$")
    type: Literal["function"]
    function: FunctionCall


class ToolFunction(StrictModel):
    """Describe a supported function tool."""

    name: str = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_.:-]+$")
    description: str | None = Field(default=None, max_length=4_000)
    parameters: dict[str, JsonValue] | None = None


class ToolDefinition(StrictModel):
    """Describe one supported OpenAI function tool."""

    type: Literal["function"]
    function: ToolFunction


class ChatMessage(StrictModel):
    """Represent a supported chat message and tool result."""

    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: MessageContent | None = None
    name: str | None = Field(default=None, max_length=256)
    tool_calls: list[ToolCall] = Field(default_factory=list, max_length=32)
    tool_call_id: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def validate_role_fields(self) -> ChatMessage:
        """Require fields that distinguish assistant calls and tool results."""
        if self.role == "tool" and not self.tool_call_id:
            raise ValueError("tool messages require tool_call_id")  # noqa: TRY003
        if self.tool_calls and self.role != "assistant":
            raise ValueError("tool_calls are only supported on assistant messages")  # noqa: TRY003
        if self.role == "assistant" and self.content is None and not self.tool_calls:
            raise ValueError("assistant messages require content or tool_calls")  # noqa: TRY003
        return self


class OpenAIChatRequest(StrictModel):
    """Bound an OpenAI chat request to the engine's v1/studio contract."""

    model: str = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_./:-]+$")
    messages: list[ChatMessage] = Field(min_length=1, max_length=256)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    max_tokens: int | None = Field(default=None, ge=1, le=1_000_000)
    stream: bool = False
    n: int | None = Field(default=None, ge=1, le=16)
    stop: str | list[str] | None = None
    tools: list[ToolDefinition] = Field(default_factory=list, max_length=128)
    tool_choice: Literal["none", "auto", "required"] | dict[str, JsonValue] | None = None
    response_format: dict[str, JsonValue] | None = None
    user: str | None = Field(default=None, max_length=256)


class ResponseTextPart(StrictModel):
    """Represent one supported Responses API text part."""

    type: Literal["input_text", "output_text"]
    text: str = Field(min_length=1, max_length=100_000)


class ResponseMessage(StrictModel):
    """Represent one Responses API message item."""

    type: Literal["message"] = "message"
    role: Literal["system", "developer", "user", "assistant"]
    content: list[ResponseTextPart | AttachmentPart] = Field(min_length=1, max_length=64)


class ResponseFunctionCall(StrictModel):
    """Represent one Responses API function call."""

    type: Literal["function_call"]
    call_id: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_.:-]+$")
    arguments: JsonValue


class ResponseFunctionOutput(StrictModel):
    """Represent nested tool output returned to a model."""

    type: Literal["function_call_output"]
    call_id: str = Field(min_length=1, max_length=256)
    output: JsonValue


type ResponseInputItem = ResponseMessage | ResponseFunctionCall | ResponseFunctionOutput
type ResponseInput = (
    Annotated[str, Field(max_length=100_000)]
    | Annotated[list[ResponseInputItem], Field(min_length=1, max_length=256)]
)


class OpenAIResponsesRequest(StrictModel):
    """Bound a supported OpenAI Responses request."""

    model: str = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_./:-]+$")
    input: ResponseInput
    instructions: str | None = Field(default=None, max_length=100_000)
    tools: list[ToolDefinition] = Field(default_factory=list, max_length=128)
    tool_choice: Literal["none", "auto", "required"] | dict[str, JsonValue] | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    max_output_tokens: int | None = Field(default=None, ge=1, le=1_000_000)
    stream: bool = False
    previous_response_id: str | None = Field(default=None, max_length=256)
    user: str | None = Field(default=None, max_length=256)


class McpContent(StrictModel):
    """Represent a supported MCP text content block."""

    type: Literal["text"]
    text: str = Field(min_length=1, max_length=100_000)


class McpParams(StrictModel):
    """Represent bounded MCP arguments and tool-result payloads."""

    name: str | None = Field(default=None, max_length=256)
    arguments: JsonValue | None = None
    content: list[McpContent | AttachmentPart] = Field(default_factory=list, max_length=128)
    result: JsonValue | None = None


class McpRequest(StrictModel):
    """Bound a supported MCP JSON-RPC request."""

    jsonrpc: Literal["2.0"]
    id: str | int
    method: str = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_./:-]+$")
    params: McpParams


type SupportedRequest = OpenAIChatRequest | OpenAIResponsesRequest | McpRequest


class StudioAnalyzeRequest(StrictModel):
    """Wrap a supported request and optional engine-validated policy preview."""

    request: SupportedRequest
    policy: dict[str, JsonValue] | None = Field(default=None, max_length=16)


class StudioPolicyEvaluationRequest(StrictModel):
    """Accept a request sample and an unvalidated bounded policy candidate."""

    request: SupportedRequest
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
