"""
Emphasis extraction evaluator.

Compares pipeline-produced emphasis_points against human-labeled ground truth.
Computes precision/recall/F1 with semantic matching (character bigrams for Chinese,
word bigrams for English). Optional LLM-as-judge for premium accuracy.

Adversarial design: classifies every mismatch into a failure mode so you know
WHAT broke, not just that something broke.
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

# Allow importing from commands + ai_pipeline
_SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))
_COMMANDS_DIR = _SCRIPT_DIR.parent / "commands"
if str(_COMMANDS_DIR) not in sys.path:
    sys.path.insert(0, str(_COMMANDS_DIR))

from _schemas import NoteSpec  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════════
# Data models
# ═══════════════════════════════════════════════════════════════════════════

FailureMode = Literal[
    "match",        # semantic match found
    "partial",      # some overlap but not enough
    "hallucination",  # pipeline point with no ground truth support
    "miss",         # ground truth point not found by pipeline
    "wrong_section",  # emphasis placed in wrong chunk
]


@dataclass
class PointMatch:
    """Result of comparing one pipeline point to one ground truth point."""

    pipeline_point: str
    ground_truth_point: str = ""
    similarity: float = 0.0
    verdict: FailureMode = "miss"


@dataclass
class ChunkEval:
    """Per-chunk evaluation result."""

    chunk_index: int
    chunk_title: str = ""
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    matches: list[PointMatch] = field(default_factory=list)
    hallucinations: list[str] = field(default_factory=list)
    misses: list[str] = field(default_factory=list)
    partials: list[PointMatch] = field(default_factory=list)

    @property
    def total_pipeline_points(self) -> int:
        return len(self.matches) + len(self.hallucinations) + len(self.partials)

    @property
    def total_ground_truth_points(self) -> int:
        return len(self.matches) + len(self.misses) + len(self.partials)


@dataclass
class EvalReport:
    """Full evaluation report across all chunks."""

    course_title: str = ""
    lesson_title: str = ""
    total_chunks: int = 0
    chunks: list[ChunkEval] = field(default_factory=list)

    # Global metrics
    global_precision: float = 0.0
    global_recall: float = 0.0
    global_f1: float = 0.0

    # Error catalog
    total_hallucinations: int = 0
    total_misses: int = 0
    total_partials: int = 0
    total_matches: int = 0

    # Metadata
    comparison_method: str = "ngram_jaccard"
    threshold: float = 0.4

    def to_dict(self) -> dict[str, Any]:
        return {
            "course_title": self.course_title,
            "lesson_title": self.lesson_title,
            "total_chunks": self.total_chunks,
            "global_precision": round(self.global_precision, 3),
            "global_recall": round(self.global_recall, 3),
            "global_f1": round(self.global_f1, 3),
            "total_matches": self.total_matches,
            "total_hallucinations": self.total_hallucinations,
            "total_misses": self.total_misses,
            "total_partials": self.total_partials,
            "comparison_method": self.comparison_method,
            "threshold": self.threshold,
            "chunks": [
                {
                    "chunk_index": c.chunk_index,
                    "title": c.chunk_title,
                    "precision": round(c.precision, 3),
                    "recall": round(c.recall, 3),
                    "f1": round(c.f1, 3),
                    "pipeline_points": c.total_pipeline_points,
                    "ground_truth_points": c.total_ground_truth_points,
                    "hallucinations": c.hallucinations,
                    "misses": c.misses,
                    "partials": [
                        {"pipeline": p.pipeline_point, "ground_truth": p.ground_truth_point, "similarity": round(p.similarity, 3)}
                        for p in c.partials
                    ],
                    "matches": [
                        {"pipeline": m.pipeline_point, "ground_truth": m.ground_truth_point, "similarity": round(m.similarity, 3)}
                        for m in c.matches
                    ],
                }
                for c in self.chunks
            ],
        }


# ═══════════════════════════════════════════════════════════════════════════
# Ground truth format
# ═══════════════════════════════════════════════════════════════════════════

GROUND_TRUTH_TEMPLATE = {
    "course_title": "Course Name",
    "lesson_title": "Lesson Name",
    "chunks": [
        {
            "chunk_index": 1,
            "emphasis_points": [
                "The single most important thing the teacher emphasized in this chunk",
                "Second most important point",
            ],
            "pitfalls": [
                "Common mistake the teacher warned about",
            ],
        },
    ],
}


def load_ground_truth(path: str | Path) -> dict[str, Any]:
    """Load ground truth JSON file."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_ground_truth_template(path: str | Path, note_spec: NoteSpec) -> Path:
    """Generate a ground truth template from a NoteSpec for human labeling.

    Pre-fills chunk_index and empty emphasis_points arrays so the human
    only needs to fill in the actual points.
    """
    template = {
        "course_title": note_spec.course_title,
        "lesson_title": note_spec.lesson_title or "",
        "chunks": [
            {
                "chunk_index": section.section_ref.lstrip("§") if section.section_ref else str(i + 1),
                "emphasis_points": [],
                "pitfalls": [],
            }
            for i, section in enumerate(note_spec.sections)
        ],
    }
    path = Path(path)
    path.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# ═══════════════════════════════════════════════════════════════════════════
