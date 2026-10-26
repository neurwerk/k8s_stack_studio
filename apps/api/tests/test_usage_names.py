from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import httpx
import pytest
from starlette.requests import Request

from k8s_stack_studio.lib import usage_names
from k8s_stack_studio.lib.auth import StudioPrincipal
from k8s_stack_studio.models.usage import (
    UsagePeriod,
    UsagePersonSources,
    UsageSource,
    UsageSourcesResponse,
)


def sources(count=1):
    return UsageSourcesResponse(
        timezone="UTC",
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 1),
        apps=[],
        credentials=[],
        people=[
            UsagePersonSources(
                user_id="self",
                total=UsagePeriod(requests=count, total_tokens=count * 10),
                apps=[UsageSource(id="studio", requests=count, total_tokens=count * 10)],
                credentials=[
                    UsageSource(id=f"key-{index:05}", kind="personal", requests=1, total_tokens=10)
                    for index in range(count)
                ],
            )
        ],
    )


def usage_snapshot(result):
    return [
        (
            person.user_id,
            person.total.model_dump(),
            [
                (
                    row.id,
                    row.kind,
                    row.requests,
                    row.total_tokens,
                    row.cost_usd,
                    row.accounting.model_dump(),
                )
                for row in [*person.apps, *person.credentials]
            ],
        )
        for person in result.people
    ]


@pytest.fixture
def name_request(monkeypatch):
    monkeypatch.setattr(
        usage_names,
        "get_settings",
        lambda: SimpleNamespace(
            keycloak_api_key_bridge_url="http://bridge",
        ),
    )

    def request(client, admin=False):
        return Request(
            {
                "type": "http",
                "headers": [(b"authorization", b"Bearer verified-caller")],
                "app": SimpleNamespace(state=SimpleNamespace(http_client=client)),
                "user": StudioPrincipal(
                    "self", frozenset({"langfuse-admin"} if admin else set()), frozenset(), {}
                ),
            }
        )

    return request


@pytest.mark.parametrize(
    "failure",
    [
        httpx.Response(404),
        httpx.Response(503, text="private-upstream-details"),
        httpx.ReadTimeout("private-upstream-details"),
        httpx.Response(200, text="invalid-json"),
        httpx.Response(200, json={"unexpected": "private-upstream-details"}),
        httpx.Response(
            200,
            json=[
                {
                    "id": "key-00000",
                    "user_id": "self",
                    "kind": "personal",
                    "name": "visible",
                    "secret": "private-upstream-details",
                }
            ],
        ),
        httpx.Response(
            200,
            json=[
                {
                    "id": "key-00000",
                    "user_id": "self",
                    "kind": "personal",
                    "name": 123,
                }
            ],
        ),
    ],
)
async def test_metadata_failure_preserves_usage_and_does_not_leak_names(name_request, failure):
    result = sources()
    before = usage_snapshot(result)

    def upstream(request):
        if isinstance(failure, Exception):
            raise failure
        return failure

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        await usage_names.resolve_usage_key_names(result, name_request(client))
    assert usage_snapshot(result) == before
    assert result.key_name_enrichment.lookup_failed
    assert result.key_name_enrichment.looked_up_keys == 0
    assert result.people[0].credentials[0].name is None
    assert result.people[0].credentials[0].name_status == "not_looked_up"
    assert "private-upstream-details" not in result.model_dump_json()


