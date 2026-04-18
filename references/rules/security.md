# Security Rules

These rules are mandatory.

Read [`capability-boundaries.md`](./capability-boundaries.md) for operational limits, [`error-codes.md`](./error-codes.md) for how to explain auth, upload, and extraction failures, and [`agent-response-templates.md`](./agent-response-templates.md) for standardized user-facing wording.

## Login and Session Handling

- Use only the user's own logged-in browser session.
- Never ask the user to provide a password.
- Never store account credentials, cookies, or tokens in the skill files.

## Minimum Permissions

- Default to read-only access for course pages.
- Do not perform actions that mutate Canvas state.
- Before downloading media, running transcription, or batch-capturing assets, ask the user first.
- Before sending course audio to a third-party transcription API, ask the user explicitly and name the service.
- Treat missing login state, `401`, or provider auth failures as hard boundaries unless the user restores access from their own session or key configuration.

## File Storage

- Write generated files only to a user-specified directory or to a course folder under the current working directory.
- Keep notes, audio, and temporary artifacts in separate subfolders.
- Ask before deleting intermediate files.

## Sensitive Content

- Do not write course-private content into `references/rules/` or other long-lived skill files.
- If you keep sample payloads, anonymize them.
- Do not upload course audio to a remote service without user approval for that specific task.

## Traceability

- Mark whether a passage came from video, Canvas, or transcript-assisted repair.
- Do not silently blend reconstructed content into the main notes.
