#!/usr/bin/env python3

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from xcode_common import EXIT_CODES, emit_failure, emit_success, plugin_root
from xcode_version import plugin_version


MANIFEST_SCHEMA = "xcoder.package-manifest.v1"
SPEC_SCHEMA = "xcoder.package-spec.v1"
DEFAULT_EPOCH = 315532800  # ZIP's minimum timestamp: 1980-01-01 UTC.
PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN(?: OPENSSH)? PRIVATE KEY-----\s+[A-Za-z0-9+/=\s]{32,}-----END(?: OPENSSH)? PRIVATE KEY-----",
    re.MULTILINE,
)
CREDENTIAL_VALUE_PATTERNS = (
    re.compile(r'''(?i)["'](?:api_key_id|issuer_id)["']\s*:\s*["']([^"']{4,})["']'''),
    re.compile(r'''(?i)--(?:api-key-id|issuer-id)(?:=|\s+)["']?([A-Za-z0-9][A-Za-z0-9_-]{7,})'''),
)


@dataclass(frozen=True)
class PackageEntry:
    relative: str
    source: Path
    size: int
    mode: int
    sha256: str

    def manifest_record(self) -> dict[str, Any]:
        return {
            "path": self.relative,
            "size": self.size,
            "mode": f"{self.mode:04o}",
            "sha256": self.sha256,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create and audit deterministic Xcoder packages.")
    parser.add_argument("--json", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)

    zip_parser = subparsers.add_parser("zip")
    zip_parser.add_argument("--output", required=True)
    zip_parser.add_argument("--source-root")
    zip_parser.add_argument("--source-date-epoch", type=int)
    zip_parser.add_argument("--provenance")
    zip_parser.add_argument("--allow-dirty", action="store_true")
    zip_parser.add_argument("--source-revision")
    zip_parser.add_argument("--source-dirty", choices=("true", "false"))

    audit_parser = subparsers.add_parser("audit")
    audit_parser.add_argument("--zip", required=True, dest="zip_path")
    audit_parser.add_argument("--skip-smoke", action="store_true", help="Test-only: omit extracted executable smoke tests.")
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_spec(root: Path) -> dict[str, Any]:
    path = root / "packaging" / "package-spec.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SPEC_SCHEMA:
        raise ValueError(f"unsupported package specification: {payload.get('schema_version')}")
    return payload


def git_source_state(root: Path) -> tuple[str, bool]:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=normal"],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()
        )
        return revision, dirty
    except (OSError, subprocess.CalledProcessError):
        return "unknown", True


def _matches(relative: str, pattern: str) -> bool:
    candidates = [pattern]
    if pattern.startswith("**/"):
        candidates.append(pattern[3:])
    return any(fnmatch.fnmatchcase(relative, candidate) or PurePosixPath(relative).match(candidate) for candidate in candidates)


def collect_entries(root: Path, spec: dict[str, Any]) -> tuple[list[PackageEntry], list[dict[str, str]]]:
    forbidden = list(spec["forbidden_globs"])
    allowed_symlinks = set(spec.get("allowed_symlinks", []))
    executables = set(spec["executables"])
    entries: list[PackageEntry] = []
    excluded: list[dict[str, str]] = []

    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        if any(_matches(relative, pattern) for pattern in forbidden):
            excluded.append({"path": relative, "reason": "forbidden by package specification"})
            continue
        if any(part in {".git", ".serena", "__pycache__", ".pytest_cache", ".build", ".swiftpm", "DerivedData"} for part in path.relative_to(root).parts):
            excluded.append({"path": relative, "reason": "transient development content"})
            continue
        if path.is_symlink():
            if relative not in allowed_symlinks:
                excluded.append({"path": relative, "reason": "unsupported symlink"})
            continue
        if not path.is_file() or path.name.endswith(".zip.manifest.json") or path.suffix in {".pyc", ".pyo", ".zip"}:
            continue
        mode = 0o755 if relative in executables else 0o644
        entries.append(PackageEntry(relative, path, path.stat().st_size, mode, sha256_file(path)))

    included = {entry.relative for entry in entries}
    issues: list[dict[str, str]] = []
    for required in spec["required_paths"]:
        if required not in included:
            issues.append({"path": required, "reason": "required package path missing"})
    for pattern in spec["required_globs"]:
        if not any(_matches(relative, pattern) for relative in included):
            issues.append({"path": pattern, "reason": "required package glob has no matches"})
    if issues:
        raise PackageViolation(issues)
    return entries, excluded


