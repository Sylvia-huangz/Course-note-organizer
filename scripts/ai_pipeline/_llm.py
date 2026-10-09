"""
LLM abstraction layer for the AI pipeline.

Supports Anthropic (Claude) and OpenAI APIs via stdlib urllib.
Key feature: structured output — pass a Pydantic model, get a validated instance back.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

# Allow importing from the commands directory for shared utilities
_COMMANDS_DIR = Path(__file__).resolve().parent.parent / "commands"
if str(_COMMANDS_DIR) not in sys.path:
    sys.path.insert(0, str(_COMMANDS_DIR))

from _schemas import CommandError  # noqa: E402


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class LLMUsage:
    """Token usage for a single LLM call."""

    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    latency_ms: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class LLMConfig:
    """Configuration for an LLM provider."""

    provider: Literal["anthropic", "openai"] = "anthropic"
    model: str = "claude-sonnet-4-20250514"
    api_key: str = ""
    max_tokens: int = 4096
    temperature: float = 0.3
    base_url: str = ""
    timeout_seconds: float = 120.0

    def __post_init__(self) -> None:
        if not self.base_url:
            if self.provider == "anthropic":
                self.base_url = "https://api.anthropic.com/v1/messages"
            else:
                self.base_url = "https://api.openai.com/v1/chat/completions"


@dataclass
class LLMCallResult:
    """Result of an LLM call."""

    content: str
    usage: LLMUsage
    model: str
    finish_reason: str = ""


@dataclass
class PipelineMetrics:
    """Accumulated metrics across all LLM calls in a pipeline run."""

    calls: list[LLMUsage] = field(default_factory=list)
    total_latency_ms: float = 0.0

    @property
    def total_input_tokens(self) -> int:
        return sum(u.input_tokens for u in self.calls)

    @property
    def total_output_tokens(self) -> int:
        return sum(u.output_tokens for u in self.calls)

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    def record(self, usage: LLMUsage, latency_ms: float) -> None:
        self.calls.append(usage)
        self.total_latency_ms += latency_ms


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------


def json_schema_instructions(schema: dict[str, Any]) -> str:
    """Generate minimal but precise JSON-output instructions from a JSON schema."""
    props = schema.get("properties", {})
    required = schema.get("required", [])
    lines = ["Return ONLY valid JSON matching this structure. No markdown, no preamble."]
    lines.append("```json")
    example: dict[str, Any] = {}
    for key, prop in props.items():
        prop_type = prop.get("type", "string")
        if prop_type == "array":
            example[key] = []
        elif prop_type == "object":
            example[key] = {}
        elif prop_type == "number":
            example[key] = 0.0
        elif prop_type == "integer":
            example[key] = 0
        elif prop_type == "boolean":
            example[key] = False
        else:
            example[key] = "..."
    lines.append(json.dumps(example, indent=2, ensure_ascii=False))
    lines.append("```")
    if required:
        lines.append(f"Required fields: {', '.join(required)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# API calling
# ---------------------------------------------------------------------------


def _call_anthropic(config: LLMConfig, system: str, user: str) -> LLMCallResult:
    """Call Anthropic Messages API."""
    body = {
        "model": config.model,
        "max_tokens": config.max_tokens,
        "temperature": config.temperature,
        "system": [{"type": "text", "text": system}],
        "messages": [{"role": "user", "content": [{"type": "text", "text": user}]}],
    }

    data = json.dumps(body).encode("utf-8")
    headers = {
        "x-api-key": config.api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    req = urllib.request.Request(config.base_url, data=data, headers=headers, method="POST")
    t0 = time.perf_counter()

    try:
        with urllib.request.urlopen(req, timeout=config.timeout_seconds) as resp:
            raw = resp.read().decode("utf-8")
            result = json.loads(raw)
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="ignore") if exc.fp else ""
        raise RuntimeError(f"Anthropic API HTTP {exc.code}: {body_text[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Anthropic API connection error: {exc.reason}") from exc

    latency = (time.perf_counter() - t0) * 1000

    content_blocks = result.get("content", [])
    text_parts = [b.get("text", "") for b in content_blocks if b.get("type") == "text"]
    content = "\n".join(text_parts)

    usage = LLMUsage(
        input_tokens=result.get("usage", {}).get("input_tokens", 0),
        output_tokens=result.get("usage", {}).get("output_tokens", 0),
        model=result.get("model", config.model),
        latency_ms=latency,
    )

    stop_reason = result.get("stop_reason", "")
    return LLMCallResult(content=content, usage=usage, model=result.get("model", config.model), finish_reason=stop_reason)


def _call_openai(config: LLMConfig, system: str, user: str) -> LLMCallResult:
    """Call OpenAI Chat Completions API."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    body = {
        "model": config.model,
        "max_tokens": config.max_tokens,
        "temperature": config.temperature,
        "messages": messages,
        # Request JSON output when possible
        "response_format": {"type": "json_object"},
    }

    data = json.dumps(body).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "content-type": "application/json",
    }

    req = urllib.request.Request(config.base_url, data=data, headers=headers, method="POST")
    t0 = time.perf_counter()

    try:
        with urllib.request.urlopen(req, timeout=config.timeout_seconds) as resp:
            raw = resp.read().decode("utf-8")
            result = json.loads(raw)
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="ignore") if exc.fp else ""
        raise RuntimeError(f"OpenAI API HTTP {exc.code}: {body_text[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenAI API connection error: {exc.reason}") from exc

    latency = (time.perf_counter() - t0) * 1000

    choice = result.get("choices", [{}])[0]
    content = choice.get("message", {}).get("content", "")

    usage = LLMUsage(
        input_tokens=result.get("usage", {}).get("prompt_tokens", 0),
        output_tokens=result.get("usage", {}).get("completion_tokens", 0),
        model=result.get("model", config.model),
        latency_ms=latency,
    )

    finish_reason = choice.get("finish_reason", "")
    return LLMCallResult(content=content, usage=usage, model=result.get("model", config.model), finish_reason=finish_reason)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class LLMClient:
    """Unified LLM client with structured output support."""

    def __init__(self, config: LLMConfig, metrics: PipelineMetrics | None = None) -> None:
        self.config = config
        self.metrics = metrics or PipelineMetrics()

    def complete(self, system: str, user: str) -> LLMCallResult:
        """Send a prompt and return raw text."""
        if self.config.provider == "anthropic":
            result = _call_anthropic(self.config, system, user)
        elif self.config.provider == "openai":
            result = _call_openai(self.config, system, user)
        else:
            raise ValueError(f"Unsupported provider: {self.config.provider}")

        self.metrics.record(result.usage, result.usage.latency_ms)
        return result

    def complete_json(self, system: str, user: str, *, retries: int = 2) -> dict[str, Any]:
        """Send a prompt and return parsed JSON dict.

        Raises RuntimeError if JSON parsing fails after all retries.
        """
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                result = self.complete(system, user)
                # Try to extract JSON from the response
                text = result.content.strip()
                # Handle markdown code blocks
                if text.startswith("```"):
                    # Remove ```json or ``` and trailing ```
                    lines = text.split("\n")
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].strip() == "```":
                        lines = lines[:-1]
                    text = "\n".join(lines)
                return json.loads(text)
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                if attempt < retries:
                    # Retry with a stronger prompt
                    user = f"{user}\n\nIMPORTANT: Your previous response was not valid JSON. Please respond with ONLY valid JSON, no additional text."
        raise RuntimeError(f"Failed to parse JSON after {retries} retries: {last_error}")

    def complete_structured(self, system: str, user: str, response_model: type, *, retries: int = 2) -> Any:
        """Send a prompt and return a validated Pydantic model instance.

        Uses the model's JSON schema to enforce structured output.
        Falls back to JSON parsing + validation if the API doesn't support
        native structured output.

        Raises RuntimeError or ValidationError on failure.
        """
        from pydantic import ValidationError

        schema = response_model.model_json_schema()
        schema_instructions = json_schema_instructions(schema)
        full_system = f"{system}\n\n{schema_instructions}"

        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                data = self.complete_json(full_system, user, retries=0)
                return response_model.model_validate(data)
            except (ValidationError, RuntimeError) as exc:
                last_error = exc
                if attempt < retries:
                    user = f"{user}\n\nYour previous response did not match the required schema. Please follow the JSON structure exactly."
        raise RuntimeError(f"Failed structured output after {retries} retries: {last_error}")


# ---------------------------------------------------------------------------
# Config factory
# ---------------------------------------------------------------------------


def resolve_api_key(provider: str, explicit_key: str = "") -> str:
    """Resolve API key from explicit value or environment variable."""
    if explicit_key:
        return explicit_key
    env_map = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
    }
    env_var = env_map.get(provider, "")
    key = os.environ.get(env_var, "")
    if not key:
        raise RuntimeError(
            f"No API key found for {provider}. Set {env_var} or pass api_key explicitly."
        )
    return key


def create_client(
    provider: str = "anthropic",
    model: str = "",
    api_key: str = "",
    max_tokens: int = 4096,
    temperature: float = 0.3,
    metrics: PipelineMetrics | None = None,
) -> LLMClient:
    """Create an LLMClient with sensible defaults."""
    if not model:
        model = "claude-sonnet-4-20250514" if provider == "anthropic" else "gpt-4o"

    config = LLMConfig(
        provider=provider,  # type: ignore[arg-type]
        model=model,
        api_key=resolve_api_key(provider, api_key),
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return LLMClient(config, metrics=metrics)
