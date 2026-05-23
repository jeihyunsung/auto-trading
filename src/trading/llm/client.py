"""OpenAI ChatGPT client for LLM operations."""

import hashlib
import json
import logging
import time
from json import JSONDecodeError
from typing import TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ValidationError

from trading.config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class _ResponseCache:
    """Simple TTL cache for LLM responses.

    Only caches HOLD decisions to avoid stale BUY/SELL signals.
    Cache key is derived from core market state fields.
    """

    def __init__(self, ttl_seconds: int | None = None):
        # Default TTL aligns with polling interval (600s) plus margin so
        # cached HOLD decisions survive across at least one full cycle.
        if ttl_seconds is None:
            ttl_seconds = get_settings().llm_cache_ttl_seconds
        self._cache: dict[str, tuple[float, object]] = {}
        self._ttl = ttl_seconds

    def get(self, key: str) -> object | None:
        """Get cached response if not expired."""
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, value = entry
        if time.time() - ts > self._ttl:
            del self._cache[key]
            return None
        logger.info(f"LLM cache hit (age={time.time() - ts:.0f}s)")
        return value

    def put(self, key: str, value: object) -> None:
        """Cache a response."""
        self._cache[key] = (time.time(), value)
        # Evict old entries
        cutoff = time.time() - self._ttl * 2
        expired = [k for k, (ts, _) in self._cache.items() if ts < cutoff]
        for k in expired:
            del self._cache[k]

    @staticmethod
    def make_key(system_prompt_hash: str, **fields: object) -> str:
        """Build cache key from core state fields.

        Bins continuous values into discrete ranges so similar states
        hit the same cache entry.
        """
        parts = [system_prompt_hash]
        for k, v in sorted(fields.items()):
            if isinstance(v, float):
                # Bin floats: RSI in 5-unit bins, percentages in 2-unit bins
                v = round(v / 5) * 5 if k == "rsi" else round(v / 2) * 2
            parts.append(f"{k}={v}")
        raw = "|".join(str(p) for p in parts)
        return hashlib.md5(raw.encode()).hexdigest()


# Global cache instance
_response_cache = _ResponseCache()


