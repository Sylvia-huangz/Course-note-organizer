# Error Codes

Use this file to interpret command manifests and choose the next recovery step quickly. For the exact user-facing phrasing, reuse [`agent-response-templates.md`](./agent-response-templates.md) instead of improvising.

## Error Model

Commands return a standard manifest shape:

- `status`
- optional `notes`
- optional `error.code`
- optional `error.message`
- optional `error.suggestions`
- optional `error.retryable`
- optional `error.details`

The agent should read `error.code` first, then combine `message`, `suggestions`, and any structured `details` into the user-facing next step.

## Priority Handling

1. Authentication or session boundary
2. User-consent boundary
3. Missing input or unsupported media
4. Missing dependency or API key
5. Recoverable remote/API failure
6. Formatting or schema validation failure

## Error Code Table

| Error code | Meaning | Typical trigger | Agent action |
|---|---|---|---|
| `VALIDATION_ERROR` | Command arguments failed schema validation | Missing required flag, malformed request, invalid enum | Fix arguments or rebuild the request payload before retrying |
| `MISSING_SOURCE` | A required local file or exported artifact is missing | Missing note spec, missing caption file, missing audio, missing Markdown source | Ask for the missing file or switch to another available source |
| `INVALID_JSON` | JSON input could not be parsed | Broken note spec or malformed structured input | Repair or regenerate the JSON before rerunning |
| `READ_FAILED` | A local artifact existed but could not be parsed reliably | Corrupted or unreadable Canvas export | Tell the user the export is unusable and ask for a fresh export or fallback source |
| `PARSE_FAILED` | Caption normalization failed | Broken `.srt` / `.vtt` timing blocks | Ask for a cleaner caption file or switch to audio transcription |
| `UNSUPPORTED_SOURCE` | The media or source type is not supported for that command | Non-audio file passed to transcription, non-media file passed to extraction | Choose a compatible command or ask the user for a different source |
| `MISSING_DEPENDENCY` | A required local dependency is not available | Whisper not installed, `ffmpeg` missing | Offer installation or a lower-dependency fallback |
| `MISSING_API_KEY` | Hosted transcription cannot start because the provider key is absent | No `OPENAI_API_KEY`, `ASSEMBLYAI_API_KEY`, or `DEEPGRAM_API_KEY` | Ask whether to configure the key, switch providers, or use local transcription |
| `SIZE_LIMIT_EXCEEDED` | The provider rejected the file size before upload or processing | OpenAI upload limit exceeded | Suggest splitting or compressing audio, or switch providers/local processing |
| `DOWNLOAD_FAILED` | Direct media download did not complete | Media URL needs session auth or the URL is transient | Explain that direct download failed and ask for browser-assisted capture or a local file |
| `EXTRACTION_FAILED` | Media extraction failed after the command started | `ffmpeg` could not decode or extract the video audio | Ask for a new source file, a different format, or captions-only fallback |
| `TRANSCRIPTION_FAILED` | Local Whisper failed during transcription | Local runtime/model failure | Offer retry, smaller model, captions-only path, or approved remote transcription |
| `API_ERROR` | A remote service returned an HTTP or provider-level failure | Provider error payload, request rejected, auth rejected | Inspect `error.details.http_status`; if `401`, `403`, or similar, treat as an auth/config problem; if `5xx`, retry or switch provider |
| `REQUEST_FAILED` | A remote request failed before a valid provider response | Network issue, DNS issue, transport timeout, local request construction failure | Retry if appropriate, then switch to another provider or local processing |
| `TIMEOUT` | Remote polling or completion did not finish in time | Async provider never reached completed status | Ask whether to wait longer, retry, or switch transcription mode |
| `ASSEMBLY_FAILED` | Local note assembly failed | Writing Markdown, rendering structured sections, orchestration assembly step | Retry after inspecting the spec and outputs |
| `EXPORT_FAILED` | DOCX or PDF generation failed | Converter runtime error, malformed Markdown edge case | Fall back to Markdown delivery and report export limitation |
| `OUT_OF_SCOPE_PATH` | Cleanup target is outside the managed course root | Attempted delete outside course folder | Refuse deletion and keep cleanup scoped to the course directory |

## Default Template Mapping

Use this table after reading the error manifest. Match the most specific row first.

