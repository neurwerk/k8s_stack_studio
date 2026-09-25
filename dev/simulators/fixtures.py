"""Synthetic, bounded example responses for Studio's upstream HTTP contracts."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path


def _demo_principals() -> tuple[str, str]:
    """Use the same local-only Keycloak subjects as the real dev login."""
    path = Path("/demo-users/usage-users.json")
    if path.is_file():
        with path.open() as stream:
            users = json.load(stream)
        return users["developer"], users["viewer"]
    return "demo-developer", "demo-viewer"


def usage_summary(payload: dict) -> dict:
    """Return grouped summaries aligned to the caller's UTC bucket boundaries."""
    start = datetime.fromisoformat(payload["timeRange"]["from"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(payload["timeRange"]["to"].replace("Z", "+00:00"))
    if not start < end:
        raise ValueError("bounded time range required")
    attributes = payload.get("filters", {}).get("attributes", {})
    if not isinstance(attributes, dict) or set(attributes) - {"agentgateway.user"}:
        raise ValueError("unsupported filters")
    selected_user = attributes.get("agentgateway.user")
    dimensions = payload.get("groupBy")
    by_model = dimensions == [{"field": "requestModel"}]
    by_user = dimensions == [{"field": "attributes", "key": "agentgateway.user"}]
    if dimensions != [] and not by_model and not by_user:
        raise ValueError("unsupported grouping")
    seconds = min(
        int(payload.get("bucketSeconds", 86400)),
        max(1, int((end - start).total_seconds())),
    )
    if seconds < 1:
        raise ValueError("invalid bucket duration")
    groups: dict[str, dict] = {}
    buckets: dict[tuple[datetime, str], dict] = {}
    # Synthetic usage belongs to the two actual local Keycloak subjects.
    today = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
    for person, user_id in enumerate(_demo_principals()):
        if selected_user is not None and selected_user != user_id:
            continue
        for day in range(person, 28, 3 + person * 3):
            at = today - timedelta(days=day)
            if not start <= at < end:
                continue
            model = "demo-model" if day % 2 else "sample-model"
            group_key = user_id if by_user else model if by_model else "all"
            group = (
                {"agentgateway.user": user_id}
                if by_user
                else {"requestModel": model}
                if by_model
                else {}
            )
            tokens = 120 + day * 4 + person * 40
            row = groups.setdefault(
                group_key,
                {"group": group, "requests": 0, "totalTokens": 0, "cost": 0.0},
            )
            row["requests"] += 1
            row["totalTokens"] += tokens
            row["cost"] += 0.002
            if by_model:
                bucket_start = start + timedelta(
                    seconds=((at - start) // timedelta(seconds=seconds)) * seconds
                )
                bucket = buckets.setdefault(
                    (bucket_start, model),
                    {
                        "start": bucket_start.isoformat(),
                        "group": group,
                        "requests": 0,
                        "totalTokens": 0,
                        "cost": 0.0,
                    },
                )
                bucket["requests"] += 1
                bucket["totalTokens"] += tokens
                bucket["cost"] += 0.002
    return {
        "bucketSeconds": seconds,
        "groups": list(groups.values()),
        "buckets": [buckets[key] for key in sorted(buckets)],
    }


def policy_actions() -> list[dict]:
    """Provide display metadata; the simulator is not the policy engine."""
    strictness = {
        "pass": 1,
        "mask": 2,
        "hash": 3,
        "encrypt": 4,
        "reversible_replace": 5,
        "replace": 6,
        "redact": 7,
        "reroute": 8,
        "block": 9,
    }
    return [
        {
            "name": action,
            "decision": "pass"
            if action == "pass"
            else "block"
            if action == "block"
            else "reroute"
            if action == "reroute"
            else "apply_actions",
            "reversible": action == "reversible_replace",
            "severity": "fail" if action == "block" else "info",
            "strictness": rank,
            "params": [],
            "notes": "Synthetic local action metadata.",
        }
        for action, rank in strictness.items()
    ]


def policy_result(payload: dict, *, evaluate: bool) -> dict:
    """Illustrate only literal sample emails; never claim general PII detection."""
    request = payload.get("request", {})
    if not isinstance(request, dict):
        raise ValueError("request must be an object")
    policy = payload.get("policy") or {}
    pii = policy.get("pii", {}) if isinstance(policy, dict) else {}
    action = pii.get("defaultAction", "mask") if isinstance(pii, dict) else "mask"
    messages = request.get("messages", [])
    text = (
        messages[0].get("content")
        if isinstance(messages, list) and messages and isinstance(messages[0], dict)
        else None
    )
    marker = next(
        (
            email
            for email in ("john@example.com", "a@example.com")
            if isinstance(text, str) and email in text
        ),
        None,
    )
    detected = marker is not None
    if action not in ("mask", "block", "pass"):
        if evaluate:
            return {
                "api_version": "v1",
                "valid": False,
                "issues": [
                    {
                        "stage": "compile",
                        "path": ["pii", "defaultAction"],
                        "code": "unsupported_local_sample",
                        "message": "Local sample supports only mask, block and pass for demo emails.",
                    }
                ],
                "issues_truncated": False,
            }
        raise ValueError("unsupported local sample action")
    blocked = detected and action == "block"
    transformed = detected and action == "mask"
    result_request = None if blocked else dict(request)
    if result_request is not None and transformed:
        result_request["messages"] = [
            dict(messages[0], content=text.replace(marker, "*" * len(marker))),
            *messages[1:],
        ]
    result = {
        "api_version": "v1",
        "decision": "block" if blocked else "apply_actions" if transformed else "pass",
        "entities": ["EMAIL_ADDRESS"] if detected else [],
        "entity_counts": {"EMAIL_ADDRESS": 1} if detected else {},
        "applied_actions": ["mask"] if transformed else [],
        "remote_allowed": not blocked,
        "request": result_request,
        "analysis": {
            "source": "current_request",
            "scan_performed": True,
            "duration_ms": 0,
            "overlap_count": 0,
            "overlap_resolution": "strictest_action",
            "policy_version": "synthetic-dev",
            "text_leaf_count": 1 if isinstance(text, str) else 0,
            "cached_decision_applied": False,
        },
        "notices": {
            "request": ["Local sample only: not a real policy evaluation."],
            "response": [],
        },
    }
    if not evaluate:
        return result
    detections = []
    regions = []
    rows = []
    if detected:
        index = text.index(marker)
        span = {
            "path": ["messages", 0, "content"],
            "start": index,
            "end": index + len(marker),
            "entity_type": "EMAIL_ADDRESS",
            "score": 1.0,
            "source": "deterministic",
        }
        detections.append(
            {**span, "configured_action": action, "resolved_action": action}
        )
        regions.append(
            {
                **span,
                "action": action,
                "member_entity_types": ["EMAIL_ADDRESS"],
                "overlap": False,
            }
        )
        rows.append(
            {
                "entity_type": "EMAIL_ADDRESS",
                "action": action,
                "detected_count": 1,
                "transformed_count": int(transformed),
                "unique_transformed_count": int(transformed),
            }
        )
    simulated_text = (
        "[SIMULATED - NO MODEL CALLED] "
        + (
            result_request["messages"][0]["content"]
            if isinstance(text, str) and result_request
            else "Sample response"
        )
        if not blocked
        else None
    )
    result.update(
        {
            "valid": True,
            "issues": [],
            "issues_truncated": False,
            "report": {"rows": rows},
            "diagnostics": {
                "logical_detections": detections,
                "effective_regions": regions,
                "truncated": False,
            },
            "simulation": {
                "type": "deterministic_echo",
                "status": "skipped" if blocked else "completed",
                "reason": "request_blocked" if blocked else None,
                "model_called": False,
                "model_response": simulated_text,
                "user_response": simulated_text,
                "restored_entity_counts": {},
            },
        }
    )
    return result


def search_logs(payload: dict) -> dict:
    """Apply Studio's search filters to a few synthetic recent pod records."""
    now = datetime.now(UTC)
    records = [
        ("INFO", None, "Studio dev environment started", "studio-dev", "studio-api"),
        (
            "ERROR",
            "timeout",
            "Synthetic upstream timeout while processing demo request",
            "studio-dev",
            "demo-worker",
        ),
        ("WARNING", None, "Synthetic login retry", "studio-dev", "keycloak"),
    ]
    filters = payload.get("query", {}).get("bool", {}).get("filter", [])
    must = payload.get("query", {}).get("bool", {}).get("must", [])
    text = next(
        (
            item["query_string"]["query"].lower()
            for item in must
            if "query_string" in item
        ),
        None,
    )
    hits = []
    for offset, (level, failure, message, namespace, pod) in enumerate(records):
        timestamp = now - timedelta(minutes=offset * 4)
        source = {
            "@timestamp": timestamp.isoformat(timespec="milliseconds").replace(
                "+00:00", "Z"
            ),
            "log": message,
            "kubernetes": {
                "namespace_name": namespace,
                "pod_name": pod,
                "container_name": pod,
            },
            "stack_log": {"level": level},
        }
        if failure:
            source["stack_log"]["failure_type"] = failure
        if text and text not in message.lower():
            continue
        matches = True
        for item in filters:
            for field, value in item.get("term", {}).items():
                parts = field.removesuffix(".keyword").split(".")
                found = source
                for part in parts:
                    found = found.get(part, {}) if isinstance(found, dict) else {}
                if found != value:
                    matches = False
            for field, bounds in item.get("range", {}).items():
                if field == "@timestamp" and not (
                    datetime.fromisoformat(bounds["gte"])
                    <= timestamp
                    <= datetime.fromisoformat(bounds["lte"])
                ):
                    matches = False
            if (
                "must_not" in item.get("bool", {})
                and level
                in item["bool"]["must_not"][0]["terms"]["stack_log.level.keyword"]
            ):
                matches = False
        if matches:
            hits.append({"_index": "fluent-bit-local", "_source": source})
    start = max(0, int(payload.get("from", 0)))
    size = max(0, int(payload.get("size", 100)))
    return {
        "hits": {
            "total": {"value": len(hits), "relation": "eq"},
            "hits": hits[start : start + size],
        }
    }