# Semantic comparison — n-gram Jaccard (no API needed)
# ═══════════════════════════════════════════════════════════════════════════


def _char_bigrams(text: str) -> set[str]:
    """Character-level bigrams. Works for Chinese (no segmentation) and English."""
    cleaned = re.sub(r"\s+", "", text.lower())
    if len(cleaned) < 2:
        return {cleaned}
    return {cleaned[i : i + 2] for i in range(len(cleaned) - 1)}


def _word_bigrams(text: str) -> set[str]:
    """Word-level bigrams for English. Falls back to char bigrams for CJK."""
    words = text.lower().split()
    if len(words) < 2:
        return _char_bigrams(text)
    return {" ".join(words[i : i + 2]) for i in range(len(words) - 1)}


def jaccard_similarity(a: str, b: str) -> float:
    """Hybrid n-gram Jaccard: uses word bigrams for alphabetic text,
    character bigrams for CJK-heavy text. Robust without segmentation."""
    # Detect if text is primarily CJK
    cjk_chars_a = sum(1 for c in a if "一" <= c <= "鿿" or "぀" <= c <= "ヿ")
    cjk_chars_b = sum(1 for c in b if "一" <= c <= "鿿" or "぀" <= c <= "ヿ")

    if cjk_chars_a > len(a) * 0.3 or cjk_chars_b > len(b) * 0.3:
        # CJK-heavy: use character bigrams
        set_a = _char_bigrams(a)
        set_b = _char_bigrams(b)
    else:
        # Alphabet-heavy: use word bigrams
        set_a = _word_bigrams(a)
        set_b = _word_bigrams(b)

    if not set_a or not set_b:
        return 0.0

    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


# ═══════════════════════════════════════════════════════════════════════════
# Matching — greedy bipartite
# ═══════════════════════════════════════════════════════════════════════════


def _greedy_match(
    pipeline_points: list[str],
    ground_truth_points: list[str],
    threshold: float = 0.4,
    partial_threshold: float = 0.25,
) -> tuple[list[PointMatch], list[str], list[str], list[PointMatch]]:
    """Greedy bipartite matching between pipeline and ground truth points.

    Each pipeline point matches at most one ground truth point, and vice versa.
    Matches are made in descending similarity order.

    Returns: (matches, hallucinations, misses, partials)
    """
    # Compute all pairwise similarities
    pairs: list[tuple[float, int, int]] = []
    for pi, pp in enumerate(pipeline_points):
        for gi, gt in enumerate(ground_truth_points):
            sim = jaccard_similarity(pp, gt)
            pairs.append((sim, pi, gi))

    # Sort by similarity descending
    pairs.sort(key=lambda x: x[0], reverse=True)

    matched_p = set()
    matched_g = set()
    matches: list[PointMatch] = []
    partials: list[PointMatch] = []

    for sim, pi, gi in pairs:
        if pi in matched_p or gi in matched_g:
            continue
        if sim >= threshold:
            matched_p.add(pi)
            matched_g.add(gi)
            matches.append(PointMatch(
                pipeline_point=pipeline_points[pi],
                ground_truth_point=ground_truth_points[gi],
                similarity=sim,
                verdict="match",
            ))
        elif sim >= partial_threshold:
            matched_p.add(pi)
            matched_g.add(gi)
            partials.append(PointMatch(
                pipeline_point=pipeline_points[pi],
                ground_truth_point=ground_truth_points[gi],
                similarity=sim,
                verdict="partial",
            ))

    # Unmatched pipeline points → hallucinations
    hallucinations = [
        pp for pi, pp in enumerate(pipeline_points)
        if pi not in matched_p
    ]

    # Unmatched ground truth points → misses
    misses = [
        gt for gi, gt in enumerate(ground_truth_points)
        if gi not in matched_g
    ]

    return matches, hallucinations, misses, partials


