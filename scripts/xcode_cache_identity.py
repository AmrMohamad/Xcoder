#!/usr/bin/env python3

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CACHE_IDENTITY_SCHEMA = "xcoder.cache.identity.v2"
METADATA_FILENAME = ".codex-xcode-cache.json"
LOCK_FILENAME = ".xcoder-cache.lock"

_SKIPPED_DIRECTORY_NAMES = {
    ".build",
    ".git",
    "Assets.xcassets",
    "DerivedData",
    "Pods",
    "Sources",
    "Tests",
    "checkouts",
}
_GRAPH_FILENAMES = {
    "Cartfile.resolved",
    "Package.resolved",
    "Package.swift",
    "Podfile.lock",
    "Project.swift",
    "Workspace.swift",
    "project.pbxproj",
    "project.yml",
    "workspace.yml",
}
_GRAPH_SUFFIXES = {".xcconfig", ".xcscheme", ".xctestplan"}


@dataclass(frozen=True)
class CacheMismatch:
    key: str
    expected: Any
    actual: Any

    def as_dict(self) -> dict[str, Any]:
        return {"key": self.key, "expected": self.expected, "actual": self.actual}


class CacheMetadataError(RuntimeError):
    pass


class CacheLockTimeout(CacheMetadataError):
    pass


def sha256_bytes(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def canonical_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=True)


def _safe_hash(path: Path | None) -> str | None:
    return sha256_file(path) if path is not None and path.is_file() else None


def _combined_file_hash(paths: list[Path], *, root: Path) -> str | None:
    if not paths:
        return None
    digest = hashlib.sha256()
    for path in sorted(set(paths), key=lambda item: item.as_posix().casefold()):
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            relative = path.name
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def project_graph_files(entry: Path) -> list[Path]:
    resolved_entry = canonical_path(entry)
    root = resolved_entry.parent
    files: list[Path] = []
    for directory, names, filenames in os.walk(root):
        names[:] = [
            name
            for name in names
            if name not in _SKIPPED_DIRECTORY_NAMES
            and not name.endswith(".xcassets")
            and not name.startswith(".")
        ]
        base = Path(directory)
        for filename in filenames:
            path = base / filename
            if filename in _GRAPH_FILENAMES or path.suffix in _GRAPH_SUFFIXES:
                files.append(path)

    if resolved_entry.suffix == ".xcodeproj":
        project_file = resolved_entry / "project.pbxproj"
        if project_file.is_file():
            files.append(project_file)
    elif resolved_entry.suffix == ".xcworkspace":
        workspace_file = resolved_entry / "contents.xcworkspacedata"
        if workspace_file.is_file():
            files.append(workspace_file)
    return sorted(set(files), key=lambda item: item.as_posix().casefold())


def _matching_files(files: list[Path], names: set[str] = frozenset(), suffix: str | None = None) -> list[Path]:
    return [
        path
        for path in files
        if path.name in names or (suffix is not None and path.suffix == suffix)
    ]


def selected_toolchain_identity(
    *,
    sdk: str | None,
    xcode_version: str,
    developer_dir: str | None = None,
) -> dict[str, Any]:
    selected_developer_dir = Path(
        developer_dir or os.environ.get("DEVELOPER_DIR") or "/Applications/Xcode.app/Contents/Developer"
    ).expanduser()
    try:
        selected_developer_dir = selected_developer_dir.resolve(strict=True)
    except OSError:
        selected_developer_dir = selected_developer_dir.resolve(strict=False)

    normalized = " ".join(xcode_version.split()) or "unknown"
    build_match = re.search(r"Build version\s+([^\s]+)", xcode_version)
    xcode_build = build_match.group(1) if build_match else "unknown"
    sdk_name = sdk or "default"
    sdk_version = _sdk_version(sdk_name)
    return {
        "developer_dir_hash": sha256_bytes(str(selected_developer_dir).encode("utf-8")),
        "xcode_version": normalized,
        "xcode_build": xcode_build,
        "sdk": sdk_name,
        "sdk_version": sdk_version,
    }


