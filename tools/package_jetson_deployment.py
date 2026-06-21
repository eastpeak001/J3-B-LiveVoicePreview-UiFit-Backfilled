from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Iterable


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = (
    "README_JETSON.md",
    "requirements-jetson.txt",
)
CONFIG_FILES = (
    "config/asr_commands_zh.yaml",
    "config/calibration_canonical.yaml",
    "config/calibration_maps_canonical.npz",
    "config/depth_runtime_jetson.yaml",
)
MODEL_DOC_FILES = ("models/asr/README_ASR_MODEL.md",)
ROOT_REPORT_FILES = (
    "reports/windows_static_validation.md",
    "reports/windows_j2_static_validation.md",
    "reports/windows_source_manifest.sha256",
)
RUNTIME_REPORT_DIRS = (
    "reports/runtime_j2",
    "reports/runtime_j2d",
    "reports/runtime_j3",
    "reports/runtime_j3b",
)
ALLOWED_REPORT_SUFFIXES = {".md", ".json", ".txt"}
FORBIDDEN_SUFFIXES = {".wav", ".png", ".jpg", ".jpeg", ".bat", ".pyc"}
FORBIDDEN_PARTS = {".git", ".venv", "__pycache__", ".pytest_cache", "outputs", "temp", "tmp"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def public_files(root: Path = PACKAGE_ROOT) -> list[Path]:
    relatives: set[Path] = {
        *(Path(value) for value in ROOT_FILES),
        *(Path(value) for value in CONFIG_FILES),
        *(Path(value) for value in MODEL_DOC_FILES),
        *(Path(value) for value in ROOT_REPORT_FILES),
    }
    relatives.update(path.relative_to(root) for path in (root / "scripts").glob("*.py"))
    relatives.update(path.relative_to(root) for path in (root / "tools").glob("*.sh"))
    relatives.add(Path("tools/package_jetson_deployment.py"))
    for directory_value in RUNTIME_REPORT_DIRS:
        directory = root / directory_value
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            if path.is_file() and (path.name == ".gitkeep" or path.suffix.lower() in ALLOWED_REPORT_SUFFIXES):
                relatives.add(path.relative_to(root))
    missing = [str(path) for path in relatives if not (root / path).is_file()]
    if missing:
        raise RuntimeError("Required package files are missing: " + ", ".join(sorted(missing)))
    ordered = sorted(relatives, key=lambda value: value.as_posix())
    validate_source_paths(ordered)
    return ordered


def validate_source_paths(paths: Iterable[Path]) -> None:
    for path in paths:
        pure = PurePosixPath(path.as_posix())
        lowered_parts = {part.lower() for part in pure.parts}
        if lowered_parts & FORBIDDEN_PARTS:
            raise RuntimeError(f"Forbidden package path: {pure}")
        if pure.suffix.lower() in FORBIDDEN_SUFFIXES:
            raise RuntimeError(f"Forbidden package file type: {pure}")
        if pure.parts[:2] == ("models", "asr") and pure.as_posix() not in MODEL_DOC_FILES:
            raise RuntimeError(f"ASR model payload must not be packaged: {pure}")


def zip_info(name: str, mode: int, is_directory: bool) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.compress_type = zipfile.ZIP_DEFLATED
    type_bits = stat.S_IFDIR if is_directory else stat.S_IFREG
    info.external_attr = ((type_bits | mode) & 0xFFFF) << 16
    if is_directory:
        info.external_attr |= 0x10
    return info


def archive_directories(top_level: str, files: Iterable[Path]) -> list[str]:
    directories = {PurePosixPath(top_level)}
    for relative in files:
        parent = PurePosixPath(top_level) / PurePosixPath(relative.as_posix()).parent
        while parent.as_posix() not in {".", ""}:
            directories.add(parent)
            if parent == PurePosixPath(top_level):
                break
            parent = parent.parent
    return [f"{path.as_posix().rstrip('/')}/" for path in sorted(directories, key=lambda item: (len(item.parts), item.as_posix()))]


def build_package(output: Path, top_level: str) -> dict[str, object]:
    if not top_level or "/" in top_level or "\\" in top_level or top_level in {".", ".."}:
        raise RuntimeError("Top-level directory must be one safe directory name")
    files = public_files()
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for directory in archive_directories(top_level, files):
                archive.writestr(zip_info(directory, 0o755, True), b"")
            for relative in files:
                archive_name = f"{top_level}/{relative.as_posix()}"
                mode = 0o755 if relative.suffix.lower() == ".sh" else 0o644
                archive.writestr(zip_info(archive_name, mode, False), (PACKAGE_ROOT / relative).read_bytes())
        verify_result = verify_package(temporary, expected_top_level=top_level)
        output.unlink(missing_ok=True)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    verify_result.update({
        "zip_path": str(output),
        "zip_size_bytes": output.stat().st_size,
        "zip_sha256": sha256_file(output),
    })
    return verify_result


def member_mode(member: zipfile.ZipInfo) -> int:
    return (member.external_attr >> 16) & 0o7777


def verify_package(path: Path, expected_top_level: str | None = None) -> dict[str, object]:
    errors: list[str] = []
    with zipfile.ZipFile(path, "r") as archive:
        members = archive.infolist()
        names = [member.filename for member in members]
        if len(names) != len(set(names)):
            errors.append("ZIP contains duplicate member names")
        top_levels = {PurePosixPath(name).parts[0] for name in names if PurePosixPath(name).parts}
        if len(top_levels) != 1:
            errors.append(f"ZIP must contain exactly one top-level directory: {sorted(top_levels)}")
        actual_top = next(iter(top_levels), "")
        if expected_top_level is not None and actual_top != expected_top_level:
            errors.append(f"Unexpected top-level directory: {actual_top}")

        directory_names = {member.filename for member in members if member.is_dir()}
        file_members = [member for member in members if not member.is_dir()]
        for member in members:
            pure = PurePosixPath(member.filename.rstrip("/"))
            if pure.is_absolute() or ".." in pure.parts or "\\" in member.filename:
                errors.append(f"Unsafe ZIP member path: {member.filename}")
                continue
            lowered_parts = {part.lower() for part in pure.parts}
            if lowered_parts & FORBIDDEN_PARTS or pure.suffix.lower() in FORBIDDEN_SUFFIXES:
                errors.append(f"Forbidden ZIP member: {member.filename}")
            mode = member_mode(member)
            expected_mode = 0o755 if member.is_dir() or pure.suffix.lower() == ".sh" else 0o644
            if mode != expected_mode:
                errors.append(
                    f"Wrong Unix mode for {member.filename}: {mode:04o}, expected {expected_mode:04o}"
                )
            if not member.is_dir():
                parent = PurePosixPath(member.filename).parent
                while parent.as_posix() not in {".", ""}:
                    parent_name = f"{parent.as_posix().rstrip('/')}/"
                    if parent_name not in directory_names:
                        errors.append(f"Missing explicit parent directory entry: {parent_name}")
                    parent = parent.parent

        required_model_dirs = {f"{actual_top}/models/", f"{actual_top}/models/asr/"}
        missing_model_dirs = required_model_dirs - directory_names
        if missing_model_dirs:
            errors.append("Missing writable model directory entries: " + ", ".join(sorted(missing_model_dirs)))
        model_payloads = [
            member.filename
            for member in file_members
            if member.filename.startswith(f"{actual_top}/models/asr/")
            and not member.filename.endswith("/README_ASR_MODEL.md")
        ]
        if model_payloads:
            errors.append("ASR model payloads found: " + ", ".join(model_payloads))
    if errors:
        raise RuntimeError("ZIP permission/content verification failed:\n- " + "\n- ".join(errors))
    return {
        "top_level": actual_top,
        "file_count": len(file_members),
        "directory_count": len(directory_names),
        "directory_mode": "0755",
        "shell_mode": "0755",
        "regular_file_mode": "0644",
        "models_asr_directory_verified": True,
        "forbidden_content_count": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a Linux-permission-safe Jetson ZIP")
    parser.add_argument("--output", type=Path, help="Destination ZIP path")
    parser.add_argument("--top-level", help="Single top-level directory inside the ZIP")
    parser.add_argument("--verify-only", type=Path, help="Only verify an existing ZIP")
    args = parser.parse_args()
    if args.verify_only:
        result = verify_package(args.verify_only.resolve(), args.top_level)
        result.update({
            "zip_path": str(args.verify_only.resolve()),
            "zip_size_bytes": args.verify_only.resolve().stat().st_size,
            "zip_sha256": sha256_file(args.verify_only.resolve()),
        })
    else:
        if args.output is None:
            parser.error("--output is required when not using --verify-only")
        top_level = args.top_level or args.output.stem
        result = build_package(args.output, top_level)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        print(f"PACKAGE_ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
