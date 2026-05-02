#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


ACTIONS = ("build", "test", "clean", "analyze", "build-for-testing", "test-without-building")
PERFORMANCE_PROFILES = ("none", "balanced", "fast", "trusted-fast", "diagnostic")
SPM_RESOLUTION_MODES = ("profile", "auto", "skip-updates", "locked")
SOURCE_PACKAGE_MODES = ("project-shared", "derived-data", "none")


@dataclass(frozen=True)
class ResolvedPlan:
    derived_data_path: Path | None
    source_packages_path: Path | None
    package_cache_path: Path | None
    xctestrun_path: Path | None
    command: list[str]
    optimization_notes: list[str]


def policy_scripts_dir() -> Path:
    return Path.home() / ".codex" / "skills" / "agent-policy-guard" / "scripts"


def add_policy_path() -> None:
    path = str(policy_scripts_dir())
    if path not in sys.path:
        sys.path.insert(0, path)


def validate_build_setting(value: str) -> str:
    if "=" not in value or value.startswith("="):
        raise argparse.ArgumentTypeError("build setting must be in KEY=VALUE form")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run xcodebuild with shared caches and CLI-only build-time optimizations."
    )
    entry_group = parser.add_mutually_exclusive_group(required=False)
    entry_group.add_argument("--project", help="Path to the .xcodeproj file.")
    entry_group.add_argument("--workspace", help="Path to the .xcworkspace file.")

    parser.add_argument("--scheme", help="Xcode scheme to build or test. Required unless --xctestrun is used.")
    parser.add_argument(
        "--action",
        default="build",
        choices=ACTIONS,
        help="xcodebuild action to run.",
    )
    parser.add_argument("--configuration", help="Build configuration.")
    parser.add_argument("--sdk", help="SDK name or path.")
    parser.add_argument(
        "--destination",
        action="append",
        default=[],
        help="Destination specifier. Repeat for multiple destinations.",
    )
    parser.add_argument(
        "--destination-timeout",
        help="Pass -destination-timeout <seconds> to avoid long waits for unavailable destinations.",
    )
    parser.add_argument(
        "--result-bundle-path",
        help="Result bundle path, mainly for test runs. Existing bundles are not removed automatically.",
    )
    parser.add_argument(
        "--xctestrun",
        help="Run test-without-building from this .xctestrun file. Do not combine with --project/--workspace/--scheme.",
    )
    parser.add_argument(
        "--auto-xctestrun",
        action="store_true",
        help="For test-without-building, use the newest matching .xctestrun file under the resolved DerivedData leaf.",
    )
    parser.add_argument(
        "--test-plan",
        help="Pass -testPlan. Best used with test or build-for-testing; for test-without-building prefer --xctestrun/--auto-xctestrun.",
    )
    parser.add_argument(
        "--only-testing",
        action="append",
        default=[],
        help="Pass -only-testing:<identifier>. Repeat to focus the test run.",
    )
    parser.add_argument(
        "--skip-testing",
        action="append",
        default=[],
        help="Pass -skip-testing:<identifier>. Repeat to exclude tests.",
    )

    parser.add_argument(
        "--derived-data-root",
        default="~/Library/Developer/Xcode/DerivedData",
        help="Shared DerivedData root to scan for existing leaves.",
    )
    parser.add_argument(
        "--derived-data-path",
        help="Exact DerivedData leaf to use. Overrides --derived-data-root resolution.",
    )
    parser.add_argument(
        "--derived-data-cache-strategy",
        default="metadata",
        choices=("metadata", "newest", "stable"),
        help=(
            "How to choose an existing DerivedData leaf: metadata prefers leaves whose info.plist references "
            "the current project/workspace path; newest uses the newest name-prefix match; stable uses a "
            "per-entry fallback leaf."
        ),
    )
    parser.add_argument(
        "--cloned-source-packages-dir-path",
        help="Explicit SourcePackages directory. Overrides --source-packages-mode.",
    )
    parser.add_argument(
        "--source-packages-mode",
        default="project-shared",
        choices=SOURCE_PACKAGE_MODES,
        help=(
            "Where to store SwiftPM checkouts. project-shared keeps a stable per-project folder under the "
            "DerivedData root so package checkouts survive DerivedData leaf changes."
        ),
    )
    parser.add_argument(
        "--package-cache-path",
        help="Explicit package repository cache path to pass with -packageCachePath.",
    )
    parser.add_argument(
        "--use-shared-package-cache",
        action="store_true",
        help="Pass -packageCachePath using a stable shared cache folder when supported by xcodebuild.",
    )

    parser.add_argument(
        "--optimization-profile",
        default="balanced",
        choices=PERFORMANCE_PROFILES,
        help=(
            "CLI-only optimization profile. balanced is safe for normal local validation; fast disables the "
            "index store and sets jobs automatically; trusted-fast also skips macro/package-plugin validation."
        ),
    )
    parser.add_argument(
        "--trusted-fast",
        action="store_true",
        help="Required acknowledgement when --optimization-profile trusted-fast is used.",
    )
    parser.add_argument(
        "--trust-reason",
        default="",
        help="Required non-empty reason when --optimization-profile trusted-fast is used.",
    )
    parser.add_argument(
        "--spm-resolution",
        default="profile",
        choices=SPM_RESOLUTION_MODES,
        help=(
            "SwiftPM package resolution behavior. profile means balanced=skip-updates, fast/trusted-fast=locked, "
            "diagnostic=auto, none=auto."
        ),
    )
    parser.add_argument(
        "--scm-provider",
        choices=("auto", "system", "xcode"),
        default="auto",
        help="Pass -scmProvider. system can improve package fetches when shell Git config/SSH/proxy rules matter.",
    )
    parser.add_argument(
        "--disable-package-repository-cache",
        action="store_true",
        help="Pass -disablePackageRepositoryCache. This is usually slower; use only for stuck/corrupt SwiftPM fetches.",
    )
    parser.add_argument(
        "--parallelize-targets",
        dest="parallelize_targets",
        action="store_true",
        default=None,
        help="Pass -parallelizeTargets.",
    )
    parser.add_argument(
        "--no-parallelize-targets",
        dest="parallelize_targets",
        action="store_false",
        help="Do not pass -parallelizeTargets.",
    )
    parser.add_argument(
        "--jobs",
        default="profile",
        help="Pass -jobs <n>. Use an integer, 'auto', 'profile', or 'none'.",
    )
    parser.add_argument(
        "--disable-concurrent-destination-testing",
        dest="disable_concurrent_destination_testing",
        action="store_true",
        default=None,
        help="Pass -disable-concurrent-destination-testing.",
    )
    parser.add_argument(
        "--allow-concurrent-destination-testing",
        dest="disable_concurrent_destination_testing",
        action="store_false",
        help="Do not pass -disable-concurrent-destination-testing.",
    )
    parser.add_argument(
        "--preboot-simulator",
        dest="preboot_simulator",
        action="store_true",
        default=None,
        help="Best-effort preboot of a simulator destination before test actions. Works best with destination id=<UUID>.",
    )
    parser.add_argument(
        "--no-preboot-simulator",
        dest="preboot_simulator",
        action="store_false",
        help="Disable simulator prebooting.",
    )
    parser.add_argument(
        "--preboot-timeout",
        type=int,
        default=60,
        help="Seconds to wait for simulator bootstatus when --preboot-simulator is active.",
    )
    parser.add_argument(
        "--skip-package-plugin-validation",
        dest="skip_package_plugin_validation",
        action="store_true",
        default=None,
        help="Pass -skipPackagePluginValidation. Only use on trusted repositories.",
    )
    parser.add_argument(
        "--skip-macro-validation",
        dest="skip_macro_validation",
        action="store_true",
        default=None,
        help="Pass -skipMacroValidation. Only use on trusted repositories.",
    )
    parser.add_argument(
        "--strict-xcodebuild-flag-detection",
        action="store_true",
        help="When checking optional modern flags, fail instead of silently skipping unsupported flags.",
    )

    parser.add_argument(
        "--show-build-timing-summary",
        action="store_true",
        help="Pass -showBuildTimingSummary.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Do not pass -quiet.",
    )
    parser.add_argument(
        "--keep-shell-script-environment",
        action="store_true",
        help="Do not pass -hideShellScriptEnvironment.",
    )
    parser.add_argument(
        "--keep-signing",
        action="store_true",
        help="Do not add CODE_SIGNING_ALLOWED=NO for simulator validation actions.",
    )
    parser.add_argument(
        "--disable-index-store",
        action="store_true",
        help="Add COMPILER_INDEX_STORE_ENABLE=NO regardless of optimization profile.",
    )
    parser.add_argument(
        "--keep-index-store",
        action="store_true",
        help="Do not let fast profiles disable the index store.",
    )
    parser.add_argument(
        "--clear-xcode-custom-build-location-overrides",
        dest="clear_xcode_custom_build_location_overrides",
        action="store_true",
        default=True,
        help="Pass empty Xcode custom build product/intermediate user defaults so -derivedDataPath is honored.",
    )
    parser.add_argument(
        "--keep-xcode-custom-build-location-overrides",
        dest="clear_xcode_custom_build_location_overrides",
        action="store_false",
        help="Do not clear Xcode custom build product/intermediate user defaults for this invocation.",
    )
    parser.add_argument(
        "--build-setting",
        action="append",
        default=[],
        type=validate_build_setting,
        help="Extra build setting override in KEY=VALUE form. Repeat as needed.",
    )
    parser.add_argument(
        "--extra-arg",
        action="append",
        default=[],
        help="Extra raw xcodebuild argument. For dash-prefixed args use --extra-arg=-flag or pass args after --.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        help="Terminate xcodebuild if it runs longer than this many seconds.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the resolved paths and xcodebuild command without running it. Does not create cache folders.",
    )
    parser.add_argument(
        "--json-dry-run",
        action="store_true",
        help="With --dry-run, print a machine-readable JSON plan to stdout.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Public v0.3 alias for --json-dry-run when --dry-run is used.",
    )
    parser.add_argument("--policy-session-id")
    parser.add_argument("--policy-session-dir")
    parser.add_argument(
        "--policy-init-if-missing",
        action="store_true",
        help="Initialize the guarded policy session automatically when one does not already exist.",
    )
    parser.add_argument(
        "--policy-task-text",
        default="Run and verify an Xcode CLI build",
        help="Task text used if --policy-init-if-missing creates a policy session.",
    )
    parser.add_argument(
        "passthrough_args",
        nargs=argparse.REMAINDER,
        help="Extra raw xcodebuild arguments after --.",
    )

    args = parser.parse_args()
    if args.json:
        args.json_dry_run = True
    if args.passthrough_args and args.passthrough_args[0] == "--":
        args.passthrough_args = args.passthrough_args[1:]
    return args


