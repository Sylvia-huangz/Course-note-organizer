# Export Rules

Always create a Markdown master copy first. Export commands consume the Markdown file.

## Export Targets

- `markdown`
- `docx`
- `pdf`

## Word Export

- Map Markdown headings to `Heading 1`, `Heading 2`, and `Heading 3`.
- Preserve the timestamp index as a table.
- Preserve code fences as monospaced paragraphs.
- Preserve blockquotes as visually distinct callouts.
- Try to keep formulas editable when a native Office-equation converter is available.
- If native conversion is unavailable, fall back to a clearly preserved representation and report the fallback.

## PDF Export

- Use a clean academic layout.
- Include page numbers.
- Include a title page or top-of-document title treatment.
- Keep code blocks visually distinct.
- Preserve the summary and metadata appendix.

## Delivery

- Return local file paths for generated outputs.
- Do not claim a format was generated if the command failed.
- Leave the Markdown master copy in place even when exporting other formats.
