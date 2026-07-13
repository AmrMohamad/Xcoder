from __future__ import annotations

import subprocess
from pathlib import Path

from xcode_component_build import ComponentBuild, ComponentBuildError, digest_paths, swift_bin_path


def test_component_provenance_omits_private_build_path(tmp_path: Path) -> None:
    component = ComponentBuild(
        "mcp_server",
        "bin/xcode-mcp-server",
        "source-hash",
        "binary-hash",
        str(tmp_path / "private" / "binary"),
        "unsigned",
        ("version",),
    )
    payload = component.as_dict()
    assert "binary_path" not in payload
    assert str(tmp_path) not in str(payload)


def test_source_digest_includes_relative_names_and_content(tmp_path: Path) -> None:
    first = tmp_path / "A.swift"
    second = tmp_path / "B.swift"
    first.write_text("let value = 1\n")
    second.write_text("let value = 2\n")
    original = digest_paths([first, second], tmp_path)
    second.write_text("let value = 3\n")
    assert digest_paths([first, second], tmp_path) != original


def test_swift_bin_path_builds_release_before_querying_output_path(tmp_path: Path) -> None:
    commands: list[list[str]] = []

    def runner(command, **kwargs):
        commands.append(command)
        stdout = str(tmp_path / "release") if "--show-bin-path" in command else ""
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    assert swift_bin_path(tmp_path / "Package", tmp_path / "scratch", runner) == tmp_path / "release"
    assert "--show-bin-path" not in commands[0]
    assert commands[0][1:4] == ["build", "-c", "release"]
    assert "--show-bin-path" in commands[1]


def test_component_build_error_preserves_stdout_and_stderr() -> None:
    completed = subprocess.CompletedProcess(
        ["swift", "test"],
        1,
        stdout="Test Suite failed with one failure",
        stderr="Build complete!",
    )

    message = str(ComponentBuildError(["swift", "test"], completed))

    assert "command exited 1: swift test" in message
    assert "stdout:\nTest Suite failed with one failure" in message
    assert "stderr:\nBuild complete!" in message
