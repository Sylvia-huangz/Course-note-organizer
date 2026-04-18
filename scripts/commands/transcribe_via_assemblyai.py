from __future__ import annotations

import argparse
import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from pydantic import ValidationError

from _common import ensure_course_dirs, looks_like_audio, looks_like_video
from _errors import write_error_manifest, write_manifest, write_model, write_validation_error
from _schemas import AssemblyAITranscriptionRequest, TranscriptPayload

DEFAULT_BASE_URL = "https://api.assemblyai.com"


def normalize_words(words: list[dict]) -> list[dict]:
    if not words:
        return []
    segments: list[dict] = []
    chunk: list[str] = []
    start = None
    end = None
    for word in words:
        text = (word.get("text") or "").strip()
        if not text:
            continue
        start = word.get("start", start) if start is None else start
        end = word.get("end", end)
        chunk.append(text)
        if text.endswith((".", "?", "!")) or len(chunk) >= 20:
            segments.append(
                {
                    "start": (start or 0) / 1000,
                    "end": (end or start or 0) / 1000,
                    "text": " ".join(chunk).strip(),
                }
            )
            chunk = []
            start = None
            end = None
    if chunk:
        segments.append(
            {
                "start": (start or 0) / 1000,
                "end": (end or start or 0) / 1000,
                "text": " ".join(chunk).strip(),
            }
        )
    return segments


def http_request(url: str, headers: dict[str, str], method: str = "GET", data: bytes | None = None) -> dict:
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(request) as response:  # pragma: no cover - network dependent
        return json.loads(response.read().decode("utf-8"))


def upload_local_audio(base_url: str, api_key: str, audio_path: Path) -> str:
    content_type = mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream"
    headers = {"authorization": api_key, "content-type": content_type}
    request = urllib.request.Request(
        f"{base_url}/v2/upload",
        data=audio_path.read_bytes(),
        method="POST",
        headers=headers,
    )
    with urllib.request.urlopen(request) as response:  # pragma: no cover - network dependent
        payload = json.loads(response.read().decode("utf-8"))
    return payload["upload_url"]


def normalize_assemblyai_transcript(payload: dict, speech_models: list[str]) -> dict:
    words = payload.get("words") or []
    segments = normalize_words(words)
    return {
        "segments": segments,
        "text": (payload.get("text") or "").strip(),
        "language": payload.get("language_code") or payload.get("language"),
        "model": ",".join(speech_models),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Transcribe audio through the AssemblyAI API.")
    parser.add_argument("--course-title", required=True)
    parser.add_argument("--base-dir", default=".")
    parser.add_argument("--audio", required=True, help="Local audio/video file or publicly accessible URL.")
    parser.add_argument("--api-key-env", default="ASSEMBLYAI_API_KEY")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--poll-interval", type=float, default=3.0)
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--language-code")
    parser.add_argument("--manifest", help="Optional JSON manifest path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_hint = Path(args.manifest).expanduser().resolve() if args.manifest else None
    try:
        request = AssemblyAITranscriptionRequest.model_validate(vars(args))
    except ValidationError as exc:
        if manifest_hint:
            write_validation_error(manifest_hint, exc)
        return 1

    source_value = request.audio
    course_dirs = ensure_course_dirs(request.base_dir, request.course_title)
    temp_dir = course_dirs["temp"]
    source_path = Path(source_value).expanduser().resolve() if not source_value.startswith(("http://", "https://")) else None
    manifest_stem = source_path.stem if source_path else "remote-audio"
    manifest_path = manifest_hint or temp_dir / f"{manifest_stem}.assemblyai-transcription-status.json"
    api_key = os.environ.get(request.api_key_env)

    if not api_key:
        write_error_manifest(
            manifest_path,
            code="MISSING_API_KEY",
            message="Missing API key for AssemblyAI transcription.",
            source=source_value,
            notes=[f"Set {request.api_key_env} before using AssemblyAI transcription."],
        )
        return 1

    if source_path and not source_path.exists():
        write_error_manifest(
            manifest_path,
            code="MISSING_SOURCE",
            message="Audio source file not found.",
            source=str(source_path),
        )
        return 1

    if source_path and not (looks_like_audio(source_path) or looks_like_video(source_path)):
        write_error_manifest(
            manifest_path,
            code="UNSUPPORTED_SOURCE",
            message="Unsupported media source for AssemblyAI transcription.",
            source=str(source_path),
            suggestions=["Provide an audio/video file or a public URL."],
        )
        return 1

    try:
        if source_path:
            audio_url = upload_local_audio(request.base_url, api_key, source_path)
        else:
            audio_url = source_value

        speech_models = ["universal-3-pro", "universal-2"]
        create_payload = {
            "audio_url": audio_url,
            "speech_models": speech_models,
            "language_detection": True,
        }
        if request.language_code:
            create_payload["language_code"] = request.language_code

        headers = {"authorization": api_key, "content-type": "application/json"}
        created = http_request(
            f"{request.base_url}/v2/transcript",
            headers=headers,
            method="POST",
            data=json.dumps(create_payload).encode("utf-8"),
        )
        transcript_id = created["id"]

        deadline = time.time() + request.timeout_seconds
        result = None
        while time.time() < deadline:
            polled = http_request(f"{request.base_url}/v2/transcript/{transcript_id}", headers=headers)
            status = polled.get("status")
            if status == "completed":
                result = polled
                break
            if status == "error":
                write_error_manifest(
                    manifest_path,
                    code="API_ERROR",
                    message="AssemblyAI reported a transcription error.",
                    source=source_value,
                    provider="assemblyai",
                    details={"transcript_id": transcript_id, "error": polled.get("error")},
                )
                return 1
            time.sleep(request.poll_interval)

        if result is None:
            write_error_manifest(
                manifest_path,
                code="TIMEOUT",
                message="AssemblyAI transcription did not finish before the timeout.",
                source=source_value,
                provider="assemblyai",
                details={"transcript_id": transcript_id},
                retryable=True,
            )
            return 1

    except urllib.error.HTTPError as exc:  # pragma: no cover - network dependent
        error_body = exc.read().decode("utf-8", errors="ignore")
        write_error_manifest(
            manifest_path,
            code="API_ERROR",
            message="AssemblyAI request returned an HTTP error.",
            source=source_value,
            provider="assemblyai",
            details={"http_status": exc.code, "error_body": error_body},
            retryable=exc.code >= 500,
        )
        return 1
    except Exception as exc:  # pragma: no cover - network dependent
        write_error_manifest(
            manifest_path,
            code="REQUEST_FAILED",
            message="AssemblyAI request failed before completion.",
            source=source_value,
            provider="assemblyai",
            notes=[str(exc)],
            retryable=True,
        )
        return 1

    transcript = TranscriptPayload.model_validate(normalize_assemblyai_transcript(result, speech_models))
    json_path = temp_dir / f"{manifest_stem}.transcript.json"
    txt_path = temp_dir / f"{manifest_stem}.transcript.txt"
    write_model(json_path, transcript)
    txt_path.write_text(transcript.text, encoding="utf-8")
    write_manifest(
        manifest_path,
        status="ok",
        source=source_value,
        provider="assemblyai",
        transcript_json=str(json_path),
        transcript_text=str(txt_path),
        notes=["Audio was sent to AssemblyAI after user approval."],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
