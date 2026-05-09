from __future__ import annotations

from xcode import COMMAND_TO_SCRIPT, transform_build_args


def test_build_uses_machine_wrapper() -> None:
    assert COMMAND_TO_SCRIPT["build"] == "xcode_build_cache.py"


def test_non_dry_run_json_is_not_forwarded_to_runner() -> None:
    assert transform_build_args(["--json", "-project", "App.xcodeproj"]) == ["-project", "App.xcodeproj"]


def test_dry_run_json_adds_json_dry_run() -> None:
    assert transform_build_args(["--dry-run", "--json", "-scheme", "App"]) == [
        "--dry-run",
        "-scheme",
        "App",
        "--json-dry-run",
    ]
