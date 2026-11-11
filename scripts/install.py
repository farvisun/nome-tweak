#!/usr/bin/python3
"""Install or remove Desktop Studio for one user, without elevated privileges."""
import argparse
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

APP_ID = "io.github.desktopstudio.DesktopStudio"
ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, default=Path.home() / ".local")
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()
    prefix = args.prefix.expanduser().resolve()
    appdir = prefix / "lib/desktop-studio"
    binary = prefix / "bin/desktop-studio"
    desktop = prefix / f"share/applications/{APP_ID}.desktop"
    icon = prefix / f"share/icons/hicolor/scalable/apps/{APP_ID}.svg"
    if args.uninstall:
        if appdir.exists() and not (appdir / ".desktop-studio-install").is_file():
            parser.error(f"Refusing to remove an unrecognized directory: {appdir}")
        for path in (binary, desktop, icon):
            path.unlink(missing_ok=True)
        if appdir.exists():
            shutil.rmtree(appdir)
        print("Desktop Studio removed. Your profiles, backups, logs, and GNOME settings were preserved.")
    else:
        if appdir.exists() and not (appdir / ".desktop-studio-install").exists():
            parser.error(f"An unrelated directory exists at {appdir}")
        if binary.exists() and "Desktop Studio" not in binary.read_text(errors="replace"):
            parser.error(f"An unrelated launcher exists at {binary}")
        appdir.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="desktop-studio-install-", dir=appdir.parent) as tmp:
            stage = Path(tmp) / "app"
            stage.mkdir()
            shutil.copytree(ROOT / "desktop_studio", stage / "desktop_studio", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            shutil.copytree(ROOT / "data", stage / "data")
            for name in ("README.md", "LICENSE"):
                shutil.copy2(ROOT / name, stage / name)
            (stage / ".desktop-studio-install").write_text("Desktop Studio 1\n")
            # The installed directory contains only application files, never
            # user settings. Preserve a previous installation until staging ends.
            previous = appdir.with_name("desktop-studio.previous")
            if previous.exists():
                shutil.rmtree(previous)
            if appdir.exists():
                appdir.rename(previous)
            try:
                stage.rename(appdir)
            except Exception:
                if previous.exists(): previous.rename(appdir)
                raise
            if previous.exists(): shutil.rmtree(previous)
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_text("#!/usr/bin/python3\n# Desktop Studio user launcher\nimport sys\nsys.path.insert(0, " + repr(str(appdir)) + ")\nfrom desktop_studio.__main__ import *\n")
        binary.chmod(0o755)
        desktop.parent.mkdir(parents=True, exist_ok=True)
        text = (ROOT / f"data/{APP_ID}.desktop").read_text()
        # Desktop Entry Exec quoting is separate from shell quoting.
        quoted = str(binary).replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$")
        desktop.write_text(text.replace("Exec=desktop-studio", f'Exec="{quoted}"'))
        icon.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / f"data/icons/hicolor/scalable/apps/{APP_ID}.svg", icon)
        print(f"Installed Desktop Studio. Launch: {binary}")
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", str(prefix / "share/applications")], check=False, capture_output=True)
    if shutil.which("gtk-update-icon-cache"):
        subprocess.run(["gtk-update-icon-cache", "-f", "-t", str(prefix / "share/icons/hicolor")], check=False, capture_output=True)


if __name__ == "__main__": main()
