from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import run_xcode_cli_build as runner
from xcode_cache_identity import write_cache_metadata_atomic


def args_for(tmp_path: Path, project: Path, strategy: str = "metadata") -> SimpleNamespace:
    return SimpleNamespace(
        xctestrun=None,
        auto_xctestrun=False,
        derived_data_path=None,
        derived_data_root=str(tmp_path / "DerivedData"),
        derived_data_cache_strategy=strategy,
        project=str(project),
        workspace=None,
    )


def test_metadata_reuses_only_exact_identity(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "App.xcodeproj"
    project.mkdir()
    root = tmp_path / "DerivedData"
    exact = root / "App-exact"
    wrong = root / "App-wrong"
    exact.mkdir(parents=True)
    wrong.mkdir(parents=True)
    expected = {"schema_version": "xcoder.cache.identity.v2", "hard": "expected"}
    write_cache_metadata_atomic(exact, expected)
    write_cache_metadata_atomic(wrong, {**expected, "hard": "wrong"})
    monkeypatch.setattr(runner, "cache_identity", lambda _: expected)

    assert runner.resolve_derived_data_path(args_for(tmp_path, project), create=False) == exact


def test_metadata_never_falls_back_to_wrong_same_stem(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "App.xcodeproj"
    project.mkdir()
    root = tmp_path / "DerivedData"
    wrong = root / "App-newest"
    wrong.mkdir(parents=True)
    expected = {"schema_version": "xcoder.cache.identity.v2", "hard": "expected"}
    write_cache_metadata_atomic(wrong, {**expected, "hard": "wrong"})
    monkeypatch.setattr(runner, "cache_identity", lambda _: expected)
    monkeypatch.setattr(runner, "stable_project_key", lambda _: "App-v2")

    assert runner.resolve_derived_data_path(args_for(tmp_path, project), create=False) == root / "App-v2-codex-cli"


def test_legacy_metadata_is_ignored_without_rewrite(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "App.xcodeproj"
    project.mkdir()
    root = tmp_path / "DerivedData"
    legacy = root / "App-legacy"
    legacy.mkdir(parents=True)
    metadata = legacy / ".codex-xcode-cache.json"
    metadata.write_text('{"trusted_fast":false}\n', encoding="utf-8")
    expected = {"schema_version": "xcoder.cache.identity.v2", "hard": "expected"}
    monkeypatch.setattr(runner, "cache_identity", lambda _: expected)
    monkeypatch.setattr(runner, "stable_project_key", lambda _: "App-v2")
    arguments = args_for(tmp_path, project)

    assert runner.resolve_derived_data_path(arguments, create=False) == root / "App-v2-codex-cli"
    assert metadata.read_text(encoding="utf-8") == '{"trusted_fast":false}\n'
    assert any("legacy_cache_ignored" in warning for warning in arguments._cache_warnings)


def test_newest_is_explicit_and_warned(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "App.xcodeproj"
    project.mkdir()
    newest = tmp_path / "DerivedData" / "App-newest"
    newest.mkdir(parents=True)
    monkeypatch.setattr(runner, "cache_identity", lambda _: {"schema_version": "xcoder.cache.identity.v2"})
    arguments = args_for(tmp_path, project, strategy="newest")

    assert runner.resolve_derived_data_path(arguments, create=False) == newest
    assert any("unsafe_legacy_cache_selection" in warning for warning in arguments._cache_warnings)
