from __future__ import annotations

import httpx
import pytest

from k8s_stack_studio.lib.auth import StudioPrincipal
from tests.test_daily_usage import daily_api as daily_api


def source_group(owner, app, key, kind, *, tokens=0, cost=None, known=None, requests=1):
    return {
        "group": {
            "agentgateway.user": owner,
            "neurwerk.app_id": app,
            "neurwerk.credential_id": key,
            "neurwerk.credential_kind": kind,
            "neurwerk.token_usage_known": known,
            "neurwerk.cost_known": known,
        },
        "requests": requests,
        "totalTokens": tokens,
        "cost": cost,
    }


async def test_person_app_key_and_aggregate_views_conserve_usage_and_evidence(daily_api):
    client, payloads, state = daily_api
    state["principal"] = StudioPrincipal(
        "self", frozenset({"studio-user", "langfuse-admin"}), frozenset(), {}
    )
    state["response"] = httpx.Response(
        200,
        json={
            "groups": [
                source_group(
                    "self", "studio", "first-key", "personal", cost=0, known=True, requests=2
                ),
                source_group("self", "librechat", "first-key", "personal", tokens=7, known=True),
                source_group("self", None, "second-key", "personal", tokens=3, cost=0.25),
                source_group("other", "studio", "other-key", "personal", known=False),
                source_group(
                    "machine", None, "managed-key", "managed", tokens=20, cost=0.1, known=True
                ),
                source_group(None, None, None, None),
            ]
        },
    )
    response = await client.get("/api/usage/sources?start=2026-11-02")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    people = {person["user_id"]: person for person in body["people"]}
    assert set(people) == {"self", "other", "machine", None}
    for dimension in ("apps", "credentials"):
        for metric in ("requests", "total_tokens", "cost_usd"):
            assert sum(row[metric] for row in body[dimension]) == pytest.approx(
                sum(person["total"][metric] for person in people.values())
            )
            for person in people.values():
                assert sum(row[metric] for row in person[dimension]) == pytest.approx(
                    person["total"][metric]
                )
        for person in people.values():
            for metric in ("tokens", "cost_usd"):
                for counter in ("known_records", "total_records", "reported_sum"):
                    assert sum(
                        row["accounting"][metric][counter] for row in person[dimension]
                    ) == pytest.approx(person["total"]["accounting"][metric][counter])
    own = people["self"]
    assert own["total"]["requests"] == 4
    assert own["total"]["total_tokens"] == 10
    assert own["total"]["accounting"]["tokens"]["state"] == "partial"
    assert own["total"]["accounting"]["tokens"]["complete_total"] is None
    assert own["total"]["accounting"]["cost_usd"] == {
        "state": "partial",
        "reported_sum": 0.25,
        "complete_total": None,
        "known_records": 2,
        "total_records": 4,
    }
    first_key = next(key for key in own["credentials"] if key["id"] == "first-key")
    assert first_key["requests"] == 3
    assert first_key["accounting"]["tokens"]["complete_total"] == 7
    known_zero = next(app for app in own["apps"] if app["id"] == "studio")
    assert known_zero["accounting"]["cost_usd"]["complete_total"] == 0
    for metric in ("tokens", "cost_usd"):
        unknown_zero = people["other"]["total"]["accounting"][metric]
        assert unknown_zero["state"] == "unknown" and unknown_zero["complete_total"] is None
    assert people[None]["total"]["requests"] == 1
    assert people["machine"]["credentials"][0]["kind"] == "managed"
    assert "filters" not in payloads[0]


@pytest.mark.parametrize(
    "roles,target,status",
    [
        ({"studio-user"}, "self", 200),
        ({"studio-user"}, "other", 403),
        ({"studio-user"}, None, 403),
        ({"studio-user", "api-key-admin"}, "other", 403),
        ({"studio-user", "langfuse-admin"}, "other", 200),
        ({"studio-user", "langfuse-admin"}, None, 200),
    ],
)
async def test_sources_preserve_self_or_usage_admin_scope(daily_api, roles, target, status):
    client, payloads, state = daily_api
    state["principal"] = StudioPrincipal("self", frozenset(roles), frozenset(), {})
    state["response"] = httpx.Response(200, json={"groups": []})
    route = f"/api/users/{target}/usage/sources" if target else "/api/usage/sources"
    response = await client.get(route)
    assert response.status_code == status
    if status == 403:
        assert payloads == []
    elif target:
        assert payloads[0]["filters"]["attributes"]["agentgateway.user"] == target


async def test_self_sources_reject_conflicting_upstream_principal(daily_api):
    client, _, state = daily_api
    state["response"] = httpx.Response(
        200,
        json={
            "groups": [
                source_group("foreign", "studio", "foreign-key", "personal"),
            ]
        },
    )
    response = await client.get("/api/users/self/usage/sources")
    assert response.status_code == 502
    assert "foreign" not in response.text
