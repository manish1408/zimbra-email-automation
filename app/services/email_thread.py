from __future__ import annotations

import html as html_module
import re
from typing import Any

# Common reply/forward separators in plain-text and HTML-derived bodies
_QUOTE_MARKERS = [
    re.compile(r"\n-{3,}\s*Original Message\s*-{3,}", re.IGNORECASE),
    re.compile(r"\nOn .+ wrote:\s*\n", re.IGNORECASE | re.DOTALL),
    re.compile(r"\nFrom:\s.+?\n(?:Sent|Date):\s.+?\n", re.IGNORECASE | re.DOTALL),
    re.compile(r"\n_{10,}\n"),
    re.compile(r"\nBegin forwarded message:\s*\n", re.IGNORECASE),
]

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+", re.IGNORECASE)
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)[\s.-]?|\d{2,4}[\s.-])\d{3,4}[\s.-]?\d{3,4}(?!\d)"
)
_URL_RE = re.compile(r"https?://[^\s<>\"]+|www\.[^\s<>\"]+", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MIN_READABLE_CHARS = 40


def _looks_like_html(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.startswith("<!DOCTYPE") or stripped.startswith("<html"):
        return True
    return bool(_HTML_TAG_RE.search(stripped)) and stripped.count("<") >= 2


def html_to_text(html: str) -> str:
    """Convert HTML email bodies to plain text for LLM analysis."""
    if not html or not html.strip():
        return ""
    text = re.sub(
        r"<(script|style|head)[^>]*>[\s\S]*?</\1>",
        "",
        html,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</(?:p|div|tr|li|h[1-6])>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_module.unescape(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_message_text(message: dict[str, Any]) -> str:
    """Best-effort plain text from stored body or inbox fragment."""
    body = (message.get("body") or "").strip()
    fragment = (message.get("fragment") or "").strip()

    if body:
        if _looks_like_html(body):
            body = html_to_text(body)
        if len(body) >= len(fragment):
            return body
    return fragment or body


def message_needs_full_body(message: dict[str, Any]) -> bool:
    """True when we should fetch full content from Zimbra before LLM analysis."""
    return len(extract_message_text(message).strip()) < _MIN_READABLE_CHARS


def normalize_subject(subject: str | None) -> str:
    if not subject:
        return ""
    value = subject.strip()
    while True:
        lower = value.lower()
        if lower.startswith("re:"):
            value = value[3:].strip()
        elif lower.startswith("fwd:"):
            value = value[4:].strip()
        elif lower.startswith("fw:"):
            value = value[3:].strip()
        else:
            break
    return value


def split_reply_body(body: str | None) -> tuple[str, str]:
    """Split an email body into the current message and quoted history."""
    if not body or not body.strip():
        return "", ""

    text = body.replace("\r\n", "\n").strip()
    earliest = len(text)
    for pattern in _QUOTE_MARKERS:
        match = pattern.search(text)
        if match and match.start() < earliest:
            earliest = match.start()

    if earliest < len(text):
        current = text[:earliest].strip()
        history = text[earliest:].strip()
        return current, history

    # Fallback: split at first long quoted block (> prefix)
    quoted_lines: list[str] = []
    current_lines: list[str] = []
    in_quote = False
    for line in text.split("\n"):
        if line.strip().startswith(">"):
            in_quote = True
            quoted_lines.append(line)
        elif in_quote and not line.strip():
            quoted_lines.append(line)
        elif in_quote:
            quoted_lines.append(line)
        else:
            current_lines.append(line)

    if quoted_lines and current_lines:
        return "\n".join(current_lines).strip(), "\n".join(quoted_lines).strip()

    return text, ""


def redact_user_details(text: str) -> str:
    """Remove/redact personal identifiers from email text."""
    if not text:
        return ""
    redacted = _EMAIL_RE.sub("[EMAIL]", text)
    redacted = _PHONE_RE.sub("[PHONE]", redacted)
    redacted = _URL_RE.sub("[LINK]", redacted)
    redacted = re.sub(
        r"\b(?:From|To|Cc|Sent by|Contact):\s*[^\n]+",
        lambda m: m.group(0).split(":")[0] + ": [REDACTED]",
        redacted,
        flags=re.IGNORECASE,
    )
    return redacted.strip()


def build_thread_context(
    message: dict[str, Any],
    related_messages: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    """Build redacted current + history text for summarization."""
    body = extract_message_text(message)
    current_text, inline_history = split_reply_body(body)

    history_parts: list[str] = []
    if related_messages:
        for item in related_messages:
            if str(item.get("id")) == str(message.get("id")):
                continue
            part_body = extract_message_text(item)
            _, quoted = split_reply_body(part_body)
            snippet = part_body if not quoted else quoted
            if snippet.strip():
                history_parts.append(snippet.strip())

    if inline_history:
        history_parts.append(inline_history)

    return {
        "subject": redact_user_details(message.get("subject") or "(no subject)"),
        "current_text": redact_user_details(current_text),
        "history_text": redact_user_details("\n\n---\n\n".join(history_parts)),
    }
