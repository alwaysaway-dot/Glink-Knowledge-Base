"""Deterministic HTML metadata and readable-text extraction; no AI operations."""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser


NOISE_TAGS = {"script", "style", "noscript", "svg", "canvas", "nav", "header", "footer", "aside", "form"}
BLOCK_TAGS = {"article", "main", "section", "div", "p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "pre", "br"}
AUTHOR_META = ("author", "article:author", "og:article:author")
PUBLISHED_META = ("article:published_time", "datepublished", "publishdate", "pubdate", "date")


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.meta: dict[str, str] = {}
        self.body_parts: list[str] = []
        self.preferred_parts: list[str] = []
        self.stack: list[str] = []
        self.noise_depth = 0
        self.preferred_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        self.stack.append(tag)
        if tag in NOISE_TAGS:
            self.noise_depth += 1
        if tag in {"article", "main"}:
            self.preferred_depth += 1
        values = {key.lower(): value or "" for key, value in attrs}
        if tag == "meta":
            key = (values.get("name") or values.get("property") or values.get("itemprop") or "").strip().lower()
            content = values.get("content", "").strip()
            if key and content and key not in self.meta:
                self.meta[key] = content
        if tag in BLOCK_TAGS and not self.noise_depth:
            self.body_parts.append("\n")
            if self.preferred_depth:
                self.preferred_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in BLOCK_TAGS and not self.noise_depth:
            self.body_parts.append("\n")
            if self.preferred_depth:
                self.preferred_parts.append("\n")
        if tag in NOISE_TAGS and self.noise_depth:
            self.noise_depth -= 1
        if tag in {"article", "main"} and self.preferred_depth:
            self.preferred_depth -= 1
        if tag in self.stack:
            reverse_index = self.stack[::-1].index(tag)
            del self.stack[len(self.stack) - reverse_index - 1 :]

    def handle_data(self, data: str) -> None:
        if self.noise_depth:
            return
        value = " ".join(data.split())
        if not value:
            return
        if self.stack and self.stack[-1] == "title":
            self.title_parts.append(value)
            return
        self.body_parts.append(value)
        if self.preferred_depth:
            self.preferred_parts.append(value)


def normalize_text(parts: list[str]) -> str:
    value = " ".join(parts)
    value = re.sub(r"[ \t\f\v]+", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return html.unescape(value).strip()


def first_meta(meta: dict[str, str], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = meta.get(key)
        if value:
            return value
    return None


def extract(raw_html: bytes, encoding: str = "utf-8") -> dict:
    text = raw_html.decode(encoding or "utf-8", errors="replace")
    parser = PageParser()
    parser.feed(text)
    preferred = normalize_text(parser.preferred_parts)
    body = normalize_text(parser.body_parts)
    readable = preferred if len(preferred) >= 80 else body
    if not readable:
        # HTMLParser intentionally treats an unclosed <title> as raw text. Keep
        # malformed documents recoverable with a conservative tag-strip fallback.
        fallback = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1\s*>", " ", text)
        readable = normalize_text([re.sub(r"(?s)<[^>]*>", "\n", fallback)])
    title = first_meta(parser.meta, ("og:title", "twitter:title")) or normalize_text(parser.title_parts) or None
    return {
        "readable_text": readable,
        "title": title,
        "author": first_meta(parser.meta, AUTHOR_META),
        "published_at": first_meta(parser.meta, PUBLISHED_META),
    }


def looks_like_login(raw: str, readable: str) -> bool:
    lower = (raw + " " + readable).lower()
    signals = ("login", "sign in", "log in", "登录", "请登录", "password", "用户名")
    return sum(signal in lower for signal in signals) >= 2


def looks_like_challenge(raw: str, readable: str) -> bool:
    lower = (raw + " " + readable).lower()
    signals = ("captcha", "cloudflare", "verify you are human", "人机验证", "安全验证", "challenge-platform")
    return any(signal in lower for signal in signals)


def looks_like_js_shell(raw: str, readable: str) -> bool:
    lower = raw.lower()
    shell_signals = ("id=\"root\"", "id='root'", "id=\"app\"", "id='app'", "__next_data__", "enable javascript")
    return len(readable) < 80 and any(signal in lower for signal in shell_signals) and "<script" in lower