# ═══════════════════════════════════════════════════════════════════════════
# LLM-as-judge (premium comparison)
# ═══════════════════════════════════════════════════════════════════════════

JUDGE_SYSTEM = """You are an expert evaluator comparing AI-extracted emphasis points against human-labeled ground truth.

Your task: for each pair of (pipeline point, ground truth point), judge whether they express the SAME teaching emphasis.

## Rules
- "Same" means they point to the same underlying concept the teacher emphasized
- Wording can differ — judge by MEANING, not vocabulary
- If the pipeline point is more specific than ground truth (or vice versa), it's still a match if the core concept is the same
- If the pipeline point is about a DIFFERENT concept, it's NOT a match
- Score each pair: 1.0 (identical meaning), 0.5 (partially overlapping), 0.0 (different concepts)

Return JSON array of scores."""


def llm_judge_match(
    pipeline_points: list[str],
    ground_truth_points: list[str],
    llm_client: Any = None,
) -> list[PointMatch]:
    """Use LLM to judge semantic equivalence of emphasis points.

    Much more accurate than n-gram Jaccard, but requires API call.
    """
    if llm_client is None:
        # Fall back to Jaccard
        matches, hallucinations, misses, partials = _greedy_match(pipeline_points, ground_truth_points)
        return matches + partials + [
            PointMatch(pipeline_point=h, verdict="hallucination") for h in hallucinations
        ] + [
            PointMatch(ground_truth_point=m, verdict="miss") for m in misses
        ]

    # Build pairwise comparison prompt
    pairs_text = "## Pipeline Points\n"
    for i, pp in enumerate(pipeline_points):
        pairs_text += f"P{i}: {pp}\n"
    pairs_text += "\n## Ground Truth Points\n"
    for j, gt in enumerate(ground_truth_points):
        pairs_text += f"G{j}: {gt}\n"
    pairs_text += "\nFor each pair (P_i, G_j), return a score: 1.0 (same), 0.5 (partial), 0.0 (different)."

    try:
        result = llm_client.complete_json(JUDGE_SYSTEM, pairs_text)
        scores = result if isinstance(result, list) else result.get("scores", [])

        # Convert scores to PointMatch list
        all_matches: list[PointMatch] = []
        for item in scores:
            pi = item.get("pipeline_index", item.get("pi", -1))
            gi = item.get("ground_truth_index", item.get("gi", -1))
            score = item.get("score", item.get("similarity", 0.0))
            if pi >= 0 and gi >= 0:
                verdict: FailureMode = "match" if score >= 0.7 else ("partial" if score >= 0.3 else "miss")
                all_matches.append(PointMatch(
                    pipeline_point=pipeline_points[pi] if pi < len(pipeline_points) else "",
                    ground_truth_point=ground_truth_points[gi] if gi < len(ground_truth_points) else "",
                    similarity=score,
                    verdict=verdict,
                ))
        return all_matches
    except Exception:
        # Fallback
        matches, hallucinations, misses, partials = _greedy_match(pipeline_points, ground_truth_points)
        return matches + partials + [
            PointMatch(pipeline_point=h, verdict="hallucination") for h in hallucinations
        ] + [
            PointMatch(ground_truth_point=m, verdict="miss") for m in misses
        ]


# ═══════════════════════════════════════════════════════════════════════════
# Main eval
# ═══════════════════════════════════════════════════════════════════════════


