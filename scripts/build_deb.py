#!/usr/bin/python3
"""Build a local Debian package without root, network access, or desktop writes."""
from pathlib import Path
import json
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
APP_ID = "io.github.desktopstudio.DesktopStudio"
sys.path.insert(0, str(ROOT))
from desktop_studio import __version__
from desktop_studio.core.versions import Version


def copy_source_directory(root, relative, destination):
    """Package tracked files; never pick up ignored credentials or local caches."""
    root, destination = Path(root), Path(destination)
    if (root / ".git").exists():
        raw = subprocess.check_output(["git", "-C", str(root), "ls-files", "-z", "--", relative])
        destination.mkdir(parents=True, exist_ok=True)
        for name in raw.decode().split("\0"):
            if not name:
                continue
            path = Path(name).relative_to(relative)
            target = destination / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / name, target, follow_symlinks=False)
    else:
        # Downloaded source archives have no Git metadata and already contain
        # the selected source. Still exclude common local credentials/caches.
        shutil.copytree(root / relative, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".env", ".env.*", "*.log"))


def build(output_dir=None, repository=None):
    version = str(Version.parse(__version__))
    dest = Path(output_dir) if output_dir else ROOT / "dist"
    dest.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="desktop-studio-deb-") as tmp:
        stage = Path(tmp)
        appdir = stage / "usr/lib/desktop-studio"
        appdir.mkdir(parents=True)
        copy_source_directory(ROOT, "desktop_studio", appdir / "desktop_studio")
        copy_source_directory(ROOT, "data", appdir / "data")
        if repository is not None:
            (appdir / "data/update-source.json").write_text(json.dumps({"version": 1, "repository": repository}, indent=2) + "\n")
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
        # The Python version is the single release version source. Debian uses
        # '~' for prerelease ordering; filenames keep the upstream SemVer.
        debian_version = version.replace("-", "~", 1)
        control.write_text(re.sub(r"(?m)^Version: .*$", "Version: " + debian_version, (ROOT / "packaging/control").read_text()))
        output = dest / f"desktop-studio_{version}_all.deb"
        # Package permissions must not inherit the developer's umask or the
        # private mode of TemporaryDirectory, especially for the archive root.
        stage.chmod(0o755)
        for path in stage.rglob("*"):
            if not path.is_symlink():
                path.chmod(0o755 if path.is_dir() else 0o644)
        binary.chmod(0o755)
        subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(stage), str(output)], check=True)
        print(output)
        return output


if __name__ == "__main__": build()