def validate_args(args: argparse.Namespace) -> None:
    if args.optimization_profile == "trusted-fast" and (not args.trusted_fast or not args.trust_reason.strip()):
        raise SystemExit(
            "error: trusted_fast_denied: --optimization-profile trusted-fast requires --trusted-fast and --trust-reason"
        )
    has_entry = bool(args.project or args.workspace)
    has_xctestrun = bool(args.xctestrun)
    if args.action != "test-without-building" and has_xctestrun:
        raise SystemExit("error: --xctestrun is only valid with --action test-without-building")
    if has_xctestrun and (has_entry or args.scheme):
        raise SystemExit("error: do not combine --xctestrun with --project, --workspace, or --scheme")
    if args.auto_xctestrun and args.action != "test-without-building":
        raise SystemExit("error: --auto-xctestrun is only valid with --action test-without-building")
    if not has_xctestrun:
        if not has_entry:
            raise SystemExit("error: provide --project or --workspace, unless --xctestrun is used")
        if not args.scheme:
            raise SystemExit("error: provide --scheme, unless --xctestrun is used")
    if args.jobs not in {"profile", "auto", "none"}:
        try:
            jobs = int(args.jobs)
        except ValueError as exc:
            raise SystemExit("error: --jobs must be an integer, 'auto', 'profile', or 'none'") from exc
        if jobs < 1:
            raise SystemExit("error: --jobs must be >= 1")
    if args.timeout_seconds is not None and args.timeout_seconds <= 0:
        raise SystemExit("error: --timeout-seconds must be > 0")


