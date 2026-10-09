"""
Phase 5 — Global Review.

Cross-chunk consistency check, terminology unification, gap detection,
cross-referencing, global summary generation, and topic index generation.

Runs once after all per-chunk phases complete. Uses LLM for semantic checks
and deterministic logic for mechanical tasks (topic index, dedup).
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

_COMMANDS_DIR = Path(__file__).resolve().parent.parent / "commands"
if str(_COMMANDS_DIR) not in sys.path:
    sys.path.insert(0, str(_COMMANDS_DIR))

from ._llm import LLMClient, create_client
from .chunker import Chunk
from .emphasis import EmphasisResult
from .narrative import NarrativeResult
from .prompts.global_review import (
    GLOBAL_REVIEW_SCHEMA,
    GLOBAL_REVIEW_SYSTEM,
    build_global_review_prompt,
)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class Contradiction(BaseModel):
    section_a: int
    section_b: int
    issue: str
    resolution: str = ""


class TerminologyFix(BaseModel):
    section_index: int
    original_term: str
    canonical_term: str


class Gap(BaseModel):
    section_index: int
    description: str
    suggested_fix: str = ""


class CrossReference(BaseModel):
    from_section: int
    to_section: int
    note: str


class GlobalReviewData(BaseModel):
    """LLM-produced global review output."""

    contradictions: list[Contradiction] = Field(default_factory=list)
    terminology_fixes: list[TerminologyFix] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    cross_references: list[CrossReference] = Field(default_factory=list)
    global_takeaways: list[str] = Field(default_factory=list)
    global_pitfalls: list[str] = Field(default_factory=list)
    overview: str = ""
    review_steps: list[str] = Field(default_factory=list)


class TopicIndexItem(BaseModel):
    timestamp: str
    topic: str
    subtopic: str = ""
    section_ref: str = ""


class GlobalReviewResult(BaseModel):
    """Final output of the global review phase."""

    data: GlobalReviewData = Field(default_factory=GlobalReviewData)
    topic_index: list[TopicIndexItem] = Field(default_factory=list)
    # Deduplicated keywords across all sections
    unified_keywords: list[str] = Field(default_factory=list)
    # Merged formulas from all sections
    formulas: list[str] = Field(default_factory=list)
    # Review time estimate
    estimated_review_minutes: int = 30
    # Stats
    token_usage: dict[str, int] = Field(default_factory=dict)
    error: str | None = None


# ---------------------------------------------------------------------------
# Deterministic: Topic index generation
# ---------------------------------------------------------------------------


def generate_topic_index(chunks: list[Chunk]) -> list[TopicIndexItem]:
    """Generate timestamped topic index from chunk boundaries.

    Uses chunk start times and titles. LLM can later refine the topic names.
    """
    items: list[TopicIndexItem] = []
    for chunk in chunks:
        items.append(
            TopicIndexItem(
                timestamp=chunk.start_timestamp,
                topic=chunk.title or f"Section {chunk.index}",
                subtopic="",
                section_ref=f"§{chunk.index}",
            )
        )
    return items


# ---------------------------------------------------------------------------
# Deterministic: Keyword dedup & formula extraction
# ---------------------------------------------------------------------------


def dedup_keywords(emphasis_results: list[EmphasisResult]) -> list[str]:
    """Combine and deduplicate keywords across all chunks."""
    all_keywords: list[str] = []
    for r in emphasis_results:
        all_keywords.extend(r.data.keywords)

    seen: set[str] = set()
    unified: list[str] = []
    for kw in all_keywords:
        cleaned = kw.strip().lower()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            unified.append(kw.strip())
    return unified[:15]


def extract_all_formulas(text: str) -> list[str]:
    """Extract LaTeX formulas from text."""
    formulas: list[str] = []
    patterns = [
        r"\\\[(.+?)\\\]",
        r"\\\((.+?)\\\)",
        r"\$\$(.+?)\$\$",
        r"\$(.+?)\$",
    ]
    for pattern in patterns:
        matches = re.findall(pattern, text, flags=re.DOTALL)
        for m in matches:
            cleaned = " ".join(m.split())
            if cleaned not in formulas:
                formulas.append(cleaned)
    return formulas


# ---------------------------------------------------------------------------
# Build section summary for LLM input
# ---------------------------------------------------------------------------


def build_section_summaries(
    chunks: list[Chunk],
    narrative_results: list[NarrativeResult],
    emphasis_results: list[EmphasisResult],
) -> str:
    """Build a compact section-summary string for the LLM global review prompt."""
    # Create lookups
    narr_map = {r.chunk_index: r for r in narrative_results}
    emph_map = {r.chunk_index: r for r in emphasis_results}

    parts: list[str] = []
    for chunk in chunks:
        narr = narr_map.get(chunk.index)
        emph = emph_map.get(chunk.index)

        lines = [
            f"## Section {chunk.index}: {chunk.title or 'Untitled'}",
            f"Time: {chunk.start_timestamp} – {chunk.end_timestamp}",
            f"Duration: {chunk.end_seconds - chunk.start_seconds:.0f}s",
        ]

        if emph:
            lines.append(f"Emphasis: {'; '.join(emph.data.emphasis_points[:3])}")
            lines.append(f"Keywords: {', '.join(emph.data.keywords)}")

        if narr:
            # Include first ~200 chars as preview
            preview = narr.cleaned_narrative[:200]
            lines.append(f"Preview: {preview}...")

        parts.append("\n".join(lines))

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def review(
    chunks: list[Chunk],
    narrative_results: list[NarrativeResult],
    emphasis_results: list[EmphasisResult],
    all_cleaned_text: str = "",
    course_title: str = "",
    lesson_title: str = "",
    llm: LLMClient | None = None,
    provider: str = "anthropic",
    model: str = "",
    api_key: str = "",
) -> GlobalReviewResult:
    """Run global review across all chunks.

    Args:
        chunks: All teaching units from Phase 1.
        narrative_results: All cleaned narratives from Phase 2.
        emphasis_results: All emphasis extractions from Phase 3.
        all_cleaned_text: Concatenated cleaned narratives (for formula extraction).
        course_title: Course name.
        lesson_title: Lesson name.
        llm: LLM client instance.
        provider: LLM provider if creating a client.
        model: Model name if creating a client.
        api_key: API key if creating a client.
    """
    if llm is None:
        llm = create_client(provider=provider, model=model, api_key=api_key)

    # Build section summaries for LLM
    section_summaries = build_section_summaries(chunks, narrative_results, emphasis_results)

    total_duration = sum(
        c.end_seconds - c.start_seconds for c in chunks if c.end_seconds > c.start_seconds
    )
    total_minutes = total_duration / 60

    user_prompt = build_global_review_prompt(
        section_summaries=section_summaries,
        course_title=course_title,
        lesson_title=lesson_title,
        total_sections=len(chunks),
        total_duration_minutes=total_minutes,
    )

    try:
        data = llm.complete_structured(
            GLOBAL_REVIEW_SYSTEM,
            user_prompt,
            GlobalReviewData,
        )
    except Exception as exc:
        # Fallback: minimal global review
        data = GlobalReviewData(
            global_takeaways=[f"Section {c.index}: {c.title or 'Untitled'}" for c in chunks[:5]],
            overview=f"{course_title} — {lesson_title}",
            review_steps=["Review each section in order", "Focus on emphasized concepts"],
        )

    # Deterministic steps
    topic_index = generate_topic_index(chunks)
    unified_keywords = dedup_keywords(emphasis_results)

    # Extract formulas from all cleaned text
    full_text = all_cleaned_text or " ".join(
        nr.cleaned_narrative for nr in narrative_results
    )
    formulas = extract_all_formulas(full_text)

    # Estimate review time: ~2 min per section + reading time
    word_count = len(full_text.split())
    reading_minutes = word_count / 180
    estimated_review = max(10, int(len(chunks) * 2 + reading_minutes))

    usage = {}
    if llm.metrics.calls:
        last_call = llm.metrics.calls[-1]
        usage = {"input": last_call.input_tokens, "output": last_call.output_tokens}

    error_msg = None
    if isinstance(data, GlobalReviewData) is False:
        error_msg = "LLM review failed, using fallback"
    elif not data.global_takeaways:
        error_msg = "LLM returned empty takeaways"

    return GlobalReviewResult(
        data=data,
        topic_index=topic_index,
        unified_keywords=unified_keywords,
        formulas=formulas,
        estimated_review_minutes=estimated_review,
        token_usage=usage,
        error=error_msg,
    )
