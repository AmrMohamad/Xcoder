from __future__ import annotations

from conftest import parse_json_stdout, run_xcode
from xcode_ide_menu_catalog import (
    DESTRUCTIVE,
    EXTERNAL_EFFECT,
    MENU_ACTIONS,
    MENU_ACTIONS_BY_ID,
    SAFE_VIEW,
    STATE_CHANGE,
    UNSUPPORTED_DYNAMIC,
)


CAPTURED_VISIBLE_ACTION_IDS = {
    "product.perform.run_without_building",
    "product.perform.test_without_building",
    "product.perform.profile_without_building",
    "product.perform.build_timing_summary",
    "product.perform.compile_file",
    "product.perform.analyze_file",
    "product.scheme.new",
    "product.scheme.manage",
    "product.scheme.convert_test_plans",
    "product.destination.show_all",
    "product.destination.manage",
    "product.test_plan.next",
    "product.test_plan.previous",
    "product.test_plan.edit",
    "product.test_plan.new",
    "product.test_plan.manage",
    "debug.breakpoint.enable_disable_current_line",
    "debug.breakpoint.selection",
    "debug.breakpoint.delete_column_current_line",
    "debug.breakpoint.swift_error",
    "debug.breakpoint.exception",
    "debug.breakpoint.test_failure",
    "debug.console.copy_visible_metadata",
    "debug.console.copy_all_metadata",
    "debug.console.copy_without_metadata",
    "debug.console.hide_similar.dynamic",
    "debug.console.show_similar.dynamic",
    "debug.detach.dynamic",
    "debug.simulate_background_fetch",
    "debug.simulate_metrickit_payloads",
    "debug.simulate_ui_snapshot",
    "debug.view_debugging.screenshot",
    "debug.view_debugging.show_drawing",
    "debug.view_debugging.show_responsive_scrolling",
    "debug.view_debugging.disable_overrides",
    "debug.view_debugging.rendering.color_blended_layers",
    "debug.view_debugging.rendering.color_hits_green_misses_red",
    "debug.view_debugging.rendering.color_copied_images",
    "debug.view_debugging.rendering.color_layer_formats",
    "debug.view_debugging.rendering.color_immediately",
    "debug.view_debugging.rendering.color_misaligned_images",
    "debug.view_debugging.rendering.color_offscreen_rendered_yellow",
    "debug.view_debugging.rendering.color_compositing_fast_path_blue",
    "debug.view_debugging.rendering.flash_updated_regions",
    "debug.view_debugging.appearance.system",
    "debug.view_debugging.appearance.light",
    "debug.view_debugging.appearance.dark",
    "debug.view_debugging.appearance.high_contrast_light",
    "debug.view_debugging.appearance.high_contrast_dark",
    "window.move_resize.top_left",
    "window.move_resize.top_right",
    "window.move_resize.bottom_left",
    "window.move_resize.bottom_right",
    "window.move_resize.left_and_right",
    "window.move_resize.right_and_left",
    "window.move_resize.top_and_bottom",
    "window.move_resize.bottom_and_top",
    "window.move_resize.quarters",
    "window.touch_bar.show",
    "window.touch_bar.first_generation",
    "window.touch_bar.second_generation",
}


def test_menu_catalog_action_ids_are_unique_and_safe_shapes() -> None:
    assert len(MENU_ACTIONS_BY_ID) == len(MENU_ACTIONS)
    for action in MENU_ACTIONS:
        assert action.action_id
        assert "." in action.action_id
        assert action.menu_path
        assert action.menu_path[0] in {"File", "Edit", "View", "Find", "Navigate", "Editor", "Product", "Debug", "Window"}
        assert action.safety in {SAFE_VIEW, STATE_CHANGE, DESTRUCTIVE, EXTERNAL_EFFECT, UNSUPPORTED_DYNAMIC}
        assert "command" not in action.as_dict()
        assert "script" not in action.as_dict()
        assert "raw" not in action.as_dict()
        assert "Panda" not in " ".join(action.menu_path)


