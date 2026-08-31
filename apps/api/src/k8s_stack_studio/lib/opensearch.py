"""OpenSearch HTTP client — read-only log search for the Studio logs viewer.

Authenticates with the dedicated ``studio-logs-read`` internal user (basic auth,
provisioned by the monitor-opensearch init Job). TLS is verified against the
configured CA cert or the system trust store. Verification can be disabled only
for an explicitly configured loopback development endpoint.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from k8s_stack_studio.config.settings import Settings

_logger = logging.getLogger(__name__)

# Default index pattern — Fluent-Bit ships all pod logs here.
DEFAULT_INDEX = "fluent-bit-*"


class OpenSearchClient:
    """Wraps read-only OpenSearch search calls.

    Uses the shared ``httpx.AsyncClient`` for connection pooling when provided
    (via ``get_opensearch`` dependency), falling back to an ad-hoc client
    created per-request when no shared client is injected.
    """

    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Store connection settings and the optional shared HTTP client."""
        self._base = settings.opensearch_url.rstrip("/")
        self._auth = (settings.opensearch_user, settings.opensearch_password)
        self._client = client
        self._verify = settings.opensearch_tls_verify

    @staticmethod
    def build_search_body(
        q: str | None = None,
        namespace: str | None = None,
        pod: str | None = None,
        size: int = 100,
        index: str = DEFAULT_INDEX,
    ) -> dict[str, Any]:
        """Build the OpenSearch ``_search`` request body.

        - ``q`` becomes a query_string query against the ``log`` field.
        - ``namespace``/``pod`` become exact-match filters on the Fluent-Bit
          kubernetes metadata fields.
        - Results are sorted by ``@timestamp`` descending (newest first).
        """
        must: list[dict[str, Any]] = []
        filters: list[dict[str, Any]] = []

        if q:
            must.append({"query_string": {"query": q, "default_field": "log"}})
        if namespace:
            filters.append({"term": {"kubernetes.namespace_name.keyword": namespace}})
        if pod:
            filters.append({"term": {"kubernetes.pod_name.keyword": pod}})

        bool_query: dict[str, Any] = {"must": must or [{"match_all": {}}]}
        if filters:
            bool_query["filter"] = filters

        return {
            "size": size,
            "sort": [{"@timestamp": {"order": "desc"}}],
            "query": {"bool": bool_query},
            "track_total_hits": True,
        }

    async def search_logs(
        self,
        q: str | None = None,
        namespace: str | None = None,
        pod: str | None = None,
        size: int = 100,
        index: str = DEFAULT_INDEX,
    ) -> dict[str, Any]:
        """Search logs and return ``{"total": int, "hits": [LogEntry...]}``.

        Raises ``httpx.HTTPError`` on connection/HTTP failures — the controller
        maps this to a 502.
        """
        body = self.build_search_body(q=q, namespace=namespace, pod=pod, size=size)
        url = f"{self._base}/{index}/_search"

        if self._client is not None:
            # TLS verified by the shared client (C1); pass basic auth per-request.
            resp = await self._client.post(
                url,
                json=body,
                auth=self._auth,
                timeout=httpx.Timeout(15.0),
            )
        else:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(15.0),
                verify=self._verify,
                auth=self._auth,
                trust_env=False,
            ) as client:
                resp = await client.post(url, json=body)
        resp.raise_for_status()
        data = resp.json()

        hits = []
        for hit in data.get("hits", {}).get("hits", []):
            src = hit.get("_source", {})
            k8s = src.get("kubernetes", {}) or {}
            hits.append(
                {
                    "timestamp": src.get("@timestamp", ""),
                    "log": src.get("log", ""),
                    "namespace": k8s.get("namespace_name", ""),
                    "pod": k8s.get("pod_name", ""),
                    "container": k8s.get("container_name", ""),
                    "index": hit.get("_index", ""),
                }
            )

        total = data.get("hits", {}).get("total", {})
        return {"total": total.get("value", 0), "hits": hits}
