"""
Phase 1 — Hybrid Chunking.

Splits raw transcript + visual timestamps into teaching units (Chunks).
Strategy: deterministic anchor points first (timestamp gaps, slide transitions),
then optional LLM refinement for ambiguous boundaries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class TranscriptLine(BaseModel):
    """A single line from a transcript with optional timestamp."""

    timestamp: str = ""  # HH:MM:SS or HH:MM:SS.mmm
    text: str = ""
    start_seconds: float | None = None


class VisualTimestamp(BaseModel):
    """Timestamp of a screenshot, slide change, or board capture."""

    timestamp: str = ""
    seconds: float = 0.0
    source_type: str = "screenshot"  # screenshot, slide, board
    path: str = ""  # file path to the image
    caption: str = ""
    alt_text: str = ""


class Chunk(BaseModel):
    """A single teaching unit — one NoteSection worth of raw material."""

    index: int = 0
    title: str = ""  # Generated later, placeholder for now
    start_seconds: float = 0.0
    end_seconds: float = 0.0
    start_timestamp: str = ""
    end_timestamp: str = ""
    raw_text: str = ""
    transcript_lines: list[TranscriptLine] = Field(default_factory=list)
    associated_visuals: list[VisualTimestamp] = Field(default_factory=list)
    # Boundary confidence: how sure we are this is a natural teaching break
    boundary_confidence: float = 1.0
    boundary_reason: str = ""


class ChunkerResult(BaseModel):
    """Output of the chunking phase."""

    chunks: list[Chunk] = Field(default_factory=list)
    total_duration_seconds: float = 0.0
    method: str = "deterministic"  # "deterministic" | "hybrid"
    stats: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------


def parse_timestamp(ts: str) -> float | None:
    """Parse HH:MM:SS or HH:MM:SS.mmm to seconds."""
    ts = ts.strip()
    # Handle SRT-style: 00:01:23,456
    ts = ts.replace(",", ".")
    parts = ts.split(":")
    if not (2 <= len(parts) <= 3):
        return None
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except ValueError:
        return None


def format_timestamp(seconds: float) -> str:
    """Format seconds as HH:MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# ---------------------------------------------------------------------------
# Transcript parsing
# ---------------------------------------------------------------------------

# Patterns for SRT/VTT timestamp lines
_SRT_TS_RE = re.compile(r"^(\d{1,3}:\d{2}:\d{2}[.,]\d{3})\s*-->\s*(\d{1,3}:\d{2}:\d{2}[.,]\d{3})$")
_VTT_TS_RE = re.compile(r"^(\d{1,3}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{1,3}:\d{2}:\d{2}\.\d{3})")


def parse_transcript(text: str, format: str = "auto") -> list[TranscriptLine]:
    """Parse SRT, VTT, or plain text transcript into TranscriptLine list.

    For SRT/VTT: extracts text lines with their start timestamps.
    For plain text: treats each line as a segment without timestamps.
    """
    lines = text.split("\n")
    result: list[TranscriptLine] = []
    current_ts: str = ""
    current_seconds: float | None = None

    if format == "auto":
        # Detect format: look for timestamp patterns in first 50 lines
        sample = "\n".join(lines[:50])
        if _SRT_TS_RE.search(sample) or _VTT_TS_RE.search(sample):
            format = "srt"
        else:
            format = "plain"

    if format == "plain":
        for line in lines:
            stripped = line.strip()
            if stripped:
                result.append(TranscriptLine(text=stripped))
        return result

    # SRT/VTT parsing
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Skip index numbers and empty lines
        ts_match = _SRT_TS_RE.search(line) or _VTT_TS_RE.search(line)
        if ts_match:
            start_ts = ts_match.group(1).replace(",", ".")
            current_seconds = parse_timestamp(start_ts)
            current_ts = start_ts
        elif line and not line.isdigit():
            # Content line
            result.append(
                TranscriptLine(
                    timestamp=current_ts,
                    text=line,
                    start_seconds=current_seconds,
                )
            )
        i += 1

    return result


# ---------------------------------------------------------------------------
# Boundary detection
# ---------------------------------------------------------------------------

# Teacher transition phrases (Chinese + English) that signal topic shifts
TRANSITION_PATTERNS = [
    # Chinese
    r"接下来[我们]?[来]?(讲|看|介绍|讨论|进入)",
    r"下[一]?个[话题|知识点|部分|模块|内容]",
    r"现在[我们]?(来看|讲|转到|进入)",
    r"好了[,，]?(接下来|下面|现在)",
    r"以上[就]?是.*?(接下|下面|现在)",
    r"(第一章|第二章|第三章|第[四五六七八九十]章)",
    r"(第一节|第二节|第三节|第[四五六七八九十]节)",
    r"先[让]?[我们]?(复习|回顾|总结)一下",
    r"(总结|小结)[一]?下",
    r"休息.*?[再继再]",
    # English
    r"(now|next|let'?s)\s+(move on|talk about|discuss|look at|cover|turn to)",
    r"moving on to",
    r"that (covers|concludes|wraps up)",
    r"(in the |this )(next |following )?(section|chapter|part|module)",
    r"(firstly|secondly|thirdly|finally)[,，]",
    r"to summarize",
]


