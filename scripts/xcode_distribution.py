#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import signal
import subprocess
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from typing import Any

from xcode_common import (
    EXIT_CODES,
    build_envelope,
    compact_output,
    create_artifact_dir,
    normalize_path,
    plugin_root,
    print_envelope,
    redact_text,
    safe_name,
    write_json,
)


DISTRIBUTION_EXIT_CODES = {
    "export_options_invalid": EXIT_CODES["usage_error"],
    "xcode_distribution_requires_gui": EXIT_CODES["usage_error"],
    "signing_preflight_failed": EXIT_CODES["usage_error"],
    "upload_failed": EXIT_CODES["subprocess_failed"],
}

SENSITIVE_FLAGS = {"--apiKey", "--apiIssuer", "--password", "--username"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Archive, export, and upload iOS app distributions through Xcoder.")
    parser.add_argument("--json", action="store_true", help="Emit JSON. Kept for CLI symmetry; JSON is always emitted.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    archive = subparsers.add_parser("archive", help="Create an .xcarchive for an iOS app.")
    archive.add_argument("--workspace-path", required=True, help="Path to .xcworkspace or .xcodeproj.")
    archive.add_argument("--scheme", required=True)
    archive.add_argument("--configuration", default="Release")
    archive.add_argument("--destination", default="generic/platform=iOS")
    archive.add_argument("--archive-path")
    archive.add_argument("--timeout-seconds", type=int, default=3600)
    archive.add_argument("--dry-run", action="store_true")
    archive.add_argument("--preflight-only", action="store_true")

    export = subparsers.add_parser("export-archive", help="Export an IPA from an .xcarchive.")
    export.add_argument("--archive-path", required=True)
    export.add_argument("--export-method", required=True)
    export.add_argument("--team-id")
    export.add_argument("--signing-style")
    export.add_argument("--export-path", required=True)
    export.add_argument("--export-options", help="JSON object to merge into ExportOptions.plist.")
    export.add_argument("--export-options-plist", help="Existing ExportOptions.plist to validate and use as a base.")
    export.add_argument("--timeout-seconds", type=int, default=1800)
    export.add_argument("--dry-run", action="store_true")
    export.add_argument("--preflight-only", action="store_true")

    upload = subparsers.add_parser("upload-archive", help="Upload an exported IPA to App Store Connect/TestFlight.")
    upload.add_argument("--ipa-path")
    upload.add_argument("--archive-path")
    upload.add_argument("--provider")
    upload.add_argument("--api-key-id")
    upload.add_argument("--issuer-id")
    upload.add_argument("--api-key-path")
    upload.add_argument("--api-key-env")
    upload.add_argument("--timeout-seconds", type=int, default=1800)
    upload.add_argument("--dry-run", action="store_true")
    upload.add_argument("--preflight-only", action="store_true")

    distribute = subparsers.add_parser("distribute", help="Archive, export, and upload as one guarded workflow.")
    distribute.add_argument("--workspace-path", required=True)
    distribute.add_argument("--scheme", required=True)
    distribute.add_argument("--export-method", required=True)
    distribute.add_argument("--destination-channel", required=True)
    distribute.add_argument("--team-id", required=True)
    distribute.add_argument("--credentials-ref", help="JSON object or environment variable name containing upload credentials.")
    distribute.add_argument("--configuration", default="Release")
    distribute.add_argument("--destination", default="generic/platform=iOS")
    distribute.add_argument("--archive-path")
    distribute.add_argument("--export-path")
    distribute.add_argument("--signing-style", default="automatic")
    distribute.add_argument("--timeout-seconds", type=int, default=5400)
    distribute.add_argument("--dry-run", action="store_true")
    distribute.add_argument("--preflight-only", action="store_true")
    return parser.parse_args()


def xcode_bin() -> Path:
    return plugin_root() / "bin" / "xcode"


def exit_code_for(error_type: str) -> int:
    return DISTRIBUTION_EXIT_CODES.get(error_type, EXIT_CODES.get(error_type, 1))


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
    upload_id: str | None = None,
    log_paths: dict[str, Any] | None = None,
    started_at: str | None = None,
    elapsed_seconds: float | None = None,
) -> int:
    normalized_errors = errors or ([] if ok else [{"error_type": error_type or "subprocess_failed", "message": summary}])
    envelope = build_envelope(
        command_name=command_name,
        ok=ok,
        status="success" if ok else "failure",
        error_type=None if ok else error_type,
        summary=summary,
        details=details,
        artifacts=artifacts,
        warnings=warnings,
        errors=normalized_errors,
        next_actions=next_actions,
        started_at=started_at,
        elapsed_seconds=elapsed_seconds,
    )
    envelope["archive_path"] = archive_path
    envelope["ipa_path"] = ipa_path
    envelope["upload_id"] = upload_id
    envelope["log_paths"] = log_paths or {}
    print_envelope(envelope, artifact_dir=artifact_dir)
    return 0 if ok else exit_code_for(error_type or "subprocess_failed")


def redact_sensitive(text: str, secrets: list[str] | None = None) -> str:
    redacted = redact_text(text)
    redacted = re.sub(r"(?i)(--apiKey\s+)\S+", r"\1<redacted>", redacted)
    redacted = re.sub(r"(?i)(--apiIssuer\s+)\S+", r"\1<redacted>", redacted)
    redacted = re.sub(r"(?i)(api_key_id|issuer_id|api_key_path)\s*[:=]\s*[^\s,}]+", r"\1=<redacted>", redacted)
    for secret in secrets or []:
        if secret:
            redacted = redacted.replace(secret, "<redacted>")
    return redacted


def redacted_command(command: list[str], secrets: list[str] | None = None) -> list[str]:
    result: list[str] = []
    redact_next = False
    for item in command:
        if redact_next:
            result.append("<redacted>")
            redact_next = False
            continue
        result.append(redact_sensitive(item, secrets))
        if item in SENSITIVE_FLAGS:
            redact_next = True
    return result


def read_tail(path: Path, limit: int = 1600) -> str:
    if not path.exists():
        return ""
    data = path.read_bytes()
    if len(data) > limit:
        data = data[-limit:]
    return compact_output(data.decode("utf-8", errors="replace"), limit)


def stream_pipe(pipe: Any, output_path: Path, secrets: list[str]) -> None:
    with output_path.open("w", encoding="utf-8") as handle:
        for line in iter(pipe.readline, ""):
            handle.write(redact_sensitive(line, secrets))


def run_command_capture(
    command: list[str],
    *,
    timeout_seconds: int,
    artifact_dir: Path,
    stem: str,
    env: dict[str, str] | None = None,
    secrets: list[str] | None = None,
) -> dict[str, Any]:
    secret_values = [item for item in (secrets or []) if item]
    stdout_log = artifact_dir / f"{stem}.stdout.log"
    stderr_log = artifact_dir / f"{stem}.stderr.log"
    command_log = artifact_dir / f"{stem}.command.json"
    write_json(command_log, {"command": redacted_command(command, secret_values)})
    started = time.monotonic()
    timed_out = False

    try:
        process = subprocess.Popen(
            command,
            cwd=plugin_root(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        stdout_log.write_text("", encoding="utf-8")
        stderr_log.write_text(redact_sensitive(str(exc), secret_values), encoding="utf-8")
        return {
            "exit_code": 127,
            "timed_out": False,
            "elapsed_seconds": time.monotonic() - started,
            "stdout_log": str(stdout_log),
            "stderr_log": str(stderr_log),
            "command_log": str(command_log),
            "stdout_tail": "",
            "stderr_tail": read_tail(stderr_log),
        }

    stdout_thread = threading.Thread(target=stream_pipe, args=(process.stdout, stdout_log, secret_values))
    stderr_thread = threading.Thread(target=stream_pipe, args=(process.stderr, stderr_log, secret_values))
    stdout_thread.start()
    stderr_thread.start()

    try:
        exit_code = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        except Exception:
            process.terminate()
        try:
            exit_code = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            except Exception:
                process.kill()
            exit_code = process.wait()
        if exit_code == 0:
            exit_code = EXIT_CODES["command_timeout"]

    stdout_thread.join(timeout=5)
    stderr_thread.join(timeout=5)
    return {
        "exit_code": exit_code,
        "timed_out": timed_out,
        "elapsed_seconds": time.monotonic() - started,
        "stdout_log": str(stdout_log),
        "stderr_log": str(stderr_log),
        "command_log": str(command_log),
        "stdout_tail": read_tail(stdout_log),
        "stderr_tail": read_tail(stderr_log),
    }


def project_flag(path: Path) -> str:
    if path.suffix == ".xcworkspace":
        return "-workspace"
    if path.suffix == ".xcodeproj":
        return "-project"
    raise ValueError("workspace_path must point to a .xcworkspace or .xcodeproj")


def normalize_existing_path(path: str, *, description: str) -> Path:
    resolved = normalize_path(path)
    if not resolved.exists():
        raise FileNotFoundError(f"{description} does not exist: {resolved}")
    return resolved


def parse_json_log(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def modal_blockers_from_value(value: Any) -> list[Any]:
    blockers: list[Any] = []
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = key.lower()
            if lowered in {"modal_blockers", "blockers", "sheets", "sheet", "modals"} and child:
                blockers.append({key: child})
            else:
                blockers.extend(modal_blockers_from_value(child))
    elif isinstance(value, list):
        for child in value:
            blockers.extend(modal_blockers_from_value(child))
    return blockers


def modal_preflight(artifact_dir: Path) -> tuple[list[str], list[Any], dict[str, Any]]:
    result = run_command_capture(
        [str(xcode_bin()), "native", "ax", "xcode-windows", "--json"],
        timeout_seconds=30,
        artifact_dir=artifact_dir,
        stem="native-windows-preflight",
    )
    envelope = parse_json_log(Path(result["stdout_log"]))
    warnings: list[str] = []
    errors: list[Any] = []
    details: dict[str, Any] = {"native_windows": result}
    if not isinstance(envelope, dict):
        warnings.append("Native Xcode window/modal preflight did not return JSON; Organizer/signing blockers could not be confirmed.")
        return warnings, errors, details

    details["native_windows_envelope"] = envelope
    blockers = modal_blockers_from_value(envelope.get("details") or envelope)
    if envelope.get("error_type") == "xcode_modal_blocking" or blockers:
        errors.append(
            {
                "error_type": "xcode_modal_blocking",
                "message": "Xcode reports a modal window or sheet that can block archive/signing/upload automation.",
                "blockers": blockers,
            }
        )
    elif not envelope.get("ok"):
        warnings.append("Native Xcode modal preflight was unavailable; continue only if Xcode has no Organizer/signing sheets open.")
    return warnings, errors, details


def extract_build_settings(payload: Any) -> dict[str, Any]:
    entries = payload if isinstance(payload, list) else payload.get("project", []) if isinstance(payload, dict) else []
    candidates: list[dict[str, Any]] = []
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get("buildSettings"), dict):
            settings = entry["buildSettings"]
            if settings.get("PRODUCT_BUNDLE_IDENTIFIER"):
                candidates.append({"target": entry.get("target"), "buildSettings": settings})
    if not candidates:
        return {}

    preferred = next(
        (
            item
            for item in candidates
            if item["buildSettings"].get("WRAPPER_EXTENSION") == "app"
            and not str(item["buildSettings"].get("PRODUCT_BUNDLE_IDENTIFIER", "")).lower().endswith("tests")
        ),
        candidates[0],
    )
    settings = preferred["buildSettings"]
    return {
        "target": preferred.get("target"),
        "bundle_id": settings.get("PRODUCT_BUNDLE_IDENTIFIER"),
        "development_team": settings.get("DEVELOPMENT_TEAM"),
        "code_sign_style": settings.get("CODE_SIGN_STYLE"),
        "provisioning_profile_specifier": settings.get("PROVISIONING_PROFILE_SPECIFIER"),
        "product_name": settings.get("PRODUCT_NAME"),
        "configuration": settings.get("CONFIGURATION"),
        "sdkroot": settings.get("SDKROOT"),
    }


def signing_preflight(
    *,
    workspace_path: Path,
    scheme: str,
    configuration: str,
    destination: str,
    artifact_dir: Path,
    expected_team_id: str | None = None,
    timeout_seconds: int = 120,
) -> tuple[dict[str, Any], list[str], list[Any], dict[str, Any]]:
    command = [
        "xcodebuild",
        project_flag(workspace_path),
        str(workspace_path),
        "-scheme",
        scheme,
        "-configuration",
        configuration,
        "-destination",
        destination,
        "-showBuildSettings",
        "-json",
    ]
    result = run_command_capture(command, timeout_seconds=timeout_seconds, artifact_dir=artifact_dir, stem="signing-preflight")
    log_paths = {
        "signing_preflight_stdout": result["stdout_log"],
        "signing_preflight_stderr": result["stderr_log"],
        "signing_preflight_command": result["command_log"],
    }
    warnings: list[str] = []
    errors: list[Any] = []
    if result["exit_code"] != 0:
        errors.append(
            {
                "error_type": "signing_preflight_failed",
                "message": "Xcode build settings preflight failed before archive/upload.",
                "stderr_tail": result["stderr_tail"],
            }
        )
        return {}, warnings, errors, log_paths

    settings = extract_build_settings(parse_json_log(Path(result["stdout_log"])))
    if not settings.get("bundle_id"):
        errors.append({"error_type": "signing_preflight_failed", "message": "PRODUCT_BUNDLE_IDENTIFIER was not found."})
    if expected_team_id and settings.get("development_team") and settings.get("development_team") != expected_team_id:
        errors.append(
            {
                "error_type": "signing_preflight_failed",
                "message": "DEVELOPMENT_TEAM does not match requested team_id.",
                "expected_team_id": "<redacted>",
                "actual_team_id": "<redacted>",
            }
        )
    if not settings.get("development_team"):
        warnings.append("DEVELOPMENT_TEAM was not found in build settings; upload preflight cannot fully prove team ownership.")
    if not settings.get("code_sign_style"):
        warnings.append("CODE_SIGN_STYLE was not found in build settings.")
    return settings, warnings, errors, log_paths


def archive_info(archive_path: Path) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    info_path = archive_path / "Info.plist"
    if not info_path.exists():
        return {}, [f"Archive Info.plist is missing at {info_path}."]
    try:
        info = plistlib.loads(info_path.read_bytes())
    except Exception as exc:
        return {}, [f"Archive Info.plist could not be parsed: {exc}"]
    properties = info.get("ApplicationProperties") or {}
    metadata = {
        "bundle_id": properties.get("CFBundleIdentifier"),
        "application_path": properties.get("ApplicationPath"),
        "signing_identity": properties.get("SigningIdentity"),
        "team": properties.get("Team"),
        "archive_version": info.get("ArchiveVersion"),
        "creation_date": str(info.get("CreationDate")) if info.get("CreationDate") else None,
        "name": info.get("Name"),
    }
    if not metadata["bundle_id"]:
        warnings.append("Archive metadata does not include CFBundleIdentifier.")
    return metadata, warnings


def parse_export_options_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"export_options must be a JSON object: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("export_options must be a JSON object.")
    return parsed


def load_export_options(args: argparse.Namespace) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    options: dict[str, Any] = {}
    if getattr(args, "export_options_plist", None):
        plist_path = normalize_existing_path(args.export_options_plist, description="ExportOptions.plist")
        try:
            loaded = plistlib.loads(plist_path.read_bytes())
        except Exception as exc:
            raise ValueError(f"ExportOptions.plist could not be parsed: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ValueError("ExportOptions.plist root must be a dictionary.")
        options.update(loaded)

    options.update(parse_export_options_json(getattr(args, "export_options", None)))
    if getattr(args, "export_method", None):
        options["method"] = args.export_method
    if getattr(args, "team_id", None):
        options["teamID"] = args.team_id
    if getattr(args, "signing_style", None):
        options["signingStyle"] = args.signing_style

    if not options.get("method"):
        raise ValueError("ExportOptions.plist requires method.")
    signing_style = options.get("signingStyle")
    if signing_style and signing_style not in {"automatic", "manual"}:
        raise ValueError("signing_style must be automatic or manual.")
    team_id = options.get("teamID")
    if team_id and not re.fullmatch(r"[A-Z0-9]{10}", str(team_id)):
        warnings.append("team_id does not match Apple's usual 10-character team identifier shape.")
    try:
        plistlib.dumps(options)
    except Exception as exc:
        raise ValueError(f"Export options are not plist-serializable: {exc}") from exc
    return options, warnings


def write_export_options_plist(options: dict[str, Any], artifact_dir: Path) -> Path:
    path = artifact_dir / "ExportOptions.plist"
    path.write_bytes(plistlib.dumps(options, sort_keys=True))
    return path


def find_ipa(path: Path) -> Path | None:
    if path.is_file() and path.suffix == ".ipa":
        return path
    if not path.exists() or not path.is_dir():
        return None
    matches = sorted(path.rglob("*.ipa"))
    return matches[0] if matches else None


def decode_mobileprovision(data: bytes) -> tuple[dict[str, Any] | None, str | None]:
    with tempfile.NamedTemporaryFile(suffix=".mobileprovision") as handle:
        handle.write(data)
        handle.flush()
        result = subprocess.run(
            ["/usr/bin/security", "cms", "-D", "-i", handle.name],
            text=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    if result.returncode != 0:
        return None, compact_output(result.stderr.decode("utf-8", errors="replace"))
    try:
        return plistlib.loads(result.stdout), None
    except Exception as exc:
        return None, str(exc)


def ipa_metadata(ipa_path: Path) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    metadata: dict[str, Any] = {"ipa_path": str(ipa_path)}
    try:
        with zipfile.ZipFile(ipa_path, "r") as archive:
            info_name = next((name for name in archive.namelist() if re.match(r"Payload/[^/]+\.app/Info\.plist$", name)), None)
            if not info_name:
                return metadata, ["IPA does not contain Payload/<App>.app/Info.plist."]
            info = plistlib.loads(archive.read(info_name))
            metadata.update(
                {
                    "bundle_id": info.get("CFBundleIdentifier"),
                    "bundle_version": info.get("CFBundleVersion"),
                    "short_version": info.get("CFBundleShortVersionString"),
                    "app_name": info.get("CFBundleName") or info.get("CFBundleDisplayName"),
                }
            )
            profile_name = info_name.rsplit("/", 1)[0] + "/embedded.mobileprovision"
            if profile_name in archive.namelist():
                profile, profile_error = decode_mobileprovision(archive.read(profile_name))
                if profile:
                    team_ids = profile.get("TeamIdentifier") or []
                    entitlements = profile.get("Entitlements") or {}
                    metadata.update(
                        {
                            "team_id": team_ids[0] if team_ids else None,
                            "profile_name": profile.get("Name"),
                            "profile_uuid": profile.get("UUID"),
                            "application_identifier": entitlements.get("application-identifier"),
                        }
                    )
                elif profile_error:
                    warnings.append(f"embedded.mobileprovision could not be decoded: {profile_error}")
            else:
                warnings.append("IPA does not contain embedded.mobileprovision; team preflight is limited.")
    except zipfile.BadZipFile as exc:
        return metadata, [f"IPA is not a readable zip file: {exc}"]
    except Exception as exc:
        return metadata, [f"IPA metadata could not be parsed: {exc}"]
    if not metadata.get("bundle_id"):
        warnings.append("IPA Info.plist does not include CFBundleIdentifier.")
    return metadata, warnings


def credentials_from_args(args: argparse.Namespace) -> tuple[dict[str, Any], list[str]]:
    credentials: dict[str, Any] = {}
    if getattr(args, "credentials_ref", None):
        raw = args.credentials_ref
        source = os.environ.get(raw, raw)
        try:
            parsed = json.loads(source)
        except json.JSONDecodeError as exc:
            raise ValueError("credentials_ref must be a JSON object or an environment variable containing one.") from exc
        if not isinstance(parsed, dict):
            raise ValueError("credentials_ref must resolve to a JSON object.")
        credentials.update(parsed)
    for key in ("provider", "api_key_id", "issuer_id", "api_key_path", "api_key_env"):
        value = getattr(args, key, None)
        if value:
            credentials[key] = value
    if not credentials.get("api_key_id"):
        raise ValueError("api_key_id is required for App Store Connect upload.")
    if not credentials.get("issuer_id"):
        raise ValueError("issuer_id is required for App Store Connect upload.")
    if credentials.get("api_key_path") and credentials.get("api_key_env"):
        raise ValueError("Pass only one of api_key_path or api_key_env.")

    secrets = [str(credentials.get("api_key_id") or ""), str(credentials.get("issuer_id") or "")]
    key_path_raw = credentials.get("api_key_path")
    if credentials.get("api_key_env"):
        key_path_raw = os.environ.get(str(credentials["api_key_env"]))
        if not key_path_raw:
            raise ValueError("api_key_env does not point to a populated environment variable.")
    if key_path_raw:
        key_path = normalize_existing_path(str(key_path_raw), description="App Store Connect API key")
        credentials["api_key_path"] = str(key_path)
        secrets.append(str(key_path))
    else:
        raise ValueError("api_key_path or api_key_env is required for App Store Connect upload.")
    return credentials, secrets


def redacted_credentials(credentials: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": credentials.get("provider"),
        "api_key_id": "<redacted>" if credentials.get("api_key_id") else None,
        "issuer_id": "<redacted>" if credentials.get("issuer_id") else None,
        "api_key_path": "<redacted>" if credentials.get("api_key_path") else None,
        "api_key_env": credentials.get("api_key_env"),
    }


def altool_environment(credentials: dict[str, Any]) -> dict[str, str]:
    env = os.environ.copy()
    key_path = credentials.get("api_key_path")
    if key_path:
        env["API_PRIVATE_KEYS_DIR"] = str(Path(key_path).parent)
    return env


def extract_upload_id(payload: Any) -> str | None:
    if isinstance(payload, dict):
        for key in ("upload_id", "uploadId", "id", "assetDeliveryId", "apple_id"):
            value = payload.get(key)
            if value:
                return str(value)
        for value in payload.values():
            found = extract_upload_id(value)
            if found:
                return found
    if isinstance(payload, list):
        for value in payload:
            found = extract_upload_id(value)
            if found:
                return found
    return None


def archive_command(args: argparse.Namespace) -> int:
    started = time.monotonic()
    artifact_dir = create_artifact_dir("distribution-archive")
    warnings: list[Any] = []
    log_paths: dict[str, Any] = {}
    try:
        workspace_path = normalize_existing_path(args.workspace_path, description="workspace_path")
        entry_flag = project_flag(workspace_path)
    except (FileNotFoundError, ValueError) as exc:
        return emit_distribution("distribution.archive", ok=False, error_type="usage_error", summary=str(exc), artifact_dir=artifact_dir)

    _ = entry_flag
    archive_path = normalize_path(args.archive_path) if args.archive_path else None
    if archive_path:
        warnings.append("archive_path is ignored in GUI-only archive mode; Xcode Organizer owns the archive location.")

    if args.dry_run:
        return emit_distribution(
            "distribution.archive",
            ok=True,
            summary="GUI archive dry run completed without pressing Product > Archive.",
            details={
                "gui_only": True,
                "route": "Product > Archive",
                "workspace_path": str(workspace_path),
                "scheme": args.scheme,
                "configuration": args.configuration,
                "destination": args.destination,
            },
            artifact_dir=artifact_dir,
            archive_path=None,
            warnings=warnings,
            log_paths=log_paths,
        )

    modal_warnings, modal_errors, modal_details = modal_preflight(artifact_dir)
    warnings.extend(modal_warnings)
    log_paths.update(
        {
            "native_windows_stdout": modal_details["native_windows"]["stdout_log"],
            "native_windows_stderr": modal_details["native_windows"]["stderr_log"],
            "native_windows_command": modal_details["native_windows"]["command_log"],
        }
    )
    if modal_errors:
        return emit_distribution(
            "distribution.archive",
            ok=False,
            error_type="xcode_modal_blocking",
            summary="Xcode modal blockers must be resolved before archive.",
            details=modal_details,
            artifact_dir=artifact_dir,
            archive_path=None,
            warnings=warnings,
            errors=modal_errors,
            log_paths=log_paths,
        )

    if args.preflight_only:
        return emit_distribution(
            "distribution.archive",
            ok=True,
            summary="GUI archive preflight completed without pressing Product > Archive.",
            details={
                "gui_only": True,
                "route": "Product > Archive",
                "workspace_path": str(workspace_path),
                "scheme": args.scheme,
                "native_windows": modal_details.get("native_windows_envelope"),
            },
            artifact_dir=artifact_dir,
            archive_path=None,
            warnings=warnings,
            log_paths=log_paths,
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
    result = run_command_capture(command, timeout_seconds=min(args.timeout_seconds, 180), artifact_dir=artifact_dir, stem="gui-archive")
    log_paths.update({"gui_archive_stdout": result["stdout_log"], "gui_archive_stderr": result["stderr_log"], "gui_archive_command": result["command_log"]})
    ide_envelope = parse_json_log(Path(result["stdout_log"]))
    ide_ok = isinstance(ide_envelope, dict) and ide_envelope.get("ok") is True
    if result["exit_code"] != 0 or not ide_ok:
        error_type = "command_timeout" if result["timed_out"] else "xcode_ide_automation_failed"
        return emit_distribution(
            "distribution.archive",
            ok=False,
            error_type=error_type,
            summary="Xcode GUI archive action failed.",
            details={"gui_only": True, "route": "Product > Archive", "ide_envelope": ide_envelope, "stdout_tail": result["stdout_tail"], "stderr_tail": result["stderr_tail"]},
            artifact_dir=artifact_dir,
            archive_path=None,
            warnings=warnings,
            log_paths=log_paths,
            elapsed_seconds=time.monotonic() - started,
        )
    return emit_distribution(
        "distribution.archive",
        ok=True,
        summary="Xcode GUI archive action started.",
        details={"gui_only": True, "route": "Product > Archive", "ide_envelope": ide_envelope},
        artifacts={"artifact_dir": str(artifact_dir)},
        artifact_dir=artifact_dir,
        archive_path=None,
        warnings=warnings,
        log_paths=log_paths,
        elapsed_seconds=time.monotonic() - started,
    )


def export_archive_command(args: argparse.Namespace) -> int:
    started = time.monotonic()
    artifact_dir = create_artifact_dir("distribution-export")
    warnings: list[Any] = []
    return emit_distribution(
        "distribution.export_archive",
        ok=False,
        error_type="xcode_distribution_requires_gui",
        summary="Export is blocked because distribution is GUI-only. Xcode Organizer export automation is not implemented yet.",
        details={
            "gui_only": True,
            "blocked_route": "command-line export",
            "required_route": "Xcode Organizer export UI",
            "archive_path": args.archive_path,
            "export_method": args.export_method,
        },
        artifact_dir=artifact_dir,
        warnings=warnings,
        archive_path=args.archive_path,
        next_actions=[
            "Use Xcode Organizer manually for export until the plugin has a typed GUI Organizer export workflow.",
            "Do not use command-line export for distribution work in this plugin.",
        ],
        elapsed_seconds=time.monotonic() - started,
    )
    try:
        archive_path = normalize_existing_path(args.archive_path, description="archive_path")
        options, option_warnings = load_export_options(args)
        warnings.extend(option_warnings)
    except (FileNotFoundError, ValueError) as exc:
        return emit_distribution("distribution.export_archive", ok=False, error_type="export_options_invalid", summary=str(exc), artifact_dir=artifact_dir)
    export_path = normalize_path(args.export_path)
    options_path = write_export_options_plist(options, artifact_dir)
    metadata, archive_warnings = archive_info(archive_path)
    warnings.extend(archive_warnings)
    log_paths: dict[str, Any] = {"export_options_plist": str(options_path)}

    command = [
        "xcodebuild",
        "-exportArchive",
        "-archivePath",
        str(archive_path),
        "-exportPath",
        str(export_path),
        "-exportOptionsPlist",
        str(options_path),
    ]
    if args.dry_run or args.preflight_only:
        return emit_distribution(
            "distribution.export_archive",
            ok=True,
            summary="Export preflight completed without exporting an IPA.",
            details={"archive": metadata, "export_options": {**options, "teamID": "<redacted>" if options.get("teamID") else None}, "command": redacted_command(command)},
            artifacts={"artifact_dir": str(artifact_dir), "export_options_plist": str(options_path)},
            artifact_dir=artifact_dir,
            archive_path=str(archive_path),
            warnings=warnings,
            log_paths=log_paths,
        )

    result = run_command_capture(command, timeout_seconds=args.timeout_seconds, artifact_dir=artifact_dir, stem="export-archive")
    log_paths.update({"export_stdout": result["stdout_log"], "export_stderr": result["stderr_log"], "export_command": result["command_log"]})
    ipa_path = find_ipa(export_path)
    if result["exit_code"] != 0 or ipa_path is None:
        error_type = "command_timeout" if result["timed_out"] else "subprocess_failed"
        return emit_distribution(
            "distribution.export_archive",
            ok=False,
            error_type=error_type,
            summary="Xcode archive export failed.",
            details={"archive": metadata, "stdout_tail": result["stdout_tail"], "stderr_tail": result["stderr_tail"]},
            artifact_dir=artifact_dir,
            archive_path=str(archive_path),
            warnings=warnings,
            log_paths=log_paths,
            elapsed_seconds=time.monotonic() - started,
        )
    return emit_distribution(
        "distribution.export_archive",
        ok=True,
        summary="IPA export completed.",
        details={"archive": metadata, "export_path": str(export_path)},
        artifacts={"artifact_dir": str(artifact_dir), "ipa_path": str(ipa_path), "export_options_plist": str(options_path)},
        artifact_dir=artifact_dir,
        archive_path=str(archive_path),
        ipa_path=str(ipa_path),
        warnings=warnings,
        log_paths=log_paths,
        elapsed_seconds=time.monotonic() - started,
    )


def upload_archive_command(args: argparse.Namespace) -> int:
    started = time.monotonic()
    artifact_dir = create_artifact_dir("distribution-upload")
    warnings: list[Any] = []
    return emit_distribution(
        "distribution.upload_archive",
        ok=False,
        error_type="xcode_distribution_requires_gui",
        summary="Upload is blocked because distribution is GUI-only. Xcode Organizer/App Store Connect upload UI automation is not implemented yet.",
        details={
            "gui_only": True,
            "blocked_route": "command-line upload",
            "required_route": "Xcode Organizer Distribute App UI",
            "ipa_path": args.ipa_path,
            "archive_path": args.archive_path,
        },
        artifact_dir=artifact_dir,
        warnings=warnings,
        archive_path=args.archive_path,
        ipa_path=args.ipa_path,
        next_actions=[
            "Use Xcode Organizer manually for upload until the plugin has a typed GUI Organizer upload workflow.",
            "Do not use command-line upload for distribution work in this plugin.",
        ],
        elapsed_seconds=time.monotonic() - started,
    )
    try:
        credentials, secrets = credentials_from_args(args)
    except (FileNotFoundError, ValueError) as exc:
        return emit_distribution("distribution.upload_archive", ok=False, error_type="usage_error", summary=str(exc), artifact_dir=artifact_dir)

    archive_path: Path | None = normalize_path(args.archive_path) if args.archive_path else None
    ipa_path = normalize_path(args.ipa_path) if args.ipa_path else find_ipa(archive_path) if archive_path else None
    if ipa_path is None or not ipa_path.exists():
        return emit_distribution(
            "distribution.upload_archive",
            ok=False,
            error_type="usage_error",
            summary="Upload requires an exported IPA. If archive_path points to an .xcarchive, run xcode_export_archive first.",
            details={"archive_path": str(archive_path) if archive_path else None},
            artifact_dir=artifact_dir,
            archive_path=str(archive_path) if archive_path else None,
        )

    modal_warnings, modal_errors, modal_details = modal_preflight(artifact_dir)
    warnings.extend(modal_warnings)
    log_paths: dict[str, Any] = {
        "native_windows_stdout": modal_details["native_windows"]["stdout_log"],
        "native_windows_stderr": modal_details["native_windows"]["stderr_log"],
        "native_windows_command": modal_details["native_windows"]["command_log"],
    }
    if modal_errors:
        return emit_distribution(
            "distribution.upload_archive",
            ok=False,
            error_type="xcode_modal_blocking",
            summary="Xcode modal blockers must be resolved before upload.",
            details=modal_details,
            artifact_dir=artifact_dir,
            archive_path=str(archive_path) if archive_path else None,
            ipa_path=str(ipa_path),
            warnings=warnings,
            errors=modal_errors,
            log_paths=log_paths,
        )

    metadata, ipa_warnings = ipa_metadata(ipa_path)
    warnings.extend(ipa_warnings)
    if not metadata.get("bundle_id"):
        return emit_distribution(
            "distribution.upload_archive",
            ok=False,
            error_type="signing_preflight_failed",
            summary="Upload preflight could not identify the IPA bundle id.",
            details={"ipa": metadata, "credentials": redacted_credentials(credentials)},
            artifact_dir=artifact_dir,
            archive_path=str(archive_path) if archive_path else None,
            ipa_path=str(ipa_path),
            warnings=warnings,
            log_paths=log_paths,
        )
    if not metadata.get("team_id"):
        warnings.append("IPA team id could not be confirmed from embedded provisioning metadata.")

    command = [
        "xcrun",
        "altool",
        "--upload-app",
        "--file",
        str(ipa_path),
        "--type",
        "ios",
        "--apiKey",
        str(credentials["api_key_id"]),
        "--apiIssuer",
        str(credentials["issuer_id"]),
        "--output-format",
        "json",
    ]
    if credentials.get("provider"):
        command.extend(["--asc-provider", str(credentials["provider"])])

    key_path = Path(str(credentials["api_key_path"]))
    expected_name = f"AuthKey_{credentials['api_key_id']}.p8"
    if key_path.name != expected_name:
        warnings.append("App Store Connect key file name does not match AuthKey_<api_key_id>.p8; altool may not find it.")

    if args.dry_run or args.preflight_only:
        return emit_distribution(
            "distribution.upload_archive",
            ok=True,
            summary="Upload preflight completed without contacting App Store Connect.",
            details={"ipa": metadata, "credentials": redacted_credentials(credentials), "command": redacted_command(command, secrets)},
            artifact_dir=artifact_dir,
            archive_path=str(archive_path) if archive_path else None,
            ipa_path=str(ipa_path),
            warnings=warnings,
            log_paths=log_paths,
        )

    result = run_command_capture(
        command,
        timeout_seconds=args.timeout_seconds,
        artifact_dir=artifact_dir,
        stem="upload",
        env=altool_environment(credentials),
        secrets=secrets,
    )
    log_paths.update({"upload_stdout": result["stdout_log"], "upload_stderr": result["stderr_log"], "upload_command": result["command_log"]})
    upload_response = parse_json_log(Path(result["stdout_log"]))
    upload_id = extract_upload_id(upload_response)
    if result["exit_code"] != 0:
        error_type = "command_timeout" if result["timed_out"] else "upload_failed"
        return emit_distribution(
            "distribution.upload_archive",
            ok=False,
            error_type=error_type,
            summary="App Store Connect upload failed.",
            details={"ipa": metadata, "asc_response": upload_response, "stdout_tail": result["stdout_tail"], "stderr_tail": result["stderr_tail"]},
            artifact_dir=artifact_dir,
            archive_path=str(archive_path) if archive_path else None,
            ipa_path=str(ipa_path),
            upload_id=upload_id,
            warnings=warnings,
            log_paths=log_paths,
            elapsed_seconds=time.monotonic() - started,
        )
    return emit_distribution(
        "distribution.upload_archive",
        ok=True,
        summary="App Store Connect upload completed.",
        details={"ipa": metadata, "asc_response": upload_response},
        artifacts={"artifact_dir": str(artifact_dir), "ipa_path": str(ipa_path)},
        artifact_dir=artifact_dir,
        archive_path=str(archive_path) if archive_path else None,
        ipa_path=str(ipa_path),
        upload_id=upload_id,
        warnings=warnings,
        log_paths=log_paths,
        elapsed_seconds=time.monotonic() - started,
    )


def distribute_command(args: argparse.Namespace) -> int:
    started = time.monotonic()
    artifact_dir = create_artifact_dir("distribution-distribute")
    warnings: list[Any] = []
    log_paths: dict[str, Any] = {}
    return emit_distribution(
        "distribution.distribute",
        ok=False,
        error_type="xcode_distribution_requires_gui",
        summary="End-to-end distribution is blocked because distribution is GUI-only. The full Xcode Organizer archive/export/upload flow is not implemented yet.",
        details={
            "gui_only": True,
            "blocked_route": "command-line archive/export/upload",
            "required_route": "Xcode Product > Archive and Organizer Distribute App UI",
            "workspace_path": args.workspace_path,
            "scheme": args.scheme,
            "destination_channel": args.destination_channel,
        },
        artifact_dir=artifact_dir,
        warnings=warnings,
        next_actions=[
            "Use xcode_archive to start Product > Archive through the GUI.",
            "Use Xcode Organizer manually for export/upload until the plugin has typed GUI Organizer controls.",
        ],
        elapsed_seconds=time.monotonic() - started,
    )
    try:
        workspace_path = normalize_existing_path(args.workspace_path, description="workspace_path")
        entry_flag = project_flag(workspace_path)
        credentials, secrets = credentials_from_args(args)
        options, option_warnings = load_export_options(args)
        warnings.extend(option_warnings)
    except (FileNotFoundError, ValueError) as exc:
        return emit_distribution("distribution.distribute", ok=False, error_type="usage_error", summary=str(exc), artifact_dir=artifact_dir)

    archive_path = normalize_path(args.archive_path) if args.archive_path else artifact_dir / f"{safe_name(args.scheme)}.xcarchive"
    export_path = normalize_path(args.export_path) if args.export_path else artifact_dir / "export"
    options_path = write_export_options_plist(options, artifact_dir)

    modal_warnings, modal_errors, modal_details = modal_preflight(artifact_dir)
    warnings.extend(modal_warnings)
    log_paths.update(
        {
            "native_windows_stdout": modal_details["native_windows"]["stdout_log"],
            "native_windows_stderr": modal_details["native_windows"]["stderr_log"],
            "native_windows_command": modal_details["native_windows"]["command_log"],
            "export_options_plist": str(options_path),
        }
    )
    if modal_errors:
        return emit_distribution(
            "distribution.distribute",
            ok=False,
            error_type="xcode_modal_blocking",
            summary="Xcode modal blockers must be resolved before distribution.",
            details=modal_details,
            artifact_dir=artifact_dir,
            archive_path=str(archive_path),
            warnings=warnings,
            errors=modal_errors,
            log_paths=log_paths,
        )

    settings, signing_warnings, signing_errors, signing_logs = signing_preflight(
        workspace_path=workspace_path,
        scheme=args.scheme,
        configuration=args.configuration,
        destination=args.destination,
        artifact_dir=artifact_dir,
        expected_team_id=args.team_id,
        timeout_seconds=min(args.timeout_seconds, 180),
    )
    warnings.extend(signing_warnings)
    log_paths.update(signing_logs)
    if signing_errors:
        return emit_distribution(
            "distribution.distribute",
            ok=False,
            error_type="signing_preflight_failed",
            summary="Distribution signing preflight failed.",
            details={"signing": settings},
            artifact_dir=artifact_dir,
            archive_path=str(archive_path),
            warnings=warnings,
            errors=signing_errors,
            log_paths=log_paths,
        )

    archive_cmd = [
        "xcodebuild",
        entry_flag,
        str(workspace_path),
        "-scheme",
        args.scheme,
        "-configuration",
        args.configuration,
        "-destination",
        args.destination,
        "-archivePath",
        str(archive_path),
        "archive",
    ]
    export_cmd = [
        "xcodebuild",
        "-exportArchive",
        "-archivePath",
        str(archive_path),
        "-exportPath",
        str(export_path),
        "-exportOptionsPlist",
        str(options_path),
    ]

    if args.dry_run or args.preflight_only:
        return emit_distribution(
            "distribution.distribute",
            ok=True,
            summary="Distribution preflight completed without archive, export, or upload.",
            details={
                "destination_channel": args.destination_channel,
                "signing": settings,
                "credentials": redacted_credentials(credentials),
                "archive_command": redacted_command(archive_cmd),
                "export_command": redacted_command(export_cmd),
            },
            artifact_dir=artifact_dir,
            archive_path=str(archive_path),
            warnings=warnings,
            log_paths=log_paths,
        )

    archive_result = run_command_capture(archive_cmd, timeout_seconds=args.timeout_seconds, artifact_dir=artifact_dir, stem="archive")
    log_paths.update({"archive_stdout": archive_result["stdout_log"], "archive_stderr": archive_result["stderr_log"], "archive_command": archive_result["command_log"]})
    if archive_result["exit_code"] != 0 or not archive_path.exists():
        return emit_distribution(
            "distribution.distribute",
            ok=False,
            error_type="command_timeout" if archive_result["timed_out"] else "subprocess_failed",
            summary="Distribution archive step failed.",
            details={"signing": settings, "stderr_tail": archive_result["stderr_tail"]},
            artifact_dir=artifact_dir,
            archive_path=str(archive_path),
            warnings=warnings,
            log_paths=log_paths,
        )

    export_result = run_command_capture(export_cmd, timeout_seconds=args.timeout_seconds, artifact_dir=artifact_dir, stem="export-archive")
    log_paths.update({"export_stdout": export_result["stdout_log"], "export_stderr": export_result["stderr_log"], "export_command": export_result["command_log"]})
    ipa_path = find_ipa(export_path)
    if export_result["exit_code"] != 0 or ipa_path is None:
        return emit_distribution(
            "distribution.distribute",
            ok=False,
            error_type="command_timeout" if export_result["timed_out"] else "subprocess_failed",
            summary="Distribution export step failed.",
            details={"stderr_tail": export_result["stderr_tail"]},
            artifact_dir=artifact_dir,
            archive_path=str(archive_path),
            warnings=warnings,
            log_paths=log_paths,
        )

    upload_args = argparse.Namespace(
        ipa_path=str(ipa_path),
        archive_path=str(archive_path),
        provider=credentials.get("provider"),
        api_key_id=credentials.get("api_key_id"),
        issuer_id=credentials.get("issuer_id"),
        api_key_path=credentials.get("api_key_path"),
        api_key_env=None,
        timeout_seconds=args.timeout_seconds,
        dry_run=False,
        preflight_only=False,
        credentials_ref=None,
    )
    metadata, ipa_warnings = ipa_metadata(ipa_path)
    warnings.extend(ipa_warnings)
    upload_cmd = [
        "xcrun",
        "altool",
        "--upload-app",
        "--file",
        str(ipa_path),
        "--type",
        "ios",
        "--apiKey",
        str(upload_args.api_key_id),
        "--apiIssuer",
        str(upload_args.issuer_id),
        "--output-format",
        "json",
    ]
    if upload_args.provider:
        upload_cmd.extend(["--asc-provider", str(upload_args.provider)])
    upload_result = run_command_capture(
        upload_cmd,
        timeout_seconds=args.timeout_seconds,
        artifact_dir=artifact_dir,
        stem="upload",
        env=altool_environment(credentials),
        secrets=secrets,
    )
    log_paths.update({"upload_stdout": upload_result["stdout_log"], "upload_stderr": upload_result["stderr_log"], "upload_command": upload_result["command_log"]})
    upload_response = parse_json_log(Path(upload_result["stdout_log"]))
    upload_id = extract_upload_id(upload_response)
    if upload_result["exit_code"] != 0:
        return emit_distribution(
            "distribution.distribute",
            ok=False,
            error_type="command_timeout" if upload_result["timed_out"] else "upload_failed",
            summary="Distribution upload step failed.",
            details={"ipa": metadata, "asc_response": upload_response, "stderr_tail": upload_result["stderr_tail"]},
            artifact_dir=artifact_dir,
            archive_path=str(archive_path),
            ipa_path=str(ipa_path),
            upload_id=upload_id,
            warnings=warnings,
            log_paths=log_paths,
        )

    return emit_distribution(
        "distribution.distribute",
        ok=True,
        summary="Distribution workflow completed.",
        details={"destination_channel": args.destination_channel, "signing": settings, "ipa": metadata, "asc_response": upload_response},
        artifacts={"artifact_dir": str(artifact_dir), "archive_path": str(archive_path), "ipa_path": str(ipa_path)},
        artifact_dir=artifact_dir,
        archive_path=str(archive_path),
        ipa_path=str(ipa_path),
        upload_id=upload_id,
        warnings=warnings,
        log_paths=log_paths,
        elapsed_seconds=time.monotonic() - started,
    )


def main() -> int:
    args = parse_args()
    if args.command == "archive":
        return archive_command(args)
    if args.command == "export-archive":
        return export_archive_command(args)
    if args.command == "upload-archive":
        return upload_archive_command(args)
    if args.command == "distribute":
        return distribute_command(args)
    return emit_distribution("distribution", ok=False, error_type="usage_error", summary="Unknown distribution command")


if __name__ == "__main__":
    raise SystemExit(main())
