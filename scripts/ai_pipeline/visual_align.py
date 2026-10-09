"""
Phase 4 — Visual Alignment.

Matches screenshots (board captures, slides, diagrams) to teaching chunks
using timestamp matching as primary signal and content-based matching as fallback.
Deduplicates near-identical frames.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

_COMMANDS_DIR = Path(__file__).resolve().parent.parent / "commands"
if str(_COMMANDS_DIR) not in sys.path:
    sys.path.insert(0, str(_COMMANDS_DIR))

from .chunker import Chunk, VisualTimestamp


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class AlignedVisual(BaseModel):
    """A visual asset aligned to a specific chunk."""

    timestamp: str = ""
    seconds: float = 0.0
    source_type: str = "screenshot"  # screenshot, slide, board, diagram
    path: str = ""
    caption: str = ""
    alt_text: str = ""
    chunk_index: int = 0
    match_method: str = "timestamp"  # timestamp | content_similarity | manual
    is_duplicate: bool = False


class VisualAlignmentResult(BaseModel):
    """Output of visual alignment phase."""

    alignments: list[AlignedVisual] = Field(default_factory=list)
    unaligned: list[VisualTimestamp] = Field(default_factory=list)
    duplicates_removed: int = 0
    summary: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def _time_proximity(a: VisualTimestamp, b: VisualTimestamp, threshold: float = 3.0) -> bool:
    """Check if two visuals are very close in time — likely same content."""
    return abs(a.seconds - b.seconds) < threshold


def _same_source_type(a: VisualTimestamp, b: VisualTimestamp) -> bool:
    """Check if two visuals are the same type."""
    return a.source_type == b.source_type


def deduplicate(
    visuals: list[VisualTimestamp],
    time_threshold: float = 3.0,
) -> tuple[list[VisualTimestamp], int]:
    """Remove near-duplicate visuals (same type within time_threshold seconds).

    Keeps the first occurrence. Returns (deduped_list, removed_count).
    """
    if len(visuals) <= 1:
        return visuals, 0

    sorted_visuals = sorted(visuals, key=lambda v: v.seconds)
    kept: list[VisualTimestamp] = [sorted_visuals[0]]
    removed = 0

    for i in range(1, len(sorted_visuals)):
        current = sorted_visuals[i]
        previous = kept[-1]

        if _time_proximity(previous, current, time_threshold) and _same_source_type(
            previous, current
        ):
            removed += 1
            continue
        kept.append(current)

    return kept, removed


# ---------------------------------------------------------------------------
# Timestamp matching
# ---------------------------------------------------------------------------


def align_by_timestamp(
    chunks: list[Chunk],
    visuals: list[VisualTimestamp],
    window_before: float = 10.0,
    window_after: float = 5.0,
) -> tuple[list[AlignedVisual], list[VisualTimestamp]]:
    """Match visuals to chunks based on timestamp windows.

    A visual belongs to a chunk if its timestamp falls within:
    [chunk.start_seconds - window_before, chunk.end_seconds + window_after]

    Returns (aligned, unaligned).
    """
    aligned: list[AlignedVisual] = []
    unaligned: list[VisualTimestamp] = []
    chunk_list = sorted(chunks, key=lambda c: c.start_seconds)

    for visual in visuals:
        matched = False
        for chunk in chunk_list:
            window_start = chunk.start_seconds - window_before
            window_end = chunk.end_seconds + window_after
            if window_start <= visual.seconds <= window_end:
                aligned.append(
                    AlignedVisual(
                        timestamp=visual.timestamp,
                        seconds=visual.seconds,
                        source_type=visual.source_type,
                        path=visual.path,
                        caption=visual.caption,
                        alt_text=visual.alt_text,
                        chunk_index=chunk.index,
                        match_method="timestamp",
                    )
                )
                matched = True
                break
        if not matched:
            unaligned.append(visual)

    return aligned, unaligned


# ---------------------------------------------------------------------------
# Content-based fallback matching
# ---------------------------------------------------------------------------

# Simple OCR-free text overlap: compare visual caption/filename tokens
# with chunk text tokens. This is a fallback, not primary.


def _token_overlap(visual: VisualTimestamp, chunk: Chunk) -> float:
    """Compute token overlap between visual metadata and chunk text."""
    visual_text = f"{visual.caption} {visual.alt_text} {Path(visual.path).stem}"
    visual_tokens = set(visual_text.lower().split())

    chunk_tokens = set(chunk.raw_text.lower().split())

    if not visual_tokens or not chunk_tokens:
        return 0.0

    overlap = visual_tokens & chunk_tokens
    return len(overlap) / len(visual_tokens)


def align_by_content(
    chunks: list[Chunk],
    unaligned: list[VisualTimestamp],
    min_overlap: float = 0.05,
) -> list[AlignedVisual]:
    """Match remaining unaligned visuals to chunks by content similarity.

    Only used as fallback when timestamp matching fails.
    """
    aligned: list[AlignedVisual] = []
    for visual in unaligned:
        best_chunk = None
        best_score = 0.0
        for chunk in chunks:
            score = _token_overlap(visual, chunk)
            if score > best_score:
                best_score = score
                best_chunk = chunk

        if best_chunk and best_score >= min_overlap:
            aligned.append(
                AlignedVisual(
                    timestamp=visual.timestamp,
                    seconds=visual.seconds,
                    source_type=visual.source_type,
                    path=visual.path,
                    caption=visual.caption,
                    alt_text=visual.alt_text,
                    chunk_index=best_chunk.index,
                    match_method="content_similarity",
                )
            )

    return aligned


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def align(
    chunks: list[Chunk],
    visuals: list[VisualTimestamp],
    dedup_threshold: float = 3.0,
    timestamp_window_before: float = 10.0,
    timestamp_window_after: float = 5.0,
) -> VisualAlignmentResult:
    """Main entry point: align visuals to chunks.

    1. Deduplicate near-identical frames
    2. Primary: timestamp-based matching
    3. Fallback: content-based matching for unaligned

    Args:
        chunks: Teaching units from Phase 1.
        visuals: Timestamped visual assets.
        dedup_threshold: Seconds within which same-type visuals are duplicates.
        timestamp_window_before: Seconds before chunk start to include visuals.
        timestamp_window_after: Seconds after chunk end to include visuals.

    Returns:
        VisualAlignmentResult with alignments and stats.
    """
    # Step 1: Deduplicate
    deduped, removed = deduplicate(visuals, dedup_threshold)

    # Step 2: Timestamp matching
    timestamp_aligned, unaligned = align_by_timestamp(
        chunks, deduped, timestamp_window_before, timestamp_window_after
    )

    # Step 3: Content-based fallback
    content_aligned = align_by_content(chunks, unaligned)

    # Remaining unaligned
    aligned_indices = {a.seconds for a in timestamp_aligned + content_aligned}
    still_unaligned = [v for v in unaligned if v.seconds not in aligned_indices]

    all_aligned = timestamp_aligned + content_aligned

    summary = {
        "total_visuals_input": len(visuals),
        "duplicates_removed": removed,
        "total_aligned": len(all_aligned),
        "by_timestamp": len(timestamp_aligned),
        "by_content": len(content_aligned),
        "still_unaligned": len(still_unaligned),
        "chunks_with_visuals": len({a.chunk_index for a in all_aligned}),
        "chunks_total": len(chunks),
    }

    return VisualAlignmentResult(
        alignments=all_aligned,
        unaligned=still_unaligned,
        duplicates_removed=removed,
        summary=summary,
    )
