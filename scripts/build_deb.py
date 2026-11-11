#!/usr/bin/python3
"""Build a local Debian package without root, network access, or desktop writes."""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
APP_ID = "io.github.desktopstudio.DesktopStudio"


def main():
    dest = ROOT / "dist"
    dest.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="desktop-studio-deb-") as tmp:
        stage = Path(tmp)
        appdir = stage / "usr/lib/desktop-studio"
        appdir.mkdir(parents=True)
        shutil.copytree(ROOT / "desktop_studio", appdir / "desktop_studio", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copytree(ROOT / "data", appdir / "data")
        doc = stage / "usr/share/doc/desktop-studio"
        doc.mkdir(parents=True)
        shutil.copy2(ROOT / "README.md", doc / "README.md")
        shutil.copy2(ROOT / "LICENSE", doc / "copyright")
        binary = stage / "usr/bin/desktop-studio"
        binary.parent.mkdir(parents=True)
        binary.write_text("#!/usr/bin/python3\nimport sys\nsys.path.insert(0, '/usr/lib/desktop-studio')\nfrom desktop_studio.__main__ import *\n")
        binary.chmod(0o755)
        for src, target in ((ROOT / f"data/{APP_ID}.desktop", stage / f"usr/share/applications/{APP_ID}.desktop"), (ROOT / f"data/icons/hicolor/scalable/apps/{APP_ID}.svg", stage / f"usr/share/icons/hicolor/scalable/apps/{APP_ID}.svg")):
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(src, target)
        control = stage / "DEBIAN/control"
        control.parent.mkdir()
        control.write_text((ROOT / "packaging/control").read_text())
        output = dest / "desktop-studio_1.0.0_all.deb"
        subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(stage), str(output)], check=True)
        print(output)


if __name__ == "__main__": main()
