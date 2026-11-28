from __future__ import annotations

import logging
import time
from typing import Optional

from openai import OpenAI
from api_config import MODEL_NAME

try:
    from openai import (
        APIConnectionError,
        APITimeoutError,
        InternalServerError,
        RateLimitError,
    )
except ImportError:  # pragma: no cover
    APIConnectionError = None  # type: ignore[assignment]
    APITimeoutError = None  # type: ignore[assignment]
    InternalServerError = None  # type: ignore[assignment]
    RateLimitError = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Transient errors that should trigger a retry.
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# Cache the OpenAI exception-type tuple once (may be empty on older SDKs).
_OPENAI_EXC_TYPES = tuple(
    t
    for t in (APIConnectionError, APITimeoutError, InternalServerError, RateLimitError)
    if t is not None
)


class LLMClient:
    """Thin wrapper around the OpenAI-compatible chat-completion API with retries
    and per-request model / API profile overrides.

    Parameters
    ----------
    api_key:
        Default API key used when no per-request key is supplied.
    base_url:
        Default base URL (e.g. ``https://api.deepseek.com``).
    """

    # Upper bound on cached OpenAI client instances.  In practice only a
    # handful of profiles exist (default, simple, complex) so this is far
    # more than needed, but it prevents unbounded growth if someone creates
    # many LLMClient instances with varying parameters.
    _MAX_CLIENTS = 16

    def __init__(self, api_key: str, base_url: Optional[str] = None):
        self.api_key = api_key
        self.base_url = base_url
        self.model_name = MODEL_NAME
        self._clients = {}
        # Simple FIFO eviction list — cheap and sufficient for a tiny cache.
        self._client_order: list[tuple] = []

    def _make_client(self, api_key: str, base_url: Optional[str] = None):
        if not api_key:
            raise ValueError("API key is required for LLM calls.")
        if base_url:
            return OpenAI(api_key=api_key, base_url=base_url, max_retries=0)
        return OpenAI(api_key=api_key, max_retries=0)

    def _client_for(
        self, api_key: Optional[str] = None, base_url: Optional[str] = None
    ):
        api_key = api_key if api_key is not None else self.api_key
        base_url = base_url if base_url is not None else self.base_url
        cache_key = (api_key, base_url)
        if cache_key not in self._clients:
            if len(self._clients) >= self._MAX_CLIENTS:
                oldest = self._client_order.pop(0)
                self._clients.pop(oldest, None)
            self._clients[cache_key] = self._make_client(
                api_key=api_key, base_url=base_url
            )
            self._client_order.append(cache_key)
        return self._clients[cache_key]

    def chat(
        self,
        messages: list[dict],
        tools: Optional[list] = None,
        model_name: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        max_retries: int = 3,
        timeout: float = 60.0,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        on_stream=None,
        stream_control=None,
        include_stream_usage: bool = True,
    ):
        """Send a chat-completion request with automatic retry on transient errors.

        Parameters
        ----------
        messages:
            Conversation history in OpenAI format.
        tools:
            Optional list of tool definitions.
        model_name:
            Override the default model for this request.
        api_key:
            Override the default API key for this request.
        base_url:
            Override the default base URL for this request.
        max_retries:
            Maximum number of retry attempts (default 3, for up to 4 total calls).
        timeout:
            Request timeout in seconds (default 60).

        Returns
        -------
        The raw ``chat.completions.create`` response object.

        Raises
        ------
        Exception
            The last exception encountered after exhausting retries.
        """
        client = self._client_for(api_key=api_key, base_url=base_url)
        if stream:
            from llm.streaming import aggregate

            kwargs = dict(
                model=model_name or self.model_name,
                messages=messages,
                timeout=timeout,
                stream=True,
            )
            if tools:
                kwargs.update(tools=tools, tool_choice="auto")
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens
            if include_stream_usage:
                kwargs["stream_options"] = {"include_usage": True}
            started = time.monotonic()
            response = client.chat.completions.create(**kwargs)
            return aggregate(response, on_stream, stream_control, started)
        last_exception = None
        for attempt in range(max_retries + 1):
            try:
                kwargs = {
                    "model": model_name or self.model_name,
                    "messages": messages,
                    "timeout": timeout,
                }
                if max_tokens is not None:
                    kwargs["max_tokens"] = max_tokens
                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = "auto"
                response = client.chat.completions.create(**kwargs)
                return response
            except Exception as exc:
                last_exception = exc
                if attempt >= max_retries:
                    break
                if not self._is_retryable(exc):
                    break
                delay = 2**attempt
                logger.warning(
                    "LLM call attempt %d/%d failed (retryable), retrying in %ds: %s",
                    attempt + 1,
                    max_retries + 1,
                    delay,
                    exc,
                )
                time.sleep(delay)
        raise last_exception

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        if _OPENAI_EXC_TYPES and isinstance(exc, _OPENAI_EXC_TYPES):
            return True
        status_code = getattr(exc, "status_code", None) or getattr(
            exc, "http_status", None
        )
        if status_code is not None and status_code in _RETRYABLE_STATUS_CODES:
            return True
        error_str = str(exc).lower()
        # Be precise — broad keywords like "connection" can match permanent
        # configuration errors.  Prefer substrings that signal transient events.
        retryable_keywords = {
            "rate limit",
            "timed out",
            "connection reset",
            "connection refused",
            "connection error",
            "server error",
            "overloaded",
            "too many requests",
            "service unavailable",
        }
        return any(kw in error_str for kw in retryable_keywords)
