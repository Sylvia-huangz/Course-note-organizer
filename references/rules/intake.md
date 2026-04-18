# Intake Rules

Use a configuration-first intake flow. Skip any question the user has already answered clearly in the current conversation.

## Required Configuration Slots

Capture these values before full note assembly:

1. `supplementary_materials`
   - Does the user want textbooks, handouts, or other study materials folded into the notes?
2. `ppt_screenshot_pdf`
   - Does the user want PPT screenshots collected into a separate PDF?
3. `note_style`
   - Which style preset should structure the notes?
4. `export_format`
   - Should the final delivery stay in Markdown or also export to Word or PDF?

## Default Behavior

- If `note_style` is not provided, default to `standard-structured`.
- If `export_format` is not provided, ask once and offer `markdown`, `docx`, or `pdf`.
- If the user already supplied textbooks, PDFs, or links to extra materials, treat `supplementary_materials` as known.
- If the user already asked for a PDF of slide screenshots, treat `ppt_screenshot_pdf` as known.

## Intake Tone

- Keep the questions short and operational.
- Ask only what changes the output or workflow.
- Do not re-ask known answers.
- Do not force the user through a rigid checklist when the answer is already in the prompt.

## Saved Intake Shape

Use this normalized configuration shape:

```json
{
  "supplementary_materials": true,
  "ppt_screenshot_pdf": false,
  "note_style": "standard-structured",
  "export_format": "markdown"
}
```
