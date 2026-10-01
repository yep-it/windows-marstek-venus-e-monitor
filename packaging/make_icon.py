"""Render packaging/icon.ico (green tile with "M") with the app's own tile renderer."""
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication


def main() -> None:
    app = QApplication(sys.argv[:1])  # noqa: F841 - QPixmap needs an application object
    from marstek_monitor.ui.tray import render_tile

    out = Path(__file__).with_name("icon.ico")
    if not render_tile("M", "#2ea043", 256).toImage().save(str(out), "ICO"):
        raise SystemExit("Could not write icon.ico (Qt ICO image plugin missing)")
    print(f"written {out}")


if __name__ == "__main__":
    main()
