# PyInstaller spec: one-folder build of MarstekMonitor.exe (design spec §10).
import re
from pathlib import Path

ROOT = Path(SPECPATH).parent

# the one version number lives in marstek_monitor/__init__.py; the exe's file properties get it from there
VERSION = re.search(r'__version__ = "([^"]+)"', (ROOT / "marstek_monitor" / "__init__.py").read_text()).group(1)
numbers = [int(x) for x in VERSION.split(".")]
version_file = ROOT / "build" / "version_info.txt"
version_file.parent.mkdir(exist_ok=True)
version_file.write_text((ROOT / "packaging" / "version_info.template.txt").read_text()
                        .replace("{vers}", str(tuple(numbers + [0] * (4 - len(numbers)))))
                        .replace("{version}", VERSION))

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "marstek_monitor" / "i18n" / "*.json"), "marstek_monitor/i18n")],
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MarstekMonitor",
    console=False,
    icon=str(ROOT / "packaging" / "icon.ico"),
    version=str(version_file),
)
coll = COLLECT(exe, a.binaries, a.datas, name="MarstekMonitor")
