from __future__ import annotations

import argparse
import shutil
import urllib.parse
import urllib.request
from pathlib import Path

from pydantic import ValidationError

from _common import detect_ffmpeg, ensure_course_dirs, looks_like_audio, looks_like_video
from _errors import write_error_manifest, write_manifest, write_validation_error
from _schemas import ExtractCanvasAudioRequest


def download_media(url: str, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, destination)
    return destination


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract or prepare audio for approved transcription workflows.")
    parser.add_argument("--course-title", required=True)
    parser.add_argument("--source", required=True, help="Local media path or directly accessible media URL.")
    parser.add_argument("--base-dir", default=".")
    parser.add_argument("--ffmpeg-path")
    parser.add_argument("--output-name", help="Optional audio filename without extension.")
    parser.add_argument("--manifest", help="Optional path for a JSON manifest.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_hint = Path(args.manifest).expanduser().resolve() if args.manifest else None
    try:
        request = ExtractCanvasAudioRequest.model_validate(vars(args))
    except ValidationError as exc:
        if manifest_hint:
            write_validation_error(manifest_hint, exc)
        return 1

    course_dirs = ensure_course_dirs(request.base_dir, request.course_title)
    audio_dir = course_dirs["audio"]
    temp_dir = course_dirs["temp"]
    ffmpeg_path = detect_ffmpeg(request.ffmpeg_path)
    manifest_path = manifest_hint or temp_dir / "audio-extraction.json"

    parsed = urllib.parse.urlparse(request.source)
    if parsed.scheme in {"http", "https"}:
        source_name = Path(parsed.path).name or "canvas_media.bin"
        downloaded_source = temp_dir / source_name
        try:
            source_path = download_media(request.source, downloaded_source)
        except Exception as exc:  # pragma: no cover - network is environment-dependent
            write_error_manifest(
                manifest_path,
                code="DOWNLOAD_FAILED",
                message="Failed to download the media source.",
                source=request.source,
                notes=["If the media URL requires a logged-in browser session, capture or download the media from the browser first."],
                details={"exception": str(exc)},
                retryable=True,
            )
            return 1
    else:
        source_path = Path(request.source).expanduser().resolve()
        if not source_path.exists():
            write_error_manifest(
                manifest_path,
                code="MISSING_SOURCE",
                message="Local media source file not found.",
                source=str(source_path),
            )
            return 1

    output_stem = request.output_name or source_path.stem or "lecture-audio"
    output_audio = audio_dir / f"{output_stem}.wav"

    if looks_like_audio(source_path):
        actual_output = output_audio if source_path.suffix.lower() != ".wav" else audio_dir / source_path.name
        shutil.copy2(source_path, actual_output)
        write_manifest(
            manifest_path,
            status="ok",
            source=str(source_path),
            ffmpeg_available=bool(ffmpeg_path),
            audio_output=str(actual_output),
        )
        return 0

    if looks_like_video(source_path):
        if not ffmpeg_path:
            write_error_manifest(
                manifest_path,
                code="MISSING_DEPENDENCY",
                message="ffmpeg is required to extract audio from local video files.",
                source=str(source_path),
                suggestions=[
                    "Install ffmpeg and retry.",
                    "Or download an audio track directly from the logged-in browser session.",
                ],
                ffmpeg_available=False,
            )
            return 1

        import subprocess

        try:
            subprocess.run(
                [
                    ffmpeg_path,
                    "-y",
                    "-i",
                    str(source_path),
                    "-vn",
                    "-acodec",
                    "pcm_s16le",
                    str(output_audio),
                ],
                check=True,
                text=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as exc:
            write_error_manifest(
                manifest_path,
                code="EXTRACTION_FAILED",
                message="ffmpeg failed while extracting audio from the video source.",
                source=str(source_path),
                details={"stderr": exc.stderr, "stdout": exc.stdout, "returncode": exc.returncode},
                retryable=True,
            )
            return 1
        write_manifest(
            manifest_path,
            status="ok",
            source=str(source_path),
            ffmpeg_available=True,
            audio_output=str(output_audio),
        )
        return 0

    write_error_manifest(
        manifest_path,
        code="UNSUPPORTED_SOURCE",
        message="Unsupported media source.",
        source=str(source_path),
        suggestions=[
            "Provide a local audio file, a local video file, or a directly accessible media URL.",
            "This command does not log in to Canvas or inspect a browser session by itself.",
        ],
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
