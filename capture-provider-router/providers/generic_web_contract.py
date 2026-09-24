"""Guanlan-owned Generic Web Provider request/result types."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Protocol


class FailureClass(StrEnum):
    INVALID_URL = "invalid_url"
    DNS_ERROR = "dns_error"
    NETWORK_ERROR = "network_error"
    TIMEOUT = "timeout"
    REDIRECT_ERROR = "redirect_error"
    HTTP_4XX = "http_4xx"
    HTTP_429 = "http_429"
    HTTP_5XX = "http_5xx"
    UNSUPPORTED_CONTENT_TYPE = "unsupported_content_type"
    EMPTY_HTML = "empty_html"
    NO_READABLE_CONTENT = "no_readable_content"
    JAVASCRIPT_REQUIRED = "javascript_required"
    AUTHENTICATION_REQUIRED = "authentication_required"
    CHALLENGE_PAGE = "challenge_page"
    PROVIDER_ERROR = "provider_error"


@dataclass(frozen=True)
class GenericWebCaptureRequest:
    capture_request_id: str
    url: str
    requested_at: str
    timeout_seconds: float = 30.0
    language_hint: str | None = None
    allow_private_test: bool = False


@dataclass(frozen=True)
class GenericWebPayload:
    requested_url: str
    final_url: str | None = None
    http_status: int | None = None
    response_headers_subset: dict[str, str] = field(default_factory=dict)
    raw_html: bytes | None = None
    readable_text: str | None = None
    title: str | None = None
    author: str | None = None
    published_at: str | None = None
    extraction_method: str = "static_html_v1"
    warnings: tuple[str, ...] = ()
    failure_class: str | None = None
    failure_detail: str | None = None
    redirect_count: int = 0
    handoff_kind: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.failure_class is None

    def serializable(self) -> dict:
        return asdict(self)


class GenericWebProvider(Protocol):
    def fetch(self, request: GenericWebCaptureRequest) -> GenericWebPayload: ...
