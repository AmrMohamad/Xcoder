from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import xcode_release
from xcode_component_build import ComponentBuild


def test_release_builds_before_staging_and_packages_after_self_tests(tmp_path: Path, monkeypatch) -> None:
    events: list[str] = []
    source = tmp_path / "source"
    source.mkdir()
    output = tmp_path / "release.zip"

    monkeypatch.setattr(xcode_release, "plugin_root", lambda: source)
    monkeypatch.setattr(xcode_release, "plugin_version", lambda root: "0.6.0")
    monkeypatch.setattr(xcode_release, "git_state", lambda root, runner: ("abc123", False, 315532800))
    monkeypatch.setattr(xcode_release, "version_issues", lambda root: [])
    monkeypatch.setattr(xcode_release, "toolchain_details", lambda root, runner: {})

    def fake_components(root, component_root, scratch, **kwargs):
        events.extend(["swift_tests", "mcp_release_build", "native_helper_release_build"])
        (component_root / "bin/XcodeNativeHelper.app/Contents/MacOS").mkdir(parents=True)
        (component_root / "bin/xcode-mcp-server").write_bytes(b"mcp")
        (component_root / "bin/XcodeNativeHelper.app/Contents/MacOS/xcode-native-helper").write_bytes(b"helper")
        return {
            "mcp_server": ComponentBuild("mcp_server", "bin/xcode-mcp-server", "source", "binary", "private", "test", ()),
            "native_helper": ComponentBuild("native_helper", "bin/XcodeNativeHelper.app/Contents/MacOS/xcode-native-helper", "source", "binary", "private", "test", ()),
        }

    def fake_stage(root, stage):
        events.append("staging_tree_creation")
        (stage / "bin/XcodeNativeHelper.app").mkdir(parents=True)

    monkeypatch.setattr(xcode_release, "build_components", fake_components)
    monkeypatch.setattr(xcode_release, "copy_source_tree", fake_stage)
    monkeypatch.setattr(xcode_release, "self_test_mcp_server", lambda stage, runner: events.append("component_self_tests") or ("version", "doctor", "list_tools"))
    monkeypatch.setattr(xcode_release, "self_test_native_helper", lambda stage, runner: ("helper_version",))

    def runner(command, **kwargs):
        if "pytest" in command:
            events.append("python_tests")
        if "xcode_package.py" in " ".join(command) and "zip" in command:
            events.append("package_creation")
            Path(command[command.index("--output") + 1]).write_bytes(b"deterministic")
        if "xcode_package.py" in " ".join(command) and "audit" in command:
            events.append("package_audit_and_extracted_smoke")
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    args = argparse.Namespace(output=str(output), allow_dirty=False, source_date_epoch=315532800, signing_identity=None)
    assert xcode_release.release_verify(args, runner=runner) == 0
    assert events.index("swift_tests") < events.index("mcp_release_build")
    assert events.index("staging_tree_creation") < events.index("component_self_tests")
    assert events.index("component_self_tests") < events.index("package_creation")
    assert events.index("package_creation") < events.index("package_audit_and_extracted_smoke")
    assert events.count("package_creation") == 2
