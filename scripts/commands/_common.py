from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

NOTE_DIRNAME = "\u7b14\u8bb0"
AUDIO_DIRNAME = "\u97f3\u9891"
TEMP_DIRNAME = "\u5176\u4ed6\u4e34\u65f6\u6587\u4ef6"


class _HTMLStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.block_tags = {
            "p",
            "div",
            "section",
            "article",
            "header",
            "footer",
            "li",
            "ul",
            "ol",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "br",
        }

    def handle_data(self, data: str) -> None:
        if data:
            self.parts.append(data)

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag in self.block_tags:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.block_tags:
            self.parts.append("\n")

    def get_text(self) -> str:
        return "".join(self.parts)


def build_parser(description: str) -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description=description)


def slugify(value: str, fallback: str = "course") -> str:
    cleaned = re.sub(r"[^\w\-\u4e00-\u9fff]+", "-", value.strip(), flags=re.UNICODE)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return cleaned or fallback


def ensure_parent(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def resolve_course_root(base_dir: str | Path, course_title: str) -> Path:
    return Path(base_dir).expanduser().resolve() / slugify(course_title)


def ensure_course_dirs(base_dir: str | Path, course_title: str) -> dict[str, Path]:
    root = resolve_course_root(base_dir, course_title)
    notes = root / NOTE_DIRNAME
    audio = root / AUDIO_DIRNAME
    temp = root / TEMP_DIRNAME
    for item in (root, notes, audio, temp):
        item.mkdir(parents=True, exist_ok=True)
    return {"root": root, "notes": notes, "audio": audio, "temp": temp}


def write_json(path: Path, payload: Any) -> Path:
    ensure_parent(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def strip_html(raw_text: str) -> str:
    parser = _HTMLStripper()
    parser.feed(raw_text)
    return unescape(parser.get_text())


def read_text_any(path: Path) -> str:
    suffix = path.suffix.lower()
    raw = path.read_text(encoding="utf-8-sig", errors="ignore")
    if suffix in {".html", ".htm"} or "<html" in raw.lower():
        return strip_html(raw)
    if suffix == ".json":
        return json.dumps(json.loads(raw), ensure_ascii=False)
    return raw


def token_set(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[A-Za-z0-9\u4e00-\u9fff]{2,}", text.lower())
        if token not in {"this", "that", "with", "from", "have", "will", "\u8bfe\u7a0b", "\u8001\u5e08"}
    }


def overlap_score(a: str, b: str) -> int:
    return len(token_set(a) & token_set(b))


def detect_ffmpeg(explicit_path: str | None = None) -> str | None:
    if explicit_path:
        candidate = Path(explicit_path)
        if candidate.exists():
            return str(candidate)
    return shutil.which("ffmpeg")


def run_checked(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=True, text=True, capture_output=True)


def looks_like_audio(path: Path) -> bool:
    return path.suffix.lower() in {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}


def looks_like_video(path: Path) -> bool:
    return path.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}


def estimate_review_minutes(text: str, section_count: int) -> int:
    word_count = max(1, len(re.findall(r"\S+", text)))
    reading_minutes = word_count / 180
    structure_overhead = max(1, section_count) * 2
    return max(10, math.ceil(reading_minutes + structure_overhead))


def extract_formulas(text: str) -> list[str]:
    formulas = re.findall(r"\\\[(.+?)\\\]", text, flags=re.DOTALL)
    formulas += re.findall(r"\\\((.+?)\\\)", text, flags=re.DOTALL)
    formulas += re.findall(r"\$\$(.+?)\$\$", text, flags=re.DOTALL)
    cleaned = []
    for item in formulas:
        formula = " ".join(item.split())
        if formula and formula not in cleaned:
            cleaned.append(formula)
    return cleaned


def timestamp_to_seconds(label: str) -> int | None:
    parts = label.strip().split(":")
    if not 2 <= len(parts) <= 3:
        return None
    try:
        values = [int(part) for part in parts]
    except ValueError:
        return None
    if len(values) == 2:
        minutes, seconds = values
        return minutes * 60 + seconds
    hours, minutes, seconds = values
    return hours * 3600 + minutes * 60 + seconds


def normalize_timestamp(label: str) -> str:
    seconds = timestamp_to_seconds(label)
    if seconds is None:
        return label
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def safe_delete(path: Path) -> bool:
    if path.is_dir():
        shutil.rmtree(path)
        return True
    if path.exists():
        path.unlink()
        return True
    return False
