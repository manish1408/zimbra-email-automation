from __future__ import annotations

import pytest

from app.services.llm import _extract_json_object


def test_extract_json_object_from_thinking_block():
    text = '{"analyses": [{"message_id": "1", "category": "spam"}]}'
    data = _extract_json_object(text)
    assert data["analyses"][0]["message_id"] == "1"


def test_extract_json_object_strips_thinking_prefix():
    text = (
        'reasoning here'
        '{"analyses": [{"message_id": "203684", "category": "spam"}]}'
    )
    data = _extract_json_object(text)
    assert data["analyses"][0]["message_id"] == "203684"


def test_extract_json_object_raises_when_missing_json():
    with pytest.raises(ValueError, match="Model did not return JSON"):
        _extract_json_object("   ")
