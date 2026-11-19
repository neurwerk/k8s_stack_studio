"""One bounded collector run; suitable for a fifteen-minute CronJob."""

from __future__ import annotations

import asyncio
import logging
import ssl
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import asyncpg
import httpx
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from studio_collector import store
from studio_collector.calendar import hours
from studio_collector.mcp_events import McpEventSource
from studio_collector.models import Kind, SourceError, StoreError
from studio_collector.pricing import Catalogue
from studio_collector.sources import LlmSource

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Explicit collector connections; secrets are never logged."""

    model_config = SettingsConfigDict(env_prefix="STUDIO_COLLECTOR_")
    postgres_host: str
    postgres_port: int = 5432
    postgres_database: str = "studio_usage"
    postgres_user: str = "studio_usage_collector"
    postgres_password: SecretStr
    timezone: str = "Europe/Berlin"
    agentgateway_url: str
    opensearch_url: str
    opensearch_user: str = "studio-logs-read"
    opensearch_password: SecretStr
    opensearch_ca_cert: Path
    overlap_hours: int = Field(default=24, ge=1, le=168)
    pricing_file: Path


def validate_prices(catalogue: Catalogue, timezone: ZoneInfo) -> None:
    """Require dated prices to align to this reporting calendar's hourly buckets."""
    for account in catalogue.accounts:
        for price in account.prices:
            instant = price.effective_from
            if next(hours(instant, instant + timedelta(seconds=1), timezone))[0] != instant:
                raise ValueError("Price must start on a reporting hour")  # noqa: TRY003


async def collect(settings: Settings, *, initialize_only: bool = False) -> bool:
    """Serialize before source reads, then update sources independently."""
    timezone = ZoneInfo(settings.timezone)
    # JSON is also valid YAML; chart ConfigMaps serialize the client YAML as JSON.
    catalogue = Catalogue.model_validate_json(settings.pricing_file.read_text())
    validate_prices(catalogue, timezone)
    connection = await asyncpg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_database,
        user=settings.postgres_user,
        password=settings.postgres_password.get_secret_value(),
        timeout=10,
        command_timeout=60,
    )
    try:
        await store.initialize(connection, timezone)
        if initialize_only:
            return True
        if not await connection.fetchval("SELECT pg_try_advisory_lock($1)", store.WRITER_LOCK):
            logger.info("Another collector owns the writer lock")
            return True
        now = datetime.now(UTC).replace(microsecond=0)
        async with (
            httpx.AsyncClient(timeout=45, trust_env=False) as client,
            httpx.AsyncClient(
                timeout=45,
                trust_env=False,
                verify=ssl.create_default_context(cafile=settings.opensearch_ca_cert),
                auth=(settings.opensearch_user, settings.opensearch_password.get_secret_value()),
            ) as search,
        ):
            sources: dict[Kind, LlmSource | McpEventSource] = {
                "llm": LlmSource(client, settings.agentgateway_url),
                "mcp": McpEventSource(search, settings.opensearch_url),
            }
            success = True
            for kind, source in sources.items():
                activation = await store.metadata(connection, timezone, kind)
                # Retry collection gaps, as well as late events in the overlap.
                previous = await connection.fetchval(
                    "SELECT COALESCE(completed_through,succeeded_at) "
                    "FROM usage_source_status WHERE kind=$1",
                    kind,
                )
                start = max(
                    activation,
                    min(previous or activation, now - timedelta(hours=settings.overlap_hours)),
                )
                source_failed = False
                for bucket_start, bucket_end in hours(start, now, timezone):
                    until = min(bucket_end, now)
                    try:
                        rows = await source.collect(max(bucket_start, activation), until)
                        pricing = None
                        if kind == "mcp":
                            pricing = await store.pricing_for(connection, bucket_start, catalogue)
                            rows = [pricing.apply(row, bucket_start) for row in rows]
                        await store.replace(
                            connection,
                            kind,
                            bucket_start,
                            bucket_end,
                            until,
                            timezone,
                            rows,
                            pricing,
                        )
                        await connection.execute(
                            "UPDATE usage_source_status SET completed_through="
                            "GREATEST(completed_through,$2) WHERE kind=$1",
                            kind,
                            until,
                        )
                    except (SourceError, asyncpg.PostgresError, OSError, TimeoutError):
                        logger.warning("%s bucket unavailable: %s", kind, bucket_start.isoformat())
                        source_failed = True
                        break  # Keep the watermark before the first missing bucket.
                if source_failed:
                    await store.failed(connection, kind)
                    success = False
            return success
    finally:
        await connection.close()


def main() -> None:
    """Exit unsuccessfully on missing data, with no private error payloads."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        settings = Settings()  # ty: ignore[missing-argument] -- values come from the environment
        succeeded = asyncio.run(collect(settings, initialize_only="--initialize" in sys.argv))
    except (ValueError, StoreError, asyncpg.PostgresError, OSError, TimeoutError):
        # Error details can contain credentials or private source responses.
        logger.error("Collector failed; check configuration and source availability")  # noqa: TRY400
        raise SystemExit(1) from None
    raise SystemExit(0 if succeeded else 1)
