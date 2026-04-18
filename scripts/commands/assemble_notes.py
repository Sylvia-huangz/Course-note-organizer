from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from _common import TEMP_DIRNAME, ensure_course_dirs, ensure_within_course_root, estimate_review_minutes, extract_formulas, slugify
from _errors import write_error_manifest, write_manifest, write_validation_error
from _schemas import AssembleNotesRequest, MetadataSpec, NoteSpec


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for item in items:
        cleaned = " ".join(str(item).split()).strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def _extract_keywords(spec: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    for field in ("course_title", "lesson_title"):
        value = spec.get(field)
        if value:
            candidates.extend(re.findall(r"[A-Za-z0-9\u4e00-\u9fff]{2,}", str(value)))
    for section in spec.get("sections", []):
        candidates.extend(re.findall(r"[A-Za-z0-9\u4e00-\u9fff]{2,}", section.get("title", "")))
        candidates.extend(section.get("keywords", []))
    for item in spec.get("video_topic_index", []):
        candidates.extend(re.findall(r"[A-Za-z0-9\u4e00-\u9fff]{2,}", item.get("topic", "")))
    filtered = []
    for token in candidates:
        if token.lower() not in {"section", "topic", "lesson", "course", "notes"}:
            filtered.append(token)
    return _dedupe(filtered)[:12]


def build_metadata(spec: NoteSpec, markdown_body: str) -> dict[str, Any]:
    spec_dump = spec.model_dump(mode="json")
    metadata = dict(spec.metadata.model_dump(mode="json", exclude_none=True))
    metadata.setdefault("course_title", spec.course_title)
    metadata.setdefault("lesson_title", spec.lesson_title)
    metadata.setdefault("keywords", _extract_keywords(spec_dump))
    metadata.setdefault("core_concepts", _dedupe([section.title for section in spec.sections])[:8])
    metadata.setdefault("formulas", _dedupe(extract_formulas(markdown_body)))
    metadata.setdefault("estimated_review_time_minutes", estimate_review_minutes(markdown_body, len(spec.sections)))
    metadata.setdefault(
        "timeline_topics",
        [{"timestamp": item.timestamp, "topic": item.topic} for item in spec.video_topic_index],
    )
    metadata.setdefault("exam_assignment_relevance", spec.canvas_context.relevance_lines)
    metadata.setdefault("repair_annotations_present", any(section.repair_annotations for section in spec.sections))
    return MetadataSpec.model_validate(metadata).model_dump(mode="json")


def render_timestamp_index(index_items: list[dict[str, Any]]) -> list[str]:
    lines = [
        "## Video Topic Index",
        "",
        "| Timestamp | Topic | Subtopic or Event | Note Section |",
        "|---|---|---|---|",
    ]
    for item in index_items:
        lines.append(
            f"| {item.get('timestamp', '')} | {item.get('topic', '')} | "
            f"{item.get('subtopic', '')} | {item.get('section_ref', '')} |"
        )
    lines.append("")
    return lines


def render_canvas_context(canvas_context: dict[str, Any]) -> list[str]:
    if not canvas_context:
        return []
    summary_lines = canvas_context.get("summary_lines") or canvas_context.get("relevance_lines") or []
    if not summary_lines:
        return []
    lines = ["## Course Context (Canvas)", ""]
    for item in summary_lines:
        lines.append(f"- {item}")
    lines.append("")
    return lines


def render_sources(section: dict[str, Any]) -> list[str]:
    sources = section.get("sources") or []
    if not sources:
        return []
    return [f"**Source Trace:** {', '.join(sources)}", ""]


def render_repairs(section: dict[str, Any]) -> list[str]:
    lines = []
    for note in section.get("repair_annotations") or []:
        lines.append(f"> [Repair: {note.get('type', 'context-assisted')}] {note.get('note', '').strip()}")
        lines.append("")
    return lines


def render_standard_section(section: dict[str, Any]) -> list[str]:
    lines = [f"## {section.get('section_ref', '').strip()} {section.get('title', '').strip()}".strip(), ""]
    lines.extend(render_sources(section))
    lines.extend(render_repairs(section))
    if section.get("content"):
        lines.append(section["content"].strip())
        lines.append("")
    for bullet in section.get("key_points") or []:
        lines.append(f"- {bullet}")
    if section.get("key_points"):
        lines.append("")
    for pitfall in section.get("pitfalls") or []:
        lines.append(f"> [Pitfall] {pitfall}")
        lines.append("")
    for example in section.get("examples") or []:
        lines.append(f"### Example: {example.get('title', 'Worked example')}")
        lines.append("")
        lines.append(example.get("content", "").strip())
        lines.append("")
    return lines


def render_cornell_section(section: dict[str, Any]) -> list[str]:
    lines = [f"## {section.get('section_ref', '').strip()} {section.get('title', '').strip()}".strip(), ""]
    lines.extend(render_sources(section))
    lines.extend(render_repairs(section))
    lines.append("### Cue")
    lines.append("")
    cues = section.get("keywords") or [section.get("title", "Key idea")]
    for cue in cues:
        lines.append(f"- {cue}")
    lines.append("")
    lines.append("### Notes")
    lines.append("")
    lines.append(section.get("content", "").strip())
    lines.append("")
    if section.get("key_points"):
        lines.append("### Review Prompt")
        lines.append("")
        for item in section["key_points"]:
            lines.append(f"- How would you explain: {item}?")
        lines.append("")
    return lines


def render_qa_section(section: dict[str, Any]) -> list[str]:
    lines = [f"## {section.get('section_ref', '').strip()} {section.get('title', '').strip()}".strip(), ""]
    lines.extend(render_sources(section))
    lines.extend(render_repairs(section))
    question = section.get("question") or f"What should I remember about {section.get('title', 'this topic')}?"
    lines.append(f"### Q: {question}")
    lines.append("")
    lines.append(f"### A: {section.get('content', '').strip()}")
    lines.append("")
    for item in section.get("key_points") or []:
        lines.append(f"- Fast recall: {item}")
    if section.get("key_points"):
        lines.append("")
    return lines


def render_outline_section(section: dict[str, Any]) -> list[str]:
    lines = [f"## {section.get('section_ref', '').strip()} {section.get('title', '').strip()}".strip(), ""]
    lines.extend(render_sources(section))
    lines.extend(render_repairs(section))
    summary = section.get("content", "").strip()
    if summary:
        lines.append(f"- Summary: {summary}")
    for item in section.get("key_points") or []:
        lines.append(f"- {item}")
    for pitfall in section.get("pitfalls") or []:
        lines.append(f"- Pitfall: {pitfall}")
    lines.append("")
    return lines


def render_section(section: dict[str, Any], style: str) -> list[str]:
    if style == "cornell":
        return render_cornell_section(section)
    if style == "qa-sprint":
        return render_qa_section(section)
    if style == "outline-map":
        return render_outline_section(section)
    return render_standard_section(section)


def render_summary(spec: dict[str, Any], metadata: dict[str, Any]) -> list[str]:
    summary = spec.get("summary") or {}
    takeaways = summary.get("key_takeaways") or metadata.get("core_concepts") or []
    formulas = summary.get("formulas") or metadata.get("formulas") or []
    review_steps = summary.get("review_steps") or [
        "Revisit the timestamp index and replay the hardest section.",
        "Re-derive the main formula or method once without notes.",
    ]
    lines = ["## Lesson Summary", ""]
    overview = summary.get("overview") or f"This lesson focused on {spec.get('lesson_title') or spec.get('course_title')}."
    lines.append(f"- What this lesson covered: {overview}")
    lines.append("- Key takeaways:")
    for item in takeaways:
        lines.append(f"  - {item}")
    if formulas:
        lines.append("- Formulas or methods:")
        for formula in formulas:
            lines.append(f"  - {formula}")
    pitfalls = summary.get("pitfalls") or []
    if pitfalls:
        lines.append("- Common pitfalls:")
        for pitfall in pitfalls:
            lines.append(f"  - {pitfall}")
    lines.append("- Review plan:")
    for step in review_steps:
        lines.append(f"  - {step}")
    lines.append("")
    return lines


def assemble_markdown(spec: NoteSpec, style: str) -> tuple[str, dict[str, Any]]:
    lines = [f"# {spec.course_title}", ""]
    if spec.lesson_title:
        lines.append(f"## {spec.lesson_title}")
        lines.append("")
    if spec.video_topic_index:
        lines.extend(render_timestamp_index([item.model_dump(mode="json") for item in spec.video_topic_index]))
    lines.extend(render_canvas_context(spec.canvas_context.model_dump(mode="json")))
    for section in spec.sections:
        lines.extend(render_section(section.model_dump(mode="json"), style))
    placeholder_body = "\n".join(lines)
    metadata = build_metadata(spec, placeholder_body)
    lines.extend(render_summary(spec.model_dump(mode="json"), metadata))
    lines.append("```json")
    lines.append(json.dumps(metadata, ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")
    return "\n".join(lines), metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assemble the Markdown master copy for course notes.")
    parser.add_argument("--spec", required=True, help="Path to the structured note JSON spec.")
    parser.add_argument("--course-title", help="Override course title for output directory creation.")
    parser.add_argument("--base-dir", default=".")
    parser.add_argument("--style", default="standard-structured")
    parser.add_argument("--output", help="Optional Markdown output path.")
    parser.add_argument("--metadata-sidecar", help="Optional JSON metadata sidecar path.")
    parser.add_argument("--manifest", help="Optional status manifest path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_hint = Path(args.manifest).expanduser().resolve() if args.manifest else None
    try:
        request = AssembleNotesRequest.model_validate(vars(args))
    except ValidationError as exc:
        if manifest_hint:
            write_validation_error(manifest_hint, exc)
        return 1

    spec_path = Path(request.spec).expanduser().resolve()
    provisional_course_title = request.course_title or spec_path.stem or "course-notes"
    provisional_dirs = ensure_course_dirs(request.base_dir, provisional_course_title)
    provisional_manifest_path = ensure_within_course_root(
        manifest_hint or provisional_dirs["temp"] / "assemble-notes-status.json",
        provisional_dirs["root"],
    )
    try:
        raw_spec = json.loads(spec_path.read_text(encoding="utf-8-sig"))
        spec = NoteSpec.model_validate(raw_spec)
    except json.JSONDecodeError as exc:
        write_error_manifest(
            provisional_manifest_path,
            code="INVALID_JSON",
            message="Failed to parse the note spec JSON.",
            source=str(spec_path),
            details={"exception": str(exc)},
        )
        return 1
    except ValidationError as exc:
        write_validation_error(provisional_manifest_path, exc, source=str(spec_path))
        return 1

    course_title = request.course_title or spec.course_title or "course-notes"
    course_dirs = ensure_course_dirs(request.base_dir, course_title)
    manifest_path = ensure_within_course_root(
        manifest_hint or course_dirs["temp"] / "assemble-notes-status.json",
        course_dirs["root"],
    )
    style = request.style or spec.note_style or "standard-structured"
    output_path = Path(request.output).expanduser().resolve() if request.output else course_dirs["notes"] / f"{slugify(course_title)}.md"
    output_path = ensure_within_course_root(output_path, course_dirs["root"])
    metadata_path = (
        Path(request.metadata_sidecar).expanduser().resolve()
        if request.metadata_sidecar
        else course_dirs["temp"] / f"{slugify(course_title)}.metadata.json"
    )
    metadata_path = ensure_within_course_root(metadata_path, course_dirs["root"])
    try:
        markdown, metadata = assemble_markdown(spec, style)
        output_path.write_text(markdown, encoding="utf-8")
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        write_error_manifest(
            manifest_path,
            code="ASSEMBLY_FAILED",
            message="Failed while assembling or writing the Markdown note package.",
            source=str(spec_path),
            details={"exception": str(exc)},
            retryable=True,
        )
        return 1
    write_manifest(
        manifest_path,
        status="ok",
        source=str(spec_path),
        output=str(output_path),
        metadata_json=str(metadata_path),
        style=style,
        metadata_preview=metadata,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