def expand_path(path: str) -> Path:
    return Path(os.path.expanduser(path)).resolve()


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    cleaned = cleaned.strip(".-")
    return cleaned or "xcode"


def short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def entry_path(args: argparse.Namespace) -> Path | None:
    entry = args.project or args.workspace
    return expand_path(entry) if entry else None


def project_stem(args: argparse.Namespace) -> str:
    entry = args.project or args.workspace
    if entry:
        return safe_name(Path(entry).stem)
    if args.xctestrun:
        return safe_name(Path(args.xctestrun).stem)
    return "xcode"


def stable_project_key(args: argparse.Namespace) -> str:
    return f"{project_stem(args)}-{short_hash(json.dumps(cache_identity(args), sort_keys=True))}"


def xcode_version_for_cache() -> str:
    try:
        result = subprocess.run(
            ["xcodebuild", "-version"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
        )
    except Exception:
        return "unknown"
    text = (result.stdout or result.stderr or "").strip()
    return " ".join(text.split()) or "unknown"


def cache_identity(args: argparse.Namespace) -> dict[str, Any]:
    entry = entry_path(args)
    xctestrun_path = expand_path(args.xctestrun) if args.xctestrun else None
    return {
        "optimization_profile": args.optimization_profile,
        "trusted_fast": args.optimization_profile == "trusted-fast",
        "xcode_version": xcode_version_for_cache(),
        "scheme": args.scheme,
        "configuration": args.configuration,
        "project_path_hash": short_hash(str(entry or xctestrun_path or Path.cwd())),
    }


def ensure_cache_metadata(path: Path | None, args: argparse.Namespace, *, create: bool) -> None:
    if path is None:
        return
    metadata_path = path / ".codex-xcode-cache.json"
    expected = cache_identity(args)
    if metadata_path.exists():
        try:
            current = json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raise SystemExit(f"error: cache_invalid: could not parse cache metadata at {metadata_path}")
        if current.get("trusted_fast") != expected["trusted_fast"]:
            raise SystemExit(
                f"error: cache_invalid: trusted_fast differs for cache {path}; refuse to reuse silently"
            )
    if create:
        path.mkdir(parents=True, exist_ok=True)
        write_json(metadata_path, expected)


def plist_string_values(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str):
                yield key
            yield from plist_string_values(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from plist_string_values(item)


def derived_data_leaf_mentions_entry(leaf: Path, entry: Path) -> bool:
    info_plist = leaf / "info.plist"
    if not info_plist.exists():
        return False
    try:
        with info_plist.open("rb") as handle:
            data = plistlib.load(handle)
    except Exception:
        return False
    entry_text = str(entry)
    entry_parent_text = str(entry.parent)
    for text in plist_string_values(data):
        if text == entry_text or text.startswith(entry_parent_text):
            return True
    return False


def candidate_derived_data_leaves(root: Path, stem: str) -> list[Path]:
    if not root.exists():
        return []
    try:
        children = list(root.iterdir())
    except OSError:
        return []
    prefix = f"{stem}-"
    return [
        child
        for child in children
        if child.is_dir()
        and child.name.startswith(prefix)
        and not child.name.endswith(".noindex")
        and not child.name.startswith("_codex_")
    ]


def newest_path(paths: list[Path]) -> Path | None:
    if not paths:
        return None
    return max(paths, key=lambda item: item.stat().st_mtime)


def stable_fallback_leaf(root: Path, args: argparse.Namespace) -> Path:
    return root / f"{stable_project_key(args)}-codex-cli"


def resolve_derived_data_path(args: argparse.Namespace, create: bool) -> Path | None:
    if args.xctestrun and not args.auto_xctestrun:
        return None
    if args.derived_data_path:
        path = expand_path(args.derived_data_path)
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    root = expand_path(args.derived_data_root)
    if create:
        root.mkdir(parents=True, exist_ok=True)

    fallback = stable_fallback_leaf(root, args)
    if args.derived_data_cache_strategy == "stable":
        if create:
            fallback.mkdir(parents=True, exist_ok=True)
        return fallback

    stem = project_stem(args)
    candidates = candidate_derived_data_leaves(root, stem)
    if args.derived_data_cache_strategy == "metadata":
        current_entry = entry_path(args)
        if current_entry is not None:
            metadata_matches = [leaf for leaf in candidates if derived_data_leaf_mentions_entry(leaf, current_entry)]
            match = newest_path(metadata_matches)
            if match is not None:
                return match

    match = newest_path(candidates)
    if match is not None and args.derived_data_cache_strategy == "newest":
        return match
    if match is not None and args.derived_data_cache_strategy == "metadata":
        return match

    if create:
        fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def shared_root(args: argparse.Namespace) -> Path:
    return expand_path(args.derived_data_root) / "_codex_cli_shared"


def resolve_source_packages_path(args: argparse.Namespace, derived_data_path: Path | None, create: bool) -> Path | None:
    if args.xctestrun or (args.auto_xctestrun and args.action == "test-without-building"):
        return None
    if args.cloned_source_packages_dir_path:
        path = expand_path(args.cloned_source_packages_dir_path)
    elif args.source_packages_mode == "none":
        return None
    elif args.source_packages_mode == "derived-data":
        if derived_data_path is None:
            return None
        path = derived_data_path / "SourcePackages"
    else:
        path = shared_root(args) / "SourcePackages" / stable_project_key(args)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_package_cache_path(args: argparse.Namespace, create: bool) -> Path | None:
    if args.xctestrun or (args.auto_xctestrun and args.action == "test-without-building"):
        return None
    if args.package_cache_path:
        path = expand_path(args.package_cache_path)
    elif args.use_shared_package_cache:
        path = shared_root(args) / "PackageCache"
    else:
        return None
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def profile_wants_fast_index(args: argparse.Namespace) -> bool:
    return args.optimization_profile in {"fast", "trusted-fast"}


def should_disable_index_store(args: argparse.Namespace) -> bool:
    if args.keep_index_store:
        return False
    return args.disable_index_store or profile_wants_fast_index(args)


def resolved_spm_mode(args: argparse.Namespace) -> str:
    if args.spm_resolution != "profile":
        return args.spm_resolution
    if args.optimization_profile in {"fast", "trusted-fast"}:
        return "locked"
    if args.optimization_profile == "balanced":
        return "skip-updates"
    return "auto"


def resolved_parallelize_targets(args: argparse.Namespace) -> bool:
    if args.parallelize_targets is not None:
        return bool(args.parallelize_targets)
    return args.optimization_profile in {"balanced", "fast", "trusted-fast", "diagnostic"}


def auto_jobs() -> int:
    env = os.environ.get("XCODE_CLI_BUILD_JOBS")
    if env:
        try:
            value = int(env)
            if value > 0:
                return value
        except ValueError:
            pass
    count = os.cpu_count() or 4
    return max(2, min(count, 12))


def resolved_jobs(args: argparse.Namespace) -> int | None:
    if args.jobs == "none":
        return None
    if args.jobs == "auto":
        return auto_jobs()
    if args.jobs == "profile":
        if args.optimization_profile in {"fast", "trusted-fast"}:
            return auto_jobs()
        return None
    return int(args.jobs)


def is_test_action(action: str) -> bool:
    return action in {"test", "test-without-building"}


def is_build_action(action: str) -> bool:
    return action in {"build", "build-for-testing"}


def is_simulator_destination(args: argparse.Namespace) -> bool:
    return any("simulator" in item.lower() for item in args.destination) or bool(args.sdk and "simulator" in args.sdk.lower())


def should_disable_concurrent_destination_testing(args: argparse.Namespace) -> bool:
    if args.disable_concurrent_destination_testing is not None:
        return bool(args.disable_concurrent_destination_testing)
    return args.optimization_profile in {"fast", "trusted-fast"} and is_test_action(args.action) and len(args.destination) <= 1


def should_preboot_simulator(args: argparse.Namespace) -> bool:
    if args.preboot_simulator is not None:
        return bool(args.preboot_simulator)
    return args.optimization_profile in {"fast", "trusted-fast"} and is_test_action(args.action) and is_simulator_destination(args)


def should_skip_package_plugin_validation(args: argparse.Namespace) -> bool:
    if args.skip_package_plugin_validation is not None:
        return bool(args.skip_package_plugin_validation)
    return args.optimization_profile == "trusted-fast"


def should_skip_macro_validation(args: argparse.Namespace) -> bool:
    if args.skip_macro_validation is not None:
        return bool(args.skip_macro_validation)
    return args.optimization_profile == "trusted-fast"


def supports_xcodebuild_flag(flag: str) -> bool:
    xcodebuild = shutil.which("xcodebuild")
    if xcodebuild is None:
        return False
    try:
        completed = subprocess.run(
            [xcodebuild, "-help"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=20,
            check=False,
        )
    except Exception:
        return False
    return flag in completed.stdout


def append_optional_supported_flag(command: list[str], flag: str, args: argparse.Namespace, notes: list[str]) -> None:
    if supports_xcodebuild_flag(flag):
        command.append(flag)
    elif args.strict_xcodebuild_flag_detection:
        raise SystemExit(f"error: xcodebuild does not report support for {flag}")
    else:
        notes.append(f"Skipped unsupported optional flag {flag}")


def find_auto_xctestrun(derived_data_path: Path | None, args: argparse.Namespace) -> Path | None:
    if derived_data_path is None:
        return None
    products = derived_data_path / "Build" / "Products"
    if not products.exists():
        return None
    candidates = list(products.glob("*.xctestrun"))
    if not candidates:
        return None
    scheme = safe_name(args.scheme or "")
    test_plan = safe_name(args.test_plan or "")

    def score(path: Path) -> tuple[int, float]:
        name = path.name.lower()
        value = 0
        if scheme and scheme.lower() in name:
            value += 2
        if test_plan and test_plan.lower() in name:
            value += 3
        return (value, path.stat().st_mtime)

    return max(candidates, key=score)


def destination_parts(destination: str) -> dict[str, str]:
    parts: dict[str, str] = {}
    for item in destination.split(","):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        parts[key.strip().lower()] = value.strip()
    return parts


def simulator_id_from_destination(destination: str) -> str | None:
    parts = destination_parts(destination)
    device_id = parts.get("id")
    if device_id:
        return device_id
    return None


def preboot_simulator_if_requested(args: argparse.Namespace) -> None:
    if not should_preboot_simulator(args):
        return
    if len(args.destination) != 1:
        print("note: skipping simulator preboot because multiple destinations were supplied", file=sys.stderr)
        return
    destination = args.destination[0]
    if "simulator" not in destination.lower():
        return
    device_id = simulator_id_from_destination(destination)
    if not device_id:
        print("note: simulator preboot works best with destination id=<UUID>; skipping preboot", file=sys.stderr)
        return
    if shutil.which("xcrun") is None:
        print("note: xcrun not found; skipping simulator preboot", file=sys.stderr)
        return
    print(f"Preboot simulator: {device_id}", file=sys.stderr)
    subprocess.run(["xcrun", "simctl", "boot", device_id], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    try:
        subprocess.run(
            ["xcrun", "simctl", "bootstatus", device_id, "-b"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=args.preboot_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print(f"note: simulator bootstatus timed out after {args.preboot_timeout}s; continuing", file=sys.stderr)


def build_command(args: argparse.Namespace, derived_data_path: Path | None, source_packages_path: Path | None, package_cache_path: Path | None, xctestrun_path: Path | None) -> tuple[list[str], list[str]]:
    command = ["xcodebuild"]
    notes: list[str] = []
    using_xctestrun = bool(args.xctestrun or xctestrun_path)

    if using_xctestrun:
        command.extend(["-xctestrun", str(xctestrun_path or expand_path(args.xctestrun))])
    else:
        if args.project:
            command.extend(["-project", args.project])
        elif args.workspace:
            command.extend(["-workspace", args.workspace])
        if args.scheme:
            command.extend(["-scheme", args.scheme])

    if args.configuration:
        command.extend(["-configuration", args.configuration])
    if args.sdk:
        command.extend(["-sdk", args.sdk])
    for destination in args.destination:
        command.extend(["-destination", destination])
    if args.destination_timeout:
        command.extend(["-destination-timeout", args.destination_timeout])

    if not args.verbose and args.optimization_profile != "diagnostic":
        command.append("-quiet")
    if not args.keep_shell_script_environment:
        command.append("-hideShellScriptEnvironment")
    if args.show_build_timing_summary or args.optimization_profile == "diagnostic":
        command.append("-showBuildTimingSummary")

    if args.clear_xcode_custom_build_location_overrides and not using_xctestrun:
        command.extend(["-IDECustomBuildProductsPath=", "-IDECustomBuildIntermediatesPath="])

    if derived_data_path is not None and not using_xctestrun:
        command.extend(["-derivedDataPath", str(derived_data_path)])
    if source_packages_path is not None:
        command.extend(["-clonedSourcePackagesDirPath", str(source_packages_path)])

    if package_cache_path is not None:
        append_optional_supported_flag(command, "-packageCachePath", args, notes)
        if command and command[-1] == "-packageCachePath":
            command.append(str(package_cache_path))

    if args.result_bundle_path:
        command.extend(["-resultBundlePath", args.result_bundle_path])
    if args.test_plan and not (using_xctestrun):
        command.extend(["-testPlan", args.test_plan])

    if resolved_parallelize_targets(args) and not using_xctestrun:
        command.append("-parallelizeTargets")
    jobs = resolved_jobs(args)
    if jobs is not None and not using_xctestrun:
        command.extend(["-jobs", str(jobs)])
        notes.append(f"Using -jobs {jobs}")

    spm_mode = resolved_spm_mode(args)
    if spm_mode in {"skip-updates", "locked"} and not using_xctestrun:
        command.append("-skipPackageUpdates")
    if spm_mode == "locked" and not using_xctestrun:
        command.append("-disableAutomaticPackageResolution")
    if args.scm_provider != "auto" and not using_xctestrun:
        command.extend(["-scmProvider", args.scm_provider])
    if args.disable_package_repository_cache and not using_xctestrun:
        command.append("-disablePackageRepositoryCache")

    if should_disable_concurrent_destination_testing(args):
        command.append("-disable-concurrent-destination-testing")
    if should_skip_package_plugin_validation(args) and not using_xctestrun:
        append_optional_supported_flag(command, "-skipPackagePluginValidation", args, notes)
    if should_skip_macro_validation(args) and not using_xctestrun:
        append_optional_supported_flag(command, "-skipMacroValidation", args, notes)

    for item in args.only_testing:
        command.append(f"-only-testing:{item}")
    for item in args.skip_testing:
        command.append(f"-skip-testing:{item}")

    command.extend(args.extra_arg)
    command.extend(args.passthrough_args)

    if should_disable_index_store(args) and not using_xctestrun:
        command.append("COMPILER_INDEX_STORE_ENABLE=NO")
    if (
        is_simulator_destination(args)
        and (is_build_action(args.action) or is_test_action(args.action))
        and not args.keep_signing
        and not using_xctestrun
    ):
        command.append("CODE_SIGNING_ALLOWED=NO")

    command.extend(args.build_setting)
    command.append(args.action)

    return command, notes


def make_plan(args: argparse.Namespace, create_dirs: bool) -> ResolvedPlan:
    derived_data_path = resolve_derived_data_path(args, create=create_dirs)
    source_packages_path = resolve_source_packages_path(args, derived_data_path, create=create_dirs)
    package_cache_path = resolve_package_cache_path(args, create=create_dirs)
    ensure_cache_metadata(derived_data_path, args, create=create_dirs)
    ensure_cache_metadata(source_packages_path, args, create=create_dirs)
    ensure_cache_metadata(package_cache_path, args, create=create_dirs)
    xctestrun_path = None
    if args.xctestrun:
        xctestrun_path = expand_path(args.xctestrun)
    elif args.auto_xctestrun:
        xctestrun_path = find_auto_xctestrun(derived_data_path, args)
        if xctestrun_path is None and not args.dry_run:
            raise SystemExit("error: --auto-xctestrun requested, but no .xctestrun file was found under DerivedData/Build/Products")
    command, notes = build_command(args, derived_data_path, source_packages_path, package_cache_path, xctestrun_path)
    return ResolvedPlan(
        derived_data_path=derived_data_path,
        source_packages_path=source_packages_path,
        package_cache_path=package_cache_path,
        xctestrun_path=xctestrun_path,
        command=command,
        optimization_notes=notes,
    )


def shell_join(parts: list[str]) -> str:
    return shlex.join(parts)


def claim_type_for_action(action: str) -> str | None:
    if action in {"build", "build-for-testing"}:
        return "build"
    if action in {"test", "test-without-building"}:
        return "test"
    return None


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def stream_pipe(pipe: Any, destination: Any, log_handle: Any | None) -> None:
    try:
        for chunk in iter(lambda: pipe.readline(), ""):
            if not chunk:
                break
            destination.write(chunk)
            destination.flush()
            if log_handle is not None:
                log_handle.write(chunk)
                log_handle.flush()
    finally:
        try:
            pipe.close()
        except Exception:
            pass


def run_command_streaming(command: list[str], stdout_log: Path | None, stderr_log: Path | None, timeout_seconds: int | None) -> tuple[int, float, bool]:
    start = time.monotonic()
    stdout_handle = stdout_log.open("w", encoding="utf-8") if stdout_log else None
    stderr_handle = stderr_log.open("w", encoding="utf-8") if stderr_log else None
    timed_out = False
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
    except FileNotFoundError:
        message = "error: xcodebuild was not found. Run this skill on macOS with Xcode command line tools installed.\n"
        sys.stderr.write(message)
        if stderr_handle is not None:
            stderr_handle.write(message)
        if stdout_handle is not None:
            stdout_handle.close()
        if stderr_handle is not None:
            stderr_handle.close()
        return 127, time.monotonic() - start, False

    assert process.stdout is not None
    assert process.stderr is not None
    stdout_thread = threading.Thread(target=stream_pipe, args=(process.stdout, sys.stdout, stdout_handle), daemon=True)
    stderr_thread = threading.Thread(target=stream_pipe, args=(process.stderr, sys.stderr, stderr_handle), daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    try:
        return_code = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        except Exception:
            process.terminate()
        try:
            return_code = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            except Exception:
                process.kill()
            return_code = process.wait()
    stdout_thread.join(timeout=5)
    stderr_thread.join(timeout=5)
    if stdout_handle is not None:
        stdout_handle.close()
    if stderr_handle is not None:
        stderr_handle.close()
    return return_code, time.monotonic() - start, timed_out


def print_plan(plan: ResolvedPlan) -> None:
    if plan.derived_data_path is not None:
        print(f"DerivedData: {plan.derived_data_path}", file=sys.stderr)
    if plan.source_packages_path is not None:
        print(f"SourcePackages: {plan.source_packages_path}", file=sys.stderr)
    if plan.package_cache_path is not None:
        print(f"PackageCache: {plan.package_cache_path}", file=sys.stderr)
    if plan.xctestrun_path is not None:
        print(f"XCTestRun: {plan.xctestrun_path}", file=sys.stderr)
    for note in plan.optimization_notes:
        print(f"note: {note}", file=sys.stderr)
    print(f"Command: {shell_join(plan.command)}", file=sys.stderr)


def plan_as_json(args: argparse.Namespace, plan: ResolvedPlan) -> dict[str, Any]:
    return {
        "action": args.action,
        "optimization_profile": args.optimization_profile,
        "security": {
            "trusted_fast": args.optimization_profile == "trusted-fast",
            "trust_reason": args.trust_reason if args.optimization_profile == "trusted-fast" else None,
            "skips_package_plugin_validation": should_skip_package_plugin_validation(args),
            "skips_macro_validation": should_skip_macro_validation(args),
        },
        "spm_resolution": resolved_spm_mode(args),
        "derived_data_path": str(plan.derived_data_path) if plan.derived_data_path else None,
        "source_packages_path": str(plan.source_packages_path) if plan.source_packages_path else None,
        "package_cache_path": str(plan.package_cache_path) if plan.package_cache_path else None,
        "xctestrun_path": str(plan.xctestrun_path) if plan.xctestrun_path else None,
        "command": plan.command,
        "shell_command": shell_join(plan.command),
        "optimization_notes": plan.optimization_notes,
    }


def main() -> int:
    args = parse_args()
    try:
        validate_args(args)
    except SystemExit as exc:
        message = str(exc)
        if "trusted_fast_denied" in message:
            print(message, file=sys.stderr)
            return 5
        raise

    session_dir = None
    command_log_paths: tuple[Path, Path, Path] | None = None
    if args.policy_session_id or args.policy_session_dir:
        add_policy_path()
        from policy_session import (  # type: ignore
            command_capture_paths,
            ensure_policy_session,
            infer_session_id,
            resolve_session_dir,
        )

        raw_session_dir = Path(args.policy_session_dir).expanduser() if args.policy_session_dir else None
        session_id = infer_session_id(args.policy_session_id, raw_session_dir)
        if args.policy_init_if_missing:
            session_dir = ensure_policy_session(
                session_id=session_id,
                session_dir=raw_session_dir,
                task_text=args.policy_task_text,
                cwd=str(Path.cwd()),
            )
        else:
            session_dir = resolve_session_dir(
                session_id=session_id,
                session_dir=raw_session_dir,
                create=False,
            )
        command_log_paths = command_capture_paths(session_dir, args.action)

    try:
        plan = make_plan(args, create_dirs=not args.dry_run)
    except SystemExit as exc:
        message = str(exc)
        if "cache_invalid" in message:
            print(message, file=sys.stderr)
            return 50
        raise
    print_plan(plan)

    if args.dry_run:
        if args.json_dry_run:
            print(json.dumps(plan_as_json(args, plan), indent=2, sort_keys=True))
        return 0

    preboot_simulator_if_requested(args)

    stdout_log = command_log_paths[0] if command_log_paths else None
    stderr_log = command_log_paths[1] if command_log_paths else None
    summary_log = command_log_paths[2] if command_log_paths else None
    return_code, elapsed_seconds, timed_out = run_command_streaming(
        plan.command,
        stdout_log=stdout_log,
        stderr_log=stderr_log,
        timeout_seconds=args.timeout_seconds,
    )
    if timed_out:
        print(f"error: xcodebuild timed out after {args.timeout_seconds}s", file=sys.stderr)
        if return_code == 0:
            return_code = 124
    print(f"Elapsed: {elapsed_seconds:.1f}s", file=sys.stderr)

    if session_dir is not None and command_log_paths is not None and summary_log is not None:
        from policy_session import (  # type: ignore
            append_evidence_record,
            collect_verification_observation,
            latest_verification_observation,
            promote_verification_observation,
            record_artifact_generated,
        )

        result_bundle = expand_path(args.result_bundle_path) if args.result_bundle_path else None
        result_bundle_exists = bool(result_bundle and result_bundle.exists())
        claim_type = claim_type_for_action(args.action)
        summary = {
            "action": args.action,
            "command": shell_join(plan.command),
            "derived_data_path": str(plan.derived_data_path) if plan.derived_data_path else None,
            "source_packages_path": str(plan.source_packages_path) if plan.source_packages_path else None,
            "package_cache_path": str(plan.package_cache_path) if plan.package_cache_path else None,
            "xctestrun_path": str(plan.xctestrun_path) if plan.xctestrun_path else None,
            "exit_code": return_code,
            "elapsed_seconds": elapsed_seconds,
            "timed_out": timed_out,
            "outcome": "success" if return_code == 0 else "failure",
            "result_bundle_path": str(result_bundle) if result_bundle else None,
            "result_bundle_exists": result_bundle_exists,
            "stdout_log": command_log_paths[0].as_posix(),
            "stderr_log": command_log_paths[1].as_posix(),
            "optimization_profile": args.optimization_profile,
            "spm_resolution": resolved_spm_mode(args),
            "optimization_notes": plan.optimization_notes,
        }
        record = append_evidence_record(
            session_dir,
            record_type="command_run",
            phase="work_executed_or_analysis_completed",
            command=shell_join(plan.command),
            metadata={**summary, "target": str(Path.cwd())},
        )
        summary["record"] = record
        write_json(summary_log, summary)

        if claim_type is not None:
            artifact_paths = [result_bundle.as_posix()] if result_bundle_exists and result_bundle is not None else []
            command_observation = collect_verification_observation(
                session_dir,
                claim_type=claim_type,
                collector="command_exit",
                scope=str(Path.cwd()),
                target=str(Path.cwd()),
                source_paths=[summary_log.as_posix()],
                source_evidence_refs=[f"command_run:{args.action}"],
                artifact_paths=artifact_paths,
                status_hint="success" if return_code == 0 else "failure",
            )
            if result_bundle_exists and result_bundle is not None:
                record_artifact_generated(
                    session_dir,
                    files=[result_bundle.as_posix()],
                    action=args.action,
                    metadata={"source": "xcode-cli-shared-cache-build"},
                )
                collect_verification_observation(
                    session_dir,
                    claim_type=claim_type,
                    collector="xcresult_summary",
                    scope=str(Path.cwd()),
                    target=result_bundle.as_posix(),
                    source_paths=[result_bundle.as_posix()],
                    source_evidence_refs=[
                        f"observation:{command_observation['observation']['observation_id']}",
                        f"command_run:{args.action}",
                    ],
                    artifact_paths=[result_bundle.as_posix()],
                    status_hint="success" if return_code == 0 else "failure",
                )
            preferred_observation = None
            if result_bundle_exists:
                xcresult_observation = latest_verification_observation(
                    session_dir,
                    claim_type=claim_type,
                    collector="xcresult_summary",
                )
                metadata = (
                    xcresult_observation.get("metadata", {})
                    if isinstance(xcresult_observation, dict) and isinstance(xcresult_observation.get("metadata"), dict)
                    else {}
                )
                if metadata.get("status_hint") in {"success", "failure", "skipped"}:
                    preferred_observation = xcresult_observation
            if preferred_observation is None:
                preferred_observation = latest_verification_observation(
                    session_dir,
                    claim_type=claim_type,
                    collector="command_exit",
                ) or latest_verification_observation(session_dir, claim_type=claim_type)
            if preferred_observation is not None:
                promote_verification_observation(
                    session_dir,
                    claim_type=claim_type,
                    observation=preferred_observation,
                    scope=str(Path.cwd()),
                )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