class PackageViolation(Exception):
    def __init__(self, issues: list[dict[str, str]]) -> None:
        super().__init__("package specification violation")
        self.issues = issues


def deterministic_datetime(epoch: int) -> tuple[int, int, int, int, int, int]:
    value = max(DEFAULT_EPOCH, epoch)
    moment = datetime.fromtimestamp(value, tz=timezone.utc)
    return moment.year, moment.month, moment.day, moment.hour, moment.minute, moment.second - moment.second % 2


def zip_info(name: str, mode: int, epoch: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, deterministic_datetime(epoch))
    info.create_system = 3
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (stat.S_IFREG | mode) << 16
    info.flag_bits = 0
    return info


def manifest_for(
    root: Path,
    version: str,
    entries: list[PackageEntry],
    epoch: int,
    source_revision: str,
    source_dirty: bool,
    provenance: dict[str, Any] | None,
) -> dict[str, Any]:
    binaries: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if entry.relative not in load_spec(root)["binaries"]:
            continue
        architectures = subprocess.run(
            ["/usr/bin/lipo", "-archs", str(entry.source)], text=True, capture_output=True
        )
        binaries[Path(entry.relative).name] = {
            "path": entry.relative,
            "sha256": entry.sha256,
            "version": version,
            "architectures": architectures.stdout.strip().split() if architectures.returncode == 0 else [],
        }
    return {
        "schema_version": MANIFEST_SCHEMA,
        "plugin_version": version,
        "source_revision": source_revision,
        "source_dirty": source_dirty,
        "source_date_epoch": epoch,
        "entries": [entry.manifest_record() for entry in entries],
        "binaries": binaries,
        "provenance": provenance,
    }


def write_archive(output: Path, prefix: str, entries: list[PackageEntry], manifest: dict[str, Any], epoch: int) -> None:
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True, separators=(",", ": ")) + "\n").encode()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for entry in entries:
            info = zip_info(f"{prefix}{entry.relative}", entry.mode, epoch)
            with entry.source.open("rb") as source, archive.open(info, "w", force_zip64=True) as destination:
                shutil.copyfileobj(source, destination, length=1024 * 1024)
        archive.writestr(zip_info(f"{prefix}package-manifest.json", 0o644, epoch), manifest_bytes, compresslevel=9)


def zip_command(args: argparse.Namespace) -> int:
    root = Path(args.source_root).expanduser().resolve() if args.source_root else plugin_root()
    output = Path(args.output).expanduser().resolve(strict=False)
    try:
        spec = load_spec(root)
        version = plugin_version(root)
        entries, excluded = collect_entries(root, spec)
        revision, dirty = git_source_state(root)
        if args.source_revision is not None:
            revision = args.source_revision
        if args.source_dirty is not None:
            dirty = args.source_dirty == "true"
        if dirty and not args.allow_dirty:
            return emit_failure(
                "package", "release_source_dirty", "Packaging a dirty source tree requires --allow-dirty",
                details={"source_root": str(root), "source_revision": revision},
                exit_code=EXIT_CODES["release_source_dirty"],
            )
        epoch = args.source_date_epoch if args.source_date_epoch is not None else int(os.environ.get("SOURCE_DATE_EPOCH", DEFAULT_EPOCH))
        provenance = json.loads(Path(args.provenance).read_text()) if args.provenance else None
        manifest = manifest_for(root, version, entries, epoch, revision, dirty, provenance)
        output.parent.mkdir(parents=True, exist_ok=True)
        write_archive(output, spec["root_prefix"].format(version=version), entries, manifest, epoch)
    except PackageViolation as exc:
        return emit_failure("package", "package_spec_violation", "Source tree violates package specification", details={"issues": exc.issues}, errors=exc.issues[:20], exit_code=EXIT_CODES["package_spec_violation"])
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return emit_failure("package", "package_spec_violation", "Plugin package could not be created", errors=[str(exc)], exit_code=EXIT_CODES["package_spec_violation"])

    sidecar = output.with_suffix(output.suffix + ".manifest.json")
    sidecar.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return emit_success(
        "package", "Deterministic plugin archive created",
        details={"source_root": str(root), "prefix": spec["root_prefix"].format(version=version), "entry_count": len(entries) + 1, "excluded_count": len(excluded), "source_dirty": dirty, "sha256": sha256_file(output)},
        artifacts={"zip": str(output), "package_manifest": str(sidecar)},
    )


