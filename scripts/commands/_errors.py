from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from _common import ensure_parent
from _schemas import CommandError, CommandManifest


def write_model(path: Path, model) -> Path:
    ensure_parent(path)
    path.write_text(model.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")
    return path


def make_error(
    code: str,
    message: str,
    *,
    suggestions: list[str] | None = None,
    retryable: bool = False,
    details: dict[str, Any] | None = None,
) -> CommandError:
    return CommandError(
        code=code,
        message=message,
        suggestions=suggestions or [],
        retryable=retryable,
        details=details,
    )


def write_manifest(
    path: Path,
    *,
    status: str,
    notes: list[str] | None = None,
    error: CommandError | None = None,
    **extra: Any,
) -> Path:
    manifest = CommandManifest(status=status, notes=notes or [], error=error, **extra)
    return write_model(path, manifest)


def write_error_manifest(
    path: Path,
    *,
    code: str,
    message: str,
    notes: list[str] | None = None,
    suggestions: list[str] | None = None,
    retryable: bool = False,
    details: dict[str, Any] | None = None,
    **extra: Any,
) -> Path:
    return write_manifest(
        path,
        status="error",
        notes=notes,
        error=make_error(code, message, suggestions=suggestions, retryable=retryable, details=details),
        **extra,
    )


def write_validation_error(path: Path, exc: ValidationError, **extra: Any) -> Path:
    return write_error_manifest(
        path,
        code="VALIDATION_ERROR",
        message="Input validation failed.",
        suggestions=["Check the command arguments and required file paths."],
        details={"errors": exc.errors(include_url=False)},
        **extra,
    )
