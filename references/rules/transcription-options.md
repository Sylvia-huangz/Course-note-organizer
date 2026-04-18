# Transcription Options

Check [`capability-boundaries.md`](./capability-boundaries.md) for upload and extraction limits, [`error-codes.md`](./error-codes.md) for recovery when local or hosted transcription fails, and [`agent-response-templates.md`](./agent-response-templates.md) for consent wording.

When transcription is needed, explain the available modes before taking action.

## Ask Before Installing Whisper

If local Whisper is not already available, tell the user:

- local Whisper keeps audio processing on the user's machine
- local Whisper may require installing Python packages and audio dependencies
- remote transcription avoids local model installation but sends audio to a third-party service

Then ask the user which path they want:

1. install or use local Whisper
2. use existing captions only
3. use an approved remote transcription API

Do not assume the user wants to install local dependencies.

## Local Whisper

Use this path when:

- the user wants local-only processing
- the machine can support Python-based transcription dependencies
- no approved remote upload is allowed

Benefits:

- audio stays local
- works offline after dependencies are installed
- good fit for privacy-sensitive course material

Tradeoffs:

- installation overhead
- runtime depends on local CPU or GPU

## Remote API Transcription

Use this path only after the user approves sending audio off the machine.

Current built-in remote option:

- `transcribe_via_openai.py`
  - requires `OPENAI_API_KEY`
  - uses the OpenAI Audio Transcriptions API
  - defaults to a timestamp-friendly request shape
- `transcribe_via_assemblyai.py`
  - requires `ASSEMBLYAI_API_KEY`
  - uploads local audio and polls AssemblyAI until the transcript completes
- `transcribe_via_deepgram.py`
  - requires `DEEPGRAM_API_KEY`
  - sends local audio or a remote media URL to Deepgram's pre-recorded transcription API

Remote transcription is best when:

- the user does not want to install Whisper locally
- the machine environment is too constrained for local transcription
- a fast programmatic integration matters more than local-only processing

Agent reminders:

- name the exact service before upload
- do not treat general note-taking consent as upload consent
- if the provider responds with `401`, `403`, or another auth failure, treat it as a configuration boundary rather than retrying blindly

## Caption Normalization

If usable `.srt` or `.vtt` captions already exist, prefer normalizing them first. This avoids both local model install and third-party uploads.
