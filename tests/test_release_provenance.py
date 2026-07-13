from __future__ import annotations

import json
import subprocess
from pathlib import Path

import xcode_release
from xcode_component_build import ComponentBuild


def test_release_provenance_records_revision_hashes_without_private_build_paths(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(xcode_release, "toolchain_details", lambda root, runner: {"swift_version": "Swift test"})
    component = ComponentBuild(
        "mcp_server",
        "bin/xcode-mcp-server",
        "source-hash",
        "binary-hash",
        str(tmp_path / "private" / "xcode-mcp-server"),
        "ad-hoc",
        ("version", "doctor", "list_tools"),
    )
    payload = xcode_release.provenance_payload(
        tmp_path,
        "0.6.0",
        "abc123",
        False,
        {"mcp_server": component},
        runner=lambda *args, **kwargs: None,
    )
    assert payload["schema_version"] == "xcoder.release-provenance.v1"
    assert payload["git"] == {"commit": "abc123", "dirty": False}
    assert payload["components"]["mcp_server"]["binary_hash"] == "binary-hash"
    assert str(tmp_path) not in str(payload)


def test_toolchain_details_extracts_xcode_version_and_build(tmp_path: Path) -> None:
    def runner(command, **kwargs):
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, stdout="Swift 6.3.2", stderr="")
        payload = {
            "details": {
                "checks": [
                    {
                        "name": "xcodebuild-version",
                        "status": "ok",
                        "output": "Xcode 26.5\nBuild version 17F42",
                    }
                ]
            }
        }
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    details = xcode_release.toolchain_details(tmp_path, runner)
    assert details["xcode_version"] == "26.5"
    assert details["xcode_build"] == "17F42"