| Error code | Extra condition | Default template ID | Default action |
|---|---|---|---|
| `API_ERROR` | `error.details.http_status = 401` or provider auth failure is explicit | `TPL_API_401_AUTH` | Stop retrying blindly, explain auth/config boundary, switch provider or stay local |
| `API_ERROR` | `error.details.http_status = 403` | `TPL_API_401_AUTH` | Treat as provider auth/account boundary unless the manifest clearly says otherwise |
| `API_ERROR` | `error.details.http_status >= 500` | `TPL_API_RETRY_OR_SWITCH` | Retry once or switch provider |
| `API_ERROR` | no auth signal, no clear local input problem | `TPL_API_RETRY_OR_SWITCH` | Retry once or switch provider/local path |
| `REQUEST_FAILED` | any | `TPL_API_RETRY_OR_SWITCH` | Retry once, then switch provider or local path |
| `TIMEOUT` | any | `TPL_API_RETRY_OR_SWITCH` | Offer retry with patience, switch provider, or use local path |
| `MISSING_DEPENDENCY` | local Whisper path | `TPL_LOCAL_WHISPER_INSTALL` | Offer install vs captions vs remote API |
| `MISSING_DEPENDENCY` | `ffmpeg` or extraction tool path | `TPL_LOCAL_DEPENDENCY_MISSING` | Offer install vs captions/screenshots/local file fallback |
| `MISSING_DEPENDENCY` | other local tool | `TPL_LOCAL_DEPENDENCY_MISSING` | Explain local tool is missing and offer fallback |
| `EXTRACTION_FAILED` | any | `TPL_VIDEO_CAPTURE_FAILED` | Stop extraction retries and switch to captions, screenshots, or a captured local media file |
| `DOWNLOAD_FAILED` | media URL needs session auth or download is unreliable | `TPL_VIDEO_CAPTURE_FAILED` | Use browser-assisted capture or other source materials |
| `MISSING_API_KEY` | hosted transcription provider | `TPL_HOSTED_API_KEY_MISSING` | Configure key or switch provider/local |
| `MISSING_SOURCE` | any | `TPL_SOURCE_MISSING_OR_UNSUPPORTED` | Ask for compatible source or switch path |
| `UNSUPPORTED_SOURCE` | any | `TPL_SOURCE_MISSING_OR_UNSUPPORTED` | Ask for compatible source or switch path |
| `PARSE_FAILED` | captions-only path | `TPL_SOURCE_MISSING_OR_UNSUPPORTED` | Ask for cleaner caption file or switch to audio transcription |
| `READ_FAILED` | Canvas export parse failure | `TPL_SOURCE_MISSING_OR_UNSUPPORTED` | Ask for a fresh export or continue without Canvas context |
| `OUT_OF_SCOPE_PATH` | cleanup path outside course root | `TPL_SAFE_CLEANUP_CONFIRM` | Refuse unsafe deletion and keep cleanup scoped |

## Boundary-Specific Interpretation

### `401 Unauthorized`

This skill may surface `401` in two common ways:

- Canvas or browser-access workflow shows login is unavailable
- hosted transcription returns `API_ERROR` with `error.details.http_status = 401`

Agent rule:

- do not ask for passwords, cookies, or tokens
- explain which session or API key is missing
- ask the user to restore their own logged-in browser session or configure the provider key
- use `TPL_CANVAS_401` for Canvas login loss
- use `TPL_API_401_AUTH` for hosted provider auth/config failures

### No Logged-In Browser Session

Treat as a workflow boundary rather than a fatal blocker:

- skip live Canvas reads
- ask for exported HTML, copied text, or screenshots
- continue note-making with available lecture materials

Default template:

- `TPL_NO_BROWSER_SESSION`

### Video Cannot Be Captured Reliably

If direct extraction or download is blocked:

- say that the current session or source does not permit reliable capture
- prefer captions, screenshots, OCR, or manual repair
- offer transcription only if the user can provide a local media file or a directly accessible URL

Default template:

- `TPL_VIDEO_CAPTURE_FAILED`

### User Confirmation Required Before Upload

Remote transcription is never implied by general note-taking consent.

Before running `transcribe_via_openai.py`, `transcribe_via_assemblyai.py`, or `transcribe_via_deepgram.py`, the agent must confirm:

- which service will receive the audio
- that course audio will leave the machine
- that the user approves that upload for this task

Default template:

- `TPL_REMOTE_UPLOAD_CONFIRM`

## Recommended User-Facing Recovery Style

When reporting an error:

1. state what failed in plain language
2. name the boundary or error code
3. give the shortest safe next action
4. continue with a fallback path when one exists

Example:

`Canvas preflight hit a login boundary (401), so I did not keep retrying. If you open the course in your own logged-in browser or export the page, I can use that context; otherwise I can continue from the lecture video and slides alone.`