def _is_transition(line: str) -> bool:
    """Check if a transcript line contains a transition phrase."""
    for pattern in TRANSITION_PATTERNS:
        if re.search(pattern, line, re.IGNORECASE):
            return True
    return False


def detect_boundaries(
    transcript: list[TranscriptLine],
    visuals: list[VisualTimestamp],
    min_chunk_seconds: float = 120.0,
    max_chunk_seconds: float = 600.0,
    silence_gap_threshold: float = 30.0,
) -> list[int]:
    """Detect chunk boundary indices in the transcript.

    Returns list of line indices where a new chunk starts.
    The first chunk always starts at index 0.

    Strategy (in priority order):
    1. Visual transitions (slide changes) — strongest signal
    2. Timestamp gaps > silence_gap_threshold
    3. Transition phrases
    4. Minimum chunk duration enforcement
    """
    n = len(transcript)
    if n == 0:
        return [0]

    boundaries: list[int] = [0]

    # Collect candidate boundary scores per line index
    scores: list[float] = [0.0] * n

    # 1. Visual transitions: score 1.0
    visual_seconds = {v.seconds for v in visuals if v.seconds > 0}
    for i, line in enumerate(transcript):
        if line.start_seconds is not None:
            # Check if a visual change happens within 5s of this line
            for vs in visual_seconds:
                if abs(line.start_seconds - vs) < 5.0:
                    scores[i] = max(scores[i], 1.0)

    # 2. Timestamp gaps
    for i in range(1, n):
        prev_ts = transcript[i - 1].start_seconds
        curr_ts = transcript[i].start_seconds
        if prev_ts is not None and curr_ts is not None:
            gap = curr_ts - prev_ts
            if gap > silence_gap_threshold:
                scores[i] = max(scores[i], 0.9)
            elif gap > silence_gap_threshold * 0.5:
                scores[i] = max(scores[i], 0.5)

    # 3. Transition phrases
    for i in range(n):
        if _is_transition(transcript[i].text):
            scores[i] = max(scores[i], 0.7)

    # Build boundaries with min_chunk constraint
    last_boundary_time: float | None = None
    if transcript[0].start_seconds is not None:
        last_boundary_time = transcript[0].start_seconds

    for i in range(1, n):
        curr_time = transcript[i].start_seconds
        if scores[i] >= 0.7:
            # Strong boundary signal
            if last_boundary_time is not None and curr_time is not None:
                duration = curr_time - last_boundary_time
                if duration >= min_chunk_seconds:
                    boundaries.append(i)
                    last_boundary_time = curr_time
            else:
                boundaries.append(i)

    # Enforce max_chunk_seconds: insert forced splits for overly long chunks
    final_boundaries: list[int] = [0]
    for i, b_idx in enumerate(boundaries[1:], start=1):
        prev_idx = final_boundaries[-1]
        prev_time = transcript[prev_idx].start_seconds
        curr_time = transcript[b_idx].start_seconds if b_idx < n else None
        if prev_time is not None and curr_time is not None:
            gap = curr_time - prev_time
            if gap > max_chunk_seconds:
                # Need intermediate splits
                mid_idx = _find_mid_split(transcript, prev_idx, b_idx, min_chunk_seconds)
                if mid_idx and mid_idx not in final_boundaries:
                    final_boundaries.append(mid_idx)
        final_boundaries.append(b_idx)

    return sorted(set(final_boundaries))


def _find_mid_split(
    transcript: list[TranscriptLine],
    start_idx: int,
    end_idx: int,
    min_seconds: float,
) -> int | None:
    """Find the best split point within an over-long segment."""
    if start_idx >= end_idx:
        return None

    start_ts = transcript[start_idx].start_seconds or 0
    end_ts = transcript[end_idx].start_seconds or 0
    target_ts = start_ts + max(min_seconds, (end_ts - start_ts) / 2)

    best_idx = None
    best_dist = float("inf")
    for i in range(start_idx + 1, end_idx):
        ts = transcript[i].start_seconds
        if ts is None:
            continue
        dist = abs(ts - target_ts)
        # Prefer lines with transition phrases within ±10 lines
        bonus = 0
        for j in range(max(start_idx, i - 10), min(end_idx, i + 10)):
            if _is_transition(transcript[j].text):
                bonus = 30  # seconds equivalent
                break
        if dist - bonus < best_dist:
            best_dist = dist - bonus
            best_idx = i

    return best_idx


# ---------------------------------------------------------------------------
# Main chunker
# ---------------------------------------------------------------------------