def test_menu_catalog_covers_visible_top_level_menus_and_representative_items() -> None:
    top_level = {action.menu_path[0] for action in MENU_ACTIONS}
    assert top_level == {"File", "Edit", "View", "Find", "Navigate", "Editor", "Product", "Debug", "Window"}

    expected_ids = {
        "file.open_quickly",
        "edit.copy_file_and_line",
        "view.navigator.project",
        "view.debug_area.activate_console",
        "find.find_in_project",
        "navigate.jump_definition",
        "editor.layout.left",
        "product.build",
        "product.scheme.dynamic",
        "product.destination.dynamic",
        "debug.console.clear",
        "debug.view_debugging.capture_hierarchy",
        "window.minimize",
        "window.touch_bar.dynamic",
    }
    assert expected_ids.issubset(MENU_ACTIONS_BY_ID)
    assert CAPTURED_VISIBLE_ACTION_IDS.issubset(MENU_ACTIONS_BY_ID)


def test_menu_catalog_blocks_direct_build_test_run_menu_workflows() -> None:
    workflow_ids = {
        "product.run",
        "product.test",
        "product.profile",
        "product.analyze",
        "product.build_for.running",
        "product.build_for.testing",
        "product.build_for.profiling",
        "product.perform.run_without_building",
        "product.perform.test_without_building",
        "product.perform.profile_without_building",
        "product.perform.build_timing_summary",
        "product.perform.test",
        "product.perform.test_again",
        "product.perform.compile_file",
        "product.perform.analyze_file",
        "product.build",
        "product.stop",
    }
    for action_id in workflow_ids:
        assert MENU_ACTIONS_BY_ID[action_id].implemented is False


def test_dynamic_project_specific_actions_are_not_executable() -> None:
    dynamic_ids = {
        "product.scheme.dynamic",
        "product.destination.dynamic",
        "product.test_plan.dynamic",
        "debug.detach.dynamic",
        "debug.simulate_location.dynamic",
        "debug.console.hide_similar.dynamic",
        "debug.console.show_similar.dynamic",
        "window.dynamic_open_windows",
    }
    for action_id in dynamic_ids:
        action = MENU_ACTIONS_BY_ID[action_id]
        assert action.implemented is False
        assert action.safety == UNSUPPORTED_DYNAMIC


def test_menu_catalog_cli_returns_full_catalog() -> None:
    completed = run_xcode("ide", "menu-catalog", "--json")
    assert completed.returncode == 0, completed.stderr
    payload = parse_json_stdout(completed)
    assert payload["ok"] is True
    assert payload["summary"] == "Xcode IDE menu catalog listed"
    actions = payload["details"]["actions"]
    assert payload["details"]["menu_action_count"] == len(MENU_ACTIONS)
    assert any(action["action_id"] == "view.navigator.project" for action in actions)
    assert any(action["safety"] == DESTRUCTIVE for action in actions)


def test_menu_perform_rejects_unknown_and_blocked_actions_without_xcode() -> None:
    unknown = run_xcode("ide", "menu-perform", "--action-id", "not.real", "--json")
    assert unknown.returncode == 2
    unknown_payload = parse_json_stdout(unknown)
    assert unknown_payload["error_type"] == "usage_error"

    external = run_xcode("ide", "menu-perform", "--action-id", "file.add_package_dependencies", "--json")
    assert external.returncode != 0
    external_payload = parse_json_stdout(external)
    assert external_payload["error_type"] == "xcode_menu_action_blocked"
    assert external_payload["details"]["blocked_reason"] == EXTERNAL_EFFECT

    destructive = run_xcode("ide", "menu-perform", "--action-id", "debug.console.clear", "--json")
    assert destructive.returncode != 0
    destructive_payload = parse_json_stdout(destructive)
    assert destructive_payload["error_type"] == "xcode_menu_action_blocked"
    assert destructive_payload["details"]["blocked_reason"] == "destructive_requires_allow_destructive"

    workflow = run_xcode("ide", "menu-perform", "--action-id", "product.perform.run_without_building", "--json")
    assert workflow.returncode != 0
    workflow_payload = parse_json_stdout(workflow)
    assert workflow_payload["error_type"] == "xcode_menu_action_blocked"
    assert workflow_payload["details"]["blocked_reason"] == "not_implemented"
