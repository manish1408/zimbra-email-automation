from __future__ import annotations

import json
from typing import Any

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_openai import ChatOpenAI
from app.config import Settings


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


class VastAIChatModel(BaseChatModel):
    """Ollama-compatible /api/generate client for Vast.ai tunnel endpoints."""

    base_url: str
    token: str
    model: str
    temperature: float = 0.1
    cookie_name: str = "C.39613280_auth_token"
    timeout_seconds: float = 300.0

    @property
    def _llm_type(self) -> str:
        return "vastai"

    def _build_url(self) -> str:
        base = self.base_url.rstrip("/")
        return f"{base}/api/generate?token={self.token}"

    def _build_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Cookie": f"{self.cookie_name}={self.token}",
        }

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
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(
                self._build_url(),
                headers=self._build_headers(),
                json=body,
            )
            response.raise_for_status()
            return self._parse_response(response.json())

    async def _call_async(self, prompt: str) -> str:
        body = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": self.temperature},
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                self._build_url(),
                headers=self._build_headers(),
                json=body,
            )
            response.raise_for_status()
            return self._parse_response(response.json())

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
