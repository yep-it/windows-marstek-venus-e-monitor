"""Start menu shortcut (spec §10.1), created with PowerShell's WScript.Shell (no extra dependency)."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)
CREATE_NO_WINDOW = 0x08000000


def shortcut_path() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Marstek Monitor.lnk"


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def create_shortcut(lnk: Path, target: Path, working_dir: Path) -> bool:
    lnk.parent.mkdir(parents=True, exist_ok=True)
    script = (
        f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({_ps_quote(str(lnk))}); "
        f"$s.TargetPath = {_ps_quote(str(target))}; "
        f"$s.WorkingDirectory = {_ps_quote(str(working_dir))}; "
        "$s.Save()"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, creationflags=CREATE_NO_WINDOW, timeout=30,
    )
    if result.returncode != 0:
        log.warning("Creating the Start menu shortcut failed: %s", result.stderr.strip())
    return result.returncode == 0 and lnk.exists()


def remove_shortcut(lnk: Path) -> None:
    lnk.unlink(missing_ok=True)


def sync(enabled: bool) -> None:
    """Create or remove the Start menu shortcut. Only the packaged exe gets one."""
    if not getattr(sys, "frozen", False):
        return
    lnk = shortcut_path()
    exe = Path(sys.executable)
    if enabled and not lnk.exists():
        create_shortcut(lnk, exe, exe.parent)
    elif not enabled and lnk.exists():
        remove_shortcut(lnk)
