# Agent Response Templates

Use these templates when the skill hits a boundary, needs approval, or must choose the safest next step quickly.

## Usage Rule

Each reply should do four things in this order:

1. say what happened in plain language
2. name the boundary or decision
3. offer the shortest safe next step
4. continue with a fallback when one exists

Keep the tone calm, specific, and action-oriented. Do not ask broad open-ended questions when a narrow next step is available.

## Decision Shortcuts

| Situation | Default decision sentence |
|---|---|
| Canvas returned `401` or redirected to login | `I hit a login boundary on Canvas, so I did not keep retrying unauthenticated access.` |
| No usable browser login session | `I cannot rely on live Canvas access in the current session, so I can continue from exported pages or the lecture materials you already provided.` |
| Remote upload needs consent | `This next step would send course audio to [service], so I need your approval before uploading it.` |
| Video cannot be captured reliably | `The current video source is not reliably capturable from this session, so I should switch to captions, screenshots, or a local media file.` |
| Local dependency is missing | `The local tool for this path is not installed in the current environment.` |
| A fallback exists | `I can keep moving with [fallback] while leaving this blocked path aside.` |

## Template IDs

Use these stable IDs when mapping an error code or boundary to a default reply.

| Template ID | Use when |
|---|---|
| `TPL_CANVAS_401` | Canvas returns `401`, redirects to login, or the session is clearly unauthenticated |
| `TPL_NO_BROWSER_SESSION` | Live Canvas access is desired but no usable logged-in browser session is available |
| `TPL_REMOTE_UPLOAD_CONFIRM` | A hosted transcription step needs explicit upload approval |
| `TPL_LOCAL_WHISPER_INSTALL` | The next local step needs Whisper or related local dependencies installed |
| `TPL_VIDEO_CAPTURE_FAILED` | Audio/video extraction failed or the source is not reliably capturable |
| `TPL_HOSTED_API_KEY_MISSING` | A hosted provider path is blocked by a missing API key |
| `TPL_LOCAL_DEPENDENCY_MISSING` | A local tool such as Whisper or `ffmpeg` is missing |
| `TPL_SOURCE_MISSING_OR_UNSUPPORTED` | A required local file is missing or the source type is unsupported |
| `TPL_SAFE_CLEANUP_CONFIRM` | The skill is ready to delete only course-local intermediate files after confirmation |
| `TPL_API_401_AUTH` | A hosted API returned `401` or another auth/config failure that should not be retried blindly |
| `TPL_API_RETRY_OR_SWITCH` | A hosted API failed but looks retryable or provider-specific rather than a consent/auth issue |

## Standard Templates

### `TPL_CANVAS_401`

Use when:

- Canvas preflight gets `401`
- Canvas redirects to login
- a browser page opens without a usable authenticated session

Template:

`Canvas preflight hit a login boundary (401 or redirect), so I did not keep retrying. If you open the course in your own logged-in browser or give me exported Canvas page files, I can use that context; otherwise I can continue from the lecture video, slides, and captions alone.`

Decision short form:

`Login boundary on Canvas; continue with exports or lecture materials.`

### `TPL_NO_BROWSER_SESSION`

Use when:

- the user wants live Canvas context
- the current browser session is unavailable, expired, or not authenticated

Template:

`I do not have a usable logged-in browser session for this Canvas page. If you want Canvas context included, the cleanest next step is to open it in your own logged-in browser or provide exported HTML, copied text, or screenshots. If not, I can continue the note workflow without Canvas weighting.`

Decision short form:

`No live session; ask for exports or continue without Canvas context.`

### `TPL_REMOTE_UPLOAD_CONFIRM`

Use when:

- the next step is `transcribe_via_openai.py`
- the next step is `transcribe_via_assemblyai.py`
- the next step is `transcribe_via_deepgram.py`

Template:

`To fill this gap with transcription, I can send the audio to [service]. That would upload course audio off the machine, so I need your explicit approval before I run it. If you prefer, I can stay local with Whisper or use captions only.`

Decision short form:

`Remote upload required; name service and ask approval.`

### `TPL_LOCAL_WHISPER_INSTALL`

Use when:

- local Whisper is the preferred next step
- the environment may require installing Python/audio dependencies first

