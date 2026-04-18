---
name: course-note-organizer
description: Create complete, study-ready course notes from lecture videos, Canvas pages, slide decks, handwritten board work, software demos, textbooks, and related class materials. Use when Codex needs to turn course content into structured lecture-order notes, build timestamped topic indexes, incorporate Canvas announcements or assignments, optionally trigger transcription to repair OCR or subtitle gaps, apply note-style presets, or export notes to Markdown, Word, or PDF.
---

# Course Note Organizer

Turn course materials into detailed notes that are easy to review, trace back to the source, and hand off to downstream study tools.

## Default Outcome

Produce a complete Markdown note package that:

- follows the real lecture order
- opens with a timestamped topic index
- optionally includes a short Canvas course-context note
- clearly labels content that came from video, Canvas, or transcription repair
- ends with a structured lesson summary
- ends with a visible JSON metadata block for downstream tools such as NotebookLM, flashcard generators, or exam-prep agents

When the user asks for Word or PDF, first produce the Markdown master copy and then run the export commands.

## Operating Model

Use the skill in this order:

1. Run the Canvas preflight only when the user provides a Canvas entry point, exported Canvas pages, screenshots, or a usable logged-in browser session.
2. Load the capability boundaries before deciding what can be accessed, extracted, or uploaded.
3. Run the intake flow from [`references/rules/intake.md`](./references/rules/intake.md).
4. Build a source inventory and keep the lecture order intact.
5. Create the timestamp index before drafting the body.
6. Repair gaps conservatively. Ask before running transcription.
7. Assemble the Markdown note package.
8. Export to Word or PDF only if requested.
9. Keep all artifacts local and follow the security rules.

## Command Layer

Use the commands in [`scripts/commands`](./scripts/commands) as task-focused building blocks:

- `inspect_canvas_context.py`
  - Parse Canvas course pages, exported HTML, copied text, or JSON snapshots into structured course context.
- `extract_canvas_audio.py`
  - Prepare audio from a local media file or a browser-captured media file. This command never logs in by itself.
- `transcribe_audio.py`
  - Run transcription when the user approves it, or convert captions into the same transcript schema.
- `transcribe_via_openai.py`
  - Send approved audio to the OpenAI Audio Transcriptions API when the user prefers a no-local-install path.
- `transcribe_via_assemblyai.py`
  - Send approved audio to AssemblyAI for asynchronous transcription when the user prefers a hosted API path.
- `transcribe_via_deepgram.py`
  - Send approved audio to Deepgram for pre-recorded transcription when the user prefers a hosted API path.
- `assemble_notes.py`
  - Turn structured course-note JSON into the final Markdown note package.
- `export_docx.py`
  - Convert the Markdown master copy into a navigable `.docx` file.
- `export_pdf.py`
  - Convert the Markdown master copy into a printable `.pdf` file.
- `cleanup_artifacts.py`
  - Preview or delete temporary audio, transcript, and screenshot artifacts after the user confirms cleanup.
- `orchestrate_course_notes.py`
  - Run the assembly and export steps behind one stable entry point.

Before using a command, check [`references/rules/capability-boundaries.md`](./references/rules/capability-boundaries.md) so the agent does not assume login access, silent uploads, or unsupported video extraction paths.

## Rules Index

Load the relevant rule file before acting:

- Capability boundaries: [`references/rules/capability-boundaries.md`](./references/rules/capability-boundaries.md)
- Error codes and recovery: [`references/rules/error-codes.md`](./references/rules/error-codes.md)
- Agent response templates: [`references/rules/agent-response-templates.md`](./references/rules/agent-response-templates.md)
- Intake flow: [`references/rules/intake.md`](./references/rules/intake.md)
- Timestamp index requirements: [`references/rules/timestamp-index.md`](./references/rules/timestamp-index.md)
- Canvas preflight and matching rules: [`references/rules/canvas-preflight.md`](./references/rules/canvas-preflight.md)
- Repair and transcription triggers: [`references/rules/repair-and-transcription.md`](./references/rules/repair-and-transcription.md)
- Transcription mode selection: [`references/rules/transcription-options.md`](./references/rules/transcription-options.md)
- Style presets: [`references/rules/style-presets.md`](./references/rules/style-presets.md)
- Export behavior: [`references/rules/export.md`](./references/rules/export.md)
- Metadata schema: [`references/rules/metadata-schema.md`](./references/rules/metadata-schema.md)
- Security and privacy constraints: [`references/rules/security.md`](./references/rules/security.md)

## Canvas Usage

Use the `web-access` skill when you need to inspect Canvas in a logged-in browser session. This skill must not ask the user for passwords and must not store credentials, cookies, or tokens.

Canvas context is optional support, not a gate. If the course pages are unavailable, blocked by login, or too incomplete to trust, state the limitation and continue with the available lecture materials.

Only let Canvas context influence the amount of detail in the notes when both of these are true:

- the topic matches the current lecture
- the week, module, release timing, or instructor wording confirms that match

If the match is weak, keep the course-context note brief and do not rewrite the lecture around assignments.

If Canvas returns `401`, redirects to login, or opens without a usable logged-in session:

- do not ask the user for credentials
- do not keep retrying with the same unauthenticated path
- ask the user to open Canvas in their own logged-in browser session or provide exported page artifacts
- continue without Canvas context when the lecture materials are otherwise sufficient

Use [`references/rules/agent-response-templates.md`](./references/rules/agent-response-templates.md) for the shortest safe user-facing wording when you hit this boundary.

## Gap Repair

When OCR is blurry, captions are incomplete, or the explanation jumps too far for a reliable note:

1. Use nearby context and supplied study material for light repair.
2. If the gap still affects understanding, explain the available transcription modes and ask whether the user wants to install Whisper or use an approved remote transcription path.
3. If the user chooses local transcription, run `extract_canvas_audio.py` and `transcribe_audio.py`.
4. If the user chooses remote transcription and approves sending audio to a third-party API, run `transcribe_via_openai.py` or another approved remote path.
5. Mark repaired content clearly in the final note.

Do not silently blend uncertain repairs into the main body.

When the skill pauses for consent, login recovery, or extraction fallback, use the standardized response templates instead of improvising vague wording.

## Output Contract

The Markdown master copy must include these sections in order:

1. Title and lesson identification
2. Timestamped topic index table
3. Optional Canvas course-context note
4. Main lecture-order notes
5. Structured lesson summary
6. Visible JSON metadata block

If the user chooses a style preset, adapt the structure without removing the index, summary, metadata block, or source traceability markers.

## Artifact Layout

When the user does not specify an output directory, create a course folder under the current working directory and keep these subfolders:

- `笔记`
- `音频`
- `其他临时文件`

Place the Markdown master copy in `笔记`. Place extracted audio in `音频`. Place transcripts, screenshots, formula images, and temporary render assets in `其他临时文件` unless a command needs them elsewhere.

## Safety

Follow [`references/rules/security.md`](./references/rules/security.md) exactly:

- read-only browser usage by default
- no password handling
- no persistent storage of user course data in the skill files
- no silent deletion of generated artifacts
- clear source labels in the notes
