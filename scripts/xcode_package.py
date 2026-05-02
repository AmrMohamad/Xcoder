#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import stat
import zipfile
from pathlib import Path

from xcode_common import EXIT_CODES, emit_failure, emit_success, plugin_root, plugin_version, write_json


EXCLUDED_DIR_NAMES = {
    ".git",
    "__MACOSX",
    "__pycache__",
    ".build",
    "DerivedData",
}

EXCLUDED_FILE_NAMES = {
    ".DS_Store",
}

EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".zip",
}

EXCLUDED_NAME_SUFFIXES = {
    ".zip.manifest.json",
}

EXCLUDED_PARTS = {
    (".codex", "xcode", "artifacts"),
}

REQUIRED_PACKAGE_FILES = {
    "bin/xcode",
    "bin/xcode-native-helper",
}

REQUIRED_EXECUTABLE_FILES = REQUIRED_PACKAGE_FILES


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Package the local xcode plugin with deterministic exclusions.")
    parser.add_argument("--json", action="store_true", help="Emit JSON. Kept for CLI symmetry; JSON is always emitted.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    zip_parser = subparsers.add_parser("zip", help="Create a clean plugin zip archive.")
    zip_parser.add_argument("--output", required=True, help="Output zip path.")
    audit_parser = subparsers.add_parser("audit", help="Audit a plugin zip archive for packaging junk.")
    audit_parser.add_argument("--zip", required=True, dest="zip_path", help="Zip archive to inspect.")
    return parser.parse_args()


def is_excluded(path: Path, root: Path) -> tuple[bool, str | None]:
    relative = path.relative_to(root)
    parts = relative.parts
    if any(part in EXCLUDED_DIR_NAMES for part in parts[:-1]):
        return True, "excluded directory"
    if path.is_dir() and path.name in EXCLUDED_DIR_NAMES:
        return True, "excluded directory"
    if path.name in EXCLUDED_FILE_NAMES:
        return True, "excluded file"
    if any(path.name.endswith(suffix) for suffix in EXCLUDED_NAME_SUFFIXES):
        return True, "excluded package sidecar"
    if path.suffix in EXCLUDED_SUFFIXES:
        return True, "excluded suffix"
    for excluded in EXCLUDED_PARTS:
        if len(parts) >= len(excluded) and parts[: len(excluded)] == excluded:
            return True, "excluded transient artifact path"
    return False, None


def collect_files(root: Path) -> tuple[list[Path], list[dict[str, str]]]:
    files: list[Path] = []
    excluded: list[dict[str, str]] = []
    for path in sorted(root.rglob("*")):
        skip, reason = is_excluded(path, root)
        if skip:
            excluded.append({"path": str(path.relative_to(root)), "reason": reason or "excluded"})
            if path.is_dir():
                continue
            continue
        if path.is_file():
            files.append(path)
    return files, excluded


def archive_file_mode(path: Path, relative: Path) -> int:
    relative_posix = relative.as_posix()
    mode = stat.S_IFREG | (path.stat().st_mode & 0o777)
    if relative_posix in REQUIRED_EXECUTABLE_FILES:
        mode = stat.S_IFREG | 0o755
    return mode


def write_archive_file(archive: zipfile.ZipFile, path: Path, arcname: str, relative: Path) -> None:
    info = zipfile.ZipInfo.from_file(path, arcname)
    info.create_system = 3
    info.external_attr = archive_file_mode(path, relative) << 16
    with path.open("rb") as stream:
        archive.writestr(info, stream.read(), compress_type=zipfile.ZIP_DEFLATED)


def zip_command(output: str) -> int:
    root = plugin_root()
    output_path = Path(output).expanduser().resolve(strict=False)
    files, excluded = collect_files(root)
    prefix = f"xcode/{plugin_version()}"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    command_record = {
        "root": str(root),
        "output": str(output_path),
        "prefix": prefix,
        "included_count": len(files),
        "excluded_count": len(excluded),
    }

    try:
        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in files:
                relative = path.relative_to(root)
                write_archive_file(archive, path, f"{prefix}/{relative.as_posix()}", relative)
            archive.writestr(f"{prefix}/package-manifest.json", json.dumps(command_record, indent=2, sort_keys=True) + "\n")
    except OSError as exc:
        return emit_failure(
            "package",
            "subprocess_failed",
            "Plugin package could not be written",
            details=command_record,
            errors=[str(exc)],
            exit_code=EXIT_CODES["subprocess_failed"],
        )

    manifest_path = output_path.with_suffix(output_path.suffix + ".manifest.json")
    write_json(manifest_path, {"command": command_record, "excluded": excluded})
    return emit_success(
        "package",
        "Plugin zip archive created",
        details=command_record,
        artifacts={"zip": str(output_path), "manifest": str(manifest_path)},
        warnings=[
            "Existing local transient files were excluded from the archive but not deleted from disk.",
        ],
    )


def bad_archive_reason(name: str) -> str | None:
    path = Path(name)
    parts = path.parts
    if any(part in {"__MACOSX", "__pycache__", ".build", "DerivedData"} for part in parts):
        return "excluded directory in archive"
    if any(part == ".DS_Store" for part in parts):
        return "excluded file in archive"
    for index in range(0, max(0, len(parts) - 2)):
        if parts[index : index + 3] == (".codex", "xcode", "artifacts"):
            return "transient artifact path in archive"
    if len(parts) >= 3 and parts[-3:] == (".codex", "xcode", "artifacts"):
        return "transient artifact path in archive"
    if path.suffix == ".zip":
        return "nested zip in archive"
    if path.name.endswith(".zip.manifest.json"):
        return "package sidecar in archive"
    return None


def archive_file_mode_from_info(info: zipfile.ZipInfo) -> int:
    return (info.external_attr >> 16) & 0o777777


def structural_archive_issues(names: list[str], archive: zipfile.ZipFile) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    expected_prefix = f"xcode/{plugin_version()}/"
    file_names = [name for name in names if not name.endswith("/")]
    wrong_prefix = [name for name in file_names if not name.startswith(expected_prefix)]
    if wrong_prefix:
        issues.append(
            {
                "path": wrong_prefix[0],
                "reason": f"archive entry is outside expected root prefix {expected_prefix}",
            }
        )

    manifest = f"{expected_prefix}package-manifest.json"
    if manifest not in names:
        issues.append({"path": manifest, "reason": "package manifest missing from archive"})

    for relative in sorted(REQUIRED_PACKAGE_FILES):
        archive_name = f"{expected_prefix}{relative}"
        if archive_name not in names:
            issues.append({"path": archive_name, "reason": "required package file missing from archive"})
            continue
        if relative in REQUIRED_EXECUTABLE_FILES:
            mode = archive_file_mode_from_info(archive.getinfo(archive_name))
            if not (mode & 0o111):
                issues.append({"path": archive_name, "reason": f"required executable is not executable: {oct(mode)}"})

    return issues


def audit_command(zip_path: str) -> int:
    archive_path = Path(zip_path).expanduser().resolve(strict=False)
    if not archive_path.exists() or not archive_path.is_file():
        return emit_failure(
            "package",
            "path_violation",
            "Zip archive does not exist",
            details={"zip": str(archive_path)},
            exit_code=EXIT_CODES["path_violation"],
        )

    bad_entries: list[dict[str, str]] = []
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            names = archive.namelist()
            for name in names:
                reason = bad_archive_reason(name)
                if reason:
                    bad_entries.append({"path": name, "reason": reason})
            structural_issues = structural_archive_issues(names, archive)
    except zipfile.BadZipFile as exc:
        return emit_failure(
            "package",
            "subprocess_failed",
            "Archive is not a readable zip file",
            details={"zip": str(archive_path)},
            errors=[str(exc)],
            exit_code=EXIT_CODES["subprocess_failed"],
        )

    details = {
        "zip": str(archive_path),
        "entry_count": len(names),
        "expected_prefix": f"xcode/{plugin_version()}/",
        "bad_entries": bad_entries,
        "structural_issues": structural_issues,
    }
    if bad_entries or structural_issues:
        return emit_failure(
            "package",
            "cache_invalid",
            "Plugin zip archive contains excluded packaging content",
            details=details,
            errors=[*structural_issues, *bad_entries][:20],
            exit_code=EXIT_CODES["cache_invalid"],
        )
    return emit_success("package", "Plugin zip archive passed packaging audit", details=details)


def main() -> int:
    args = parse_args()
    if args.command == "zip":
        return zip_command(args.output)
    if args.command == "audit":
        return audit_command(args.zip_path)
    return emit_failure("package", "usage_error", "Unknown package command", exit_code=EXIT_CODES["usage_error"])


if __name__ == "__main__":
    raise SystemExit(main())