def archive_mode(info: zipfile.ZipInfo) -> int:
    return (info.external_attr >> 16) & 0o7777


def normalized_entry_path(name: str) -> PurePosixPath | None:
    if not name or name.startswith("/") or "\\" in name:
        return None
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    return path


def inspect_structure(archive: zipfile.ZipFile, spec: dict[str, Any], version: str) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    infos = archive.infolist()
    limits = spec["limits"]
    if len(infos) > limits["maximum_entries"]:
        issues.append({"path": "<archive>", "reason": "entry count exceeds package limit"})
    total = 0
    seen: set[str] = set()
    casefolded: set[str] = set()
    prefix = spec["root_prefix"].format(version=version)
    for info in infos:
        name = info.filename
        path = normalized_entry_path(name)
        if path is None:
            issues.append({"path": name, "reason": "unsafe archive path"})
            continue
        if name in seen:
            issues.append({"path": name, "reason": "duplicate archive path"})
        seen.add(name)
        folded = name.casefold()
        if folded in casefolded:
            issues.append({"path": name, "reason": "case-insensitive path collision"})
        casefolded.add(folded)
        if not name.startswith(prefix):
            issues.append({"path": name, "reason": f"entry outside expected root {prefix}"})
        if info.is_dir():
            continue
        file_type = (info.external_attr >> 16) & 0o170000
        if file_type == stat.S_IFLNK:
            issues.append({"path": name, "reason": "unsupported symlink"})
        if file_type not in {0, stat.S_IFREG}:
            issues.append({"path": name, "reason": "unsupported archive entry type"})
        if name.lower().endswith(".zip"):
            issues.append({"path": name, "reason": "nested zip is forbidden"})
        total += info.file_size
        if info.file_size > limits["maximum_single_entry_bytes"]:
            issues.append({"path": name, "reason": "entry exceeds uncompressed size limit"})
        ratio = info.file_size / max(1, info.compress_size)
        if ratio > limits["maximum_compression_ratio"]:
            issues.append({"path": name, "reason": "suspicious compression ratio"})
    if total > limits["maximum_total_uncompressed_bytes"]:
        issues.append({"path": "<archive>", "reason": "archive exceeds total uncompressed size limit"})
    return issues


def manifest_and_integrity_issues(archive: zipfile.ZipFile, spec: dict[str, Any], version: str) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    prefix = spec["root_prefix"].format(version=version)
    manifest_name = f"{prefix}package-manifest.json"
    issues: list[dict[str, str]] = []
    if archive.namelist().count(manifest_name) != 1:
        return None, [{"path": manifest_name, "reason": "exactly one package manifest is required"}]
    try:
        manifest = json.loads(archive.read(manifest_name))
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError) as exc:
        return None, [{"path": manifest_name, "reason": f"invalid package manifest: {exc}"}]
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        issues.append({"path": manifest_name, "reason": "unsupported package manifest schema"})
    if manifest.get("plugin_version") != version:
        issues.append({"path": manifest_name, "reason": "package manifest version mismatch"})
    records = manifest.get("entries")
    if not isinstance(records, list):
        return manifest, issues + [{"path": manifest_name, "reason": "manifest entries must be a list"}]
    record_map = {record.get("path"): record for record in records if isinstance(record, dict)}
    if len(record_map) != len(records) or None in record_map:
        issues.append({"path": manifest_name, "reason": "manifest entry records must have unique non-empty paths"})
    archive_relatives = {name.removeprefix(prefix) for name in archive.namelist() if not name.endswith("/") and name != manifest_name}
    if set(record_map) != archive_relatives:
        issues.append({"path": manifest_name, "reason": "manifest entry set does not match archive content"})
    for relative in sorted(archive_relatives & set(record_map)):
        info = archive.getinfo(f"{prefix}{relative}")
        digest = hashlib.sha256()
        with archive.open(info) as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        record = record_map[relative]
        if record.get("sha256") != digest.hexdigest() or record.get("size") != info.file_size or record.get("mode") != f"{archive_mode(info):04o}":
            issues.append({"path": relative, "reason": "manifest hash, size, or mode mismatch"})
    binary_records = manifest.get("binaries", {})
    for relative in spec["binaries"]:
        name = Path(relative).name
        record = record_map.get(relative, {})
        binary_record = binary_records.get(name, {})
        if binary_record.get("sha256") != record.get("sha256"):
            issues.append({"path": relative, "reason": "binary identity does not match entry manifest"})
        if binary_record.get("version") != version or not binary_record.get("architectures"):
            issues.append({"path": relative, "reason": "binary version or architecture identity is incomplete"})
        elif "arm64" not in binary_record.get("architectures", []):
            issues.append({"path": relative, "reason": "required arm64 binary slice is missing"})
    provenance = manifest.get("provenance")
    if isinstance(provenance, dict):
        components = provenance.get("components", {})
        for component in components.values() if isinstance(components, dict) else []:
            if not isinstance(component, dict):
                continue
            binary_path = component.get("package_path")
            binary_hash = component.get("binary_hash")
            if binary_path and record_map.get(binary_path, {}).get("sha256") != binary_hash:
                issues.append({"path": str(binary_path), "reason": "package binary does not match release provenance"})
    return manifest, issues


