# Intake Rules

Use a configuration-first intake flow. Skip any question the user has already answered clearly in the current conversation.

## Core Configuration Slots

Capture these values before full note assembly:

1. `supplementary_materials`
   - Does the user want textbooks, handouts, or other study materials folded into the notes?
2. `note_style`
   - Which style preset should structure the notes?
3. `export_format`
   - Should the final delivery stay in Markdown or also export to Word or PDF?

## Conditional Configuration Slot

Capture this value only when the user explicitly asks for this capability:

1. `ppt_screenshot_pdf`
   - Ask this only if the user clearly says they want PPT or video screenshots collected, organized, or exported separately.
   - Do not ask this just because slide assets, screenshots, or PPT files are present.
   - Do not ask this by default when the task is just lecture-note assembly.

## Default Behavior

- If `note_style` is not provided, default to `standard-structured`.
- If `export_format` is not provided, ask once and offer `markdown`, `docx`, or `pdf`.
- If the user already supplied textbooks, PDFs, or links to extra materials, treat `supplementary_materials` as known.
- If the user did not explicitly ask for screenshot collection or slide-image export, leave `ppt_screenshot_pdf` unset and do not raise it proactively.
- If the user already asked for a PDF of slide screenshots, treat `ppt_screenshot_pdf` as known.

## Intake Tone

- Keep the questions short and operational.
- Ask only what changes the output or workflow.
- Do not re-ask known answers.
- Do not force the user through a rigid checklist when the answer is already in the prompt.
- Do not assume PPT screenshots, board screenshots, or slide-image PDFs are needed unless the user says so.
- The presence of PPTs or screenshots alone is not a reason to ask about separate screenshot export.

## Saved Intake Shape

Use this normalized configuration shape:

```json
{
  "supplementary_materials": true,
  "note_style": "standard-structured",
  "export_format": "markdown",
  "ppt_screenshot_pdf": null
}
```
