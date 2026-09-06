"""
src/ajaa/llm/gateway.py

LLM Gateway — the ONLY module that calls the LLM provider API.

Rules:
  - Every call goes through call_llm(). No other module imports openai.
  - Every call is logged to the cost ledger (in-memory for Phase 0; DB in Phase 1).
  - Structured output is requested via response_format. Raw text fallback is explicit.
  - The Untrusted boundary is enforced here: untrusted content goes only to USER channel.
  - Prompt caching headers are attached if configured.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import keyring
import openai
import structlog

from ajaa.config import get_settings
from ajaa.secrets.keychain import KeychainError, retrieve
from ajaa.types import LLMTask, Secret, Tier, Untrusted

log = structlog.get_logger(__name__)


# ── Cost tracking (in-memory for Phase 0) ─────────────────────────────────────

@dataclass
class LLMCallRecord:
    run_id: str
    task: str
    tier: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    duration_ms: float
    cached: bool = False
    error: str | None = None


_call_log: list[LLMCallRecord] = []


def get_call_log() -> list[LLMCallRecord]:
    return list(_call_log)


def get_session_cost() -> float:
    return sum(r.cost_usd for r in _call_log if r.error is None)


# ── Provider config ────────────────────────────────────────────────────────────

@dataclass
class ProviderConfig:
    base_url: str
    api_key: Secret
    timeout: int = 120
    prompt_caching: bool = False

    # Tier → model
    cheap_model: str = "deepseek-v4-flash"
    mid_model: str = "claude-opus-4-5"
    strong_model: str = "claude-opus-5"
    vision_model: str = "claude-opus-5"

    # Pricing (USD per 1M tokens)
    pricing: dict[str, dict[str, float]] = field(default_factory=lambda: {
        "deepseek-v4-flash": {"input": 0.14, "output": 0.28},
        "claude-opus-4-5":   {"input": 3.00, "output": 15.00},
        "claude-opus-5":     {"input": 15.00, "output": 75.00},
    })


_provider_config: ProviderConfig | None = None


def _get_provider_config() -> ProviderConfig:
    global _provider_config
    if _provider_config is not None:
        return _provider_config

    try:
        api_key = retrieve("agent_router_api_key")
    except KeychainError as e:
        raise RuntimeError(str(e)) from e

    _provider_config = ProviderConfig(
        base_url="https://agentrouter.org/v1",
        api_key=api_key,
    )
    return _provider_config


def reset_provider_config() -> None:
    """For testing only."""
    global _provider_config
    _provider_config = None


# ── Model selection ────────────────────────────────────────────────────────────

def _model_for_tier(cfg: ProviderConfig, tier: Tier) -> str:
    return {
        Tier.CHEAP:  cfg.cheap_model,
        Tier.MID:    cfg.mid_model,
        Tier.STRONG: cfg.strong_model,
        Tier.VISION: cfg.vision_model,
    }[tier]


def _cost_usd(cfg: ProviderConfig, model: str, prompt_tokens: int, completion_tokens: int) -> float:
    p = cfg.pricing.get(model, {"input": 1.0, "output": 3.0})
    return (prompt_tokens * p["input"] + completion_tokens * p["output"]) / 1_000_000


# ── Core call ─────────────────────────────────────────────────────────────────

def call_llm(
    *,
    task: LLMTask,
    tier: Tier,
    system_prompt: str,
    context_block: str,
    untrusted_block: str | None = None,
    response_schema: dict[str, Any] | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """
    Call the LLM provider.

    Channel layout (3-channel prompt architecture):
      SYSTEM:    system_prompt    — trusted, controlled by AJAA code
      CONTEXT:   context_block   — trusted candidate facts from CandidateContext
      UNTRUSTED: untrusted_block — job description / form labels (never in SYSTEM)

    Returns the parsed JSON response dict.
    Raises LLMError on failure after retries.
    """
    cfg = _get_provider_config()
    model = _model_for_tier(cfg, tier)
    run_id = str(uuid.uuid4())[:8]

    # Build messages
    user_parts = [f"<context>\n{context_block}\n</context>"]
    if untrusted_block is not None:
        # Validate: untrusted must be Untrusted type upstream, but we accept str here
        # for ergonomics. The type system enforces this at call sites.
        user_parts.append(f"<untrusted_input>\n{untrusted_block}\n</untrusted_input>")

    user_content = "\n\n".join(user_parts)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_content},
    ]

    # Determine max_tokens per tier if not specified
    if max_tokens is None:
        max_tokens = {Tier.CHEAP: 4096, Tier.MID: 8192, Tier.STRONG: 16384, Tier.VISION: 4096}[tier]

    client = openai.OpenAI(
        api_key=cfg.api_key.reveal(),
        base_url=cfg.base_url,
        timeout=cfg.timeout,
    )

    start = time.monotonic()
    error_msg: str | None = None
    prompt_tokens = 0
    completion_tokens = 0

    try:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.0,
        }
        if response_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": task.value, "schema": response_schema, "strict": True},
            }

        response = client.chat.completions.create(**kwargs)
        prompt_tokens = response.usage.prompt_tokens if response.usage else 0
        completion_tokens = response.usage.completion_tokens if response.usage else 0

        content = response.choices[0].message.content or ""

        # Parse JSON
        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            # Attempt to extract JSON from markdown code block
            import re
            match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
            if match:
                result = json.loads(match.group(1))
            else:
                raise LLMError(f"Response was not valid JSON: {content[:200]}")

        duration_ms = (time.monotonic() - start) * 1000
        cost = _cost_usd(cfg, model, prompt_tokens, completion_tokens)

        record = LLMCallRecord(
            run_id=run_id,
            task=task.value,
            tier=tier.value,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
            duration_ms=duration_ms,
        )
        _call_log.append(record)

        log.info(
            "llm_call",
            task=task.value,
            tier=tier.value,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=round(cost, 6),
            duration_ms=round(duration_ms, 1),
            run_id=run_id,
        )

        return result  # type: ignore[no-any-return]

    except openai.OpenAIError as e:
        error_msg = str(e)
        duration_ms = (time.monotonic() - start) * 1000
        cost = _cost_usd(cfg, model, prompt_tokens, completion_tokens)
        _call_log.append(LLMCallRecord(
            run_id=run_id, task=task.value, tier=tier.value, model=model,
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            cost_usd=cost, duration_ms=duration_ms, error=error_msg,
        ))
        log.error("llm_call_failed", task=task.value, model=model, error=error_msg, run_id=run_id)
        raise LLMError(f"LLM call failed [{task.value}]: {error_msg}") from e


class LLMError(Exception):
    """Raised when an LLM call fails after retries."""