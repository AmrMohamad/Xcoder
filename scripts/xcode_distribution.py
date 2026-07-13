#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from xcode_common import (
    EXIT_CODES,
    build_envelope,
    create_artifact_dir,
    normalize_path,
    plugin_root,
    print_envelope,
    write_json,
)


DISTRIBUTION_EXIT_CODES = {
    "xcode_distribution_requires_gui": EXIT_CODES["usage_error"],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Use Xcode GUI archive and typed blocked distribution routes.")
    parser.add_argument("--json", action="store_true", help="JSON is always emitted.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    archive = subparsers.add_parser("archive", help="Start Product > Archive through Xcode GUI automation.")
    archive.add_argument("--workspace-path", required=True)
    archive.add_argument("--scheme", required=True)
    archive.add_argument("--configuration", default="Release")
    archive.add_argument("--destination", default="generic/platform=iOS")
    archive.add_argument("--archive-path")
    archive.add_argument("--timeout-seconds", type=int, default=3600)
    archive.add_argument("--dry-run", action="store_true")
    archive.add_argument("--preflight-only", action="store_true")

    export = subparsers.add_parser("export-archive", help="Report the required Organizer GUI export route.")
    export.add_argument("--archive-path")

    upload = subparsers.add_parser("upload-archive", help="Report the required Organizer GUI upload route.")
    upload.add_argument("--archive-path")
    upload.add_argument("--ipa-path")

    distribute = subparsers.add_parser("distribute", help="Report the required Organizer GUI distribution route.")
    distribute.add_argument("--workspace-path")
    distribute.add_argument("--scheme")
    return parser.parse_args()


def xcode_bin() -> Path:
    return plugin_root() / "bin" / "xcode"


def emit_distribution(
    command_name: str,
    *,
    ok: bool,
    summary: Any,
    error_type: str | None = None,
    details: dict[str, Any] | None = None,
    artifacts: dict[str, Any] | None = None,
    warnings: list[Any] | None = None,
    errors: list[Any] | None = None,
    next_actions: list[Any] | None = None,
    artifact_dir: Path | None = None,
    archive_path: str | None = None,
    ipa_path: str | None = None,
    elapsed_seconds: float | None = None,
) -> int:
    envelope = build_envelope(
        command_name=command_name,
        ok=ok,
        status="success" if ok else "failure",
        error_type=None if ok else error_type,
        summary=summary,
        details=details,
        artifacts=artifacts,
        warnings=warnings,
        errors=errors or ([] if ok else [{"error_type": error_type, "message": summary}]),
        next_actions=next_actions,
        elapsed_seconds=elapsed_seconds,
    )
    envelope.update(
        {
            "archive_path": archive_path,
            "ipa_path": ipa_path,
            "upload_id": None,
            "log_paths": {},
        }
    )
    print_envelope(envelope, artifact_dir=artifact_dir)
    return 0 if ok else DISTRIBUTION_EXIT_CODES.get(
        error_type or "",
        EXIT_CODES.get(error_type or "", 1),
    )


def normalize_existing_path(value: str, *, description: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"{description} does not exist: {path}")
    return path


def archive_command(args: argparse.Namespace) -> int:
    started = time.monotonic()
    artifact_dir = create_artifact_dir("distribution-archive")
    try:
        workspace_path = normalize_existing_path(args.workspace_path, description="workspace_path")
    except FileNotFoundError as exc:
        return emit_distribution(
            "distribution.archive",
            ok=False,
            error_type="usage_error",
            summary=str(exc),
            artifact_dir=artifact_dir,
        )

    warnings: list[Any] = []
    if args.archive_path:
        warnings.append("archive_path is ignored in GUI-only archive mode; Xcode Organizer owns archive location.")
    details = {
        "gui_only": True,
        "route": "Product > Archive",
        "workspace_path": str(workspace_path),
        "scheme": args.scheme,
        "configuration": args.configuration,
        "destination": args.destination,
    }
    if args.dry_run or args.preflight_only:
        return emit_distribution(
            "distribution.archive",
            ok=True,
            summary=(
                "GUI archive dry run completed without pressing Product > Archive."
                if args.dry_run
                else "GUI archive preflight completed without pressing Product > Archive."
            ),
            details=details,
            artifact_dir=artifact_dir,
            warnings=warnings,
            elapsed_seconds=time.monotonic() - started,
        )

    command = [
        str(xcode_bin()),
        "ide",
        "archive",
        "--workspace-path",
        str(workspace_path),
        "--scheme",
        args.scheme,
        "--timeout-seconds",
        str(min(args.timeout_seconds, 120)),
        "--require-native-preflight",
        "--json",
    ]
    command_path = artifact_dir / "gui-archive.command.json"
    stdout_path = artifact_dir / "gui-archive.stdout.log"
    stderr_path = artifact_dir / "gui-archive.stderr.log"
    write_json(command_path, {"command": command})
    try:
        completed = subprocess.run(
            command,
            cwd=plugin_root(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=min(args.timeout_seconds, 180),
            check=False,
        )
        stdout_path.write_text(completed.stdout, encoding="utf-8")
        stderr_path.write_text(completed.stderr, encoding="utf-8")
    except subprocess.TimeoutExpired as exc:
        stdout_path.write_text(str(exc.stdout or ""), encoding="utf-8")
        stderr_path.write_text(str(exc.stderr or ""), encoding="utf-8")
        return emit_distribution(
            "distribution.archive",
            ok=False,
            error_type="command_timeout",
            summary="Xcode GUI archive action timed out.",
            details=details,
            artifacts={"artifact_dir": str(artifact_dir)},
            artifact_dir=artifact_dir,
            warnings=warnings,
            elapsed_seconds=time.monotonic() - started,
        )

    try:
        ide_envelope = json.loads(completed.stdout)
    except json.JSONDecodeError:
        ide_envelope = None
    if completed.returncode != 0 or not isinstance(ide_envelope, dict) or ide_envelope.get("ok") is not True:
        return emit_distribution(
            "distribution.archive",
            ok=False,
            error_type="xcode_ide_automation_failed",
            summary="Xcode GUI archive action failed.",
            details={**details, "ide_envelope": ide_envelope},
            artifacts={"artifact_dir": str(artifact_dir)},
            artifact_dir=artifact_dir,
            warnings=warnings,
            elapsed_seconds=time.monotonic() - started,
        )
    return emit_distribution(
        "distribution.archive",
        ok=True,
        summary="Xcode GUI archive action started.",
        details={**details, "ide_envelope": ide_envelope},
        artifacts={"artifact_dir": str(artifact_dir)},
        artifact_dir=artifact_dir,
        warnings=warnings,
        elapsed_seconds=time.monotonic() - started,
    )


def blocked_command(args: argparse.Namespace, *, capability: str, route: str) -> int:
    return emit_distribution(
        f"distribution.{args.command.replace('-', '_')}",
        ok=False,
        error_type="xcode_distribution_requires_gui",
        summary=f"{capability.capitalize()} requires a typed Xcode Organizer GUI workflow.",
        details={
            "capability": capability,
            "available": False,
            "required_route": route,
            "gui_only": True,
        },
        archive_path=getattr(args, "archive_path", None),
        ipa_path=getattr(args, "ipa_path", None),
        next_actions=[f"Use {route} until Xcoder exposes the complete typed GUI state machine."],
    )


def main() -> int:
    args = parse_args()
    if args.command == "archive":
        return archive_command(args)
    if args.command == "export-archive":
        return blocked_command(args, capability="export", route="Xcode Organizer export UI")
    if args.command == "upload-archive":
        return blocked_command(args, capability="upload", route="Xcode Organizer upload UI")
    if args.command == "distribute":
        return blocked_command(args, capability="distribution", route="Xcode Organizer GUI")
    return emit_distribution(
        "distribution",
        ok=False,
        error_type="usage_error",
        summary="Unknown distribution command",
    )


if __name__ == "__main__":
    raise SystemExit(main())
