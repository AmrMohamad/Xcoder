from __future__ import annotations

import zipfile
from pathlib import Path

from conftest import parse_json_stdout, run_xcode
from xcode_common import plugin_version


def write_zip(path: Path, entries: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)


def test_audit_rejects_ds_store(tmp_path: Path) -> None:
    zip_path = tmp_path / "bad.zip"
    prefix = f"xcode/{plugin_version()}"
    write_zip(zip_path, {f"{prefix}/.DS_Store": "", f"{prefix}/package-manifest.json": "{}"})

    completed = run_xcode("package", "audit", "--zip", str(zip_path), "--json")
    payload = parse_json_stdout(completed)

    assert completed.returncode == 50
    assert payload["ok"] is False
    assert payload["details"]["bad_entries"][0]["reason"] == "excluded file in archive"


def test_audit_rejects_pytest_cache(tmp_path: Path) -> None:
    zip_path = tmp_path / "bad-pytest-cache.zip"
    prefix = f"xcode/{plugin_version()}"
    write_zip(
        zip_path,
        {
            f"{prefix}/.pytest_cache/CACHEDIR.TAG": "Signature: 8a477f597d28d172789f06886806bc55",
            f"{prefix}/package-manifest.json": "{}",
        },
    )

    completed = run_xcode("package", "audit", "--zip", str(zip_path), "--json")
    payload = parse_json_stdout(completed)

    assert completed.returncode == 50
    assert payload["ok"] is False
    assert payload["details"]["bad_entries"][0]["reason"] == "excluded directory in archive"


def test_audit_rejects_missing_package_manifest(tmp_path: Path) -> None:
    zip_path = tmp_path / "missing-manifest.zip"
    prefix = f"xcode/{plugin_version()}"
    write_zip(zip_path, {f"{prefix}/README.md": "# xcode\n"})

    completed = run_xcode("package", "audit", "--zip", str(zip_path), "--json")
    payload = parse_json_stdout(completed)

    assert completed.returncode == 50
    assert payload["ok"] is False
    assert any(issue["reason"] == "package manifest missing from archive" for issue in payload["details"]["structural_issues"])
