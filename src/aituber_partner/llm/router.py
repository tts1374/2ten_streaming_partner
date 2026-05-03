"""Model routing rules for the Phase 1 local LLM path."""

from __future__ import annotations

from typing import Literal

from aituber_partner.config import AppConfig
from aituber_partner.llm.client import LLMClient, LLMRequest, LLMResponse
from aituber_partner.llm.text import strip_thinking_text

LLMPurpose = Literal["classification", "safety", "selection", "reply", "vision", "review"]


class LLMRouter:
    """Prepare LLM requests with fixed model roles and runtime safety constraints."""

    def __init__(self, config: AppConfig, client: LLMClient) -> None:
        self._config = config
        self._client = client

    async def generate(
        self,
        *,
        purpose: LLMPurpose,
        prompt: str,
        system: str | None = None,
        images: list[str] | None = None,
    ) -> LLMResponse:
        llm_request = self.build_request(
            purpose=purpose,
            prompt=prompt,
            system=system,
            images=images,
        )
        response = await self._client.generate(llm_request)
        return response.model_copy(update={"text": strip_thinking_text(response.text)})

    def build_request(
        self,
        *,
        purpose: LLMPurpose,
        prompt: str,
        system: str | None = None,
        images: list[str] | None = None,
    ) -> LLMRequest:
        image_list = images or []
        model = self._model_for(purpose=purpose, has_images=bool(image_list))
        return LLMRequest(
            model=model,
            prompt=prompt,
            purpose=purpose,
            system=system,
            images=image_list,
            think=False if _is_qwen_model(model) else None,
            keep_alive=self._config.ollama.keep_alive,
        )

    def _model_for(self, *, purpose: LLMPurpose, has_images: bool) -> str:
        if purpose in {"classification", "safety", "selection"}:
            return self._config.models.classifier
        if purpose == "reply":
            return self._config.models.reply
        if purpose == "vision":
            if not has_images:
                raise ValueError("Vision routing requires image input.")
            return self._config.models.vision
        if purpose == "review":
            return self._config.models.review
        raise ValueError(f"Unsupported LLM purpose: {purpose}")


def _is_qwen_model(model: str) -> bool:
    return model.lower().startswith("qwen")

