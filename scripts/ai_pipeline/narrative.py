"""
Phase 2 — Narrative Cleaning.

Transforms raw spoken transcription into clean, readable "teacher's words"
via LLM. Preserves meaning, order, and detail — removes only noise.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

# Allow importing from commands directory
_COMMANDS_DIR = Path(__file__).resolve().parent.parent / "commands"
if str(_COMMANDS_DIR) not in sys.path:
    sys.path.insert(0, str(_COMMANDS_DIR))

from ._llm import LLMClient, create_client
from .chunker import Chunk
from .prompts.narrative import NARRATIVE_SYSTEM, build_narrative_prompt


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class NarrativeResult(BaseModel):
    """Output of narrative cleaning for a single chunk."""

    chunk_index: int
    raw_text: str = ""
    cleaned_narrative: str = ""
    token_usage: dict[str, int] = Field(default_factory=dict)
    latency_ms: float = 0.0
    error: str | None = None


class NarrativeBatchResult(BaseModel):
    """Output of narrative cleaning for all chunks."""

    results: list[NarrativeResult] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Cleaning
# ---------------------------------------------------------------------------


def clean_chunk(
    chunk: Chunk,
    llm: LLMClient,
    course_title: str = "",
) -> NarrativeResult:
    """Clean a single chunk's raw transcript into readable narrative.

    Args:
        chunk: The chunk to clean.
        llm: LLM client instance.
        course_title: Optional course name for context.

    Returns:
        NarrativeResult with cleaned text and metadata.
    """
    user_prompt = build_narrative_prompt(
        raw_transcript=chunk.raw_text,
        course_title=course_title,
        section_title=chunk.title or f"Section {chunk.index}",
    )

    try:
        result = llm.complete(NARRATIVE_SYSTEM, user_prompt)
        return NarrativeResult(
            chunk_index=chunk.index,
            raw_text=chunk.raw_text,
            cleaned_narrative=result.content.strip(),
            token_usage={
                "input": result.usage.input_tokens,
                "output": result.usage.output_tokens,
            },
            latency_ms=result.usage.latency_ms,
        )
    except Exception as exc:
        # Fallback: use raw text with basic regex cleaning
        import re

        cleaned = chunk.raw_text
        # Remove common filler words
        for filler in ["um", "uh", "er", "you know", "like", "嗯", "啊", "呃", "这个", "那个", "就是说", "然后"]:
            cleaned = re.sub(rf"\b{re.escape(filler)}\b", "", cleaned, flags=re.IGNORECASE)
        # Collapse multiple spaces
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()

        return NarrativeResult(
            chunk_index=chunk.index,
            raw_text=chunk.raw_text,
            cleaned_narrative=cleaned,
            error=str(exc),
        )


def clean_all_chunks(
    chunks: list[Chunk],
    llm: LLMClient | None = None,
    course_title: str = "",
    provider: str = "anthropic",
    model: str = "",
    api_key: str = "",
    max_parallel: int = 3,
) -> NarrativeBatchResult:
    """Clean all chunks. If no LLM client provided, creates one with defaults.

    Note: Chunks are processed sequentially to avoid rate limits.
    For parallel processing, call clean_chunk() directly with multiple clients.
    """
    if llm is None:
        llm = create_client(provider=provider, model=model, api_key=api_key)

    results: list[NarrativeResult] = []
    total_tokens = 0
    total_latency = 0.0
    errors = 0

    for chunk in chunks:
        result = clean_chunk(chunk, llm, course_title)
        results.append(result)
        if result.token_usage:
            total_tokens += result.token_usage.get("input", 0) + result.token_usage.get("output", 0)
        total_latency += result.latency_ms
        if result.error:
            errors += 1

    # Length stats
    raw_lengths = [len(r.raw_text) for r in results]
    cleaned_lengths = [len(r.cleaned_narrative) for r in results]
    compression_ratios = [
        (c / r) if r > 0 else 1.0 for r, c in zip(raw_lengths, cleaned_lengths)
    ]

    summary = {
        "total_chunks": len(chunks),
        "total_tokens": total_tokens,
        "total_latency_ms": total_latency,
        "errors": errors,
        "avg_compression_ratio": sum(compression_ratios) / len(compression_ratios) if compression_ratios else 0,
        "raw_chars": sum(raw_lengths),
        "cleaned_chars": sum(cleaned_lengths),
    }

    return NarrativeBatchResult(results=results, summary=summary)
