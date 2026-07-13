from __future__ import annotations

import ast
from pathlib import Path


FORBIDDEN_EXECUTABLE_FRAGMENTS = {
    "al" + "tool",
    "--api" + "Key",
    "--api" + "Issuer",
    "-export" + "Archive",
}


def test_distribution_module_contains_no_cli_export_or_upload_execution() -> None:
    source_path = Path(__file__).parents[1] / "scripts" / "xcode_distribution.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    string_literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    joined_literals = "\n".join(string_literals)
    assert FORBIDDEN_EXECUTABLE_FRAGMENTS.isdisjoint(
        fragment for fragment in FORBIDDEN_EXECUTABLE_FRAGMENTS if fragment in joined_literals
    )

    subprocess_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
    ]
    assert len(subprocess_calls) == 1
    command_assignment = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "command" for target in node.targets)
    )
    command_source = ast.get_source_segment(source, command_assignment) or ""
    assert '"ide"' in command_source
    assert '"archive"' in command_source