def content_issues(archive: zipfile.ZipFile, spec: dict[str, Any], version: str) -> list[dict[str, str]]:
    prefix = spec["root_prefix"].format(version=version)
    relatives = [name.removeprefix(prefix) for name in archive.namelist() if name.startswith(prefix) and not name.endswith("/")]
    issues: list[dict[str, str]] = []
    for required in spec["required_paths"]:
        if required not in relatives:
            issues.append({"path": required, "reason": "required package path missing"})
    for pattern in spec["required_globs"]:
        if not any(_matches(relative, pattern) for relative in relatives):
            issues.append({"path": pattern, "reason": "required package glob has no matches"})
    for relative in relatives:
        if any(_matches(relative, pattern) for pattern in spec["forbidden_globs"]):
            issues.append({"path": relative, "reason": "forbidden package content"})
        if relative in spec["executables"]:
            if archive_mode(archive.getinfo(f"{prefix}{relative}")) != 0o755:
                issues.append({"path": relative, "reason": "required executable mode is not 0755"})
        elif relative != "package-manifest.json" and archive_mode(archive.getinfo(f"{prefix}{relative}")) != 0o644:
            issues.append({"path": relative, "reason": "non-executable mode is not normalized to 0644"})
    return issues


def secret_issues(archive: zipfile.ZipFile, spec: dict[str, Any], version: str) -> list[dict[str, str]]:
    prefix = spec["root_prefix"].format(version=version)
    issues: list[dict[str, str]] = []
    for info in archive.infolist():
        relative = info.filename.removeprefix(prefix)
        if info.is_dir() or info.file_size > 2_000_000 or Path(relative).suffix.lower() not in {".md", ".json", ".py", ".swift", ".sh", ".txt", ".plist"}:
            continue
        try:
            text = archive.read(info).decode("utf-8")
        except UnicodeDecodeError:
            continue
        if PRIVATE_KEY_PATTERN.search(text):
            issues.append({"path": relative, "reason": "private key material detected"})
        if relative.startswith(("docs/", "tests/", "benchmarks/")) or "/Tests/" in relative or relative == "README.md":
            continue
        for pattern in CREDENTIAL_VALUE_PATTERNS:
            match = pattern.search(text)
            if match and not re.search(r"(?i)placeholder|example|redacted|secret|issuer", match.group(1)):
                issues.append({"path": relative, "reason": "non-placeholder upload credential material detected"})
                break
    return issues


def verify_embedded_versions(archive: zipfile.ZipFile, spec: dict[str, Any], version: str) -> list[dict[str, str]]:
    prefix = spec["root_prefix"].format(version=version)
    issues: list[dict[str, str]] = []
    try:
        plugin_payload = json.loads(archive.read(f"{prefix}.codex-plugin/plugin.json"))
        helper_payload = plistlib.loads(archive.read(f"{prefix}bin/XcodeNativeHelper.app/Contents/Info.plist"))
        mcp_constants = archive.read(f"{prefix}native/XcodeMCPServer/Sources/XcodeMCPServer/Constants.swift").decode("utf-8")
        helper_source = archive.read(f"{prefix}native/XcodeNativeHelper/Sources/XcodeNativeHelper/main.swift").decode("utf-8")
        hooks = archive.read(f"{prefix}hooks/hooks.json").decode("utf-8")
        if plugin_payload.get("version") != version:
            issues.append({"path": ".codex-plugin/plugin.json", "reason": "plugin version mismatch"})
        if helper_payload.get("CFBundleShortVersionString") != version:
            issues.append({"path": "bin/XcodeNativeHelper.app/Contents/Info.plist", "reason": "native helper version mismatch"})
        if f'serverVersion = "{version}"' not in mcp_constants:
            issues.append({"path": "native/XcodeMCPServer/Sources/XcodeMCPServer/Constants.swift", "reason": "MCP server version mismatch"})
        if f'helperVersion = "{version}"' not in helper_source:
            issues.append({"path": "native/XcodeNativeHelper/Sources/XcodeNativeHelper/main.swift", "reason": "native helper source version mismatch"})
        if "xcode/*/scripts/" not in hooks:
            issues.append({"path": "hooks/hooks.json", "reason": "hook lookup is not version independent"})
    except (KeyError, json.JSONDecodeError, plistlib.InvalidFileException) as exc:
        issues.append({"path": "<version metadata>", "reason": f"version metadata invalid: {exc}"})
    return issues


