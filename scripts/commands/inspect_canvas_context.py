from __future__ import annotations

import argparse
import re
from pathlib import Path

from pydantic import ValidationError

from _common import overlap_score, read_text_any
from _errors import make_error, write_model, write_validation_error
from _schemas import CanvasContextPayload, InspectCanvasContextRequest


DATE_PATTERN = re.compile(
    r"\b(?:due|deadline|quiz|exam|assignment|announcement|module|week|"
    r"\u622a\u6b62|\u622a\u81f3|\u4f5c\u4e1a|\u8003\u8bd5|\u6d4b\u9a8c|\u516c\u544a|\u5468|\u5355\u5143)\b.*",
    flags=re.IGNORECASE,
)


def extract_relevant_lines(text: str) -> list[str]:
    lines = []
    for raw_line in text.splitlines():
        line = " ".join(raw_line.split())
        if line and DATE_PATTERN.search(line):
            lines.append(line)
    return lines


def classify_lines(lines: list[str]) -> tuple[list[str], list[str], list[str]]:
    announcements: list[str] = []
    assignments: list[str] = []
    modules: list[str] = []
    for line in lines:
        lower = line.lower()
        if any(
            token in lower
            for token in ("announcement", "notice", "reminder", "\u516c\u544a", "\u63d0\u9192")
        ):
            announcements.append(line)
        elif any(
            token in lower
            for token in ("assignment", "quiz", "exam", "deadline", "due", "\u4f5c\u4e1a", "\u8003\u8bd5", "\u6d4b\u9a8c")
        ):
            assignments.append(line)
        elif any(
            token in lower
            for token in ("module", "week", "unit", "\u7ae0\u8282", "\u5355\u5143", "\u5468")
        ):
            modules.append(line)
    return announcements, assignments, modules


def build_payload(
    sources: list[Path],
    course_title: str,
    lesson_title: str | None,
) -> CanvasContextPayload:
    extracted_sources = []
    combined_lines: list[str] = []
    for source in sources:
        text = read_text_any(source)
        lines = extract_relevant_lines(text)
        extracted_sources.append({"path": str(source), "matched_lines": lines[:30]})
        combined_lines.extend(lines)

    announcements, assignments, modules = classify_lines(combined_lines)
    match_candidates = []
    if lesson_title:
        for line in assignments + announcements + modules:
            score = overlap_score(lesson_title, line)
            if score > 0:
                match_candidates.append({"line": line, "overlap_score": score})
        match_candidates.sort(key=lambda item: item["overlap_score"], reverse=True)

    return CanvasContextPayload.model_validate(
        {
            "course_title": course_title,
            "lesson_title": lesson_title,
            "sources": extracted_sources,
            "announcements": announcements[:10],
            "assignments": assignments[:10],
            "modules": modules[:10],
            "match_candidates": match_candidates[:10],
            "status": "ok" if combined_lines else "no_relevant_context_found",
            "notes": [
                "This command is read-only and expects browser-captured or exported Canvas content.",
                "Use a logged-in browser session outside this command when live Canvas access is required.",
            ],
        }
    )


def error_payload(
    *,
    course_title: str,
    lesson_title: str | None,
    source_paths: list[str],
    code: str,
    message: str,
    details: dict | None = None,
) -> CanvasContextPayload:
    return CanvasContextPayload(
        course_title=course_title,
        lesson_title=lesson_title,
        sources=[{"path": item, "matched_lines": []} for item in source_paths],
        status="error",
        notes=["Canvas preflight degraded gracefully; proceed without context weighting."],
        error=make_error(
            code,
            message,
            suggestions=[
                "Check that the exported Canvas files exist and are readable.",
                "If live Canvas access is needed, use the user's logged-in browser session to capture the page first.",
            ],
            details=details,
        ),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse Canvas page artifacts into structured context.")
    parser.add_argument("--course-title", required=True)
    parser.add_argument("--lesson-title")
    parser.add_argument("--input", dest="input_paths", action="append", required=True, help="Path to Canvas HTML, JSON, or text export.")
    parser.add_argument("--output", required=True, help="Path to the structured JSON output.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_path = Path(args.output).expanduser().resolve()
    try:
        request = InspectCanvasContextRequest.model_validate(vars(args))
    except ValidationError as exc:
        write_validation_error(output_path, exc)
        return 1

    sources = [Path(item).expanduser().resolve() for item in request.input_paths]
    missing = [str(path) for path in sources if not path.exists()]
    if missing:
        write_model(
            output_path,
            error_payload(
                course_title=request.course_title,
                lesson_title=request.lesson_title,
                source_paths=[str(path) for path in sources],
                code="MISSING_SOURCE",
                message="One or more Canvas export files could not be found.",
                details={"missing": missing},
            ),
        )
        return 1

    try:
        payload = build_payload(sources=sources, course_title=request.course_title, lesson_title=request.lesson_title)
    except Exception as exc:
        write_model(
            output_path,
            error_payload(
                course_title=request.course_title,
                lesson_title=request.lesson_title,
                source_paths=[str(path) for path in sources],
                code="READ_FAILED",
                message="Failed to parse the provided Canvas artifacts.",
                details={"exception": str(exc)},
            ),
        )
        return 1

    write_model(output_path, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
