from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

import xcode_bootstrap


EXPECTED_STEP_NAMES = [
    "plugin-json",
    "mcp-json",
    "python-compile",
    "chmod-public-bin",
    "host-macos-version",
    "xcode-select",
    "swift-version",
    "fresh-component-build",
    "mcp-version",
    "mcp-doctor",
    "mcp-list-tools",
    "plugin-doctor",
]


def parse_envelope(stdout: str) -> dict[str, Any]:
    return json.loads(stdout)


def fake_step_result(name: str, artifact_dir: Path, *, ok: bool = True, exit_code: int = 0) -> dict[str, Any]:
    stdout_path = artifact_dir / f"{name}.stdout.txt"
    stderr_path = artifact_dir / f"{name}.stderr.txt"
    stdout_path.write_text(f"{name} stdout\n", encoding="utf-8")
    stderr_path.write_text(f"{name} stderr\n", encoding="utf-8")
    return {
        "name": name,
        "ok": ok,
        "exit_code": exit_code,
        "timed_out": False,
        "artifacts": {
            "stdout": str(stdout_path),
            "stderr": str(stderr_path),
        },
    }


def configure_bootstrap_test(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    fail_step: str | None = None,
) -> Path:
    root = tmp_path / "plugin"
    artifact_dir = root / ".codex" / "xcode" / "artifacts" / "bootstrap-test"
    artifact_dir.mkdir(parents=True)
    (root / "bin").mkdir(parents=True)

    monkeypatch.setattr(sys, "argv", ["xcode_bootstrap.py", "--json"])
    monkeypatch.setattr(xcode_bootstrap, "plugin_root", lambda: root)
    monkeypatch.setattr(xcode_bootstrap.platform, "mac_ver", lambda: ("15.0", ("", "", ""), ""))
    monkeypatch.setattr(xcode_bootstrap, "create_artifact_dir", lambda *_args, **_kwargs: artifact_dir)

    def fake_run_step(
        name: str,
        _command: list[str],
        *,
        artifact_dir: Path,
        cwd: Path | None = None,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        del cwd, timeout_seconds
        if name == fail_step:
            return fake_step_result(name, artifact_dir, ok=False, exit_code=1)
        return fake_step_result(name, artifact_dir)

    monkeypatch.setattr(xcode_bootstrap, "run_step", fake_run_step)
    return artifact_dir


def test_bootstrap_success_preserves_step_names(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact_dir = configure_bootstrap_test(monkeypatch, tmp_path)

    assert xcode_bootstrap.main() == 0
    payload = parse_envelope(capsys.readouterr().out)

    assert payload["ok"] is True
    assert payload["command_name"] == "mcp-bootstrap"
    assert [step["name"] for step in payload["details"]["steps"]] == EXPECTED_STEP_NAMES
    assert Path(payload["artifacts"]["steps"]).read_text(encoding="utf-8")
    assert Path(payload["artifacts"]["envelope"]).exists()
    assert Path(payload["artifacts"]["artifact_dir"]) == artifact_dir


def test_bootstrap_failure_includes_failed_step_artifacts_and_recovery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_bootstrap_test(monkeypatch, tmp_path, fail_step="fresh-component-build")

    assert xcode_bootstrap.main() == 2
    payload = parse_envelope(capsys.readouterr().out)
    step_names = [step["name"] for step in payload["details"]["steps"]]
    failed_step = payload["details"]["steps"][-1]

    assert payload["ok"] is False
    assert payload["error_type"] == "mcp_bootstrap_failed"
    assert payload["details"]["recovery"] == "environment"
    assert payload["errors"][0]["recovery"] == "environment"
    assert step_names == EXPECTED_STEP_NAMES[: EXPECTED_STEP_NAMES.index("fresh-component-build") + 1]
    assert failed_step["name"] == "fresh-component-build"
    assert failed_step["ok"] is False
    assert Path(failed_step["artifacts"]["stdout"]).exists()
    assert Path(failed_step["artifacts"]["stderr"]).exists()
