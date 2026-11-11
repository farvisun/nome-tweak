#!/usr/bin/python3
"""Build version-matched Debian and user-install packages for GitHub Releases."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from desktop_studio import __version__
from desktop_studio.core.versions import Version
from desktop_studio.platform.updates import normalize_repository, shipped_repository
from build_deb import build as build_deb, copy_source_directory

SOURCES = ("desktop_studio", "data", "scripts", "packaging", "po", "tests", "README.md", "LICENSE", "Makefile", ".gitignore", ".github")


def verify_tag(tag, root=ROOT):
    version = Version.parse(__version__)
    if version.prerelease or version.build or tag != "v" + str(version):
        raise ValueError("A stable release tag must exactly match v" + str(version))
    root = Path(root)
    def git(*args):
        return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()
    if git("status", "--porcelain"):
        raise ValueError("Commit all source changes before building a tagged release")
    if git("rev-parse", tag + "^{commit}") != git("rev-parse", "HEAD"):
        raise ValueError("The release tag must point to the checked-out commit")


def build_user_archive(destination, repository, root=ROOT, version=__version__):
    root, destination = Path(root), Path(destination)
    repository = normalize_repository(repository)
    version = str(Version.parse(version))
    if not repository:
        raise ValueError("A release needs a configured GitHub repository")
    destination.mkdir(parents=True, exist_ok=True)
    name = f"desktop-studio-{version}"
    output = destination / (name + "-linux.tar.gz")
    with tempfile.TemporaryDirectory(prefix="desktop-studio-release-") as tmp:
        stage = Path(tmp) / name
        stage.mkdir()
        for entry in SOURCES:
            source = root / entry
            if source.is_dir():
                copy_source_directory(root, entry, stage / entry)
            elif source.is_file():
                shutil.copy2(source, stage / entry)
        data = stage / "data"
        data.mkdir(exist_ok=True)
        (data / "update-source.json").write_text(json.dumps({"version": 1, "repository": repository}, indent=2) + "\n")
        with tarfile.open(output, "w:gz") as archive:
            archive.add(stage, arcname=name)
    return output


def write_checksums(paths, destination):
    lines = []
    for path in paths:
        path = Path(path)
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        lines.append(digest.hexdigest() + "  " + path.name)
    output = Path(destination) / "SHA256SUMS"
    output.write_text("\n".join(lines) + "\n")
    return output


def build_release(destination=None, repository=None, tag=None):
    repository = normalize_repository(repository or os.environ.get("GITHUB_REPOSITORY") or shipped_repository())
    if not repository:
        raise ValueError("Configure data/update-source.json or pass --repository OWNER/REPO")
    if tag:
        verify_tag(tag)
    destination = Path(destination) if destination else ROOT / "dist"
    deb = build_deb(destination, repository)
    archive = build_user_archive(destination, repository)
    checksums = write_checksums([deb, archive], destination)
    return [deb, archive, checksums]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", help="GitHub owner/repository (defaults to the configured source or GITHUB_REPOSITORY)")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--tag", help="Require a clean checkout at this matching stable version tag")
    args = parser.parse_args()
    try:
        for path in build_release(args.output_dir, args.repository, args.tag):
            print(path)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