Template:

`I can try a local Whisper transcription path, which keeps the audio on your machine, but it may require installing Python/audio dependencies first. If you want to avoid installation, I can use captions only or an approved remote API instead.`

Decision short form:

`Local install required; offer Whisper vs captions vs remote API.`

### `TPL_VIDEO_CAPTURE_FAILED`

Use when:

- `EXTRACTION_FAILED` occurs
- a media URL cannot be downloaded reliably
- the current video source is DRM-protected, segmented, or not directly capturable

Template:

`I could not reliably extract audio from this video source in the current session. The safest next options are: use existing captions, work from screenshots/OCR, or use a local media file that you already captured from the logged-in browser session.`

Decision short form:

`Video capture unreliable; switch to captions, screenshots, or local media file.`

### `TPL_HOSTED_API_KEY_MISSING`

Use when:

- `MISSING_API_KEY` blocks a hosted provider path

Template:

`The hosted transcription path is configured in the skill, but the required API key is not available in the current environment. If you want that provider, we need the key configured first; otherwise I can switch to local transcription or captions.`

Decision short form:

`Hosted path blocked by missing API key; switch provider or stay local.`

### `TPL_LOCAL_DEPENDENCY_MISSING`

Use when:

- `MISSING_DEPENDENCY` is raised by local Whisper
- `MISSING_DEPENDENCY` is raised by `ffmpeg`
- another local-only tool is missing

Template:

`The local tool needed for this step is not installed right now. I can either stop here and wait for that dependency, or switch to a lower-dependency fallback such as captions, manual repair, or a hosted transcription path if you approve upload.`

Decision short form:

`Local dependency missing; install or use fallback.`

### `TPL_SOURCE_MISSING_OR_UNSUPPORTED`

Use when:

- `MISSING_SOURCE` occurs
- `UNSUPPORTED_SOURCE` occurs
- the skill does not have a compatible input for the chosen command

Template:

`This command does not have a usable source file yet. If you send the matching local file or exported artifact, I can continue on this path; otherwise I should switch to a source type the skill can process directly.`

Decision short form:

`Source missing or unsupported; request compatible input or switch path.`

### `TPL_SAFE_CLEANUP_CONFIRM`

Use when:

- cleanup is available
- deletion is scoped to the course folder and still needs user confirmation

Template:

`I can clean up the intermediate audio, transcript, and temporary files now. I will only remove files inside the course folder after you confirm.`

Decision short form:

`Cleanup available; confirm before deleting.`

### `TPL_API_401_AUTH`

Use when:

- `API_ERROR` includes `error.details.http_status = 401`
- the hosted provider rejects the request due to missing or invalid credentials
- the provider response clearly indicates auth or account configuration failure

Template:

`The hosted transcription request reached [service], but the provider rejected it as an authentication or configuration problem. I should not keep retrying that request blindly. If you want this provider, the next step is to fix the API key or account setup; otherwise I can switch to local transcription or captions.`

Decision short form:

`Hosted API auth boundary; fix key/config or switch path.`

### `TPL_API_RETRY_OR_SWITCH`

Use when:

- `API_ERROR` looks retryable but is not an auth failure
- `REQUEST_FAILED` occurs
- `TIMEOUT` occurs

Template:

`The hosted transcription path failed before producing a usable result, but this looks retryable or provider-specific rather than a consent issue. I can retry once, switch providers, or fall back to local transcription or captions.`

Decision short form:

`Hosted API failed; retry once, switch provider, or stay local.`

## Preferred Confirmation Questions

Use narrow confirmation prompts like these:

- `Do you want me to upload the audio to OpenAI for transcription?`
- `Do you want me to try the local Whisper path and install dependencies if needed?`
- `Do you want me to continue without Canvas context and build the notes from the lecture materials only?`
- `Do you want me to delete the intermediate audio and transcript files inside the course folder?`

Avoid prompts like:

- `What do you want to do?`
- `How should I proceed?`
- `Any preference?`

## Fallback Rule

If the blocked path is non-essential, prefer ending with a forward-moving fallback:

`I can keep going with [fallback] now, and we can come back to [blocked path] only if you want the extra context or repair quality later.`
