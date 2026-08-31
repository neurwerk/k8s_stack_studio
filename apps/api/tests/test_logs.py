"""Tests for the logs viewer — OpenSearch query building and role enforcement."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from k8s_stack_studio.lib.auth import StudioPrincipal
from k8s_stack_studio.lib.dependencies import require_role
from k8s_stack_studio.lib.opensearch import OpenSearchClient


def _request_with_roles(roles: list[str]) -> MagicMock:
    request = MagicMock()
    request.scope = {
        "user": StudioPrincipal(
            subject="user-1",
            roles=frozenset(roles),
            agentgateway_roles=frozenset(),
            profile={},
        )
    }
    return request


# ── Query building ────────────────────────────────────────────────────────────


def test_build_search_body_defaults() -> None:
    body = OpenSearchClient.build_search_body()
    assert body["size"] == 100
    assert body["sort"] == [{"@timestamp": {"order": "desc"}}]
    assert body["query"] == {"bool": {"must": [{"match_all": {}}]}}


def test_build_search_body_with_query() -> None:
    body = OpenSearchClient.build_search_body(q="error AND timeout")
    assert body["query"]["bool"]["must"] == [
        {"query_string": {"query": "error AND timeout", "default_field": "log"}}
    ]
    assert "filter" not in body["query"]["bool"]


def test_build_search_body_with_filters() -> None:
    body = OpenSearchClient.build_search_body(namespace="monitor-opensearch", pod="os-0", size=50)
    assert body["size"] == 50
    assert body["query"]["bool"]["filter"] == [
        {"term": {"kubernetes.namespace_name.keyword": "monitor-opensearch"}},
        {"term": {"kubernetes.pod_name.keyword": "os-0"}},
    ]


# ── Role enforcement ──────────────────────────────────────────────────────────


def test_require_role_allows_opensearch_admin() -> None:
    check = require_role("opensearch-admin")
    check(_request_with_roles(["opensearch-admin"]))  # must not raise


def test_require_role_rejects_missing_role() -> None:
    check = require_role("opensearch-admin")
    with pytest.raises(HTTPException) as exc_info:
        check(_request_with_roles(["keycloak-admin"]))
    assert exc_info.value.status_code == 403


def test_require_role_rejects_without_token() -> None:
    request = MagicMock()
    request.scope = {}
    check = require_role("opensearch-admin")
    with pytest.raises(HTTPException) as exc_info:
        check(request)
    assert exc_info.value.status_code == 401
