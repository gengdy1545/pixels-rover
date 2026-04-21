import json
import logging
from dataclasses import dataclass

import litellm

from app.config import get_settings

logger = logging.getLogger(__name__)

litellm.drop_params = True


@dataclass
class LLMResponse:
    content: str
    tokens_in: int
    tokens_out: int


class LLMClient:
    """Thin wrapper around LiteLLM for unified LLM access."""

    def __init__(self) -> None:
        settings = get_settings()
        self.model = settings.llm_model
        self.temperature = settings.llm_temperature
        self.timeout = settings.llm_timeout
        if settings.llm_api_key:
            litellm.api_key = settings.llm_api_key
        if settings.llm_api_base:
            litellm.api_base = settings.llm_api_base

    async def call(
        self,
        messages: list[dict],
        response_format: dict | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "timeout": self.timeout,
        }
        if response_format:
            kwargs["response_format"] = response_format

        response = await litellm.acompletion(**kwargs)
        content = response.choices[0].message.content or ""
        usage = response.usage
        return LLMResponse(
            content=content,
            tokens_in=usage.prompt_tokens if usage else 0,
            tokens_out=usage.completion_tokens if usage else 0,
        )

    async def call_json(
        self,
        messages: list[dict],
        temperature: float | None = None,
    ) -> LLMResponse:
        return await self.call(
            messages,
            response_format={"type": "json_object"},
            temperature=temperature,
        )
