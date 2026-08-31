"""Tests for the verified Studio session endpoint."""

from k8s_stack_studio.controllers.session import SessionResponse, get_session
from k8s_stack_studio.lib.auth import StudioPrincipal


def test_session_returns_sorted_verified_authorization_claims() -> None:
    """Expose only claims already validated by the API middleware."""
    principal = StudioPrincipal(
        subject="user-1",
        roles=frozenset({"studio-user", "pii-admin"}),
        agentgateway_roles=frozenset({"model:remote/example:invoke", "llm:invoke"}),
        profile={"email": "user@example.test"},
    )

    assert get_session(principal) == SessionResponse(
        subject="user-1",
        realm_roles=["pii-admin", "studio-user"],
        agentgateway_roles=["llm:invoke", "model:remote/example:invoke"],
    )
