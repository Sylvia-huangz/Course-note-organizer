from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from _common import ensure_course_dirs, slugify
from _errors import write_error_manifest, write_manifest, write_validation_error
from _schemas import NoteSpec, OrchestrateRequest
from assemble_notes import assemble_markdown
from export_docx import export_docx
from export_pdf import export_pdf


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assemble and optionally export a course-note package.")
    parser.add_argument("--spec", required=True)
    parser.add_argument("--course-title", required=True)
    parser.add_argument("--base-dir", default=".")
    parser.add_argument("--style", default="standard-structured")
    parser.add_argument("--export-format", choices=["markdown", "docx", "pdf", "all"], default="markdown")
    parser.add_argument("--manifest")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_hint = Path(args.manifest).expanduser().resolve() if args.manifest else None
    try:
        request = OrchestrateRequest.model_validate(vars(args))
    except ValidationError as exc:
        if manifest_hint:
            write_validation_error(manifest_hint, exc)
        return 1

    spec_path = Path(request.spec).expanduser().resolve()
    try:
        raw_spec = json.loads(spec_path.read_text(encoding="utf-8-sig"))
        spec = NoteSpec.model_validate(raw_spec)
    except json.JSONDecodeError as exc:
        if manifest_hint:
            write_error_manifest(
                manifest_hint,
                code="INVALID_JSON",
                message="Failed to parse the orchestration note spec JSON.",
                source=str(spec_path),
                details={"exception": str(exc)},
            )
        return 1
    except ValidationError as exc:
        if manifest_hint:
            write_validation_error(manifest_hint, exc, source=str(spec_path))
        return 1

    course_dirs = ensure_course_dirs(request.base_dir, request.course_title)
    file_stem = slugify(request.course_title)
    markdown_path = course_dirs["notes"] / f"{file_stem}.md"
    try:
        markdown, metadata = assemble_markdown(spec, request.style)
        markdown_path.write_text(markdown, encoding="utf-8")
    except Exception as exc:
        if manifest_hint:
            write_error_manifest(
                manifest_hint,
                code="ASSEMBLY_FAILED",
                message="Failed to assemble the Markdown master note.",
                source=str(spec_path),
                details={"exception": str(exc)},
                retryable=True,
            )
        return 1

    outputs = {"markdown": str(markdown_path)}
    try:
        if request.export_format in {"docx", "all"}:
            docx_path = course_dirs["notes"] / f"{file_stem}.docx"
            export_docx(markdown_path, docx_path)
            outputs["docx"] = str(docx_path)
        if request.export_format in {"pdf", "all"}:
            pdf_path = course_dirs["notes"] / f"{file_stem}.pdf"
            export_pdf(markdown_path, pdf_path)
            outputs["pdf"] = str(pdf_path)
    except Exception as exc:
        if manifest_hint:
            write_error_manifest(
                manifest_hint,
                code="EXPORT_FAILED",
                message="One or more orchestrated exports failed.",
                source=str(markdown_path),
                details={"exception": str(exc), "export_format": request.export_format},
                retryable=True,
            )
        return 1

    manifest_path = manifest_hint or course_dirs["temp"] / "orchestration-manifest.json"
    write_manifest(
        manifest_path,
        status="ok",
        source=str(spec_path),
        course_title=request.course_title,
        style=request.style,
        outputs=outputs,
        metadata_preview=metadata,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
