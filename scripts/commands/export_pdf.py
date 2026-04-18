from __future__ import annotations

import argparse
from pathlib import Path
from xml.sax.saxutils import escape

from pydantic import ValidationError
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    ListFlowable,
    ListItem,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

from _common import TEMP_DIRNAME, ensure_within_course_root, infer_course_root_from_artifact
from _errors import write_error_manifest, write_manifest, write_validation_error
from _markdown_blocks import MarkdownBlock, parse_markdown_blocks
from _schemas import ExportPdfRequest, ExportPdfResult


class NoteDocTemplate(BaseDocTemplate):
    def __init__(self, filename: str, **kwargs):
        super().__init__(filename, **kwargs)
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="normal")
        template = PageTemplate(id="notes", frames=[frame], onPage=self._draw_page_number)
        self.addPageTemplates([template])

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph):
            style_name = flowable.style.name
            if style_name in {"Heading1", "Heading2", "Heading3"}:
                level = {"Heading1": 0, "Heading2": 1, "Heading3": 2}[style_name]
                self.notify("TOCEntry", (level, flowable.getPlainText(), self.page))

    def _draw_page_number(self, canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 9)
        canvas.drawRightString(doc.pagesize[0] - 0.75 * inch, 0.55 * inch, f"Page {doc.page}")
        canvas.restoreState()


def build_styles():
    styles = getSampleStyleSheet()
    styles["Heading1"].spaceBefore = 12
    styles["Heading1"].spaceAfter = 6
    styles["Heading2"].spaceBefore = 10
    styles["Heading2"].spaceAfter = 4
    styles["Heading3"].spaceBefore = 8
    styles["Heading3"].spaceAfter = 4
    styles.add(
        ParagraphStyle(
            name="Quote",
            parent=styles["BodyText"],
            leftIndent=18,
            textColor=colors.HexColor("#444444"),
            italic=True,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CodeBlock",
            parent=styles["Code"],
            fontName="Courier",
            fontSize=8.5,
            leading=10,
            backColor=colors.HexColor("#F4F4F4"),
        )
    )
    return styles


def table_from_block(block: MarkdownBlock) -> Table:
    table = Table(block.rows, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E9EEF7")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return table


def block_to_flowables(block: MarkdownBlock, styles) -> list:
    if block.type == "heading":
        style_name = f"Heading{min(block.level or 1, 3)}"
        return [Paragraph(escape(block.text), styles[style_name]), Spacer(1, 0.08 * inch)]
    if block.type == "paragraph":
        return [Paragraph(escape(block.text).replace("\n", "<br/>"), styles["BodyText"]), Spacer(1, 0.08 * inch)]
    if block.type == "blockquote":
        return [Paragraph(escape(block.text), styles["Quote"]), Spacer(1, 0.08 * inch)]
    if block.type == "code":
        return [Preformatted(block.text, styles["CodeBlock"]), Spacer(1, 0.08 * inch)]
    if block.type == "bullet_list":
        flowable = ListFlowable([ListItem(Paragraph(escape(item), styles["BodyText"])) for item in block.items], bulletType="bullet")
        return [flowable, Spacer(1, 0.08 * inch)]
    if block.type == "ordered_list":
        flowable = ListFlowable([ListItem(Paragraph(escape(item), styles["BodyText"])) for item in block.items], bulletType="1")
        return [flowable, Spacer(1, 0.08 * inch)]
    if block.type == "table":
        return [table_from_block(block), Spacer(1, 0.12 * inch)]
    return []


def export_pdf(markdown_path: Path, output_path: Path) -> ExportPdfResult:
    styles = build_styles()
    blocks = parse_markdown_blocks(markdown_path.read_text(encoding="utf-8"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = NoteDocTemplate(
        str(output_path),
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )
    story = []
    title_text = markdown_path.stem
    if blocks and blocks[0].type == "heading":
        title_text = blocks[0].text
        blocks = blocks[1:]
    story.append(Paragraph(escape(title_text), styles["Title"]))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph("Table of Contents", styles["Heading1"]))
    toc = TableOfContents()
    toc.levelStyles = [styles["BodyText"], styles["BodyText"], styles["BodyText"]]
    story.append(toc)
    story.append(PageBreak())
    for block in blocks:
        story.extend(block_to_flowables(block, styles))
    doc.build(story)
    return ExportPdfResult(status="ok", output=str(output_path))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Markdown course notes to PDF.")
    parser.add_argument("--markdown", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--manifest")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_hint = Path(args.manifest).expanduser().resolve() if args.manifest else None
    try:
        request = ExportPdfRequest.model_validate(vars(args))
    except ValidationError as exc:
        if manifest_hint:
            write_validation_error(manifest_hint, exc)
        return 1

    markdown_path = Path(request.markdown).expanduser().resolve()
    try:
        course_root = infer_course_root_from_artifact(markdown_path)
        manifest_path = ensure_within_course_root(
            manifest_hint or course_root / TEMP_DIRNAME / f"{markdown_path.stem}.pdf-export-status.json",
            course_root,
        )
        output_path = ensure_within_course_root(Path(request.output).expanduser().resolve(), course_root)
    except ValueError as exc:
        if "manifest_path" in locals():
            write_error_manifest(
                manifest_path,
                code="OUT_OF_SCOPE_PATH",
                message="PDF export expects note artifacts inside a course directory.",
                source=str(markdown_path),
                details={"exception": str(exc)},
            )
        elif manifest_hint:
            write_error_manifest(
                manifest_hint,
                code="OUT_OF_SCOPE_PATH",
                message="PDF export expects note artifacts inside a course directory.",
                source=str(markdown_path),
                details={"exception": str(exc)},
            )
        return 1

    if not markdown_path.exists():
        write_error_manifest(
            manifest_path,
            code="MISSING_SOURCE",
            message="Markdown source file not found for PDF export.",
            source=str(markdown_path),
        )
        return 1

    try:
        result = export_pdf(markdown_path, output_path)
    except Exception as exc:
        write_error_manifest(
            manifest_path,
            code="EXPORT_FAILED",
            message="PDF export failed before completion.",
            source=str(markdown_path),
            details={"exception": str(exc)},
            retryable=True,
        )
        return 1

    write_manifest(manifest_path, **result.model_dump())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
