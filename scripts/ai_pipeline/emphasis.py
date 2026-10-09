"""
Phase 3 — Emphasis Extraction (Multi-Signal Fusion + LLM).

Detects emphasis signals from raw transcript patterns, then uses LLM
to extract structured teaching points: emphasis_points, pitfalls, keywords, question.

This is the core intelligence layer for the dual-column "教辅" format —
separating "what the teacher said" from "what the teacher EMPHASIZED."
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

# Allow importing from commands directory
_COMMANDS_DIR = Path(__file__).resolve().parent.parent / "commands"
if str(_COMMANDS_DIR) not in sys.path:
    sys.path.insert(0, str(_COMMANDS_DIR))

from ._llm import LLMClient, create_client
from .chunker import Chunk
from .narrative import NarrativeResult
from .prompts.emphasis import EMPHASIS_SCHEMA, EMPHASIS_SYSTEM, build_emphasis_prompt


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class EmphasisData(BaseModel):
    """Structured emphasis extraction for one teaching unit."""

    emphasis_points: list[str] = Field(default_factory=list)
    pitfalls: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    question: str = ""
    confidence: float = 0.8


class EmphasisResult(BaseModel):
    """Output of emphasis extraction for a single chunk."""

    chunk_index: int
    data: EmphasisData = Field(default_factory=EmphasisData)
    signals_detected: list[str] = Field(default_factory=list)
    signal_count: int = 0
    token_usage: dict[str, int] = Field(default_factory=dict)
    latency_ms: float = 0.0
    error: str | None = None


class EmphasisBatchResult(BaseModel):
    """Output of emphasis extraction across all chunks."""

    results: list[EmphasisResult] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Signal detection (rule-based, pre-LLM)
# ---------------------------------------------------------------------------

# Explicit emphasis markers — teacher verbally flags importance
EXPLICIT_MARKERS_CN = [
    "重点是", "关键是", "核心是", "关键在于",
    "一定要记住", "一定要掌握", "一定要理解",
    "考试会考", "考试重点", "必考",
    "这个很重要", "非常重要", "特别重要",
    "注意", "要注意的是", "值得注意",
    "强调一下", "再强调", "反复强调",
    "千万别", "不要搞混", "容易出错",
    "很多人会犯这个错", "常见错误",
    "关键是理解", "本质是", "归根结底",
]

EXPLICIT_MARKERS_EN = [
    "this is important", "key point", "the key is",
    "remember this", "you need to know", "you must understand",
    "this will be on the exam", "exam question",
    "pay attention", "note that", "it's crucial",
    "don't confuse", "common mistake", "be careful",
    "in essence", "the bottom line", "takeaway",
    "let me emphasize", "I want to highlight",
]


def detect_explicit_markers(text: str) -> list[str]:
    """Find explicit emphasis phrases in the transcript."""
    found: list[str] = []
    for marker in EXPLICIT_MARKERS_CN + EXPLICIT_MARKERS_EN:
        if marker.lower() in text.lower():
            # Extract surrounding context (±30 chars)
            idx = text.lower().find(marker.lower())
            start = max(0, idx - 15)
            end = min(len(text), idx + len(marker) + 30)
            snippet = text[start:end].strip()
            found.append(f"Explicit marker '{marker}': ...{snippet}...")
    return found


def detect_repetition(text: str) -> list[str]:
    """Detect phrases that appear repeatedly — a sign of teacher emphasis."""
    # Split into sentences
    sentences = re.split(r"[.。!！?？\n]", text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 10]

    if len(sentences) < 3:
        return []

    # Use bigram overlap as a simple repetition proxy
    found: list[str] = []
    seen_bigrams: Counter = Counter()
    for sentence in sentences:
        words = sentence.lower().split()
        bigrams = {" ".join(words[i : i + 2]) for i in range(len(words) - 1)}
        for bg in bigrams:
            seen_bigrams[bg] += 1

    repeated = [bg for bg, count in seen_bigrams.most_common(10) if count >= 3 and len(bg) > 8]
    if repeated:
        found.append(f"Repeated phrases (appeared ≥3 times): {', '.join(repeated[:5])}")

    return found


def detect_contrast_patterns(text: str) -> list[str]:
    """Detect contrast/comparison patterns — teacher distinguishing concepts."""
    patterns = [
        r"(不同于|与.*?不同|区别|差异|区分|对比|比较)",
        r"(not\s+the\s+same|difference\s+between|distinguish|contrast|compare)",
        r"(不是.*?而是)",
        r"(rather\s+than|as\s+opposed\s+to|on\s+the\s+other\s+hand)",
    ]
    found: list[str] = []
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            found.append(f"Contrast pattern detected: {', '.join(matches[:3])}")
    return found


def detect_time_density(
    chunk: Chunk, avg_speed: float | None = None
) -> list[str]:
    """Detect if teacher slowed down (high time density) — often signals important content."""
    if chunk.end_seconds <= chunk.start_seconds:
        return []

    duration = chunk.end_seconds - chunk.start_seconds
    word_count = len(chunk.raw_text.split())
    if word_count == 0:
        return []

    words_per_minute = word_count / (duration / 60)

    signals: list[str] = []
    # Typical lecture speech: 100-160 WPM. Below 80 WPM = deliberate slowdown.
    if words_per_minute < 80:
        signals.append(
            f"Slow pace: {words_per_minute:.0f} WPM over {duration:.0f}s "
            f"(typical lecture: 100-160 WPM) — possible deliberate emphasis"
        )
    elif avg_speed is not None and words_per_minute < avg_speed * 0.7:
        signals.append(
            f"Relative slowdown: {words_per_minute:.0f} WPM vs average {avg_speed:.0f} WPM"
        )

    return signals


def detect_visual_density(chunk: Chunk) -> list[str]:
    """Detect if teacher spent disproportionate time on one slide/board.

    Many visuals in one chunk → teacher may be going through detailed material.
    """
    signals: list[str] = []
    visual_count = len(chunk.associated_visuals)
    if visual_count >= 3:
        duration = chunk.end_seconds - chunk.start_seconds
        if duration > 0:
            seconds_per_visual = duration / visual_count
            signals.append(
                f"Visual density: {visual_count} screenshots over {duration:.0f}s "
                f"({seconds_per_visual:.0f}s per visual)"
            )
    return signals


def collect_signals(chunk: Chunk, avg_speed: float | None = None) -> list[str]:
    """Collect all emphasis signals for a chunk."""
    signals: list[str] = []
    signals.extend(detect_explicit_markers(chunk.raw_text))
    signals.extend(detect_repetition(chunk.raw_text))
    signals.extend(detect_contrast_patterns(chunk.raw_text))
    signals.extend(detect_time_density(chunk, avg_speed))
    signals.extend(detect_visual_density(chunk))
    return signals


# ---------------------------------------------------------------------------
# Emphasis extraction (LLM)
# ---------------------------------------------------------------------------


def extract_emphasis(
    narrative_result: NarrativeResult,
    chunk: Chunk,
    llm: LLMClient,
    course_title: str = "",
) -> EmphasisResult:
    """Extract emphasis from a cleaned narrative using LLM.

    Args:
        narrative_result: Phase 2 output (cleaned narrative).
        chunk: Original chunk (for raw text and timing signals).
        llm: LLM client instance.
        course_title: Optional course name for context.

    Returns:
        EmphasisResult with structured emphasis data.
    """
    # Phase 3a: Rule-based signal detection
    signals = collect_signals(chunk)

    # Phase 3b: LLM extraction
    user_prompt = build_emphasis_prompt(
        cleaned_narrative=narrative_result.cleaned_narrative,
        raw_transcript=chunk.raw_text,
        emphasis_signals=signals,
        course_title=course_title,
        section_title=chunk.title or f"Section {chunk.index}",
    )

    try:
        data = llm.complete_structured(
            EMPHASIS_SYSTEM,
            user_prompt,
            EmphasisData,
        )
        return EmphasisResult(
            chunk_index=chunk.index,
            data=data,
            signals_detected=signals,
            signal_count=len(signals),
            token_usage={
                "input": llm.metrics.calls[-1].input_tokens if llm.metrics.calls else 0,
                "output": llm.metrics.calls[-1].output_tokens if llm.metrics.calls else 0,
            },
            latency_ms=llm.metrics.calls[-1].latency_ms if llm.metrics.calls else 0.0,
        )
    except Exception as exc:
        # Fallback: minimal emphasis from keywords in cleaned text
        import re as _re

        words = _re.findall(r"[A-Za-z一-鿿]{2,}", narrative_result.cleaned_narrative)
        word_freq = Counter(words)
        top_words = [w for w, _ in word_freq.most_common(10) if len(w) >= 2]

        return EmphasisResult(
            chunk_index=chunk.index,
            data=EmphasisData(
                emphasis_points=[f"Key concept: {narrative_result.cleaned_narrative[:200]}..."],
                keywords=top_words[:8],
                question="",
                confidence=0.3,
            ),
            signals_detected=signals,
            signal_count=len(signals),
            error=str(exc),
        )


def extract_all(
    narrative_results: list[NarrativeResult],
    chunks: list[Chunk],
    llm: LLMClient | None = None,
    course_title: str = "",
    provider: str = "anthropic",
    model: str = "",
    api_key: str = "",
) -> EmphasisBatchResult:
    """Extract emphasis from all chunks.

    Args:
        narrative_results: Phase 2 outputs.
        chunks: Original chunks.
        llm: LLM client (created if not provided).
        course_title: Course name for context.
        provider: LLM provider if creating a client.
        model: Model name if creating a client.
        api_key: API key if creating a client.
    """
    if llm is None:
        llm = create_client(provider=provider, model=model, api_key=api_key)

    # Build lookup from chunk_index → chunk
    chunk_map: dict[int, Chunk] = {c.index: c for c in chunks}

    # Calculate average speaking speed for time-density comparison
    all_words = sum(len(c.raw_text.split()) for c in chunks)
    total_duration = sum(
        (c.end_seconds - c.start_seconds) for c in chunks if c.end_seconds > c.start_seconds
    )
    avg_wpm = (all_words / (total_duration / 60)) if total_duration > 0 else None

    results: list[EmphasisResult] = []
    errors = 0
    for nr in narrative_results:
        chunk = chunk_map.get(nr.chunk_index)
        if chunk is None:
            continue
        result = extract_emphasis(nr, chunk, llm, course_title)
        results.append(result)
        if result.error:
            errors += 1

    avg_confidence = (
        sum(r.data.confidence for r in results) / len(results) if results else 0
    )
    total_signals = sum(r.signal_count for r in results)

    summary = {
        "total_chunks": len(results),
        "errors": errors,
        "avg_confidence": avg_confidence,
        "total_signals_detected": total_signals,
        "avg_signals_per_chunk": total_signals / len(results) if results else 0,
    }

    return EmphasisBatchResult(results=results, summary=summary)
