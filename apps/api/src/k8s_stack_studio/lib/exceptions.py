"""Domain exceptions for library-layer code.

Lib code raises these types; controllers map them to HTTP responses.
"""

from __future__ import annotations


class PiiEngineError(Exception):
    """Base exception for PII Engine client failures."""


class PiiEngineUnavailableError(PiiEngineError):
    """PII Engine is unreachable (maps to HTTP 502)."""


class PiiEngineTimeoutError(PiiEngineError):
    """PII Engine request timed out (maps to HTTP 504)."""


class PiiEngineTlsConfigError(ValueError):
    """PII Engine HTTPS is missing workload TLS material."""

    def __init__(self) -> None:
        """Set a safe configuration error message."""
        super().__init__("PII Engine mTLS requires HTTPS and workload TLS paths")


class PiiEngineRequestError(PiiEngineError):
    """PII Engine returned an error status or invalid response."""

    def __init__(self, status_code: int, detail: object) -> None:
        """Store the upstream HTTP status and error detail."""
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"PII Engine {status_code}: {detail}")
