from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, TypeVar

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.config import Settings

T = TypeVar("T", bound=BaseModel)

_RETRYABLE_HTTP_STATUS = frozenset({502, 503, 524})
_MAX_LLM_ATTEMPTS = 3


def _messages_to_prompt(messages: list[BaseMessage]) -> str:
    parts: list[str] = []
    for message in messages:
        if isinstance(message, SystemMessage):
            parts.append(f"System: {message.content}")
        elif isinstance(message, HumanMessage):
            parts.append(f"User: {message.content}")
        elif isinstance(message, AIMessage):
            parts.append(f"Assistant: {message.content}")
        else:
            role = getattr(message, "type", "message")
            parts.append(f"{role}: {message.content}")
    parts.append("Assistant:")
    return "\n\n".join(parts)


def _strip_thinking(text: str) -> str:
    pattern = r"<\s*think\s*>[\s\S]*?<\s*/\s*think\s*>"
    return re.sub(pattern, "", text, flags=re.IGNORECASE).strip()


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = _strip_thinking(text.strip())
    if "```" in cleaned:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned, flags=re.IGNORECASE)
        if match:
            cleaned = match.group(1).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"Model did not return JSON. Raw output: {text[:500]}")
    return json.loads(cleaned[start : end + 1])


async def ainvoke_structured(
    llm: BaseChatModel,
    schema: type[T],
    messages: list[BaseMessage],
) -> T:
    """Structured output for OpenAI native models and JSON-prompt fallback for Vast AI."""
    if isinstance(llm, ChatOpenAI):
        structured = llm.with_structured_output(schema)
        return await structured.ainvoke(messages)

    schema_hint = json.dumps(schema.model_json_schema(), indent=2)
    augmented = [
        *messages,
        HumanMessage(
            content=(
                "Return ONLY valid JSON matching this schema. "
                "No markdown fences, no commentary, no extra keys.\n"
                f"{schema_hint}"
            )
        ),
    ]
    result = await llm.ainvoke(augmented)
    content = result.content if isinstance(result, AIMessage) else str(getattr(result, "content", result))
    data = _extract_json_object(str(content))
    return schema.model_validate(data)


class VastAIChatModel(BaseChatModel):
    """Ollama-compatible /api/generate client for Vast.ai tunnel endpoints."""

    base_url: str
    token: str
    model: str
    temperature: float = 0.1
    cookie_name: str = ""
    timeout_seconds: float = 300.0

    @property
    def _llm_type(self) -> str:
        return "vastai"

    def _build_url(self) -> str:
        base = self.base_url.rstrip("/")
        return f"{base}/api/generate?token={self.token}"

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.cookie_name:
            headers["Cookie"] = f"{self.cookie_name}={self.token}"
        return headers

    def _parse_response(self, payload: dict[str, Any]) -> str:
        if payload.get("error"):
            raise RuntimeError(str(payload["error"]))
        text = payload.get("response")
        if text is None:
            raise RuntimeError(f"Unexpected Vast AI response: {json.dumps(payload)[:500]}")
        return str(text).strip()

    def _call_sync(self, prompt: str) -> str:
        body = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": self.temperature},
        }
        last_exc: Exception | None = None
        for attempt in range(_MAX_LLM_ATTEMPTS):
            try:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.post(
                        self._build_url(),
                        headers=self._build_headers(),
                        json=body,
                    )
                    response.raise_for_status()
                    return self._parse_response(response.json())
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if (
                    exc.response.status_code in _RETRYABLE_HTTP_STATUS
                    and attempt < _MAX_LLM_ATTEMPTS - 1
                ):
                    time.sleep(2**attempt)
                    continue
                raise
        raise last_exc or RuntimeError("Vast AI request failed")

    async def _call_async(self, prompt: str) -> str:
        body = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": self.temperature},
        }
        last_exc: Exception | None = None
        for attempt in range(_MAX_LLM_ATTEMPTS):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.post(
                        self._build_url(),
                        headers=self._build_headers(),
                        json=body,
                    )
                    response.raise_for_status()
                    return self._parse_response(response.json())
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if (
                    exc.response.status_code in _RETRYABLE_HTTP_STATUS
                    and attempt < _MAX_LLM_ATTEMPTS - 1
                ):
                    await asyncio.sleep(2**attempt)
                    continue
                raise
        raise last_exc or RuntimeError("Vast AI request failed")

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        prompt = _messages_to_prompt(messages)
        text = self._call_sync(prompt)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        prompt = _messages_to_prompt(messages)
        text = await self._call_async(prompt)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])


def create_chat_llm(settings: Settings, *, temperature: float = 0.1) -> BaseChatModel:
    provider = (settings.llm_provider or "vastai").strip().lower()
    if provider == "openai":
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is not configured")
        return ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            temperature=temperature,
        )

    if provider == "vastai":
        if not settings.vastai_base_url or not settings.vastai_token:
            raise ValueError("VASTAI_BASE_URL and VASTAI_TOKEN are not configured")
        return VastAIChatModel(
            base_url=settings.vastai_base_url,
            token=settings.vastai_token,
            model=settings.vastai_model,
            temperature=temperature,
            cookie_name=settings.vastai_cookie_name,
            timeout_seconds=settings.vastai_timeout_seconds,
        )

    raise ValueError(f"Unsupported LLM provider: {settings.llm_provider}")


def llm_configured(settings: Settings) -> bool:
    provider = (settings.llm_provider or "vastai").strip().lower()
    if provider == "openai":
        return bool(settings.openai_api_key)
    if provider == "vastai":
        return bool(settings.vastai_base_url and settings.vastai_token)
    return False


def llm_not_configured_message(settings: Settings) -> str:
    provider = (settings.llm_provider or "vastai").strip().lower()
    if provider == "openai":
        return "OPENAI_API_KEY is not configured"
    if provider == "vastai":
        return "VASTAI_BASE_URL and VASTAI_TOKEN are not configured"
    return f"LLM provider '{settings.llm_provider}' is not configured"