def _sdk_version(sdk: str) -> str:
    try:
        completed = subprocess.run(
            ["xcrun", "--sdk", sdk, "--show-sdk-version"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return (completed.stdout or "").strip() or "unknown"


def build_cache_identity(
    *,
    entry: Path,
    container_type: str,
    scheme: str | None,
    configuration: str | None,
    sdk: str | None,
    platform: str | None,
    architectures: list[str],
    toolchain: str,
    optimization_profile: str,
    trusted_fast: bool,
    skip_macro_validation: bool,
    skip_package_plugin_validation: bool,
    index_store_enabled: bool,
    xcode_version: str,
    developer_dir: str | None = None,
    toolchain_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_entry = canonical_path(entry)
    root = resolved_entry.parent
    graph_files = project_graph_files(resolved_entry)
    package_resolved = _matching_files(graph_files, {"Package.resolved"})
    podfile_locks = _matching_files(graph_files, {"Podfile.lock"})
    xcconfigs = _matching_files(graph_files, suffix=".xcconfig")
    generator_files = _matching_files(
        graph_files,
        {"Project.swift", "Workspace.swift", "project.yml", "workspace.yml"},
    )
    selected_toolchain = dict(
        toolchain_identity
        or selected_toolchain_identity(
            sdk=sdk,
            xcode_version=xcode_version,
            developer_dir=developer_dir,
        )
    )
    return {
        "schema_version": CACHE_IDENTITY_SCHEMA,
        "project": {
            "container_type": container_type,
            "basename": resolved_entry.name,
            "canonical_path_hash": sha256_bytes(str(resolved_entry).encode("utf-8")),
            "graph_hash": _combined_file_hash(graph_files, root=root),
        },
        "toolchain": selected_toolchain,
        "build": {
            "scheme": scheme,
            "configuration": configuration,
            "platform": platform,
            "architectures": sorted(set(architectures)),
            "toolchain": toolchain,
        },
        "dependencies": {
            "package_resolved_hash": _combined_file_hash(package_resolved, root=root),
            "podfile_lock_hash": _combined_file_hash(podfile_locks, root=root),
        },
        "configuration": {
            "xcconfig_hash": _combined_file_hash(xcconfigs, root=root),
            "generator_manifest_hash": _combined_file_hash(generator_files, root=root),
        },
        "policy": {
            "optimization_profile": optimization_profile,
            "trusted_fast": trusted_fast,
            "skip_macro_validation": skip_macro_validation,
            "skip_package_plugin_validation": skip_package_plugin_validation,
            "index_store_enabled": index_store_enabled,
        },
    }


def compare_cache_identity(
    current: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> list[CacheMismatch]:
    mismatches: list[CacheMismatch] = []

    def compare(actual: Any, wanted: Any, key: str) -> None:
        if isinstance(wanted, Mapping):
            if not isinstance(actual, Mapping):
                mismatches.append(CacheMismatch(key, wanted, actual))
                return
            for child_key, child_value in wanted.items():
                compare(actual.get(child_key), child_value, f"{key}.{child_key}" if key else child_key)
            for extra_key in actual.keys() - wanted.keys():
                mismatches.append(
                    CacheMismatch(f"{key}.{extra_key}" if key else extra_key, None, actual[extra_key])
                )
            return
        if actual != wanted:
            mismatches.append(CacheMismatch(key, wanted, actual))

    compare(current, expected, "")
    return mismatches


def identities_compatible(current: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    return not compare_cache_identity(current, expected)


def identity_digest(identity: Mapping[str, Any], *, length: int = 16) -> str:
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:length]


def read_cache_metadata(cache_path: Path) -> dict[str, Any] | None:
    metadata_path = cache_path / METADATA_FILENAME
    if not metadata_path.exists():
        return None
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CacheMetadataError(f"cache_metadata_corrupt: {metadata_path.name}") from exc
    if not isinstance(payload, dict):
        raise CacheMetadataError(f"cache_metadata_corrupt: {metadata_path.name}")
    return payload


def write_cache_metadata_atomic(
    cache_path: Path,
    identity: Mapping[str, Any],
    *,
    lock_timeout_seconds: float = 2.0,
) -> None:
    cache_path.mkdir(parents=True, exist_ok=True)
    lock_path = cache_path / LOCK_FILENAME
    metadata_path = cache_path / METADATA_FILENAME
    with lock_path.open("a+b") as lock:
        deadline = time.monotonic() + lock_timeout_seconds
        while True:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise CacheLockTimeout(f"cache_lock_timeout: {cache_path.name}")
                time.sleep(0.01)
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{METADATA_FILENAME}.",
                suffix=".tmp",
                dir=cache_path,
            )
            temporary_path = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                    json.dump(identity, output, indent=2, sort_keys=True)
                    output.write("\n")
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary_path, metadata_path)
            finally:
                temporary_path.unlink(missing_ok=True)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
