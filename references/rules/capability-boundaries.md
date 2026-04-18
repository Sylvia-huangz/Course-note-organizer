# Capability Boundaries

Read this file before choosing a command, browser workflow, or transcription path. For the user-facing wording that goes with each boundary, pair it with [`agent-response-templates.md`](./agent-response-templates.md).

## Core Principle

This skill is designed to be high-trust and low-surprise:

- use the user's own logged-in browser session when live Canvas access is needed
- default to read-only behavior
- do not request passwords, cookies, or tokens
- do not assume audio/video extraction is always possible
- do not upload course audio unless the user explicitly approves that upload for the current task

## Boundary Table

| Situation | What the agent may do | What the agent must not do | Required next step |
|---|---|---|---|
| Canvas page opens normally in a usable logged-in browser session | Read course home, announcements, assignments, and relevant lesson pages | Change Canvas state or save credentials | Continue with Canvas preflight |
| Canvas returns `401 Unauthorized` or redirects to login | Explain that live access is unavailable in the current session | Ask for password, token, cookie, or retry endlessly with the same unauthenticated request | Ask the user to open Canvas in their own logged-in browser or provide exported page artifacts |
| User provides exported Canvas HTML, JSON, copied text, or screenshots | Parse those local artifacts with `inspect_canvas_context.py` | Pretend they are live pages with full fidelity | Continue in degraded mode and note limits |
| No usable browser session and no exported Canvas artifacts | Skip Canvas weighting | Block the full note workflow | Continue with lecture video, slides, captions, and other materials |
| Video page is visible but the media URL is not directly accessible | Use browser-assisted capture or ask the user to download/capture the media first | Claim the command can log in or directly bypass protected delivery | Explain that `extract_canvas_audio.py` does not authenticate by itself |
| Video is DRM-protected, segmented, or otherwise not capturable from the available session | Fall back to captions, OCR, screenshots, or manual note repair | Promise guaranteed extraction | Tell the user extraction is not currently reliable and continue without that media path |
| OCR or subtitles have small gaps | Apply light contextual repair and clearly mark repaired passages | Silently rewrite uncertain content as if exact | Continue with conservative repair |
| OCR or subtitles have major gaps that harm comprehension | Offer transcription choices | Force local install or remote upload without consent | Ask whether the user wants local Whisper, captions-only, or an approved remote API |
| User chooses local Whisper | Extract local audio and transcribe locally if dependencies are available | Upload audio remotely | Keep processing on-device |
| User chooses remote transcription | Use `transcribe_via_openai.py`, `transcribe_via_assemblyai.py`, or `transcribe_via_deepgram.py` after explicit approval | Upload audio silently or imply it stayed local | Name the service and proceed only after approval |
| User has not approved media download, batch capture, or upload | Pause that branch | Treat prior general note-taking consent as upload consent | Ask first |
| Cleanup is requested | Preview deletions and then remove only paths inside the course root after confirmation | Delete outside the course folder or delete silently | Use `cleanup_artifacts.py` with confirmation |

## Command-by-Command Boundaries

### `inspect_canvas_context.py`

Can do:

- parse local Canvas exports and copied content
- return structured, read-only context
- degrade cleanly when sources are missing or weak

Cannot do:

- log in to Canvas
- browse protected pages by itself
- guarantee that copied/exported content is complete

### `extract_canvas_audio.py`

Can do:

- copy local audio into the skill artifact layout
- extract audio from local video with `ffmpeg`
- download directly accessible media URLs

Cannot do:

- use browser cookies or session auth by itself
- bypass protected or DRM delivery
- guarantee extraction from every Canvas-hosted player

### `transcribe_audio.py`

Can do:

- normalize `.srt` / `.vtt`
- run local Whisper when available
- emit transcript JSON plus plain text artifacts

Cannot do:

- install Whisper by itself without user agreement
- make remote uploads
- guarantee local transcription dependencies exist

### `transcribe_via_openai.py`, `transcribe_via_assemblyai.py`, `transcribe_via_deepgram.py`

Can do:

- upload approved audio to the named service
- return standardized status manifests and transcript artifacts

Cannot do:

- run without the corresponding API key
- claim the audio stayed local
- skip user consent for third-party upload

### `assemble_notes.py`, `export_docx.py`, `export_pdf.py`, `orchestrate_course_notes.py`

Can do:

- build the note package from structured local inputs
- export local artifacts
- surface manifest-based errors

Cannot do:

- infer missing source media that was never captured
- repair inaccessible Canvas content by themselves
- delete user files outside the managed course directory

## Agent Decision Rules

When uncertain, prefer this order:

1. local artifacts already provided by the user
2. the user's live logged-in browser session
3. local-only processing
4. explicit user confirmation before any upload or destructive action

If a path fails because of login, extraction, or upload constraints, state the boundary clearly and continue with the highest-trust fallback that remains available.