def evaluate(
    note_spec: NoteSpec,
    ground_truth: dict[str, Any],
    threshold: float = 0.4,
    partial_threshold: float = 0.25,
    llm_client: Any = None,
) -> EvalReport:
    """Evaluate emphasis extraction against ground truth.

    Args:
        note_spec: Pipeline output (NoteSpec).
        ground_truth: Loaded ground truth JSON dict.
        threshold: Jaccard similarity threshold for a "match".
        partial_threshold: Jaccard threshold for "partial" match.
        llm_client: Optional LLMClient for judge mode.

    Returns:
        EvalReport with per-chunk and global metrics + error catalog.
    """
    # Build chunk lookup from ground truth
    gt_chunks: dict[int, dict[str, Any]] = {}
    for gc in ground_truth.get("chunks", []):
        ci = gc.get("chunk_index", gc.get("index", 0))
        if isinstance(ci, str):
            ci = int(ci.lstrip("§"))
        gt_chunks[int(ci)] = gc

    report = EvalReport(
        course_title=note_spec.course_title,
        lesson_title=note_spec.lesson_title or "",
        total_chunks=len(note_spec.sections),
        threshold=threshold,
        comparison_method="llm_judge" if llm_client else "ngram_jaccard",
    )

    all_matches = 0
    all_hallucinations = 0
    all_misses = 0
    all_partials = 0
    total_precision_sum = 0.0
    total_recall_sum = 0.0
    chunks_with_data = 0

    for section in note_spec.sections:
        # Extract chunk index from section_ref ("§1" → 1)
        ref = section.section_ref.lstrip("§")
        try:
            chunk_index = int(ref)
        except ValueError:
            chunk_index = 0

        gt = gt_chunks.get(chunk_index, {})
        pipeline_points = section.emphasis_points or section.key_points or []
        gt_points = gt.get("emphasis_points", [])

        if not pipeline_points and not gt_points:
            # Both empty — perfect agreement on "nothing to emphasize"
            chunk_eval = ChunkEval(chunk_index=chunk_index, chunk_title=section.title, precision=1.0, recall=1.0, f1=1.0)
            report.chunks.append(chunk_eval)
            continue

        if not pipeline_points or not gt_points:
            # One side has points, the other doesn't
            chunk_eval = ChunkEval(
                chunk_index=chunk_index,
                chunk_title=section.title,
                precision=0.0 if pipeline_points else 1.0,
                recall=0.0 if gt_points else 1.0,
                f1=0.0,
                hallucinations=pipeline_points if not gt_points else [],
                misses=gt_points if not pipeline_points else [],
            )
            report.chunks.append(chunk_eval)
            all_hallucinations += len(chunk_eval.hallucinations)
            all_misses += len(chunk_eval.misses)
            continue

        # Compare
        if llm_client:
            all_point_matches = llm_judge_match(pipeline_points, gt_points, llm_client)
            matches = [m for m in all_point_matches if m.verdict == "match"]
            partials = [m for m in all_point_matches if m.verdict == "partial"]
            hallucinations = [m.pipeline_point for m in all_point_matches if m.verdict == "hallucination"]
            misses = [m.ground_truth_point for m in all_point_matches if m.verdict == "miss"]
        else:
            matches, hallucinations, misses, partials = _greedy_match(
                pipeline_points, gt_points, threshold, partial_threshold
            )

        # Per-chunk metrics
        tp = len(matches)
        fp = len(hallucinations) + len(partials)
        fn = len(misses) + len(partials)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        chunk_eval = ChunkEval(
            chunk_index=chunk_index,
            chunk_title=section.title,
            precision=precision,
            recall=recall,
            f1=f1,
            matches=matches,
            hallucinations=hallucinations,
            misses=misses,
            partials=partials,
        )
        report.chunks.append(chunk_eval)

        all_matches += len(matches)
        all_hallucinations += len(hallucinations)
        all_misses += len(misses)
        all_partials += len(partials)
        total_precision_sum += precision
        total_recall_sum += recall
        chunks_with_data += 1

    # Global metrics: micro-averaged
    total_tp = all_matches
    total_fp = all_hallucinations + all_partials
    total_fn = all_misses + all_partials

    report.global_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    report.global_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    report.global_f1 = (
        2 * report.global_precision * report.global_recall / (report.global_precision + report.global_recall)
        if (report.global_precision + report.global_recall) > 0
        else 0.0
    )

    report.total_matches = all_matches
    report.total_hallucinations = all_hallucinations
    report.total_misses = all_misses
    report.total_partials = all_partials

    return report


