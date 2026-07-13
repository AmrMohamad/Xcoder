from __future__ import annotations

import json
import threading
from pathlib import Path

from xcode_cache_identity import (
    CACHE_IDENTITY_SCHEMA,
    build_cache_identity,
    compare_cache_identity,
    identities_compatible,
    read_cache_metadata,
    write_cache_metadata_atomic,
)


TOOLCHAIN = {
    "developer_dir_hash": "sha256:developer",
    "xcode_version": "Xcode 26.5 Build version 17F42",
    "xcode_build": "17F42",
    "sdk": "iphonesimulator",
    "sdk_version": "26.5",
}


def make_project(root: Path, name: str = "App") -> Path:
    project = root / f"{name}.xcodeproj"
    project.mkdir(parents=True)
    (project / "project.pbxproj").write_text("PBX graph\n", encoding="utf-8")
    (root / "Package.resolved").write_text('{"pins":[]}', encoding="utf-8")
    (root / "Debug.xcconfig").write_text("SETTING = one\n", encoding="utf-8")
    (root / "Sources").mkdir()
    (root / "Sources" / "Feature.swift").write_text("let value = 1\n", encoding="utf-8")
    return project


def identity(project: Path, **overrides: object) -> dict:
    values = {
        "entry": project,
        "container_type": "xcodeproj",
        "scheme": "App",
        "configuration": "Debug",
        "sdk": "iphonesimulator",
        "platform": "iOS Simulator",
        "architectures": ["arm64"],
        "toolchain": "default",
        "optimization_profile": "balanced",
        "trusted_fast": False,
        "skip_macro_validation": False,
        "skip_package_plugin_validation": False,
        "index_store_enabled": True,
        "xcode_version": "Xcode 26.5 Build version 17F42",
        "toolchain_identity": TOOLCHAIN,
    }
    values.update(overrides)
    return build_cache_identity(**values)


def test_identity_schema_and_private_path_hash(tmp_path: Path) -> None:
    project = make_project(tmp_path / "private-user" / "CompanySecret")
    payload = identity(project)
    encoded = json.dumps(payload)

    assert payload["schema_version"] == CACHE_IDENTITY_SCHEMA
    assert payload["project"]["basename"] == "App.xcodeproj"
    assert str(tmp_path) not in encoded
    assert "private-user" not in encoded
    assert "CompanySecret" not in encoded


def test_source_only_change_keeps_namespace_but_graph_change_misses(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    baseline = identity(project)
    (tmp_path / "Sources" / "Feature.swift").write_text("let value = 2\n", encoding="utf-8")
    assert identity(project) == baseline

    (project / "project.pbxproj").write_text("PBX graph changed\n", encoding="utf-8")
    changed = identity(project)
    assert not identities_compatible(baseline, changed)
    assert {item.key for item in compare_cache_identity(baseline, changed)} == {"project.graph_hash"}


def test_every_hard_dimension_changes_compatibility(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    baseline = identity(project)
    variations = [
        identity(project, scheme="Other"),
        identity(project, configuration="Release"),
        identity(project, architectures=["x86_64"]),
        identity(project, trusted_fast=True),
        identity(project, skip_macro_validation=True),
        identity(project, skip_package_plugin_validation=True),
        identity(project, index_store_enabled=False),
        identity(project, toolchain_identity={**TOOLCHAIN, "xcode_build": "DIFFERENT"}),
        identity(project, toolchain_identity={**TOOLCHAIN, "developer_dir_hash": "sha256:other"}),
        identity(project, toolchain_identity={**TOOLCHAIN, "sdk_version": "different"}),
    ]
    assert all(not identities_compatible(baseline, variant) for variant in variations)


def test_dependency_and_xcconfig_changes_miss(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    baseline = identity(project)
    (tmp_path / "Package.resolved").write_text('{"pins":["changed"]}', encoding="utf-8")
    package_changed = identity(project)
    assert any(item.key == "dependencies.package_resolved_hash" for item in compare_cache_identity(baseline, package_changed))

    (tmp_path / "Debug.xcconfig").write_text("SETTING = two\n", encoding="utf-8")
    config_changed = identity(project)
    assert any(item.key == "configuration.xcconfig_hash" for item in compare_cache_identity(package_changed, config_changed))


def test_symlink_hits_and_same_name_elsewhere_misses(tmp_path: Path) -> None:
    project = make_project(tmp_path / "first")
    symlink = tmp_path / "linked.xcodeproj"
    symlink.symlink_to(project)
    assert identity(symlink) == identity(project)

    other = make_project(tmp_path / "second")
    assert not identities_compatible(identity(project), identity(other))


def test_atomic_metadata_writers_leave_valid_json(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    project = make_project(tmp_path / "project")
    expected = identity(project)
    threads = [
        threading.Thread(target=write_cache_metadata_atomic, args=(cache, expected))
        for _ in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert read_cache_metadata(cache) == expected
