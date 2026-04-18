# Repair and Transcription Rules

Use conservative repair logic when source quality is weak.

## Light Repair Is Allowed

You may repair short gaps with nearby context when:

- OCR is slightly blurry but the concept is otherwise obvious
- the subtitle gap is short and the missing words do not change meaning
- the supplied textbook or handout clearly fills the prerequisite step

Mark repaired passages when the change is not trivial.

## Ask Before Running Transcription

The first time a gap materially harms understanding, ask whether the user wants transcription support.

Trigger the ask when:

- OCR is too blurry to trust a definition, formula, or board step
- subtitles drop out across a concept boundary
- the lecture jumps too far to reconstruct the reasoning safely

When you ask, explain the available paths:

- use local Whisper if it is already installed
- install Whisper locally if the user wants on-device transcription
- use a remote transcription API if the user approves sending audio to a third party
- fall back to captions only if reliable captions already exist

## After User Approval

1. Extract audio with `extract_canvas_audio.py`.
2. Run `transcribe_audio.py`.
3. Use the transcript to repair the affected note sections.
4. Mark the repaired text in the notes.

If the user declines Whisper installation but approves remote transcription, run `transcribe_via_openai.py` or another approved remote path instead of `transcribe_audio.py`.

## Repair Marker Format

Use one of these markers:

```markdown
> [Repair: transcript-assisted] Reconstructed from approved audio transcription.
```

```markdown
> [Repair: context-assisted] Light semantic repair based on nearby lecture context and supplied materials.
```

Never hide uncertain repairs inside the main prose.
