from __future__ import annotations

from pathlib import Path

from conftest import parse_json_stdout, run_xcode


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_warnings_fixture_summarizes() -> None:
    completed = run_xcode(
        "warnings",
        "summarize",
        "--log",
        str(FIXTURES / "xcodebuild-warning.log"),
        "--json",
    )
    payload = parse_json_stdout(completed)

    assert completed.returncode == 0
    assert payload["ok"] is True
    assert payload["details"]["summary"]["warning_count"] >= 1
    assert "groups" in payload["details"]["summary"]
