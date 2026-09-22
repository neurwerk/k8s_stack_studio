"""Collector-owned log classification and search vocabulary."""

from typing import Literal

LogLevel = Literal["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "FATAL", "UNKNOWN"]
FailureType = Literal[
    "timeout",
    "connection_error",
    "upstream_error",
    "processing_error",
    "background_error",
    "upload_error",
    "document_error",
    "stream_error",
    "application_error",
]
