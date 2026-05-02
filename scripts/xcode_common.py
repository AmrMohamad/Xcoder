#!/usr/bin/env python3

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "xcode-plugin.v0.3"

EXIT_CODES: dict[str, int] = {
    "usage_error": 2,
    "tool_missing": 3,
    "permission_denied": 4,
    "accessibility_not_trusted": 4,
    "trusted_fast_denied": 5,
    "path_violation": 6,
    "xcode_not_running": 10,
    "no_workspace": 11,
    "multiple_workspaces_ambiguous": 12,
    "scheme_not_found": 13,
    "scheme_not_testable": 14,
    "destination_not_found": 20,
    "destination_ambiguous": 21,
    "xcode_ide_automation_failed": 22,
    "xcode_modal_blocking": 23,
    "xcode_activation_failed": 24,
    "workspace_open_failed": 25,
    "simulator_boot_failed": 30,
    "install_failed": 31,
    "launch_failed": 32,
    "xcresult_missing": 40,
    "xcresult_corrupt": 41,
    "cache_invalid": 50,
    "native_helper_unavailable": 60,
    "native_helper_version_mismatch": 61,
    "native_helper_failed": 62,
    "native_helper_build_failed": 63,
    "subprocess_failed": 70,
    "command_timeout": 124,
}


def plugin_root() -> Path:
    return Path(__file__).resolve().parents[1]


def plugin_version() -> str:
    manifest = plugin_root() / ".codex-plugin" / "plugin.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        return str(data.get("version") or "0.0.0")
    except Exception:
        return "0.0.0"


def cache_path_version(root: Path | None = None) -> str | None:
    candidate = root or plugin_root()
    parts = candidate.parts
    for index, part in enumerate(parts[:-1]):
        if part == "xcode" and index > 0 and parts[index - 1] == "local":
            return parts[index + 1]
    return None


def plugin_identity() -> dict[str, Any]:
    version = plugin_version()
    cache_version = cache_path_version()
    return {
        "plugin_root": str(plugin_root()),
        "manifest_version": version,
        "cache_path_version": cache_version,
        "compatibility_cache_alias": bool(cache_version and cache_version != version),
    }


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def timestamp_slug() -> str:
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip(".-")
    return cleaned or "xcode"


def short_hash(value: str, length: int = 12) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def redacted_home_path(path: str) -> str:
    home = str(Path.home())
    return path.replace(home, "~") if home and path.startswith(home) else path


def redact_text(text: str) -> str:
    patterns = [
        (r"(?i)(api[_-]?key|token|secret|password)=([^\s]+)", r"\1=<redacted>"),
        (r"(?i)(Authorization:\s*Bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1<redacted>"),
    ]
    redacted = text
    for pattern, replacement in patterns:
        redacted = re.sub(pattern, replacement, redacted)
    return redacted.replace(str(Path.home()), "~")


def normalize_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def default_artifact_root(cwd: Path | None = None) -> Path:
    return (cwd or Path.cwd()) / ".codex" / "xcode" / "artifacts"


def create_artifact_dir(command_name: str, base_dir: str | Path | None = None) -> Path:
    base = normalize_path(base_dir) if base_dir else default_artifact_root()
    suffix = secrets.token_hex(3)
    path = base / f"{timestamp_slug()}-{safe_name(command_name)}-{suffix}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def assert_path_inside(path: Path, root: Path) -> None:
    candidate = normalize_path(path)
    container = normalize_path(root)
    try:
        candidate.relative_to(container)
    except ValueError as exc:
        raise ValueError(f"{candidate} is outside allowed root {container}") from exc


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_envelope(
    *,
    command_name: str,
    ok: bool,
    status: str,
    summary: Any,
    error_type: str | None = None,
    details: dict[str, Any] | None = None,
    artifacts: dict[str, Any] | None = None,
    warnings: list[Any] | None = None,
    errors: list[Any] | None = None,
    next_actions: list[Any] | None = None,
    started_at: str | None = None,
    elapsed_seconds: float | None = None,
) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "ok": ok,
        "status": status,
        "error_type": error_type,
        "command_name": command_name,
        "summary": summary,
        "artifacts": artifacts or {},
        "warnings": warnings or [],
        "errors": errors or [],
        "next_actions": next_actions or [],
    }
    if details is not None:
        envelope["details"] = details
    if started_at is not None:
        envelope["started_at"] = started_at
        envelope["finished_at"] = now_iso()
    if elapsed_seconds is not None:
        envelope["elapsed_seconds"] = round(elapsed_seconds, 3)
    return envelope


