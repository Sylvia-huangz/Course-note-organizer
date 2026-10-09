# Style Presets

Support a small preset set in v1. Use these normalized identifiers.

## `standard-structured`

- Default preset
- Straight lecture-order headings and subsections
- Best for mixed technical courses

## `cornell`

- Add `Cue`, `Notes`, and `Review Prompt` subsections where possible
- Keep the timestamp index, summary, and metadata block unchanged

## `qa-sprint`

- Organize each topic around likely review questions and short answers
- Best for exam-focused revision

## `outline-map`

- Use tighter heading nesting and concise branch-like bullets
- Best for conceptual or theory-heavy lessons

## `dual-column-teaching-aid`

- Two-column HTML table per teaching unit — the product's flagship preset
- **Left column (60%):** teacher's verbal narrative (`teacher_narrative`) + board/slide screenshots with Chinese captions via `visuals[]`
- **Right column (40%):** teacher's emphasized key points (`emphasis_points`), pitfalls, and keywords
- **Teaching unit:** each `NoteSection` = one teacher "讲解单元" (a natural block the teacher covers before moving to the next topic)
- **Visual assets:** support `board`, `slide`, `diagram`, and `screenshot` types — each requires a `path`, `caption`, and optional `alt_text`
- **Fallback behavior:** if `teacher_narrative` is empty, falls back to `content`; if `emphasis_points` is empty, falls back to `key_points`
- **Source trace** and **repair annotations** render above the table; **examples** and **review questions** render below at full width
- Best for: online course learners who want study-ready "教辅" companion notes that separate "what the teacher said" from "what matters"
- **AI pipeline integration:** the `ai_pipeline/pipeline.py` produces NoteSpec JSON with `teacher_narrative`, `emphasis_points`, `visuals[]`, and `pitfalls` pre-populated — use this preset as the `--style` flag after running the pipeline for the full automated dual-column experience

## Invariants

No preset may remove:

- the timestamp index
- Canvas context note when applicable
- source traceability markers
- structured lesson summary
- visible JSON metadata block
