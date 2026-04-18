from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class MarkdownBlock:
    type: str
    text: str = ""
    level: int | None = None
    items: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)


def _flush_paragraph(buffer: list[str], blocks: list[MarkdownBlock]) -> None:
    text = "\n".join(buffer).strip()
    if text:
        blocks.append(MarkdownBlock(type="paragraph", text=text))
    buffer.clear()


def parse_markdown_blocks(text: str) -> list[MarkdownBlock]:
    lines = text.splitlines()
    blocks: list[MarkdownBlock] = []
    paragraph_buffer: list[str] = []
    in_code = False
    code_buffer: list[str] = []
    list_kind: str | None = None
    list_buffer: list[str] = []
    table_buffer: list[list[str]] = []

    def flush_list() -> None:
        nonlocal list_kind
        if list_buffer:
            blocks.append(MarkdownBlock(type=list_kind or "bullet_list", items=list_buffer.copy()))
            list_buffer.clear()
            list_kind = None

    def flush_table() -> None:
        if table_buffer:
            blocks.append(MarkdownBlock(type="table", rows=table_buffer.copy()))
            table_buffer.clear()

    for line in lines:
        stripped = line.rstrip()
        if stripped.startswith("```"):
            flush_list()
            flush_table()
            _flush_paragraph(paragraph_buffer, blocks)
            if in_code:
                blocks.append(MarkdownBlock(type="code", text="\n".join(code_buffer)))
                code_buffer.clear()
                in_code = False
            else:
                in_code = True
            continue

        if in_code:
            code_buffer.append(line)
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading_match:
            flush_list()
            flush_table()
            _flush_paragraph(paragraph_buffer, blocks)
            blocks.append(
                MarkdownBlock(
                    type="heading",
                    level=len(heading_match.group(1)),
                    text=heading_match.group(2).strip(),
                )
            )
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            flush_list()
            _flush_paragraph(paragraph_buffer, blocks)
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if not all(re.fullmatch(r"-{3,}", cell.replace(":", "").strip()) for cell in cells):
                table_buffer.append(cells)
            continue
        flush_table()

        bullet_match = re.match(r"^\s*[-*+]\s+(.*)$", stripped)
        ordered_match = re.match(r"^\s*\d+\.\s+(.*)$", stripped)
        if bullet_match or ordered_match:
            _flush_paragraph(paragraph_buffer, blocks)
            kind = "ordered_list" if ordered_match else "bullet_list"
            if list_kind and list_kind != kind:
                flush_list()
            list_kind = kind
            list_buffer.append((ordered_match or bullet_match).group(1).strip())
            continue
        flush_list()

        if stripped.startswith(">"):
            _flush_paragraph(paragraph_buffer, blocks)
            blocks.append(MarkdownBlock(type="blockquote", text=stripped.lstrip(">").strip()))
            continue

        if not stripped:
            flush_list()
            flush_table()
            _flush_paragraph(paragraph_buffer, blocks)
            continue

        paragraph_buffer.append(stripped)

    flush_list()
    flush_table()
    _flush_paragraph(paragraph_buffer, blocks)

    if in_code and code_buffer:
        blocks.append(MarkdownBlock(type="code", text="\n".join(code_buffer)))

    return blocks