class LLMClient:
    """Client for OpenAI ChatGPT interactions."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        temperature: float = 0.1,
    ):
        """Initialize LLM client.

        Args:
            api_key: OpenAI API key (uses env if None).
            model: Model name (uses config if None).
            temperature: Sampling temperature (default 0.1 for consistency).
        """
        settings = get_settings()

        self._api_key = api_key or settings.openai_api_key
        self._model = model or settings.openai_model
        self._temperature = temperature

        if not self._api_key:
            logger.warning("OpenAI API key not provided - LLM features disabled")
            self._client = None
        else:
            self._client = ChatOpenAI(
                api_key=self._api_key,
                model=self._model,
                temperature=self._temperature,
            )

    @property
    def is_available(self) -> bool:
        """Check if LLM client is available."""
        return self._client is not None

    def invoke(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """Invoke LLM with system and user prompts.

        Args:
            system_prompt: System message setting behavior.
            user_prompt: User message with the request.

        Returns:
            LLM response text.

        Raises:
            RuntimeError: If client not initialized.
        """
        if self._client is None:
            raise RuntimeError("LLM client not initialized - API key required")

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        response = self._client.invoke(messages)
        return response.content

    def invoke_json(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
    ) -> T:
        """Invoke LLM and parse response as structured JSON.

        Args:
            system_prompt: System message.
            user_prompt: User message.
            response_model: Pydantic model for response validation.

        Returns:
            Parsed response as Pydantic model.

        Raises:
            RuntimeError: If client not initialized.
            ValueError: If response cannot be parsed.
        """
        if self._client is None:
            raise RuntimeError("LLM client not initialized - API key required")

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        structured_output = getattr(self._client, "with_structured_output", None)
        if callable(structured_output):
            try:
                response = structured_output(response_model).invoke(messages)
                return (
                    response
                    if isinstance(response, response_model)
                    else response_model.model_validate(response)
                )
            except Exception as e:
                logger.warning(f"Structured output failed, falling back to JSON parsing: {e}")

        full_system = (
            f"{system_prompt}\n\n"
            f"{self._build_json_instruction(response_model)}"
        )

        response_text = self.invoke(full_system, user_prompt)

        # Parse JSON response
        try:
            return self._parse_json_response(response_text, response_model)
        except ValueError as e:
            logger.error(f"Failed to parse LLM response: {response_text[:500]}")
            raise ValueError(f"Failed to parse LLM response as JSON: {e}") from e

    @staticmethod
    def _build_json_instruction(response_model: type[T]) -> str:
        """Build a compact JSON instruction for smaller models."""
        required_fields = ", ".join(response_model.model_fields.keys())
        return (
            "Return exactly one JSON object.\n"
            f"Required keys: {required_fields}\n"
            "Do not return a JSON schema.\n"
            "Do not wrap the JSON in markdown.\n"
            "Do not add explanations before or after the JSON."
        )

    @classmethod
    def _parse_json_response(cls, response_text: str, response_model: type[T]) -> T:
        """Parse and validate the first valid JSON object in the model response."""
        candidates = cls._extract_json_candidates(response_text)
        errors: list[str] = []

        for candidate in candidates:
            try:
                data = json.loads(candidate)
            except JSONDecodeError as e:
                errors.append(str(e))
                continue

            try:
                return response_model.model_validate(data)
            except ValidationError as e:
                errors.append(str(e))
                continue

        if not candidates:
            raise ValueError("No JSON object found in model response")

        raise ValueError(errors[-1] if errors else "Unknown JSON parsing error")

    @classmethod
    def _extract_json_candidates(cls, response_text: str) -> list[str]:
        """Extract possible JSON object snippets from a response."""
        text = response_text.strip()
        candidates: list[str] = []

        if text:
            candidates.append(text)

        fence_content = cls._extract_fenced_content(text)
        if fence_content and fence_content not in candidates:
            candidates.append(fence_content)

        for snippet in cls._find_balanced_json_objects(text):
            if snippet not in candidates:
                candidates.append(snippet)

        if fence_content:
            for snippet in cls._find_balanced_json_objects(fence_content):
                if snippet not in candidates:
                    candidates.append(snippet)

        return candidates

    @staticmethod
    def _extract_fenced_content(text: str) -> str:
        """Extract the first markdown code fence body if present."""
        if not text.startswith("```"):
            return ""

        lines = text.splitlines()
        if len(lines) < 3:
            return ""

        body: list[str] = []
        in_fence = False
        for line in lines:
            if line.startswith("```"):
                if not in_fence:
                    in_fence = True
                    continue
                break
            if in_fence:
                body.append(line)
        return "\n".join(body).strip()

    @staticmethod
    def _find_balanced_json_objects(text: str) -> list[str]:
        """Find balanced top-level JSON object substrings in text."""
        objects: list[str] = []
        start: int | None = None
        depth = 0
        in_string = False
        escape = False

        for idx, char in enumerate(text):
            if escape:
                escape = False
                continue

            if char == "\\" and in_string:
                escape = True
                continue

            if char == '"':
                in_string = not in_string
                continue

            if in_string:
                continue

            if char == "{":
                if depth == 0:
                    start = idx
                depth += 1
            elif char == "}" and depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    objects.append(text[start:idx + 1])
                    start = None

        return objects


# Global client instance (lazy loaded)
_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Get LLM client singleton.

    Returns:
        LLMClient instance.
    """
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client


def get_response_cache() -> _ResponseCache:
    """Get the global LLM response cache.

    Returns:
        _ResponseCache instance for caching HOLD decisions.
    """
    return _response_cache
