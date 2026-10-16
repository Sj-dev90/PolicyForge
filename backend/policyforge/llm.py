"""OpenAI-compatible LLM client for Nebius Token Factory with retries, latency, and token logging."""

from __future__ import annotations

import os
import time
import random
from dataclasses import dataclass, field
from typing import Any, Callable
from dotenv import load_dotenv
import openai

# Load environment variables from .env if present
load_dotenv()


@dataclass
class LLMCallRecord:
    """Telemetry record for a single LLM API call."""
    timestamp: float
    model: str
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    success: bool
    error_message: str | None = None


class LLMClient:
    """OpenAI-compatible client with timeouts, retries with backoff, and metrics logging."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        self.api_key = (
            api_key
            or os.getenv("NEBIUS_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or ""
        )
        self.base_url = (
            base_url
            or os.getenv("NEBIUS_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
            or "https://api.tokenfactory.nebius.ai/v1"
        )
        self.model = (
            model
            or os.getenv("NEBIUS_MODEL")
            or os.getenv("OPENAI_MODEL")
            or "nvidia/nemotron-4-340b-instruct"
        )
        self.timeout = (
            timeout
            if timeout is not None
            else float(os.getenv("REQUEST_TIMEOUT_SECONDS", "30.0"))
        )
        self.max_retries = (
            max_retries
            if max_retries is not None
            else int(os.getenv("MAX_RETRIES", "3"))
        )

        self.call_history: list[LLMCallRecord] = []
        self._mock_responder: Callable[[list[dict[str, str]]], str] | None = None

        self._client: openai.OpenAI | None = None
        if self.api_key:
            self._client = openai.OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout,
            )

    def set_mock_responder(self, responder: Callable[[list[dict[str, str]]], str] | None) -> None:
        """Inject a mock responder for unit testing without network/API keys."""
        self._mock_responder = responder

    def get_call_history(self) -> list[LLMCallRecord]:
        return list(self.call_history)

    def get_total_usage(self) -> dict[str, Any]:
        """Aggregate token usage and latency across all calls made by this client."""
        return {
            "call_count": len(self.call_history),
            "prompt_tokens": sum(c.prompt_tokens for c in self.call_history),
            "completion_tokens": sum(c.completion_tokens for c in self.call_history),
            "total_tokens": sum(c.total_tokens for c in self.call_history),
            "total_latency_ms": sum(c.latency_ms for c in self.call_history),
        }

    def chat_complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        """Execute chat completion with retries, backoff, and metrics tracking."""
        start_time = time.perf_counter()

        # Handle mock responder for tests
        if self._mock_responder is not None:
            resp_content = self._mock_responder(messages)
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            # Approximate token counts
            p_tokens = sum(len(m.get("content", "").split()) for m in messages)
            c_tokens = len(resp_content.split())
            record = LLMCallRecord(
                timestamp=time.time(),
                model=f"{self.model}-mock",
                latency_ms=elapsed_ms,
                prompt_tokens=p_tokens,
                completion_tokens=c_tokens,
                total_tokens=p_tokens + c_tokens,
                success=True,
            )
            self.call_history.append(record)
            return resp_content

        if not self.api_key or self._client is None:
            raise ValueError(
                "API key is not configured. Set NEBIUS_API_KEY in .env or pass api_key to LLMClient."
            )

        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                kwargs: dict[str, Any] = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                }
                if response_format is not None:
                    kwargs["response_format"] = response_format

                response = self._client.chat.completions.create(**kwargs)
                elapsed_ms = (time.perf_counter() - start_time) * 1000

                usage = getattr(response, "usage", None)
                p_tokens = usage.prompt_tokens if usage else 0
                c_tokens = usage.completion_tokens if usage else 0
                tot_tokens = usage.total_tokens if usage else 0

                content = response.choices[0].message.content or ""

                record = LLMCallRecord(
                    timestamp=time.time(),
                    model=self.model,
                    latency_ms=elapsed_ms,
                    prompt_tokens=p_tokens,
                    completion_tokens=c_tokens,
                    total_tokens=tot_tokens,
                    success=True,
                )
                self.call_history.append(record)
                return content

            except (openai.APIError, openai.APIConnectionError, openai.RateLimitError, TimeoutError) as err:
                last_err = err
                if attempt < self.max_retries:
                    # Exponential backoff with jitter
                    sleep_sec = (1.5 ** attempt) + random.uniform(0.1, 0.5)
                    time.sleep(sleep_sec)
                else:
                    elapsed_ms = (time.perf_counter() - start_time) * 1000
                    record = LLMCallRecord(
                        timestamp=time.time(),
                        model=self.model,
                        latency_ms=elapsed_ms,
                        prompt_tokens=0,
                        completion_tokens=0,
                        total_tokens=0,
                        success=False,
                        error_message=str(err),
                    )
                    self.call_history.append(record)
                    raise err

        raise last_err or RuntimeError("LLM call failed after retries.")