def safe_extract(archive: zipfile.ZipFile, target: Path) -> None:
    for info in archive.infolist():
        path = normalized_entry_path(info.filename)
        if path is None:
            raise ValueError(f"unsafe path: {info.filename}")
        destination = target.joinpath(*path.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if info.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        with archive.open(info) as source, destination.open("wb") as output:
            shutil.copyfileobj(source, output, length=1024 * 1024)
        os.chmod(destination, archive_mode(info))


def extracted_smoke(archive_path: Path, prefix: str) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    results: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []
    with tempfile.TemporaryDirectory(prefix="xcoder-package-audit-") as directory:
        root = Path(directory)
        with zipfile.ZipFile(archive_path) as archive:
            safe_extract(archive, root)
        package = root / prefix.rstrip("/")
        home = root / "home"
        home.mkdir(mode=0o700)
        env = {**os.environ, "HOME": str(home), "PYTHONPATH": str(package / "scripts")}
        expected_version = package.name
        commands: list[tuple[list[str], str | None]] = [
            ([str(package / "bin/xcode"), "--version", "--json"], "plugin"),
            ([str(package / "bin/xcode"), "--help"], None),
            ([str(package / "bin/xcode-mcp-server"), "--version", "--json"], "mcp"),
            ([str(package / "bin/xcode-mcp-server"), "--doctor", "--json"], None),
            ([str(package / "bin/xcode-mcp-server"), "--list-tools", "--json"], None),
            ([str(package / "bin/xcode-native-helper"), "helper", "version", "--json"], "helper"),
        ]
        for command, version_kind in commands:
            try:
                completed = subprocess.run(command, cwd=package, env=env, text=True, capture_output=True, timeout=20)
            except (OSError, subprocess.TimeoutExpired) as exc:
                issues.append({"path": command[0], "reason": f"smoke command failed to start: {exc}"})
                continue
            results.append({"command": [Path(command[0]).name, *command[1:]], "returncode": completed.returncode})
            if completed.returncode != 0:
                issues.append({"path": command[0], "reason": f"smoke command exited {completed.returncode}"})
            if version_kind and completed.returncode == 0:
                try:
                    payload = json.loads(completed.stdout)
                    actual = {
                        "plugin": payload.get("summary"),
                        "mcp": payload.get("version"),
                        "helper": payload.get("helper_version"),
                    }[version_kind]
                    if actual != expected_version:
                        issues.append({"path": command[0], "reason": f"reported version {actual!r} does not match package {expected_version}"})
                except json.JSONDecodeError:
                    issues.append({"path": command[0], "reason": "version smoke did not return JSON"})
        binaries = [
            package / "bin/xcode-mcp-server",
            package / "bin/XcodeNativeHelper.app/Contents/MacOS/xcode-native-helper",
        ]
        for binary in binaries:
            for command_name, command in (
                ("file", ["/usr/bin/file", str(binary)]),
                ("architectures", ["/usr/bin/lipo", "-archs", str(binary)]),
                ("minimum_os", ["/usr/bin/otool", "-l", str(binary)]),
                ("codesign", ["/usr/bin/codesign", "--verify", "--strict", str(binary)]),
            ):
                completed = subprocess.run(command, cwd=package, env=env, text=True, capture_output=True)
                results.append({"command": [command_name, binary.name], "returncode": completed.returncode})
                if completed.returncode != 0:
                    issues.append({"path": str(binary.relative_to(package)), "reason": f"binary {command_name} validation failed"})
                    continue
                if command_name == "file" and "Mach-O" not in completed.stdout:
                    issues.append({"path": str(binary.relative_to(package)), "reason": "binary is not a Mach-O executable"})
                if command_name == "architectures" and "arm64" not in completed.stdout.split():
                    issues.append({"path": str(binary.relative_to(package)), "reason": "required arm64 binary slice is missing"})
                if command_name == "minimum_os":
                    minimums = re.findall(r"\bminos\s+([0-9]+(?:\.[0-9]+)*)", completed.stdout)
                    if not minimums or any(value != "14.0" for value in minimums):
                        issues.append({"path": str(binary.relative_to(package)), "reason": f"binary minimum macOS is not 14.0: {minimums}"})
        scripts = sorted((package / "scripts").glob("*.py"))
        completed = subprocess.run([os.environ.get("PYTHON", sys.executable), "-m", "py_compile", *map(str, scripts)], cwd=package, env=env, text=True, capture_output=True)
        results.append({"command": ["python3", "-m", "py_compile", "scripts/*.py"], "returncode": completed.returncode})
        if completed.returncode != 0:
            issues.append({"path": "scripts/*.py", "reason": "extracted Python compilation failed"})
    return results, issues


def audit_command(args: argparse.Namespace) -> int:
    archive_path = Path(args.zip_path).expanduser().resolve(strict=False)
    if not archive_path.is_file():
        return emit_failure("package", "path_violation", "Zip archive does not exist", details={"zip": str(archive_path)}, exit_code=EXIT_CODES["path_violation"])
    started = time.monotonic()
    try:
        with zipfile.ZipFile(archive_path) as archive:
            roots = {PurePosixPath(name).parts[:2] for name in archive.namelist() if normalized_entry_path(name)}
            versions = {parts[1] for parts in roots if len(parts) == 2 and parts[0] == "xcode"}
            if len(versions) != 1:
                version = plugin_version(plugin_root())
            else:
                version = versions.pop()
            spec_name = f"xcode/{version}/packaging/package-spec.json"
            if spec_name not in archive.namelist():
                return emit_failure("package", "package_spec_violation", "Package specification is missing", details={"zip": str(archive_path), "structural_issues": [{"path": spec_name, "reason": "package specification missing"}], "bad_entries": []}, exit_code=EXIT_CODES["package_spec_violation"])
            spec = json.loads(archive.read(spec_name))
            if spec.get("schema_version") != SPEC_SCHEMA:
                raise ValueError("unsupported embedded package specification")
            structural = inspect_structure(archive, spec, version)
            content = content_issues(archive, spec, version)
            manifest, integrity = manifest_and_integrity_issues(archive, spec, version) if not structural else (None, [])
            secrets = secret_issues(archive, spec, version) if not structural else []
            versions_issues = verify_embedded_versions(archive, spec, version) if not structural else []
    except (zipfile.BadZipFile, OSError, ValueError, json.JSONDecodeError) as exc:
        return emit_failure("package", "package_spec_violation", "Archive is not structurally valid", details={"zip": str(archive_path)}, errors=[str(exc)], exit_code=EXIT_CODES["package_spec_violation"])

    issues = [*structural, *content, *integrity, *secrets, *versions_issues]
    smoke_results: list[dict[str, Any]] = []
    if not issues and not args.skip_smoke:
        smoke_results, smoke_issues = extracted_smoke(archive_path, spec["root_prefix"].format(version=version))
        issues.extend(smoke_issues)
    details = {
        "zip": str(archive_path), "sha256": sha256_file(archive_path), "entry_count": len(zipfile.ZipFile(archive_path).infolist()),
        "structural_issues": structural, "bad_entries": [*content, *secrets, *versions_issues], "integrity_issues": integrity,
        "smoke": smoke_results, "elapsed_seconds": round(time.monotonic() - started, 6),
    }
    if issues:
        error_type = "package_integrity_failed" if integrity else "package_spec_violation"
        return emit_failure("package", error_type, "Plugin archive failed package audit", details=details, errors=issues[:50], exit_code=EXIT_CODES[error_type])
    return emit_success("package", "Plugin archive passed structure, integrity, identity, and extracted behavior audit", details=details)


def main() -> int:
    args = parse_args()
    if args.command == "zip":
        return zip_command(args)
    if args.command == "audit":
        return audit_command(args)
    return emit_failure("package", "usage_error", "Unknown package command", exit_code=EXIT_CODES["usage_error"])


if __name__ == "__main__":
    raise SystemExit(main())
