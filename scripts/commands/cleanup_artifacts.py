from __future__ import annotations

import argparse
from pathlib import Path

from pydantic import ValidationError

from _common import TEMP_DIRNAME, safe_delete
from _errors import write_error_manifest, write_manifest, write_validation_error
from _schemas import CleanupRequest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preview or delete generated temporary artifacts.")
    parser.add_argument("--course-root", required=True, help="Course root directory that bounds deletions.")
    parser.add_argument("--path", action="append", required=True, help="Target file or directory to remove.")
    parser.add_argument("--confirm-delete", action="store_true", help="Actually delete the provided targets.")
    parser.add_argument("--manifest", help="Optional JSON manifest path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_hint = Path(args.manifest).expanduser().resolve() if args.manifest else None
    try:
        request = CleanupRequest.model_validate(vars(args))
    except ValidationError as exc:
        if manifest_hint:
            write_validation_error(manifest_hint, exc)
        return 1

    course_root = Path(request.course_root).expanduser().resolve()
    manifest_path = manifest_hint or course_root / TEMP_DIRNAME / "cleanup-manifest.json"
    targets = [Path(item).expanduser().resolve() for item in request.path]
    for target in targets:
        if course_root not in target.parents and target != course_root:
            write_error_manifest(
                manifest_path,
                code="OUT_OF_SCOPE_PATH",
                message="Refusing to touch a path outside the course root.",
                course_root=str(course_root),
                details={"target": str(target)},
                suggestions=["Pass only files inside the current course directory."],
            )
            return 1

    deleted = []
    if request.confirm_delete:
        for target in targets:
            deleted.append({"path": str(target), "deleted": safe_delete(target)})

    write_manifest(
        manifest_path,
        status="deleted" if request.confirm_delete else "preview",
        course_root=str(course_root),
        targets=[str(target) for target in targets],
        deleted=deleted,
        notes=["Keep --confirm-delete off until the user explicitly approves cleanup."],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