# ═══════════════════════════════════════════════════════════════════════════
# Report formatting
# ═══════════════════════════════════════════════════════════════════════════


def format_report(report: EvalReport) -> str:
    """Format an EvalReport as a readable text summary."""

    def bar(label: str, value: float, width: int = 30) -> str:
        filled = int(value * width)
        bar_str = "█" * filled + "░" * (width - filled)
        return f"{label:12s} │ {bar_str} │ {value:.2%}"

    lines = [
        f"EMPHASIS EXTRACTION EVAL",
        f"Course: {report.course_title}",
        f"Lesson: {report.lesson_title}",
        f"Method: {report.comparison_method} (threshold={report.threshold})",
        f"",
        f"═══ GLOBAL METRICS ═══",
        f"",
        bar("Precision", report.global_precision),
        bar("Recall", report.global_recall),
        bar("F1", report.global_f1),
        f"",
        f"═══ ERROR CATALOG ═══",
        f"",
        f"  ✅ Matches:       {report.total_matches:3d}",
        f"  🟡 Partials:       {report.total_partials:3d}",
        f"  ❌ Hallucinations: {report.total_hallucinations:3d}  (pipeline made up emphasis not in ground truth)",
        f"  ❌ Misses:         {report.total_misses:3d}  (ground truth emphasis not found by pipeline)",
        f"",
        f"═══ PER-CHUNK BREAKDOWN ═══",
        f"",
    ]

    for c in report.chunks:
        lines.append(f"  Chunk {c.chunk_index}: {c.chunk_title[:60]}")
        lines.append(f"    P={c.precision:.2%}  R={c.recall:.2%}  F1={c.f1:.2%}  "
                      f"(pipeline={c.total_pipeline_points}, gt={c.total_ground_truth_points})")
        if c.hallucinations:
            for h in c.hallucinations[:3]:
                lines.append(f"    ❌ HALLUCINATION: {h[:100]}")
        if c.misses:
            for m in c.misses[:3]:
                lines.append(f"    ❌ MISS: {m[:100]}")
        if c.partials:
            for p in c.partials[:2]:
                lines.append(f"    🟡 PARTIAL (sim={p.similarity:.2f}): pipe='{p.pipeline_point[:60]}' ↔ gt='{p.ground_truth_point[:60]}'")
        lines.append("")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Evaluate emphasis extraction against human-labeled ground truth."
    )
    parser.add_argument("--note-spec", required=True, help="Path to NoteSpec JSON (pipeline output).")
    parser.add_argument("--ground-truth", required=True, help="Path to ground truth JSON.")
    parser.add_argument("--threshold", type=float, default=0.4, help="Jaccard similarity threshold for match.")
    parser.add_argument("--partial-threshold", type=float, default=0.25)
    parser.add_argument("--output", help="Path for eval report JSON.")
    parser.add_argument("--template", action="store_true", help="Generate ground truth template from note spec.")
    parser.add_argument("--text-report", action="store_true", help="Print human-readable text report.")
    args = parser.parse_args()

    # Load note spec
    spec_path = Path(args.note_spec).expanduser().resolve()
    raw = json.loads(spec_path.read_text(encoding="utf-8"))
    note_spec = NoteSpec.model_validate(raw)

    # Template mode: generate blank ground truth for human labeling
    if args.template:
        template_path = Path(args.ground_truth).expanduser().resolve()
        save_ground_truth_template(template_path, note_spec)
        print(f"Ground truth template written to {template_path}")
        print(f"Fill in emphasis_points for each chunk, then run again without --template.")
        return 0

    # Load ground truth
    gt = load_ground_truth(args.ground_truth)

    # Evaluate
    report = evaluate(note_spec, gt, args.threshold, args.partial_threshold)

    # Output
    if args.output:
        output_path = Path(args.output).expanduser().resolve()
        output_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Eval report written to {output_path}")

    if args.text_report or not args.output:
        print(format_report(report))

    # Exit code: non-zero if F1 is concerning
    if report.global_f1 < 0.3:
        print("⚠️  F1 < 0.3 — emphasis extraction needs significant improvement", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
