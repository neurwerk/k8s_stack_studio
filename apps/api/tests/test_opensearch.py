"""Tests for OpenSearchClient."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from k8s_stack_studio.config.settings import Settings
from k8s_stack_studio.lib.opensearch import OpenSearchClient


@pytest.fixture
def os_settings() -> Settings:
    """Minimal settings for OpenSearch tests."""
    return Settings(
        opensearch_url="https://os:9200",
        opensearch_user="user",
        opensearch_password="pass",
        opensearch_ca_cert="",
        keycloak_server_url="http://kc:80",
        keycloak_realm="r",
        keycloak_client_id="c",
    )


def test_init_without_client(os_settings: Settings) -> None:
    """Init without an injected client keeps TLS verification enabled."""
    client = OpenSearchClient(settings=os_settings)
    assert client._base == "https://os:9200"
    assert client._auth == ("user", "pass")
    assert client._client is None
    assert client._verify is True


def test_init_with_client(os_settings: Settings) -> None:
    """Init with a shared httpx client stores the reference."""
    mock = MagicMock(spec=httpx.AsyncClient)
    client = OpenSearchClient(settings=os_settings, client=mock)
    assert client._client is mock


@pytest.mark.asyncio
async def test_search_logs_with_shared_client(os_settings: Settings) -> None:
    """search_logs uses the shared client when injected."""
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {
        "hits": {
            "total": {"value": 1},
            "hits": [
                {
                    "_index": "fluent-bit-2026.08",
                    "_source": {
                        "@timestamp": "2026-08-01T00:00:00Z",
                        "log": "hello",
                        "kubernetes": {
                            "namespace_name": "ns",
                            "pod_name": "pod",
                            "container_name": "ctr",
                        },
                    },
                }
            ],
        },
    }

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_resp)

    client = OpenSearchClient(settings=os_settings, client=mock_client)
    result = await client.search_logs(q="hello")

    assert result["total"] == 1
    assert result["hits"][0]["log"] == "hello"
    assert result["hits"][0]["namespace"] == "ns"
    mock_client.post.assert_called_once()


@pytest.mark.asyncio
async def test_search_logs_fallback_ignores_proxy_environment(os_settings: Settings) -> None:
    """The ad-hoc fallback preserves the isolated OpenSearch trust boundary."""
    response = MagicMock(spec=httpx.Response)
    response.raise_for_status.return_value = None
    response.json.return_value = {"hits": {"total": {"value": 0}, "hits": []}}
    fallback = MagicMock(spec=httpx.AsyncClient)
    fallback.__aenter__ = AsyncMock(return_value=fallback)
    fallback.__aexit__ = AsyncMock(return_value=None)
    fallback.post = AsyncMock(return_value=response)

    with patch(
        "k8s_stack_studio.lib.opensearch.httpx.AsyncClient", return_value=fallback
    ) as constructor:
        await OpenSearchClient(settings=os_settings).search_logs()

    constructor.assert_called_once_with(
        timeout=httpx.Timeout(15.0),
        verify=True,
        auth=("user", "pass"),
        trust_env=False,
    )
