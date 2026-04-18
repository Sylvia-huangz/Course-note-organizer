from __future__ import annotations

import argparse
import json
import mimetypes
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from pydantic import ValidationError

from _common import ensure_course_dirs, ensure_within_course_root, looks_like_audio, looks_like_video
from _errors import write_error_manifest, write_manifest, write_model, write_validation_error
from _schemas import DeepgramTranscriptionRequest, TranscriptPayload

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"


def http_json(url: str, headers: dict[str, str], method: str = "POST", data: bytes | None = None) -> dict:
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(request) as response:  # pragma: no cover - network dependent
        return json.loads(response.read().decode("utf-8"))


def normalize_deepgram_response(payload: dict, model: str) -> dict:
    channels = payload.get("results", {}).get("channels", [])
    alternative = {}
    if channels:
        alternative = (channels[0].get("alternatives") or [{}])[0]
    transcript_text = (alternative.get("transcript") or "").strip()

    utterances = payload.get("results", {}).get("utterances") or alternative.get("utterances") or []
    if utterances:
        segments = [
            {"start": item.get("start"), "end": item.get("end"), "text": (item.get("transcript") or "").strip()}
            for item in utterances
            if (item.get("transcript") or "").strip()
        ]
    else:
        words = alternative.get("words") or []
        segments = []
        chunk: list[str] = []
        start = None
        end = None
        for word in words:
            text = (word.get("punctuated_word") or word.get("word") or "").strip()
            if not text:
                continue
            start = word.get("start", start) if start is None else start
            end = word.get("end", end)
            chunk.append(text)
            if text.endswith((".", "?", "!")) or len(chunk) >= 20:
                segments.append({"start": start, "end": end, "text": " ".join(chunk).strip()})
                chunk = []
                start = None
                end = None
        if chunk:
            segments.append({"start": start, "end": end, "text": " ".join(chunk).strip()})

    metadata = payload.get("metadata", {})
    detected_language = metadata.get("languages", [None])
    language = detected_language[0] if isinstance(detected_language, list) else detected_language
    return {
        "segments": segments,
        "text": transcript_text,
        "language": language,
        "model": model,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Transcribe audio through the Deepgram pre-recorded API.")
    parser.add_argument("--course-title", required=True)
    parser.add_argument("--base-dir", default=".")
    parser.add_argument("--audio", required=True, help="Local audio/video file or a remote media URL.")
    parser.add_argument("--api-key-env", default="DEEPGRAM_API_KEY")
    parser.add_argument("--model", default="nova-3")
    parser.add_argument("--language")
    parser.add_argument("--manifest", help="Optional JSON manifest path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_hint = Path(args.manifest).expanduser().resolve() if args.manifest else None
    try:
        request = DeepgramTranscriptionRequest.model_validate(vars(args))
    except ValidationError as exc:
        if manifest_hint:
            write_validation_error(manifest_hint, exc)
        return 1

    source_value = request.audio
    course_dirs = ensure_course_dirs(request.base_dir, request.course_title)
    temp_dir = course_dirs["temp"]
    source_path = Path(source_value).expanduser().resolve() if not source_value.startswith(("http://", "https://")) else None
    manifest_stem = source_path.stem if source_path else "remote-audio"
    manifest_path = ensure_within_course_root(
        manifest_hint or temp_dir / f"{manifest_stem}.deepgram-transcription-status.json",
        course_dirs["root"],
    )
    api_key = os.environ.get(request.api_key_env)

    if not api_key:
        write_error_manifest(
            manifest_path,
            code="MISSING_API_KEY",
            message="Missing API key for Deepgram transcription.",
            source=source_value,
            notes=[f"Set {request.api_key_env} before using Deepgram transcription."],
        )
        return 1

    if source_path:
        if not source_path.exists():
            write_error_manifest(
                manifest_path,
                code="MISSING_SOURCE",
                message="Audio source file not found.",
                source=str(source_path),
            )
            return 1
        if not (looks_like_audio(source_path) or looks_like_video(source_path)):
            write_error_manifest(
                manifest_path,
                code="UNSUPPORTED_SOURCE",
                message="Unsupported media source for Deepgram transcription.",
                source=str(source_path),
                suggestions=["Provide an audio/video file or a remote media URL."],
            )
            return 1

    query = {"model": request.model, "smart_format": "true", "utterances": "true", "punctuate": "true"}
    if request.language:
        query["language"] = request.language
    request_url = f"{DEEPGRAM_URL}?{urllib.parse.urlencode(query)}"

    if source_path:
        content_type = mimetypes.guess_type(source_path.name)[0] or "application/octet-stream"
        headers = {"Authorization": f"Token {api_key}", "Content-Type": content_type}
        data = source_path.read_bytes()
    else:
        headers = {"Authorization": f"Token {api_key}", "Content-Type": "application/json"}
        data = json.dumps({"url": source_value}).encode("utf-8")

    try:
        payload = http_json(request_url, headers=headers, method="POST", data=data)
    except urllib.error.HTTPError as exc:  # pragma: no cover - network dependent
        error_body = exc.read().decode("utf-8", errors="ignore")
        write_error_manifest(
            manifest_path,
            code="API_ERROR",
            message="Deepgram request returned an HTTP error.",
            source=source_value,
            provider="deepgram",
            details={"http_status": exc.code, "error_body": error_body},
            retryable=exc.code >= 500,
        )
        return 1
    except Exception as exc:  # pragma: no cover - network dependent
        write_error_manifest(
            manifest_path,
            code="REQUEST_FAILED",
            message="Deepgram request failed before completion.",
            source=source_value,
            provider="deepgram",
            notes=[str(exc)],
            retryable=True,
        )
        return 1

    transcript = TranscriptPayload.model_validate(normalize_deepgram_response(payload, request.model))
    json_path = temp_dir / f"{manifest_stem}.transcript.json"
    txt_path = temp_dir / f"{manifest_stem}.transcript.txt"
    write_model(json_path, transcript)
    txt_path.write_text(transcript.text, encoding="utf-8")
    write_manifest(
        manifest_path,
        status="ok",
        source=source_value,
        provider="deepgram",
        transcript_json=str(json_path),
        transcript_text=str(txt_path),
        notes=["Audio was sent to Deepgram after user approval."],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
