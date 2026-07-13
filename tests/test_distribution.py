from __future__ import annotations

from pathlib import Path

from conftest import parse_json_stdout, run_xcode
from xcode import COMMAND_TO_SCRIPT


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


def test_export_upload_and_distribute_return_typed_gui_block() -> None:
    scenarios = [
        ("export-archive", "export", "Xcode Organizer export UI"),
        ("upload-archive", "upload", "Xcode Organizer upload UI"),
        ("distribute", "distribution", "Xcode Organizer GUI"),
    ]
    for command, capability, route in scenarios:
        completed = run_xcode("distribution", command, "--json")
        payload = parse_json_stdout(completed)
        assert completed.returncode != 0
        assert payload["error_type"] == "xcode_distribution_requires_gui"
        assert payload["details"] == {
            "capability": capability,
            "available": False,
            "required_route": route,
            "gui_only": True,
        }


def test_blocked_distribution_parser_has_no_credential_inputs() -> None:
    completed = run_xcode(
        "distribution",
        "upload-archive",
        "--api-key-id",
        "SHOULD_NOT_BE_ACCEPTED",
        "--json",
    )
    assert completed.returncode != 0
    assert "unrecognized arguments" in completed.stderr