def build_chunks(
    transcript: list[TranscriptLine],
    visuals: list[VisualTimestamp],
    boundaries: list[int],
) -> tuple[list[Chunk], dict[str, Any]]:
    """Build Chunk objects from transcript and boundary indices."""

    chunks: list[Chunk] = []
    for i, start_idx in enumerate(boundaries):
        end_idx = boundaries[i + 1] if i + 1 < len(boundaries) else len(transcript)

        chunk_lines = transcript[start_idx:end_idx]
        if not chunk_lines:
            continue

        raw_text = " ".join(line.text for line in chunk_lines if line.text)

        start_seconds = chunk_lines[0].start_seconds or 0.0
        end_seconds = chunk_lines[-1].start_seconds or 0.0

        # Match visuals to this chunk by time window
        chunk_visuals = [
            v for v in visuals if start_seconds - 5.0 <= v.seconds <= end_seconds + 5.0
        ]

        chunk = Chunk(
            index=i + 1,
            title="",
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            start_timestamp=format_timestamp(start_seconds),
            end_timestamp=format_timestamp(end_seconds),
            raw_text=raw_text,
            transcript_lines=chunk_lines,
            associated_visuals=chunk_visuals,
            boundary_confidence=1.0 if i > 0 else 1.0,
            boundary_reason="deterministic" if i > 0 else "start",
        )
        chunks.append(chunk)

    # Calculate stats
    durations = [c.end_seconds - c.start_seconds for c in chunks if c.end_seconds > c.start_seconds]
    stats = {
        "chunk_count": len(chunks),
        "avg_duration_seconds": sum(durations) / len(durations) if durations else 0,
        "min_duration_seconds": min(durations) if durations else 0,
        "max_duration_seconds": max(durations) if durations else 0,
        "total_duration_seconds": sum(durations),
        "visuals_matched": sum(len(c.associated_visuals) for c in chunks),
        "visuals_total": len(visuals),
    }

    return chunks, stats


def chunk(
    transcript_text: str,
    transcript_format: str = "auto",
    visuals: list[VisualTimestamp] | None = None,
    min_chunk_seconds: float = 120.0,
    max_chunk_seconds: float = 600.0,
    silence_gap_threshold: float = 30.0,
    llm_client: Any = None,  # Optional LLMClient for hybrid mode
) -> ChunkerResult:
    """Main entry point: chunk a transcript into teaching units.

    Args:
        transcript_text: Raw transcript (SRT, VTT, or plain text).
        transcript_format: "srt", "vtt", "plain", or "auto" for detection.
        visuals: Timestamped screenshots/slides/board captures.
        min_chunk_seconds: Minimum duration per chunk.
        max_chunk_seconds: Maximum duration before forced split.
        silence_gap_threshold: Timestamp gap in seconds that triggers a boundary.
        llm_client: If provided, enables hybrid mode — LLM refines boundaries
                     for ambiguous cases (0.4 ≤ score < 0.7).

    Returns:
        ChunkerResult with chunks and stats.
    """
    visuals = visuals or []
    transcript_lines = parse_transcript(transcript_text, transcript_format)

    if not transcript_lines:
        return ChunkerResult(chunks=[], method="deterministic", stats={"error": "No transcript lines parsed"})

    # Detect boundaries
    boundaries = detect_boundaries(
        transcript_lines,
        visuals,
        min_chunk_seconds=min_chunk_seconds,
        max_chunk_seconds=max_chunk_seconds,
        silence_gap_threshold=silence_gap_threshold,
    )

    # Build chunks
    chunks, stats = build_chunks(transcript_lines, visuals, boundaries)

    method = "hybrid" if llm_client else "deterministic"

    # TODO: Hybrid mode — use LLM to refine boundaries for ambiguous cases
    # if llm_client and any low-confidence boundaries exist:
    #     chunks = _llm_refine_boundaries(chunks, transcript_lines, llm_client)

    total_duration = max(c.end_seconds for c in chunks) if chunks else 0.0

    return ChunkerResult(
        chunks=chunks,
        total_duration_seconds=total_duration,
        method=method,
        stats=stats,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    import argparse
    import json
    import sys
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Chunk a transcript into teaching units.")
    parser.add_argument("--transcript", required=True, help="Path to transcript file (SRT/VTT/TXT).")
    parser.add_argument("--format", default="auto", choices=["auto", "srt", "vtt", "plain"])
    parser.add_argument("--visuals", help="Path to JSON file with visual timestamps.")
    parser.add_argument("--output", help="Path for output JSON (default: stdout).")
    parser.add_argument("--min-chunk", type=float, default=120.0)
    parser.add_argument("--max-chunk", type=float, default=600.0)
    parser.add_argument("--silence-gap", type=float, default=30.0)
    args = parser.parse_args()

    transcript_text = Path(args.transcript).read_text(encoding="utf-8-sig", errors="ignore")

    visuals = []
    if args.visuals:
        raw = json.loads(Path(args.visuals).read_text(encoding="utf-8"))
        visuals = [VisualTimestamp(**v) for v in raw]

    result = chunk(
        transcript_text,
        transcript_format=args.format,
        visuals=visuals,
        min_chunk_seconds=args.min_chunk,
        max_chunk_seconds=args.max_chunk,
        silence_gap_threshold=args.silence_gap,
    )

    output_json = result.model_dump_json(indent=2, exclude_none=True)
    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
        print(f"Chunks written to {args.output}")
    else:
        print(output_json)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
