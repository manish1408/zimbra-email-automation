from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

_GKUS_RE = re.compile(r"#?\s*(GKUS\d+)", re.IGNORECASE)


@dataclass
class ReferenceExtractionResult:
    reference: str | None = None
    candidates: list[str] | None = None
    confidence: Literal["high", "low", "none"] = "none"
    source: Literal["current", "history", "none"] = "none"
    ambiguous: bool = False

    def __post_init__(self) -> None:
        if self.candidates is None:
            self.candidates = []


def normalize_reference(raw: str) -> str:
    match = _GKUS_RE.search(raw.strip())
    if not match:
        return raw.strip().upper()
    return match.group(1).upper()


def is_valid_reference(reference: str | None) -> bool:
    if not reference:
        return False
    return bool(re.fullmatch(r"GKUS\d+", reference, re.IGNORECASE))


def extract_references_from_text(text: str) -> list[str]:
    if not text:
        return []
    seen: set[str] = set()
    ordered: list[str] = []
    for match in _GKUS_RE.finditer(text):
        ref = match.group(1).upper()
        if ref not in seen:
            seen.add(ref)
            ordered.append(ref)
    return ordered


def extract_order_reference(
    current_text: str,
    history_text: str = "",
) -> ReferenceExtractionResult:
    current_refs = extract_references_from_text(current_text)
    if len(current_refs) == 1:
        ref = current_refs[0]
        return ReferenceExtractionResult(
            reference=ref,
            candidates=current_refs,
            confidence="high",
            source="current",
            ambiguous=False,
        )
    if len(current_refs) > 1:
        return ReferenceExtractionResult(
            reference=None,
            candidates=current_refs,
            confidence="low",
            source="current",
            ambiguous=True,
        )

    history_refs = extract_references_from_text(history_text)
    if len(history_refs) == 1:
        return ReferenceExtractionResult(
            reference=history_refs[0],
            candidates=history_refs,
            confidence="high",
            source="history",
            ambiguous=False,
        )
    if len(history_refs) > 1:
        return ReferenceExtractionResult(
            reference=None,
            candidates=history_refs,
            confidence="low",
            source="history",
            ambiguous=True,
        )

    return ReferenceExtractionResult(
        reference=None,
        candidates=[],
        confidence="none",
        source="none",
        ambiguous=False,
    )
