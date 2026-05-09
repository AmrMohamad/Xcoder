from __future__ import annotations

from pathlib import Path

from conftest import parse_json_stdout, run_xcode


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_single_device_fixture_resolves() -> None:
    completed = run_xcode(
        "simulator",
        "resolve",
        "--fixture",
        str(FIXTURES / "simctl-list-single-device.json"),
        "--name",
        "iPhone SE (3rd generation)",
        "--json",
    )
    payload = parse_json_stdout(completed)

    assert completed.returncode == 0
    assert payload["ok"] is True
    assert payload["details"]["udid"]


def test_duplicate_device_fixture_is_ambiguous() -> None:
    completed = run_xcode(
        "simulator",
        "resolve",
        "--fixture",
        str(FIXTURES / "simctl-list-duplicate-names.json"),
        "--name",
        "iPhone SE (3rd generation)",
        "--json",
    )
    payload = parse_json_stdout(completed)

    assert completed.returncode == 21
    assert payload["ok"] is False
    assert payload["error_type"] == "destination_ambiguous"
    assert payload["details"]["recovery"] == "user_input"
