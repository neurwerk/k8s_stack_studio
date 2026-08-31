"""Policy-engine HTTP routes backed by the versioned PII Engine contract."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from k8s_stack_studio.lib.dependencies import (
    get_current_user_id,
    get_pii_engine_client,
    require_role,
)
from k8s_stack_studio.lib.pii_engine import PiiEngineClient
from k8s_stack_studio.models.policy_engine import (
    ActionDescription,
    AnalyzeRequest,
    AnalyzeResponse,
    EvaluateRequest,
    EvaluateResponse,
    PolicyResponse,
)

router = APIRouter(prefix="/api/policy-engine", tags=["policy-engine"])
_PII_ADMIN = Depends(require_role("pii-admin"))


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    request: AnalyzeRequest,
    _user_id: str = Depends(get_current_user_id),
    _pii_admin: None = _PII_ADMIN,
    client: PiiEngineClient = Depends(get_pii_engine_client),
) -> AnalyzeResponse:
    """Analyze a supported request and optional draft policy with the shared core."""
    return await client.analyze(request)


@router.post("/evaluate", response_model=EvaluateResponse)
async def evaluate(
    request: EvaluateRequest,
    _user_id: str = Depends(get_current_user_id),
    _pii_admin: None = _PII_ADMIN,
    client: PiiEngineClient = Depends(get_pii_engine_client),
) -> EvaluateResponse:
    """Evaluate a policy candidate through the dedicated model-free engine path."""
    return await client.evaluate(request)


@router.get("/actions", response_model=list[ActionDescription])
async def actions(
    _user_id: str = Depends(get_current_user_id),
    _pii_admin: None = _PII_ADMIN,
    client: PiiEngineClient = Depends(get_pii_engine_client),
) -> list[ActionDescription]:
    """Return the shared PII action registry."""
    return await client.get_actions()


@router.get("/policy", response_model=PolicyResponse)
async def policy(
    _user_id: str = Depends(get_current_user_id),
    _pii_admin: None = _PII_ADMIN,
    client: PiiEngineClient = Depends(get_pii_engine_client),
) -> PolicyResponse:
    """Return shared policy metadata for the Studio configuration UI."""
    return await client.get_policy()