def print_envelope(envelope: dict[str, Any], *, artifact_dir: Path | None = None) -> None:
    if artifact_dir is not None:
        stored = dict(envelope)
        artifacts = dict(stored.get("artifacts") or {})
        artifacts.setdefault("envelope", str(artifact_dir / "envelope.json"))
        stored["artifacts"] = artifacts
        write_json(artifact_dir / "envelope.json", stored)
        envelope = stored
    print(json.dumps(envelope, indent=2, sort_keys=True))


def emit_success(
    command_name: str,
    summary: Any,
    *,
    details: dict[str, Any] | None = None,
    artifacts: dict[str, Any] | None = None,
    warnings: list[Any] | None = None,
    next_actions: list[Any] | None = None,
    artifact_dir: Path | None = None,
    started_at: str | None = None,
    elapsed_seconds: float | None = None,
) -> int:
    envelope = build_envelope(
        command_name=command_name,
        ok=True,
        status="success",
        error_type=None,
        summary=summary,
        details=details,
        artifacts=artifacts,
        warnings=warnings,
        errors=[],
        next_actions=next_actions,
        started_at=started_at,
        elapsed_seconds=elapsed_seconds,
    )
    print_envelope(envelope, artifact_dir=artifact_dir)
    return 0


def emit_failure(
    command_name: str,
    error_type: str,
    summary: Any,
    *,
    details: dict[str, Any] | None = None,
    artifacts: dict[str, Any] | None = None,
    warnings: list[Any] | None = None,
    errors: list[Any] | None = None,
    next_actions: list[Any] | None = None,
    exit_code: int | None = None,
    artifact_dir: Path | None = None,
    started_at: str | None = None,
    elapsed_seconds: float | None = None,
) -> int:
    envelope = build_envelope(
        command_name=command_name,
        ok=False,
        status="failure",
        error_type=error_type,
        summary=summary,
        details=details,
        artifacts=artifacts,
        warnings=warnings,
        errors=errors or [],
        next_actions=next_actions,
        started_at=started_at,
        elapsed_seconds=elapsed_seconds,
    )
    print_envelope(envelope, artifact_dir=artifact_dir)
    return exit_code if exit_code is not None else EXIT_CODES.get(error_type, 1)


def run_command(
    command: list[str],
    *,
    timeout_seconds: int | None = None,
    cwd: str | Path | None = None,
    input_text: str | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            command,
            cwd=str(cwd) if cwd is not None else None,
            stdin=subprocess.PIPE if input_text is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        return {
            "command": command,
            "exit_code": 127,
            "stdout": "",
            "stderr": str(exc),
            "timed_out": False,
            "elapsed_seconds": time.monotonic() - started,
            "error_type": "tool_missing",
        }

    try:
        stdout, stderr = process.communicate(input=input_text, timeout=timeout_seconds)
        return {
            "command": command,
            "exit_code": process.returncode,
            "stdout": stdout or "",
            "stderr": stderr or "",
            "timed_out": False,
            "elapsed_seconds": time.monotonic() - started,
            "error_type": None if process.returncode == 0 else "subprocess_failed",
        }
    except subprocess.TimeoutExpired:
        pgid = None
        try:
            pgid = os.getpgid(process.pid)
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except Exception:
            process.terminate()

        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                if pgid is not None:
                    os.killpg(pgid, signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                pass
            stdout, stderr = process.communicate()

        return {
            "command": command,
            "exit_code": EXIT_CODES["command_timeout"],
            "stdout": stdout or "",
            "stderr": stderr or f"timed out after {timeout_seconds}s",
            "timed_out": True,
            "elapsed_seconds": time.monotonic() - started,
            "error_type": "command_timeout",
        }


def exit_for_result(result: dict[str, Any], default_error_type: str = "subprocess_failed") -> tuple[str, int]:
    if result.get("timed_out"):
        return "command_timeout", EXIT_CODES["command_timeout"]
    if result.get("exit_code") == 127:
        return "tool_missing", EXIT_CODES["tool_missing"]
    return default_error_type, int(result.get("exit_code") or EXIT_CODES.get(default_error_type, 1))


def compact_output(text: str, limit: int = 1600) -> str:
    stripped = redact_text(text.strip())
    if len(stripped) <= limit:
        return stripped
    return stripped[:limit] + "\n...<truncated>"


def copy_executable_permissions(path: Path) -> None:
    path.chmod(path.stat().st_mode | 0o755)


if __name__ == "__main__":
    print("Shared helpers for the xcode plugin; import this module from command scripts.")
