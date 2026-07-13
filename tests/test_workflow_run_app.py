from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import xcode_workflow


def result(ok: bool, error_type: str | None = None, *, timed_out: bool = False) -> dict:
    payload = {
        "schema_version": "xcode-plugin.v0.3",
        "ok": ok,
        "status": "success" if ok else "failure",
        "error_type": error_type,
        "summary": "ok" if ok else "failed",
    }
    return {
        "exit_code": 0 if ok else 1,
        "stdout": json.dumps(payload),
        "stderr": "",
        "timed_out": timed_out,
    }


def arguments(tmp_path: Path, *, configuration: str | None = None, no_cli_fallback: bool = False) -> SimpleNamespace:
    project = tmp_path / "App.xcodeproj"
    project.mkdir()
    return SimpleNamespace(
        project_path=str(project),
        scheme="App",
        simulator_name="iPhone",
        runtime=None,
        destination_id="SIMULATOR",
        configuration=configuration,
        timeout_seconds=30,
        no_cli_fallback=no_cli_fallback,
    )


def install_plugin_fake(monkeypatch, *, build: dict, run: dict | None = None) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_call(argv: list[str], timeout_seconds: int) -> dict:
        calls.append(argv)
        if argv[:2] == ["ide", "preflight"]:
            return result(True)
        if "--action" in argv:
            action = argv[argv.index("--action") + 1]
            if action == "build":
                return build
            if action == "run":
                assert run is not None
                return run
        return result(True)

    monkeypatch.setattr(xcode_workflow, "call_plugin", fake_call)
    return calls


def emitted_payload(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def test_compile_failure_never_launches_run(monkeypatch, tmp_path: Path, capsys) -> None:
    calls = install_plugin_fake(monkeypatch, build=result(False, "subprocess_failed"))
    exit_code = xcode_workflow.run_app_command(arguments(tmp_path))
    payload = emitted_payload(capsys)

    assert exit_code != 0
    assert payload["error_type"] == "subprocess_failed"
    assert not any("--action" in call and call[call.index("--action") + 1] == "run" for call in calls)
    run_step = next(step for step in payload["details"]["steps"] if step["name"] == "ide_run")
    assert run_step == {
        "name": "ide_run",
        "attempted": False,
        "ok": False,
        "skipped_reason": "prerequisite_failed",
        "prerequisite": "ide_build",
    }


def test_build_timeout_never_launches_run_or_fallback(monkeypatch, tmp_path: Path, capsys) -> None:
    calls = install_plugin_fake(monkeypatch, build=result(False, "command_timeout", timed_out=True))
    monkeypatch.setattr(
        xcode_workflow,
        "call_plugin_capture",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("fallback must not run")),
    )

    xcode_workflow.run_app_command(arguments(tmp_path))
    payload = emitted_payload(capsys)
    assert payload["error_type"] == "command_timeout"
    assert sum("--action" in call for call in calls) == 1


def test_transport_failure_fallback_build_is_not_run_success(monkeypatch, tmp_path: Path, capsys) -> None:
    calls = install_plugin_fake(monkeypatch, build=result(False, "xcode_ide_automation_failed"))
    monkeypatch.setattr(xcode_workflow, "create_artifact_dir", lambda _: tmp_path / "artifacts")
    monkeypatch.setattr(
        xcode_workflow,
        "call_plugin_capture",
        lambda *args, **kwargs: {"exit_code": 0, "stdout": "", "stderr": "", "timed_out": False},
    )

    exit_code = xcode_workflow.run_app_command(arguments(tmp_path))
    payload = emitted_payload(capsys)
    assert exit_code != 0
    assert payload["error_type"] == "run_not_verified"
    assert payload["details"]["outcome"] == "build_only"
    assert payload["details"]["run_validated"] is False
    assert not any("--action" in call and call[call.index("--action") + 1] == "run" for call in calls)


def test_successful_build_runs_exactly_once(monkeypatch, tmp_path: Path, capsys) -> None:
    calls = install_plugin_fake(monkeypatch, build=result(True), run=result(True))
    exit_code = xcode_workflow.run_app_command(arguments(tmp_path))
    payload = emitted_payload(capsys)

    assert exit_code == 0
    assert payload["ok"] is True
    assert sum("--action" in call and call[call.index("--action") + 1] == "run" for call in calls) == 1


def test_explicit_configuration_is_rejected_before_build(monkeypatch, tmp_path: Path, capsys) -> None:
    calls = install_plugin_fake(monkeypatch, build=result(True), run=result(True))
    exit_code = xcode_workflow.run_app_command(arguments(tmp_path, configuration="Release"))
    payload = emitted_payload(capsys)

    assert exit_code != 0
    assert payload["error_type"] == "configuration_not_supported"
    assert not any("--action" in call for call in calls)
