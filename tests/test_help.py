from __future__ import annotations

from conftest import parse_json_stdout, run_xcode
from xcode_help import TOPICS


def test_valid_help_topic_succeeds() -> None:
    completed = run_xcode("help", "--topic", "ide-vs-cli", "--json")
    payload = parse_json_stdout(completed)

    assert completed.returncode == 0
    assert payload["schema_version"] == "xcode-plugin.v0.3"
    assert payload["ok"] is True
    assert payload["details"]["topic"] == "ide-vs-cli"


def test_invalid_help_topic_has_user_input_recovery() -> None:
    completed = run_xcode("help", "--topic", "bad-topic", "--json")
    payload = parse_json_stdout(completed)

    assert completed.returncode == 2
    assert payload["ok"] is False
    assert payload["error_type"] == "usage_error"
    assert payload["details"]["recovery"] == "user_input"
    assert "ide-vs-cli" in payload["details"]["valid_topics"]


def test_help_command_examples_use_supported_cli_shapes() -> None:
    known_prefixes = (
        "bin/xcode mcp bootstrap",
        "bin/xcode mcp list-tools",
        "bin/xcode ide status",
        "bin/xcode ide preflight",
        "bin/xcode ide organizer-open",
        "bin/xcode ide organizer-inspect",
        "bin/xcode ide organizer-distribution-inspect",
        "bin/xcode ide organizer-distribution-select",
        "bin/xcode ide organizer-distribution-confirm",
        "bin/xcode ide organizer-distribution-step-inspect",
        "bin/xcode ide organizer-distribution-probe-method",
        "bin/xcode ide organizer-distribution-custom-select",
        "bin/xcode ide organizer-distribution-probe-custom-route",
        "bin/xcode ide list-schemes",
        "bin/xcode ide list-destinations",
        "bin/xcode scheme --path",
        "bin/xcode simulator resolve",
        "bin/xcode build",
        "bin/xcode distribution",
        "bin/xcode package zip",
        "bin/xcode package audit",
        "bin/xcode release verify",
        "bin/xcode doctor",
    )

    commands = [
        command
        for topic in TOPICS.values()
        for command in topic.get("commands", [])
    ]

    assert commands
    assert all(command.startswith(known_prefixes) for command in commands)
    assert all("scheme inspect" not in command for command in commands)
    assert all("--project-path" not in command for command in commands)
