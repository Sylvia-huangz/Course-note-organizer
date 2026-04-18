from __future__ import annotations

import argparse
import json
import mimetypes
import os
import uuid
import urllib.error
import urllib.request
from pathlib import Path

from pydantic import ValidationError

from _common import ensure_course_dirs
from _errors import write_error_manifest, write_manifest, write_model, write_validation_error
from _schemas import OpenAITranscriptionRequest, TranscriptPayload

OPENAI_TRANSCRIPT_URL = "https://api.openai.com/v1/audio/transcriptions"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def build_multipart(fields: dict[str, str], file_field: str, file_path: Path) -> tuple[bytes, str]:
    boundary = f"----CodexBoundary{uuid.uuid4().hex}"
    mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    chunks: list[bytes] = []

    for key, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )

    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"\r\n'.encode(),
            f"Content-Type: {mime_type}\r\n\r\n".encode(),
            file_path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(chunks), boundary


def normalize_openai_transcript(payload: dict, model: str) -> dict:
    segments = [
        {
            "start": segment.get("start"),
            "end": segment.get("end"),
            "text": (segment.get("text") or "").strip(),
        }
        for segment in payload.get("segments", []) or []
    ]
    return {
        "segments": segments,
        "text": (payload.get("text") or "").strip(),
        "language": payload.get("language"),
        "model": model,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Transcribe audio through the OpenAI Audio API without local Whisper installation.")
    parser.add_argument("--course-title", required=True)
    parser.add_argument("--base-dir", default=".")
    parser.add_argument("--audio", required=True)
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--model", default="whisper-1")
    parser.add_argument("--language")
    parser.add_argument("--prompt")
    parser.add_argument("--manifest", help="Optional JSON manifest path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_hint = Path(args.manifest).expanduser().resolve() if args.manifest else None
    try:
        request = OpenAITranscriptionRequest.model_validate(vars(args))
    except ValidationError as exc:
        if manifest_hint:
            write_validation_error(manifest_hint, exc)
        return 1

    audio_path = Path(request.audio).expanduser().resolve()
    course_dirs = ensure_course_dirs(request.base_dir, request.course_title)
    temp_dir = course_dirs["temp"]
    manifest_path = manifest_hint or temp_dir / f"{audio_path.stem}.openai-transcription-status.json"
    api_key = os.environ.get(request.api_key_env)

    if not api_key:
        write_error_manifest(
            manifest_path,
            code="MISSING_API_KEY",
            message="Missing API key for OpenAI transcription.",
            source=str(audio_path),
            notes=[f"Set {request.api_key_env} before using remote OpenAI transcription."],
        )
        return 1

    if not audio_path.exists():
        write_error_manifest(
            manifest_path,
            code="MISSING_SOURCE",
            message="Audio source file not found.",
            source=str(audio_path),
        )
        return 1

    if audio_path.stat().st_size > MAX_UPLOAD_BYTES:
        write_error_manifest(
            manifest_path,
            code="SIZE_LIMIT_EXCEEDED",
            message="Audio file exceeds the OpenAI upload size limit.",
            source=str(audio_path),
            notes=["OpenAI Audio API file uploads are limited to 25 MB."],
            suggestions=["Split or compress the file before retrying."],
        )
        return 1

    fields = {"model": request.model}
    if request.model == "whisper-1":
        fields["response_format"] = "verbose_json"
        fields["timestamp_granularities[]"] = "segment"
    else:
        fields["response_format"] = "json"
    if request.language:
        fields["language"] = request.language
    if request.prompt:
        fields["prompt"] = request.prompt

    body, boundary = build_multipart(fields, "file", audio_path)
    http_request = urllib.request.Request(
        OPENAI_TRANSCRIPT_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )

    try:
        with urllib.request.urlopen(http_request) as response:  # pragma: no cover - network dependent
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # pragma: no cover - network dependent
        error_body = exc.read().decode("utf-8", errors="ignore")
        write_error_manifest(
            manifest_path,
            code="API_ERROR",
            message="OpenAI transcription API returned an error.",
            source=str(audio_path),
            details={"http_status": exc.code, "error_body": error_body},
            retryable=exc.code >= 500,
        )
        return 1
    except Exception as exc:  # pragma: no cover - network dependent
        write_error_manifest(
            manifest_path,
            code="REQUEST_FAILED",
            message="OpenAI transcription request failed before completion.",
            source=str(audio_path),
            notes=[str(exc)],
            retryable=True,
        )
        return 1

    transcript = TranscriptPayload.model_validate(normalize_openai_transcript(payload, request.model))
    json_path = temp_dir / f"{audio_path.stem}.transcript.json"
    txt_path = temp_dir / f"{audio_path.stem}.transcript.txt"
    write_model(json_path, transcript)
    txt_path.write_text(transcript.text, encoding="utf-8")
    write_manifest(
        manifest_path,
        status="ok",
        source=str(audio_path),
        provider="openai",
        model=request.model,
        transcript_json=str(json_path),
        transcript_text=str(txt_path),
        notes=["Audio was sent to the OpenAI Audio Transcriptions API after user approval."],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