async def test_unsolicited_metadata_tuples_cannot_name_another_credential(name_request):
    result = sources(2)

    def upstream(request):
        assert request.headers["Authorization"] == "Bearer verified-caller"
        return httpx.Response(
            200,
            json=[
                {"id": "key-00000", "user_id": "self", "kind": "personal", "name": "my-name"},
                {"id": "key-00000", "user_id": "other", "kind": "personal", "name": "foreign-name"},
                {"id": "key-00001", "user_id": "self", "kind": "managed", "name": "wrong-kind"},
                {
                    "id": "unrequested",
                    "user_id": "self",
                    "kind": "personal",
                    "name": "unrequested-name",
                },
            ],
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        await usage_names.resolve_usage_key_names(result, name_request(client))
    first, second = result.people[0].credentials
    assert (first.name, first.name_status) == ("my-name", "resolved")
    assert (second.name, second.name_status) == (None, "unavailable")
    assert result.key_name_enrichment.named_keys == 1
    assert not result.key_name_enrichment.lookup_failed
    assert not any(
        name in result.model_dump_json()
        for name in ("foreign-name", "wrong-kind", "unrequested-name")
    )


@pytest.mark.parametrize("count,successful_batches", [(501, 2), (501, 1), (5001, 10)])
async def test_deduplicated_bounded_lookup_reports_limits_and_keeps_successful_batches(
    name_request,
    count,
    successful_batches,
):
    result = sources(count)
    result.people[0].credentials.append(result.people[0].credentials[0].model_copy(deep=True))
    before = usage_snapshot(result)
    batches = []

    def upstream(request):
        batch = json.loads(request.content)["keys"]
        batches.append(batch)
        if len(batches) > successful_batches:
            return httpx.Response(503)
        return httpx.Response(200, json=[{**entry, "name": "saved-name"} for entry in batch])

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        await usage_names.resolve_usage_key_names(result, name_request(client))
    assert usage_snapshot(result) == before
    references = [
        (entry["id"], entry["user_id"], entry["kind"]) for batch in batches for entry in batch
    ]
    assert len(references) == len(set(references)) == min(count, 5000)
    assert all(0 < len(batch) <= 500 for batch in batches)
    enrichment = result.key_name_enrichment
    expected = min(count, 5000, successful_batches * 500)
    assert enrichment.eligible_keys == count
    assert enrichment.looked_up_keys == enrichment.named_keys == expected
    assert enrichment.limit_reached == (count > 5000)
    assert enrichment.lookup_failed == (successful_batches < len(batches))
    assert result.people[0].credentials[0].name == "saved-name"
    for row in result.people[0].credentials:
        looked_up = int(row.id.removeprefix("key-")) < expected
        assert row.name_status == ("resolved" if looked_up else "not_looked_up")
        assert row.name == ("saved-name" if looked_up else None)


async def test_non_admin_enrichment_never_requests_foreign_managed_or_unknown_owner(name_request):
    result = sources()
    result.people.extend(
        [
            UsagePersonSources(
                user_id="foreign", credentials=[UsageSource(id="foreign", kind="personal")]
            ),
            UsagePersonSources(
                user_id=None, credentials=[UsageSource(id="unowned", kind="personal")]
            ),
        ]
    )
    result.people[0].credentials.append(UsageSource(id="managed", kind="managed"))
    batches = []

    def upstream(request):
        batches.append(json.loads(request.content)["keys"])
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        await usage_names.resolve_usage_key_names(result, name_request(client))
    assert batches == [[{"id": "key-00000", "user_id": "self", "kind": "personal"}]]
    assert result.key_name_enrichment.eligible_keys == 1
    assert all(row.name is None for person in result.people for row in person.credentials)


async def test_admin_enrichment_includes_recorded_service_owner_but_not_unknown_owner(name_request):
    result = sources()
    result.people.extend(
        [
            UsagePersonSources(
                user_id="machine", credentials=[UsageSource(id="managed", kind="managed")]
            ),
            UsagePersonSources(
                user_id=None, credentials=[UsageSource(id="unowned", kind="personal")]
            ),
        ]
    )
    references = []

    def upstream(request):
        references.extend(json.loads(request.content)["keys"])
        return httpx.Response(200, json=[{**entry, "name": "saved-name"} for entry in references])

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        await usage_names.resolve_usage_key_names(result, name_request(client, admin=True))
    assert {tuple(sorted(entry.items())) for entry in references} == {
        tuple(sorted({"id": "key-00000", "user_id": "self", "kind": "personal"}.items())),
        tuple(sorted({"id": "managed", "user_id": "machine", "kind": "managed"}.items())),
    }
    assert result.people[1].credentials[0].name == "saved-name"
    assert result.people[2].credentials[0].name is None
    assert result.people[2].credentials[0].name_status == "not_looked_up"
