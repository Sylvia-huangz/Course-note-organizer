from __future__ import annotations

import argparse
import importlib.util
import json
import re
from pathlib import Path

from pydantic import ValidationError

from _common import ensure_course_dirs
from _errors import write_error_manifest, write_manifest, write_model, write_validation_error
from _schemas import TranscriptPayload, TranscribeAudioRequest


def whisper_available() -> bool:
    return importlib.util.find_spec("whisper") is not None


def parse_timestamp(label: str) -> float:
    parts = label.strip().split(":")
    numbers = [float(part.replace(",", ".")) for part in parts]
    if len(numbers) == 3:
        hours, minutes, seconds = numbers
        return hours * 3600 + minutes * 60 + seconds
    minutes, seconds = numbers
    return minutes * 60 + seconds


def parse_caption_file(path: Path) -> dict:
    text = path.read_text(encoding="utf-8-sig", errors="ignore")
    segments = []
    if path.suffix.lower() == ".vtt":
        blocks = [block.strip() for block in text.split("\n\n") if "-->" in block]
        for block in blocks:
            lines = [line for line in block.splitlines() if line.strip() and "WEBVTT" not in line]
            if not lines:
                continue
            timing = lines[0]
            start, end = [part.strip() for part in timing.split("-->")]
            content = " ".join(lines[1:]).strip()
            segments.append({"start": parse_timestamp(start), "end": parse_timestamp(end), "text": content})
    else:
        blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if "-->" in block]
        for block in blocks:
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            timing_line = next((line for line in lines if "-->" in line), None)
            if not timing_line:
                continue
            start, end = [part.strip() for part in timing_line.split("-->")]
            content_lines = [line for line in lines if line != timing_line and not line.isdigit()]
            segments.append({"start": parse_timestamp(start), "end": parse_timestamp(end), "text": " ".join(content_lines)})
    return {
        "segments": segments,
        "text": " ".join(segment["text"] for segment in segments).strip(),
    }


def run_whisper(audio_path: Path, model_name: str, language: str | None, initial_prompt: str | None) -> dict:
    import whisper  # type: ignore

    model = whisper.load_model(model_name)
    kwargs = {}
    if language:
        kwargs["language"] = language
    if initial_prompt:
        kwargs["initial_prompt"] = initial_prompt
    result = model.transcribe(str(audio_path), word_timestamps=False, **kwargs)
    segments = [
        {"start": segment["start"], "end": segment["end"], "text": segment["text"].strip()}
        for segment in result.get("segments", [])
    ]
    return {
        "segments": segments,
        "text": result.get("text", "").strip(),
        "language": result.get("language"),
        "model": model_name,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Transcribe audio or normalize caption files into transcript artifacts.")
    parser.add_argument("--course-title", required=True)
    parser.add_argument("--base-dir", default=".")
    parser.add_argument("--audio")
    parser.add_argument("--caption-file")
    parser.add_argument("--model", default="base")
    parser.add_argument("--language")
    parser.add_argument("--initial-prompt")
    parser.add_argument("--manifest", help="Optional JSON manifest path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_hint = Path(args.manifest).expanduser().resolve() if args.manifest else None
    try:
        request = TranscribeAudioRequest.model_validate(vars(args))
    except ValidationError as exc:
        if manifest_hint:
            write_validation_error(manifest_hint, exc)
        return 1

    course_dirs = ensure_course_dirs(request.base_dir, request.course_title)
    temp_dir = course_dirs["temp"]

    if request.caption_file:
        source_path = Path(request.caption_file).expanduser().resolve()
        if not source_path.exists():
            write_error_manifest(
                manifest_hint or temp_dir / "transcription-status.json",
                code="MISSING_SOURCE",
                message="Caption source file not found.",
                source=str(source_path),
            )
            return 1
        try:
            transcript = TranscriptPayload.model_validate(parse_caption_file(source_path))
        except Exception as exc:
            write_error_manifest(
                manifest_hint or temp_dir / f"{source_path.stem}.transcription-status.json",
                code="PARSE_FAILED",
                message="Failed to normalize the caption file.",
                source=str(source_path),
                details={"exception": str(exc)},
            )
            return 1
        notes = ["Transcript normalized from captions without Whisper."]
        status_ok = True
    else:
        source_path = Path(request.audio).expanduser().resolve()
        if not source_path.exists():
            write_error_manifest(
                manifest_hint or temp_dir / "transcription-status.json",
                code="MISSING_SOURCE",
                message="Audio source file not found.",
                source=str(source_path),
            )
            return 1
        if whisper_available():
            try:
                transcript = TranscriptPayload.model_validate(
                    run_whisper(
                        audio_path=source_path,
                        model_name=request.model,
                        language=request.language,
                        initial_prompt=request.initial_prompt,
                    )
                )
            except Exception as exc:
                write_error_manifest(
                    manifest_hint or temp_dir / f"{source_path.stem}.transcription-status.json",
                    code="TRANSCRIPTION_FAILED",
                    message="Local Whisper failed before transcription completed.",
                    source=str(source_path),
                    details={"exception": str(exc), "model": request.model},
                    retryable=True,
                )
                return 1
            notes = ["Transcript generated with Whisper."]
            status_ok = True
        else:
            transcript = TranscriptPayload.model_validate(
                {
                    "segments": [],
                    "text": "",
                    "model": None,
                    "language": request.language,
                }
            )
            notes = [
                "Whisper is not installed in the current environment.",
                "Ask the user whether they want to install Whisper locally or use an approved remote transcription API.",
                "Install openai-whisper in a compatible Python environment or provide a caption file to normalize.",
            ]
            status_ok = False

    stem = source_path.stem
    json_path = temp_dir / f"{stem}.transcript.json"
    txt_path = temp_dir / f"{stem}.transcript.txt"
    manifest_path = manifest_hint or temp_dir / f"{stem}.transcription-status.json"

    write_model(json_path, transcript)
    txt_path.write_text(transcript.text, encoding="utf-8")

    if status_ok:
        write_manifest(
            manifest_path,
            status="ok",
            source=str(source_path),
            transcript_json=str(json_path),
            transcript_text=str(txt_path),
            notes=notes,
            transcript=transcript.model_dump(mode="json"),
        )
        return 0

    write_error_manifest(
        manifest_path,
        code="MISSING_DEPENDENCY",
        message="Local Whisper is not available.",
        source=str(source_path),
        notes=notes,
        transcript_json=str(json_path),
        transcript_text=str(txt_path),
        transcript=transcript.model_dump(mode="json"),
        suggestions=[
            "Install openai-whisper in a compatible Python environment.",
            "Or provide a caption file to normalize.",
            "Or switch to an approved remote transcription API.",
        ],
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
