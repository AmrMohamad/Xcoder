#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from xcode_common import EXIT_CODES, emit_failure, emit_success, plugin_root
from xcode_version import plugin_version


PROVENANCE_SCHEMA = "xcoder.release-provenance.v1"
CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class ComponentBuild:
    name: str
    package_path: str
    source_hash: str
    binary_hash: str
    binary_path: str
    signing_mode: str
    self_tests: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "package_path": self.package_path,
            "source_hash": self.source_hash,
            "binary_hash": self.binary_hash,
            "signing_mode": self.signing_mode,
            "self_tests": list(self.self_tests),
        }


def digest_paths(paths: list[Path], root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_checked(runner: CommandRunner, command: list[str], *, cwd: Path, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    completed = runner(command, cwd=cwd, text=True, capture_output=True, timeout=timeout)
    if completed.returncode != 0:
        raise ComponentBuildError(command, completed)
    return completed


class ComponentBuildError(RuntimeError):
    def __init__(self, command: list[str], completed: subprocess.CompletedProcess[str]) -> None:
        super().__init__(completed.stderr.strip() or completed.stdout.strip() or f"command exited {completed.returncode}")
        self.command = command
        self.completed = completed


def swift_bin_path(package: Path, scratch: Path, runner: CommandRunner) -> Path:
    run_checked(
        runner,
        ["/usr/bin/swift", "build", "-c", "release", "--package-path", str(package), "--scratch-path", str(scratch)],
        cwd=package,
        timeout=1200,
    )
    result = run_checked(
        runner,
        ["/usr/bin/swift", "build", "-c", "release", "--package-path", str(package), "--scratch-path", str(scratch), "--show-bin-path"],
        cwd=package,
    )
    return Path(result.stdout.strip())


def build_mcp_server(
    root: Path,
    stage: Path,
    scratch: Path,
    runner: CommandRunner = subprocess.run,
    signing_identity: str | None = None,
    self_test: bool = True,
) -> ComponentBuild:
    package = root / "native" / "XcodeMCPServer"
    resolved_path = package / "Package.resolved"
    resolved_before = resolved_path.read_bytes() if resolved_path.exists() else None
    run_checked(runner, ["/usr/bin/swift", "package", "resolve", "--package-path", str(package), "--scratch-path", str(scratch)], cwd=package, timeout=300)
    resolved_after = resolved_path.read_bytes() if resolved_path.exists() else None
    if resolved_before != resolved_after:
        raise RuntimeError("Swift package resolution changed native/XcodeMCPServer/Package.resolved")
    run_checked(runner, ["/usr/bin/swift", "test", "--package-path", str(package), "--scratch-path", str(scratch)], cwd=package, timeout=1200)
    bin_path = swift_bin_path(package, scratch, runner)
    source = bin_path / "xcode-mcp-server"
    destination = stage / "bin" / "xcode-mcp-server"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    destination.chmod(0o755)
    identity = signing_identity or "-"
    run_checked(runner, ["/usr/bin/codesign", "--force", "--sign", identity, "--timestamp=none", str(destination)], cwd=stage, timeout=60)
    run_checked(runner, ["/usr/bin/codesign", "--verify", "--strict", str(destination)], cwd=stage, timeout=60)
    self_tests: tuple[str, ...] = ()
    if self_test:
        self_tests = self_test_mcp_server(stage, runner)
    sources = list((package / "Sources").rglob("*.swift")) + [package / "Package.swift", package / "Package.resolved"]
    signing_mode = "configured-identity" if signing_identity else "ad-hoc"
    return ComponentBuild("mcp_server", "bin/xcode-mcp-server", digest_paths(sources, package), sha256_file(destination), str(destination), signing_mode, self_tests)


def build_native_helper(
    root: Path,
    stage: Path,
    scratch: Path,
    runner: CommandRunner = subprocess.run,
    signing_identity: str | None = None,
    self_test: bool = True,
) -> ComponentBuild:
    package = root / "native" / "XcodeNativeHelper"
    bin_path = swift_bin_path(package, scratch, runner)
    source = bin_path / "xcode-native-helper"
    app = stage / "bin" / "XcodeNativeHelper.app"
    executable = app / "Contents" / "MacOS" / "xcode-native-helper"
    resources = app / "Contents" / "Resources"
    resources.mkdir(parents=True, exist_ok=True)
    executable.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, executable)
    executable.chmod(0o755)
    plist_source = root / "bin" / "XcodeNativeHelper.app" / "Contents" / "Info.plist"
    plist = plistlib.loads(plist_source.read_bytes())
    plist["CFBundleShortVersionString"] = plugin_version(root)
    plist["CFBundleVersion"] = plugin_version(root)
    (app / "Contents" / "Info.plist").write_bytes(plistlib.dumps(plist, sort_keys=True))
    signing_mode = "ad-hoc"
    identity = signing_identity or "-"
    run_checked(runner, ["/usr/bin/codesign", "--force", "--sign", identity, "--timestamp=none", str(app)], cwd=stage, timeout=60)
    run_checked(runner, ["/usr/bin/codesign", "--verify", "--strict", str(app)], cwd=stage, timeout=60)
    self_tests: tuple[str, ...] = ()
    if self_test:
        self_tests = self_test_native_helper(stage, runner)
    if signing_identity:
        signing_mode = "configured-identity"
    sources = list((package / "Sources").rglob("*.swift")) + [package / "Package.swift"]
    return ComponentBuild("native_helper", "bin/XcodeNativeHelper.app/Contents/MacOS/xcode-native-helper", digest_paths(sources, package), sha256_file(executable), str(executable), signing_mode, self_tests)


def self_test_mcp_server(stage: Path, runner: CommandRunner = subprocess.run) -> tuple[str, ...]:
    executable = stage / "bin" / "xcode-mcp-server"
    run_checked(runner, [str(executable), "--version", "--json"], cwd=stage, timeout=30)
    run_checked(runner, [str(executable), "--doctor", "--json"], cwd=stage, timeout=30)
    run_checked(runner, [str(executable), "--list-tools", "--json"], cwd=stage, timeout=30)
    return ("version", "doctor", "list_tools")


def self_test_native_helper(stage: Path, runner: CommandRunner = subprocess.run) -> tuple[str, ...]:
    executable = stage / "bin" / "XcodeNativeHelper.app" / "Contents" / "MacOS" / "xcode-native-helper"
    run_checked(runner, [str(executable), "helper", "version", "--json"], cwd=stage, timeout=30)
    return ("helper_version",)


def build_components(
    root: Path,
    stage: Path,
    scratch_root: Path,
    components: tuple[str, ...] = ("mcp-server", "native-helper"),
    runner: CommandRunner = subprocess.run,
    signing_identity: str | None = None,
    self_test: bool = True,
) -> dict[str, ComponentBuild]:
    results: dict[str, ComponentBuild] = {}
    if "mcp-server" in components:
        results["mcp_server"] = build_mcp_server(root, stage, scratch_root / "mcp", runner, signing_identity, self_test)
    if "native-helper" in components:
        results["native_helper"] = build_native_helper(root, stage, scratch_root / "helper", runner, signing_identity, self_test)
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Freshly build Xcoder release components.")
    parser.add_argument("--component", choices=("mcp-server", "native-helper", "all"), default="all")
    parser.add_argument("--stage", required=True)
    parser.add_argument("--scratch")
    parser.add_argument("--signing-identity")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = plugin_root()
    stage = Path(args.stage).expanduser().resolve()
    stage.mkdir(parents=True, exist_ok=True)
    components = ("mcp-server", "native-helper") if args.component == "all" else (args.component,)
    scratch_context = None
    try:
        if args.scratch:
            scratch = Path(args.scratch).expanduser().resolve()
            scratch.mkdir(parents=True, exist_ok=True)
        else:
            scratch_context = tempfile.TemporaryDirectory(prefix="xcoder-component-build-")
            scratch = Path(scratch_context.name)
        results = build_components(root, stage, scratch, components, signing_identity=args.signing_identity)
    except (OSError, RuntimeError, ComponentBuildError) as exc:
        return emit_failure("build-components", "binary_self_test_failed", "A release component could not be built and self-tested", errors=[str(exc)], exit_code=EXIT_CODES["binary_self_test_failed"])
    finally:
        if scratch_context:
            scratch_context.cleanup()
    return emit_success("build-components", "Release components were freshly built and self-tested", details={"components": {name: value.as_dict() for name, value in results.items()}})


if __name__ == "__main__":
    raise SystemExit(main())
