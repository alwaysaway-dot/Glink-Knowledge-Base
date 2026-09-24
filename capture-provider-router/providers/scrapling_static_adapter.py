"""The only Guanlan module allowed to import and adapt Scrapling types."""

from __future__ import annotations

import ipaddress
import socket
from importlib.metadata import PackageNotFoundError, version
from typing import Callable
from urllib.parse import urlparse

from .generic_web_contract import FailureClass, GenericWebCaptureRequest, GenericWebPayload
from .web_content_extract import extract, looks_like_challenge, looks_like_js_shell, looks_like_login


SAFE_HEADERS = {"content-type", "content-length", "content-language", "etag", "last-modified", "retry-after"}
HTML_TYPES = {"text/html", "application/xhtml+xml"}


def provider_version() -> str:
    try:
        return version("scrapling")
    except PackageNotFoundError:
        return "unavailable"


def public_target(url: str, allow_private_test: bool = False) -> tuple[bool, str]:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return False, "URL must be absolute http(s) without credentials"
        if allow_private_test:
            return True, "test scope permits local fixture server"
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        for item in addresses:
            address = ipaddress.ip_address(item[4][0])
            if not address.is_global:
                return False, f"non-public address is forbidden: {address}"
        return True, "public target verified"
    except socket.gaierror as error:
        return False, f"dns_error: {error}"
    except (ValueError, OSError) as error:
        return False, str(error)


def default_transport(request: GenericWebCaptureRequest):
    # Keep this import inside the sole provider boundary. No browser is launched.
    from scrapling.fetchers import Fetcher

    return Fetcher.get(
        request.url,
        timeout=request.timeout_seconds,
        retries=1,
        retry_delay=0,
        follow_redirects=True if request.allow_private_test else "safe",
        max_redirects=10,
        impersonate=None,
        stealthy_headers=False,
        headers={"User-Agent": "Guanlan-GenericWeb/1.0 (+single-user-triggered-capture)"},
    )


def classify_transport_error(error: Exception) -> str:
    detail = f"{type(error).__name__}: {error}".lower()
    if "timed out" in detail or "timeout" in detail:
        return FailureClass.TIMEOUT
    if "could not resolve" in detail or "name or service" in detail or "dns" in detail:
        return FailureClass.DNS_ERROR
    if "redirect" in detail or "too many" in detail:
        return FailureClass.REDIRECT_ERROR
    if any(token in detail for token in ("connection", "network", "failed to connect", "curl")):
        return FailureClass.NETWORK_ERROR
    return FailureClass.PROVIDER_ERROR


def response_header_subset(headers: object) -> dict[str, str]:
    try:
        items = dict(headers).items()
    except (TypeError, ValueError):
        return {}
    return {str(key).lower(): str(value) for key, value in items if str(key).lower() in SAFE_HEADERS}


def content_handoff(content_type: str) -> str | None:
    media = content_type.split(";", 1)[0].strip().lower()
    if media == "application/pdf":
        return "pdf"
    for kind in ("audio", "video", "image"):
        if media.startswith(kind + "/"):
            return kind
    return "binary" if media and media not in HTML_TYPES else None


def fetch_static(
    request: GenericWebCaptureRequest,
    transport: Callable[[GenericWebCaptureRequest], object] | None = None,
) -> GenericWebPayload:
    valid, reason = public_target(request.url, request.allow_private_test)
    if not valid:
        failure = FailureClass.DNS_ERROR if reason.startswith("dns_error:") else FailureClass.INVALID_URL
        return GenericWebPayload(requested_url=request.url, failure_class=failure, failure_detail=reason)
    try:
        response = (transport or default_transport)(request)
    except Exception as error:  # External transport errors are normalized at this boundary.
        return GenericWebPayload(
            requested_url=request.url,
            failure_class=classify_transport_error(error),
            failure_detail=f"{type(error).__name__}: {error}"[:500],
        )

    status = int(getattr(response, "status", 0) or 0)
    final_url = str(getattr(response, "url", request.url) or request.url)
    headers = response_header_subset(getattr(response, "headers", {}))
    content_type = headers.get("content-type", "").lower()
    body = bytes(getattr(response, "body", b"") or b"")
    history = getattr(response, "history", []) or []
    base = dict(
        requested_url=request.url,
        final_url=final_url,
        http_status=status or None,
        response_headers_subset=headers,
        redirect_count=len(history),
    )
    if status == 429:
        return GenericWebPayload(**base, failure_class=FailureClass.HTTP_429, failure_detail="HTTP 429")
    if status >= 500:
        return GenericWebPayload(**base, failure_class=FailureClass.HTTP_5XX, failure_detail=f"HTTP {status}")
    if status >= 400:
        raw_preview = body.decode("utf-8", errors="replace")
        if looks_like_challenge(raw_preview, ""):
            failure = FailureClass.CHALLENGE_PAGE
        elif status == 401 or (status == 403 and looks_like_login(raw_preview, "")):
            failure = FailureClass.AUTHENTICATION_REQUIRED
        else:
            failure = FailureClass.HTTP_4XX
        return GenericWebPayload(**base, failure_class=failure, failure_detail=f"HTTP {status}")
    handoff = content_handoff(content_type)
    if handoff:
        return GenericWebPayload(**base, failure_class=FailureClass.UNSUPPORTED_CONTENT_TYPE, failure_detail=content_type or "unknown content type", handoff_kind=handoff)
    if not body:
        return GenericWebPayload(**base, failure_class=FailureClass.EMPTY_HTML, failure_detail="empty response body")
    if not content_type:
        prefix = body[:4096].lower()
        if not any(marker in prefix for marker in (b"<!doctype html", b"<html", b"<body", b"<article", b"<main")):
            return GenericWebPayload(**base, failure_class=FailureClass.UNSUPPORTED_CONTENT_TYPE, failure_detail="missing content type and no HTML signature", handoff_kind="binary")

    charset = "utf-8"
    if "charset=" in content_type:
        charset = content_type.split("charset=", 1)[1].split(";", 1)[0].strip(" \"'") or "utf-8"
    extracted = extract(body, charset)
    readable = extracted["readable_text"]
    raw_text = body.decode(charset, errors="replace")
    if looks_like_challenge(raw_text, readable):
        return GenericWebPayload(**base, raw_html=body, failure_class=FailureClass.CHALLENGE_PAGE, failure_detail="challenge page detected")
    if looks_like_login(raw_text, readable):
        return GenericWebPayload(**base, raw_html=body, failure_class=FailureClass.AUTHENTICATION_REQUIRED, failure_detail="login page detected")
    if looks_like_js_shell(raw_text, readable):
        return GenericWebPayload(**base, raw_html=body, failure_class=FailureClass.JAVASCRIPT_REQUIRED, failure_detail="static response is an application shell")
    if len(readable) < 20:
        return GenericWebPayload(**base, raw_html=body, failure_class=FailureClass.NO_READABLE_CONTENT, failure_detail="no substantive readable content")
    warnings = () if content_type else ("content_type_missing_assumed_html",)
    return GenericWebPayload(
        **base,
        raw_html=body,
        readable_text=readable,
        title=extracted["title"],
        author=extracted["author"],
        published_at=extracted["published_at"],
        warnings=warnings,
    )
