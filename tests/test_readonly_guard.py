"""Fails if any string shaped like an API method name outside the allowlist appears in source."""
import ast
import re
from pathlib import Path

from marstek_monitor.api.client import ALLOWED_METHODS

PACKAGE = Path(__file__).parent.parent / "marstek_monitor"
METHOD_SHAPE = re.compile(r"^[A-Z][A-Za-z]*\.[A-Z][A-Za-z]*$")


def test_no_non_allowlisted_method_names_in_source():
    offenders = []
    for py in PACKAGE.rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and METHOD_SHAPE.match(node.value)
                and node.value not in ALLOWED_METHODS
            ):
                offenders.append(f"{py.relative_to(PACKAGE)}:{node.lineno}: {node.value}")
    assert offenders == []
