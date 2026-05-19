from __future__ import annotations

import argparse
import json
import os
import plistlib
import zipfile
from pathlib import Path

import pytest

from conftest import parse_json_stdout, run_xcode
from xcode import COMMAND_TO_SCRIPT
from xcode_distribution import credentials_from_args, ipa_metadata, load_export_options, redact_sensitive, redacted_command


def write_fake_archive(path: Path) -> None:
    path.mkdir(parents=True)
    info = {
        "ArchiveVersion": 2,
        "Name": "Demo",
        "ApplicationProperties": {
            "ApplicationPath": "Applications/Demo.app",
            "CFBundleIdentifier": "com.example.demo",
            "SigningIdentity": "Apple Distribution",
            "Team": "ABCDE12345",
        },
    }
    (path / "Info.plist").write_bytes(plistlib.dumps(info))


def write_fake_ipa(path: Path) -> None:
    info = {
        "CFBundleIdentifier": "com.example.demo",
        "CFBundleVersion": "42",
        "CFBundleShortVersionString": "1.2.3",
        "CFBundleName": "Demo",
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Payload/Demo.app/Info.plist", plistlib.dumps(info))


def test_distribution_dispatcher_registered() -> None:
    assert COMMAND_TO_SCRIPT["distribution"] == "xcode_distribution.py"


def test_archive_dry_run_is_gui_only_and_does_not_emit_command_line_archive(tmp_path: Path) -> None:
    project_path = tmp_path / "Demo.xcodeproj"
    project_path.mkdir()

    completed = run_xcode(
        "distribution",
        "archive",
        "--workspace-path",
        str(project_path),
        "--scheme",
        "Demo",
        "--dry-run",
        "--json",
    )

    payload = parse_json_stdout(completed)
    assert completed.returncode == 0
    assert payload["ok"] is True
    assert payload["details"]["gui_only"] is True
    assert payload["details"]["route"] == "Product > Archive"
    assert "command" not in payload["details"]


def test_export_archive_is_blocked_until_gui_organizer_export_exists(tmp_path: Path) -> None:
    archive_path = tmp_path / "Demo.xcarchive"
    write_fake_archive(archive_path)
    export_path = tmp_path / "export"

    completed = run_xcode(
        "distribution",
        "export-archive",
        "--archive-path",
        str(archive_path),
        "--export-method",
        "app-store-connect",
        "--team-id",
        "ABCDE12345",
        "--signing-style",
        "automatic",
        "--export-path",
        str(export_path),
        "--export-options",
        json.dumps({"stripSwiftSymbols": True}),
        "--dry-run",
        "--json",
    )

    payload = parse_json_stdout(completed)
    assert completed.returncode != 0
    assert payload["ok"] is False
    assert payload["error_type"] == "xcode_distribution_requires_gui"
    assert payload["ipa_path"] is None
    assert payload["upload_id"] is None
    assert payload["details"]["required_route"] == "Xcode Organizer export UI"


def test_upload_redacts_api_credentials_and_key_path(tmp_path: Path) -> None:
    key_path = tmp_path / "AuthKey_SECRET123.p8"
    command = [
        "xcrun",
        "altool",
        "--apiKey",
        "SECRET123",
        "--apiIssuer",
        "ISSUER456",
        "--file",
        str(tmp_path / "Demo.ipa"),
    ]

    assert "SECRET123" not in " ".join(redacted_command(command, [str(key_path)]))
    assert "ISSUER456" not in " ".join(redacted_command(command, [str(key_path)]))
    assert str(key_path) not in redact_sensitive(f"api_key_path={key_path}", [str(key_path)])


def test_ipa_metadata_reads_bundle_and_versions(tmp_path: Path) -> None:
    ipa_path = tmp_path / "Demo.ipa"
    write_fake_ipa(ipa_path)

    metadata, warnings = ipa_metadata(ipa_path)

    assert metadata["bundle_id"] == "com.example.demo"
    assert metadata["bundle_version"] == "42"
    assert metadata["short_version"] == "1.2.3"
    assert any("embedded.mobileprovision" in warning for warning in warnings)


def test_credentials_can_resolve_key_path_from_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    key_path = tmp_path / "AuthKey_SECRET123.p8"
    key_path.write_text("private key placeholder", encoding="utf-8")
    monkeypatch.setenv("ASC_KEY_PATH", str(key_path))
    args = argparse.Namespace(
        credentials_ref=None,
        provider=None,
        api_key_id="SECRET123",
        issuer_id="ISSUER456",
        api_key_path=None,
        api_key_env="ASC_KEY_PATH",
    )

    credentials, secrets = credentials_from_args(args)

    assert credentials["api_key_path"] == str(key_path)
    assert str(key_path) in secrets


def test_export_options_rejects_invalid_signing_style() -> None:
    args = argparse.Namespace(
        export_options=None,
        export_options_plist=None,
        export_method="app-store-connect",
        team_id="ABCDE12345",
        signing_style="sometimes",
    )

    with pytest.raises(ValueError, match="signing_style"):
        load_export_options(args)
