"""
AI Pipeline — Unified Entry Point.

Orchestrates all 5 phases to transform raw transcript + screenshots
into structured NoteSpec JSON ready for assemble_notes.py.

Phases:
  1. Chunking       — split transcript into teaching units
  2. Narrative      — clean raw spoken text into readable form
  3. Emphasis       — extract what the teacher emphasized
  4. Visual Align   — match screenshots to chunks
  5. Global Review  — cross-chunk consistency + summary + topic index

Usage:
  python -m scripts.ai_pipeline.pipeline --transcript lecture.srt --visuals screenshots.json \
      --course-title "Physics 101" --lesson-title "Newton's Laws" \
      --output note_spec.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import ValidationError

# Allow importing from commands directory
_COMMANDS_DIR = Path(__file__).resolve().parent.parent / "commands"
if str(_COMMANDS_DIR) not in sys.path:
    sys.path.insert(0, str(_COMMANDS_DIR))

from _common import slugify
from _errors import write_error_manifest, write_manifest
from _schemas import (
    CanvasContextNote,
    MetadataSpec,
    NoteSection,
    NoteSpec,
    RepairAnnotation,
    SummarySpec,
    TopicIndexItem,
    VisualAsset,
)

from ._llm import PipelineMetrics, create_client
from .chunker import ChunkerResult, VisualTimestamp, chunk as run_chunking
from .emphasis import EmphasisBatchResult, extract_all
from .global_review import GlobalReviewResult, review
from .narrative import NarrativeBatchResult, clean_all_chunks
from .visual_align import VisualAlignmentResult, align


# ---------------------------------------------------------------------------
# Pipeline result
# ---------------------------------------------------------------------------


class PipelineResult:
    """Complete pipeline run result."""

    def __init__(self) -> None:
        self.chunker_result: ChunkerResult | None = None
        self.narrative_result: NarrativeBatchResult | None = None
        self.emphasis_result: EmphasisBatchResult | None = None
        self.visual_result: VisualAlignmentResult | None = None
        self.global_review_result: GlobalReviewResult | None = None
        self.note_spec: NoteSpec | None = None
        self.metrics: PipelineMetrics = PipelineMetrics()
        self.start_time: float = 0.0
        self.end_time: float = 0.0
        self.errors: list[str] = []

    @property
    def elapsed_seconds(self) -> float:
        return self.end_time - self.start_time


# ---------------------------------------------------------------------------
# NoteSpec assembly
# ---------------------------------------------------------------------------


def assemble_note_spec(
    pipeline_result: PipelineResult,
    course_title: str,
    lesson_title: str = "",
    note_style: str = "dual-column-teaching-aid",
    canvas_context: CanvasContextNote | None = None,
) -> NoteSpec:
    """Build a NoteSpec from pipeline results.

    Maps each processed chunk to one NoteSection with dual-column fields populated.
    """
    cr = pipeline_result.chunker_result
    nr = pipeline_result.narrative_result
    er = pipeline_result.emphasis_result
    vr = pipeline_result.visual_result
    gr = pipeline_result.global_review_result

    if cr is None:
        raise ValueError("Chunker result is required")

    chunks = cr.chunks
    narr_map = {r.chunk_index: r for r in (nr.results if nr else [])}
    emph_map = {r.chunk_index: r for r in (er.results if er else [])}

    # Build visual lookup by chunk_index
    visuals_by_chunk: dict[int, list[VisualAsset]] = {}
    if vr:
        for av in vr.alignments:
            if av.is_duplicate:
                continue
            visuals_by_chunk.setdefault(av.chunk_index, []).append(
                VisualAsset(
                    type=av.source_type,  # type: ignore[arg-type]
                    path=av.path,
                    caption=av.caption,
                    alt_text=av.alt_text,
                )
            )

    # Build sections
    sections: list[NoteSection] = []
    for chunk in chunks:
        narr = narr_map.get(chunk.index)
        emph = emph_map.get(chunk.index)

        # Narrative
        teacher_narrative = narr.cleaned_narrative if narr else chunk.raw_text
        content = teacher_narrative  # fallback for non-dual-column styles

        # Emphasis
        emphasis_points = emph.data.emphasis_points if emph else []
        pitfalls = emph.data.pitfalls if emph else []
        keywords = emph.data.keywords if emph else []
        question = emph.data.question if emph else None

        # Visuals
        chunk_visuals = visuals_by_chunk.get(chunk.index, [])

        # Repair annotations for low-confidence results
        repair_annotations = []
        if emph and emph.error:
            repair_annotations.append(
                RepairAnnotation(
                    type="llm-fallback",
                    note=f"Emphasis extraction failed, used fallback: {emph.error[:200]}",
                )
            )
        elif emph and emph.data.confidence < 0.5:
            repair_annotations.append(
                RepairAnnotation(
                    type="low-confidence",
                    note=f"Emphasis confidence: {emph.data.confidence:.2f}. "
                    f"Signals detected: {emph.signal_count}",
                )
            )

        section = NoteSection(
            section_ref=f"§{chunk.index}",
            title=chunk.title or f"Section {chunk.index}",
            sources=[f"transcript {chunk.start_timestamp}–{chunk.end_timestamp}"],
            content=content,
            teacher_narrative=teacher_narrative,
            key_points=emphasis_points,
            emphasis_points=emphasis_points,
            pitfalls=pitfalls,
            keywords=keywords,
            question=question,
            visuals=chunk_visuals,
            repair_annotations=repair_annotations,
        )
        sections.append(section)

    # Summary
    summary = SummarySpec()
    if gr:
        summary = SummarySpec(
            overview=gr.data.overview or f"This lesson focused on {lesson_title or course_title}.",
            key_takeaways=gr.data.global_takeaways,
            formulas=gr.formulas,
            pitfalls=gr.data.global_pitfalls,
            review_steps=gr.data.review_steps,
        )

    # Topic index
    topic_index: list[TopicIndexItem] = []
    if gr and gr.topic_index:
        topic_index = [
            TopicIndexItem(
                timestamp=item.timestamp,
                topic=item.topic,
                subtopic=item.subtopic,
                section_ref=item.section_ref,
            )
            for item in gr.topic_index
        ]
    else:
        topic_index = [
            TopicIndexItem(
                timestamp=c.start_timestamp,
                topic=c.title or f"Section {c.index}",
                subtopic="",
                section_ref=f"§{c.index}",
            )
            for c in chunks
        ]

    # Metadata
    metadata = MetadataSpec(
        course_title=course_title,
        lesson_title=lesson_title,
        keywords=gr.unified_keywords if gr else [],
        core_concepts=[s.title for s in sections[:8]],
        formulas=gr.formulas if gr else [],
        estimated_review_time_minutes=gr.estimated_review_minutes if gr else 30,
        timeline_topics=[t.model_dump(mode="json") for t in topic_index],
        exam_assignment_relevance=canvas_context.relevance_lines if canvas_context else [],
        repair_annotations_present=any(s.repair_annotations for s in sections),
    )

    return NoteSpec(
        course_title=course_title,
        lesson_title=lesson_title,
        note_style=note_style,
        video_topic_index=topic_index,
        canvas_context=canvas_context or CanvasContextNote(),
        sections=sections,
        summary=summary,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Main pipeline runner
# ---------------------------------------------------------------------------


def run_pipeline(
    transcript_text: str,
    transcript_format: str = "auto",
    visuals: list[VisualTimestamp] | None = None,
    course_title: str = "",
    lesson_title: str = "",
    note_style: str = "dual-column-teaching-aid",
    canvas_context: CanvasContextNote | None = None,
    # Chunking params
    min_chunk_seconds: float = 120.0,
    max_chunk_seconds: float = 600.0,
    silence_gap_threshold: float = 30.0,
    # LLM config
    provider: str = "anthropic",
    model: str = "",
    api_key: str = "",
    # Phase control
    skip_llm: bool = False,
    verbose: bool = False,
) -> PipelineResult:
    """Run the full AI pipeline.

    Args:
        transcript_text: Raw transcript (SRT, VTT, or plain text).
        transcript_format: "srt", "vtt", "plain", or "auto".
        visuals: Timestamped screenshots/slides.
        course_title: Course name.
        lesson_title: Lesson name.
        note_style: Style preset for the output notes.
        canvas_context: Optional Canvas course context.
        min_chunk_seconds: Minimum chunk duration.
        max_chunk_seconds: Maximum chunk duration.
        silence_gap_threshold: Timestamp gap threshold for boundaries.
        provider: LLM provider ("anthropic" or "openai").
        model: Model name override.
        api_key: API key override.
        skip_llm: If True, skip LLM phases (2, 3, 5) for testing.
        verbose: Print progress to stderr.

    Returns:
        PipelineResult with all phase outputs and assembled NoteSpec.
    """
    result = PipelineResult()
    result.start_time = time.perf_counter()
    visuals = visuals or []

    # Shared LLM client
    llm = None
    if not skip_llm:
        try:
            llm = create_client(
                provider=provider,
                model=model,
                api_key=api_key,
                metrics=result.metrics,
            )
        except RuntimeError as exc:
            result.errors.append(f"LLM client init failed: {exc}")
            if verbose:
                print(f"[pipeline] LLM init failed, continuing without LLM: {exc}", file=sys.stderr)
            skip_llm = True

    # ── Phase 1: Chunking ──────────────────────────────────────────────
    if verbose:
        print("[pipeline] Phase 1/5: Chunking...", file=sys.stderr)

    cr = run_chunking(
        transcript_text=transcript_text,
        transcript_format=transcript_format,
        visuals=visuals,
        min_chunk_seconds=min_chunk_seconds,
        max_chunk_seconds=max_chunk_seconds,
        silence_gap_threshold=silence_gap_threshold,
    )
    result.chunker_result = cr

    if not cr.chunks:
        result.errors.append("No chunks produced — empty or unparseable transcript")
        result.end_time = time.perf_counter()
        return result

    if verbose:
        print(
            f"[pipeline]   → {len(cr.chunks)} chunks, "
            f"avg {cr.stats.get('avg_duration_seconds', 0):.0f}s each",
            file=sys.stderr,
        )

    # ── Phase 2: Narrative Cleaning ─────────────────────────────────────
    if verbose:
        print("[pipeline] Phase 2/5: Narrative cleaning...", file=sys.stderr)

    if skip_llm or llm is None:
        # Fast path: basic regex cleaning without LLM
        import re as _re

        from .narrative import NarrativeResult

        cleaned = []
        for chunk in cr.chunks:
            text = chunk.raw_text
            for filler in ["um", "uh", "嗯", "啊", "呃", "这个", "那个"]:
                text = _re.sub(rf"\b{_re.escape(filler)}\b", "", text, flags=_re.IGNORECASE)
            cleaned.append(
                NarrativeResult(
                    chunk_index=chunk.index,
                    raw_text=chunk.raw_text,
                    cleaned_narrative=_re.sub(r"\s{2,}", " ", text).strip(),
                )
            )
        result.narrative_result = NarrativeBatchResult(
            results=cleaned,
            summary={"total_chunks": len(cleaned), "method": "regex-fallback"},
        )
    else:
        result.narrative_result = clean_all_chunks(
            chunks=cr.chunks,
            llm=llm,
            course_title=course_title,
        )

    if verbose:
        nr = result.narrative_result
        print(
            f"[pipeline]   → {nr.summary.get('total_chunks')} cleaned, "
            f"{nr.summary.get('errors', 0)} errors",
            file=sys.stderr,
        )

    # ── Phase 3: Emphasis Extraction ────────────────────────────────────
    if verbose:
        print("[pipeline] Phase 3/5: Emphasis extraction...", file=sys.stderr)

    if skip_llm or llm is None:
        from .emphasis import EmphasisData, EmphasisResult

        fallback_results = []
        for nr_item in (result.narrative_result.results if result.narrative_result else []):
            words = re.findall(r"[A-Za-z一-鿿]{2,}", nr_item.cleaned_narrative)
            word_freq = Counter(words)  # noqa: F821
            top_words = [w for w, _ in word_freq.most_common(8)]

            from .emphasis import collect_signals

            chunk = next((c for c in cr.chunks if c.index == nr_item.chunk_index), None)
            signals = collect_signals(chunk) if chunk else []

            fallback_results.append(
                EmphasisResult(
                    chunk_index=nr_item.chunk_index,
                    data=EmphasisData(
                        emphasis_points=[f"Key point from section {nr_item.chunk_index}"],
                        keywords=top_words,
                        question="",
                        confidence=0.2,
                    ),
                    signals_detected=signals,
                    signal_count=len(signals),
                )
            )
        result.emphasis_result = EmphasisBatchResult(
            results=fallback_results,
            summary={"total_chunks": len(fallback_results), "method": "regex-fallback"},
        )
    else:
        result.emphasis_result = extract_all(
            narrative_results=result.narrative_result.results,
            chunks=cr.chunks,
            llm=llm,
            course_title=course_title,
        )

    if verbose:
        er = result.emphasis_result
        print(
            f"[pipeline]   → {er.summary.get('total_chunks')} sections, "
            f"avg confidence {er.summary.get('avg_confidence', 0):.2f}",
            file=sys.stderr,
        )

    # ── Phase 4: Visual Alignment ──────────────────────────────────────
    if verbose:
        print("[pipeline] Phase 4/5: Visual alignment...", file=sys.stderr)

    result.visual_result = align(chunks=cr.chunks, visuals=visuals)

    if verbose:
        vr = result.visual_result
        print(
            f"[pipeline]   → {vr.summary.get('total_aligned')}/{vr.summary.get('total_visuals_input')} "
            f"aligned, {vr.summary.get('duplicates_removed')} duplicates removed",
            file=sys.stderr,
        )

    # ── Phase 5: Global Review ──────────────────────────────────────────
    if verbose:
        print("[pipeline] Phase 5/5: Global review...", file=sys.stderr)

    all_cleaned = " ".join(
        r.cleaned_narrative for r in (result.narrative_result.results if result.narrative_result else [])
    )

    if skip_llm or llm is None:
        result.global_review_result = GlobalReviewResult()
    else:
        result.global_review_result = review(
            chunks=cr.chunks,
            narrative_results=result.narrative_result.results if result.narrative_result else [],
            emphasis_results=result.emphasis_result.results if result.emphasis_result else [],
            all_cleaned_text=all_cleaned,
            course_title=course_title,
            lesson_title=lesson_title,
            llm=llm,
        )

    if verbose:
        gr = result.global_review_result
        print(
            f"[pipeline]   → {len(gr.data.global_takeaways)} takeaways, "
            f"{len(gr.topic_index)} index entries",
            file=sys.stderr,
        )

    # ── Assemble NoteSpec ───────────────────────────────────────────────
    if verbose:
        print("[pipeline] Assembling NoteSpec...", file=sys.stderr)

    result.note_spec = assemble_note_spec(
        pipeline_result=result,
        course_title=course_title,
        lesson_title=lesson_title,
        note_style=note_style,
        canvas_context=canvas_context,
    )

    result.end_time = time.perf_counter()

    if verbose:
        total_tokens = result.metrics.total_tokens
        print(
            f"[pipeline] Done in {result.elapsed_seconds:.1f}s, "
            f"{total_tokens} tokens, "
            f"{len(result.errors)} errors",
            file=sys.stderr,
        )

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AI Pipeline: transform transcript + screenshots into structured course notes."
    )
    # Required
    parser.add_argument("--transcript", required=True, help="Path to transcript file (SRT/VTT/TXT).")
    parser.add_argument("--course-title", required=True, help="Course name.")

    # Optional inputs
    parser.add_argument("--lesson-title", default="", help="Lesson/session title.")
    parser.add_argument("--visuals", help="Path to JSON file with visual timestamps.")
    parser.add_argument("--format", default="auto", choices=["auto", "srt", "vtt", "plain"])
    parser.add_argument("--canvas-context", help="Path to Canvas context JSON file.")

    # Output
    parser.add_argument("--output", required=True, help="Path for output NoteSpec JSON.")
    parser.add_argument("--output-dir", default=".", help="Base directory for course folders.")

    # Style
    parser.add_argument(
        "--style",
        default="dual-column-teaching-aid",
        choices=["standard-structured", "cornell", "qa-sprint", "outline-map", "dual-column-teaching-aid"],
    )

    # Chunking
    parser.add_argument("--min-chunk", type=float, default=120.0)
    parser.add_argument("--max-chunk", type=float, default=600.0)
    parser.add_argument("--silence-gap", type=float, default=30.0)

    # LLM
    parser.add_argument("--provider", default="anthropic", choices=["anthropic", "openai"])
    parser.add_argument("--model", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--skip-llm", action="store_true", help="Skip LLM phases (test mode).")

    # Misc
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--manifest", help="Path for status manifest JSON.")
    parser.add_argument("--save-intermediates", action="store_true",
                       help="Save intermediate phase outputs as JSON files.")

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # Load transcript
    transcript_text = Path(args.transcript).read_text(encoding="utf-8-sig", errors="ignore")

    # Load visuals
    visuals = []
    if args.visuals:
        raw = json.loads(Path(args.visuals).read_text(encoding="utf-8"))
        visuals = [VisualTimestamp(**v) for v in raw]

    # Load Canvas context
    canvas_context = None
    if args.canvas_context:
        raw = json.loads(Path(args.canvas_context).read_text(encoding="utf-8"))
        canvas_context = CanvasContextNote(**raw)

    # Run pipeline
    result = run_pipeline(
        transcript_text=transcript_text,
        transcript_format=args.format,
        visuals=visuals,
        course_title=args.course_title,
        lesson_title=args.lesson_title,
        note_style=args.style,
        canvas_context=canvas_context,
        min_chunk_seconds=args.min_chunk,
        max_chunk_seconds=args.max_chunk,
        silence_gap_threshold=args.silence_gap,
        provider=args.provider,
        model=args.model,
        api_key=args.api_key,
        skip_llm=args.skip_llm,
        verbose=args.verbose,
    )

    # Write NoteSpec
    output_path = Path(args.output).expanduser().resolve()
    if result.note_spec:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            result.note_spec.model_dump_json(indent=2, exclude_none=True),
            encoding="utf-8",
        )
        if args.verbose:
            print(f"[pipeline] NoteSpec written to {output_path}", file=sys.stderr)
    else:
        print("Error: Pipeline produced no NoteSpec", file=sys.stderr)
        return 1

    # Save intermediates if requested
    if args.save_intermediates:
        base = output_path.parent
        stem = output_path.stem
        intermediates = {
            "chunker": result.chunker_result,
            "narrative": result.narrative_result,
            "emphasis": result.emphasis_result,
            "visual": result.visual_result,
            "global_review": result.global_review_result,
        }
        for name, obj in intermediates.items():
            if obj is None:
                continue
            try:
                ipath = base / f"{stem}.{name}.json"
                ipath.write_text(obj.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")
            except Exception:
                pass

    # Write manifest
    if args.manifest:
        manifest_path = Path(args.manifest).expanduser().resolve()
        manifest_data = {
            "status": "ok" if not result.errors else "error",
            "course_title": args.course_title,
            "lesson_title": args.lesson_title,
            "style": args.style,
            "output": str(output_path),
            "chunks": len(result.chunker_result.chunks) if result.chunker_result else 0,
            "total_tokens": result.metrics.total_tokens,
            "elapsed_seconds": result.elapsed_seconds,
            "errors": result.errors,
        }
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest_data, indent=2, ensure_ascii=False), encoding="utf-8")
        write_manifest(manifest_path, status=manifest_data["status"], **manifest_data)

    # Summary
    if result.errors:
        print(f"Pipeline completed with {len(result.errors)} error(s):", file=sys.stderr)
        for error in result.errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(f"Pipeline completed. {len(result.note_spec.sections)} sections, "
          f"{result.metrics.total_tokens} tokens, "
          f"{result.elapsed_seconds:.1f}s")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
