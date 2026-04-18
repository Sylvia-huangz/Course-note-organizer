# course-note-organizer

A configurable, traceable course-note skill for turning lecture videos, Canvas pages, slide decks, captions, OCR, and related class materials into study-ready notes.

This skill is designed for Codex-style agent workflows where the agent needs to:

- preserve real lecture order
- generate a timestamped topic index
- optionally use Canvas announcements and assignments as course context
- repair OCR or subtitle gaps conservatively
- ask before transcription, upload, download, or cleanup
- export final notes to Markdown, Word, or PDF
- emit structured JSON metadata for downstream tools such as NotebookLM, flashcard generators, and exam-prep agents

## What This Skill Produces

The default output is a Markdown master note package that includes:

1. lesson title and identification
2. a timestamped topic index table
3. an optional Canvas context section
4. lecture-order notes
5. a structured lesson summary
6. a visible JSON metadata block

If requested, the Markdown master copy can also be exported to `.docx` and `.pdf`.

## Key Features

- Canvas-aware note generation with safe downgrade behavior
- Timestamped topic index for fast lecture review and navigation
- Multiple note-style presets
- Local or hosted transcription paths
- Explicit source traceability for video, Canvas, and transcript-assisted repair
- Standardized command schemas and error manifests
- Standardized response templates for login, upload, extraction, and dependency boundaries
- Privacy-first workflow with read-only defaults and explicit user consent before risky actions

## Repository Layout

```text
course-note-organizer/
|-- SKILL.md
|-- README.md
|-- agents/
|   `-- openai.yaml
|-- references/
|   `-- rules/
|       |-- agent-response-templates.md
|       |-- canvas-preflight.md
|       |-- capability-boundaries.md
|       |-- error-codes.md
|       |-- export.md
|       |-- intake.md
|       |-- metadata-schema.md
|       |-- repair-and-transcription.md
|       |-- security.md
|       |-- style-presets.md
|       |-- timestamp-index.md
|       `-- transcription-options.md
`-- scripts/
    `-- commands/
        |-- assemble_notes.py
        |-- cleanup_artifacts.py
        |-- export_docx.py
        |-- export_pdf.py
        |-- extract_canvas_audio.py
        |-- inspect_canvas_context.py
        |-- orchestrate_course_notes.py
        |-- transcribe_audio.py
        |-- transcribe_via_assemblyai.py
        |-- transcribe_via_deepgram.py
        |-- transcribe_via_openai.py
        |-- _common.py
        |-- _errors.py
        |-- _markdown_blocks.py
        `-- _schemas.py
```

## Command Overview

| Command | Purpose |
|---|---|
| `inspect_canvas_context.py` | Parse local Canvas exports, copied content, or snapshots into structured course context |
| `extract_canvas_audio.py` | Prepare audio from a local media file or directly accessible media URL |
| `transcribe_audio.py` | Normalize captions or run local Whisper when available |
| `transcribe_via_openai.py` | Hosted transcription through OpenAI Audio Transcriptions API |
| `transcribe_via_assemblyai.py` | Hosted transcription through AssemblyAI |
| `transcribe_via_deepgram.py` | Hosted transcription through Deepgram |
| `assemble_notes.py` | Build the Markdown master note package from structured note JSON |
| `export_docx.py` | Export Markdown notes to Word |
| `export_pdf.py` | Export Markdown notes to PDF |
| `cleanup_artifacts.py` | Preview or delete course-local temporary artifacts after confirmation |
| `orchestrate_course_notes.py` | Run the assembly and export flow through one stable entry point |

## Rule System

This skill separates runtime actions from decision rules.

- `SKILL.md`
  - high-level skill entry point, workflow, and trigger behavior
- `scripts/commands/`
  - task-focused executable commands
- `references/rules/`
  - intake rules, formatting rules, safety rules, fallback logic, error handling, and response templates

Important rule files:

- `capability-boundaries.md`
  - what the skill can and cannot do
- `error-codes.md`
  - standard error codes and default recovery mapping
- `agent-response-templates.md`
  - standardized user-facing wording for boundaries and consent requests
- `security.md`
  - privacy, permissions, and storage rules

## Safety Model

This skill is intentionally conservative.

- It uses only the user's own logged-in browser session for live Canvas access.
- It never asks for passwords.
- It never stores credentials, cookies, or tokens in the skill files.
- It defaults to read-only behavior.
- It asks before download, transcription, batch capture, upload, or cleanup.
- It does not silently blend uncertain reconstructions into the main notes.

## Transcription Modes

The skill supports three transcription paths:

1. Captions only
   - Best when `.srt` or `.vtt` already exist
2. Local Whisper
   - Keeps audio on-device
   - May require local dependency installation
3. Hosted APIs
   - OpenAI
   - AssemblyAI
   - Deepgram
   - Requires explicit user approval before upload

## Default Artifact Layout

When no output directory is specified, the skill creates a course folder under the current working directory with:

- `笔记`
- `音频`
- `临时文件`

All generated JSON files, including metadata sidecars, transcripts, manifests, and other machine-readable artifacts, are stored inside `临时文件`.

## Error Handling

Commands use a shared schema and error model built around:

- `Pydantic` request validation
- standardized manifests
- machine-readable `error.code`
- structured recovery suggestions
- default template mappings for common boundary situations

Examples of supported error categories:

- `VALIDATION_ERROR`
- `MISSING_SOURCE`
- `MISSING_DEPENDENCY`
- `MISSING_API_KEY`
- `EXTRACTION_FAILED`
- `API_ERROR`
- `TIMEOUT`
- `EXPORT_FAILED`

## Typical Workflow

1. Gather lecture materials.
2. Optionally inspect Canvas context if a usable session or export is available.
3. Run intake to determine note style and export format.
4. Build the timestamped topic index.
5. Draft lecture-order notes.
6. Repair gaps conservatively.
7. Ask before local install or remote transcription if needed.
8. Assemble the Markdown master note.
9. Export to Word or PDF if requested.
10. Offer cleanup of temporary artifacts.

## Best Fit

This skill is a good fit when you need:

- lecture notes that are navigable, not just summarized
- safer educational workflows with explicit permission boundaries
- outputs that can feed downstream study systems
- an agent that can explain failures and propose the next safe step clearly

## Not Designed For

This skill is not intended to:

- bypass Canvas authentication
- scrape protected video streams without user access
- perform state-changing actions inside Canvas
- upload course audio silently
- store user-private course data in long-lived rule files

## Status

Current architecture includes:

- modular command layer
- split rules layer
- shared schema and error model
- capability boundary documentation
- response-template mapping for common runtime failures

## License

Add your preferred license here before publishing to GitHub.
