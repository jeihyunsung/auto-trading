"""Tests for resilient LLM JSON parsing."""

from trading.llm.client import LLMClient
from trading.llm.schemas import LLMDecisionOutput


def _make_client(response_text: str) -> LLMClient:
    """Create a lightweight client with a mocked text response."""
    client = LLMClient.__new__(LLMClient)
    client._client = object()
    client._api_key = "test"
    client._model = "gpt-5-nano"
    client._temperature = 0.1
    client.invoke = lambda system_prompt, user_prompt: response_text
    return client


def test_invoke_json_extracts_first_valid_object_after_schema_like_output():
    response = """{
  "description": "Output from LLM trading decision.",
  "type": "object",
  "properties": {
    "action": {"type": "string"}
  }
}
{
  "action": "HOLD",
  "confidence": 0.62,
  "rationale": "RSI=48.2, Trend=neutral, Funding=0.0001%로 방향성 부족하여 관망."
}"""
    client = _make_client(response)

    result = client.invoke_json("system", "user", LLMDecisionOutput)

    assert result.action == "HOLD"
    assert result.confidence == 0.62


def test_invoke_json_handles_extra_text_after_valid_json():
    response = """```json
{
  "action": "SELL",
  "confidence": 0.81,
  "rationale": "RSI=72.4, Trend=bearish, OI 증가와 롱 과열로 차익실현 우세."
}
```

Additional explanation that should be ignored.
"""
    client = _make_client(response)

    result = client.invoke_json("system", "user", LLMDecisionOutput)

    assert result.action == "SELL"
    assert result.confidence == 0.81
