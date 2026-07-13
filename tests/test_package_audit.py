from __future__ import annotations

import json
import hashlib
import plistlib
import stat
import warnings
import zipfile
from pathlib import Path

from conftest import parse_json_stdout, run_xcode
from xcode_common import plugin_root, plugin_version


def embedded_spec() -> str:
    return (plugin_root() / "packaging" / "package-spec.json").read_text(encoding="utf-8")


def write_zip(path: Path, entries: list[tuple[str, bytes, int]]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content, mode in entries:
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = mode << 16
            archive.writestr(info, content)


def base_entries(*extras: tuple[str, bytes, int]) -> list[tuple[str, bytes, int]]:
    prefix = f"xcode/{plugin_version()}"
    return [
        (f"{prefix}/packaging/package-spec.json", embedded_spec().encode(), stat.S_IFREG | 0o644),
        (f"{prefix}/package-manifest.json", b"{}", stat.S_IFREG | 0o644),
        *extras,
    ]


def audit(tmp_path: Path, entries: list[tuple[str, bytes, int]]):
    path = tmp_path / "fixture.zip"
    write_zip(path, entries)
    completed = run_xcode("package", "audit", "--zip", str(path), "--skip-smoke", "--json")
    return completed, parse_json_stdout(completed)


def reasons(payload: dict) -> list[str]:
    details = payload["details"]
    return [item["reason"] for key in ("structural_issues", "bad_entries", "integrity_issues") for item in details.get(key, [])]


def minimal_source_tree(root: Path) -> None:
    spec = json.loads(embedded_spec())
    for relative in spec["required_paths"]:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder\n")
    (root / "packaging/package-spec.json").write_text(embedded_spec())
    (root / ".codex-plugin/plugin.json").write_text(json.dumps({"version": plugin_version()}))
    (root / "bin/XcodeNativeHelper.app/Contents/Info.plist").write_bytes(
        plistlib.dumps({"CFBundleShortVersionString": plugin_version(), "CFBundleVersion": plugin_version()})
    )
    representatives = [
        "scripts/example.py",
        "skills/example/SKILL.md",
        "native/XcodeMCPServer/Sources/XcodeMCPServer/Example.swift",
        "native/XcodeMCPServer/Tests/XcodeMCPServerTests/Example.swift",
        "native/XcodeNativeHelper/Sources/XcodeNativeHelper/Example.swift",
    ]
    for relative in representatives:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder\n")


def test_audit_rejects_forbidden_junk(tmp_path: Path) -> None:
    prefix = f"xcode/{plugin_version()}"
    completed, payload = audit(tmp_path, base_entries((f"{prefix}/.DS_Store", b"", stat.S_IFREG | 0o644)))
    assert completed.returncode != 0
    assert "forbidden package content" in reasons(payload)


def test_audit_rejects_path_traversal_absolute_and_nested_zip(tmp_path: Path) -> None:
    prefix = f"xcode/{plugin_version()}"
    completed, payload = audit(
        tmp_path,
        base_entries(
            ("../../outside", b"bad", stat.S_IFREG | 0o644),
            ("/absolute", b"bad", stat.S_IFREG | 0o644),
            (f"{prefix}/nested.zip", b"PK", stat.S_IFREG | 0o644),
        ),
    )
    assert completed.returncode != 0
    found = reasons(payload)
    assert found.count("unsafe archive path") == 2
    assert "nested zip is forbidden" in found


def test_audit_rejects_duplicate_case_collision_and_symlink(tmp_path: Path) -> None:
    prefix = f"xcode/{plugin_version()}"
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Duplicate name")
        completed, payload = audit(
            tmp_path,
            base_entries(
                (f"{prefix}/File.swift", b"a", stat.S_IFREG | 0o644),
                (f"{prefix}/file.swift", b"b", stat.S_IFREG | 0o644),
                (f"{prefix}/link", b"target", stat.S_IFLNK | 0o777),
                (f"{prefix}/duplicate", b"a", stat.S_IFREG | 0o644),
                (f"{prefix}/duplicate", b"b", stat.S_IFREG | 0o644),
            ),
        )
    assert completed.returncode != 0
    found = reasons(payload)
    assert "case-insensitive path collision" in found
    assert "unsupported symlink" in found
    assert "duplicate archive path" in found


def test_audit_rejects_missing_or_invalid_manifest(tmp_path: Path) -> None:
    prefix = f"xcode/{plugin_version()}"
    completed, payload = audit(tmp_path, [(f"{prefix}/packaging/package-spec.json", embedded_spec().encode(), stat.S_IFREG | 0o644)])
    assert completed.returncode != 0
    assert any("package manifest" in reason for reason in reasons(payload))


def test_same_tree_produces_identical_zip(tmp_path: Path) -> None:
    source = tmp_path / "source"
    minimal_source_tree(source)
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    args = ("package", "zip", "--source-root", str(source), "--allow-dirty", "--source-date-epoch", "315532800", "--json")
    one = run_xcode(*args, "--output", str(first))
    two = run_xcode(*args, "--output", str(second))
    assert one.returncode == 0, one.stderr
    assert two.returncode == 0, two.stderr
    assert first.read_bytes() == second.read_bytes()


def test_audit_rejects_manifest_hash_tampering(tmp_path: Path) -> None:
    tampered = tmp_path / "tampered.zip"
    prefix = f"xcode/{plugin_version()}"
    readme = b"tampered"
    manifest = {
        "schema_version": "xcoder.package-manifest.v1",
        "plugin_version": plugin_version(),
        "entries": [{"path": "README.md", "size": len(readme), "mode": "0644", "sha256": hashlib.sha256(b"original").hexdigest()}],
        "binaries": {},
    }
    write_zip(
        tampered,
        [
            (f"{prefix}/packaging/package-spec.json", embedded_spec().encode(), stat.S_IFREG | 0o644),
            (f"{prefix}/package-manifest.json", json.dumps(manifest).encode(), stat.S_IFREG | 0o644),
            (f"{prefix}/README.md", readme, stat.S_IFREG | 0o644),
        ],
    )
    completed = run_xcode("package", "audit", "--zip", str(tampered), "--skip-smoke", "--json")
    payload = parse_json_stdout(completed)
    assert completed.returncode != 0
    assert payload["error_type"] == "package_integrity_failed"


def test_audit_rejects_duplicate_manifest_entry_records(tmp_path: Path) -> None:
    archive = tmp_path / "duplicate-manifest-record.zip"
    prefix = f"xcode/{plugin_version()}"
    readme = b"content"
    record = {
        "path": "README.md",
        "size": len(readme),
        "mode": "0644",
        "sha256": hashlib.sha256(readme).hexdigest(),
    }
    manifest = {
        "schema_version": "xcoder.package-manifest.v1",
        "plugin_version": plugin_version(),
        "entries": [record, record],
        "binaries": {},
    }
    write_zip(
        archive,
        [
            (f"{prefix}/packaging/package-spec.json", embedded_spec().encode(), stat.S_IFREG | 0o644),
            (f"{prefix}/package-manifest.json", json.dumps(manifest).encode(), stat.S_IFREG | 0o644),
            (f"{prefix}/README.md", readme, stat.S_IFREG | 0o644),
        ],
    )
    completed = run_xcode("package", "audit", "--zip", str(archive), "--skip-smoke", "--json")
    payload = parse_json_stdout(completed)
    assert completed.returncode != 0
    assert payload["error_type"] == "package_integrity_failed"
    assert "manifest entry records must have unique non-empty paths" in reasons(payload)


def test_audit_rejects_non_placeholder_upload_credentials_in_production_text(tmp_path: Path) -> None:
    prefix = f"xcode/{plugin_version()}"
    completed, payload = audit(
        tmp_path,
        base_entries(
            (
                f"{prefix}/scripts/credential_leak.py",
                b'payload = {"api_key_id": "A1B2C3D4E5F6G7H8"}\n',
                stat.S_IFREG | 0o644,
            )
        ),
    )
    assert completed.returncode != 0
    assert "non-placeholder upload credential material detected" in reasons(payload)
