"""Every i18n key that appears as a string literal in the source exists in en.json."""
import ast
import json
from pathlib import Path

from marstek_monitor import i18n

PACKAGE = Path(i18n.__file__).parent.parent
EN = json.loads((Path(i18n.__file__).parent / "en.json").read_text(encoding="utf-8"))
PREFIXES = ("app.", "tray.", "tab.", "state.", "now.", "est.", "grid.", "banner.", "details.", "tile.", "footer.",
            "sess.", "sessions.", "tip.", "tg.", "day.", "dur.", "unit.", "num.", "n.", "sys.", "energy.",
            "month.", "live.", "events.", "settings.", "col.", "group.", "rule.", "badge.", "priority.",
            "theme.", "power.")
FILE_SUFFIXES = (".json", ".db", ".log", ".jsonl", ".lnk", ".exe", ".tmp")


def referenced_keys():
    for py in PACKAGE.rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        # fragments of f-strings (e.g. f"settings.broken-{ts}.json") are not i18n keys
        fragments = {id(part) for node in ast.walk(tree) if isinstance(node, ast.JoinedStr) for part in node.values}
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in fragments:
                value = node.value
                if value.startswith(PREFIXES) and " " not in value and not value.endswith(FILE_SUFFIXES):
                    yield f"{py.relative_to(PACKAGE)}", value


def test_all_referenced_keys_exist():
    missing = sorted({f"{where}: {key}" for where, key in referenced_keys() if key not in EN})
    assert missing == []
