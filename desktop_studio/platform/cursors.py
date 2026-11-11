"""Ryoku's upstream Bibata collection, installed as per-user Xcursor data.

Downloading/installing never changes GSettings. The immutable release digest is
the one pinned by Ryoku's ryoku-cursors package. No upstream scripts are run.
"""
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import struct
import tarfile
import tempfile
import urllib.request
import uuid

from gi.repository import GLib

from ..core.settings import SettingsError

VERSION = "2.0.7"
URL = f"https://github.com/ful1e5/Bibata_Cursor/releases/download/v{VERSION}/Bibata.tar.xz"
SHA256 = "172e33c4ae415278384dcecc7d1a9b7a024266bc944bc751fd86532be1cc6251"
SOURCE = "https://github.com/Ryoku-dev/ryoku/blob/main/release/packages/ryoku-cursors/PKGBUILD"
UPSTREAM = "https://github.com/ful1e5/Bibata_Cursor"
THEMES = tuple(f"Bibata-{style}-{color}{hand}" for hand in ("", "-Right") for style in ("Modern", "Original") for color in ("Ice", "Classic", "Amber"))


def icon_roots():
    return [Path(GLib.get_user_data_dir()) / "icons", Path.home() / ".icons", *(Path(p) / "icons" for p in GLib.get_system_data_dirs())]


def theme_directory(name):
    if not name or "/" in name or name in (".", ".."):
        return None
    return next((root / name for root in icon_roots() if (root / name / "cursors").is_dir()), None)


@dataclass(frozen=True)
class CursorImage:
    width: int
    height: int
    xhot: int
    yhot: int
    pixels: bytes  # Xcursor stores premultiplied ARGB32 in little-endian order.


def read_cursor(path, size=32):
    """Read one real cursor frame for an offline, non-applying GTK preview."""
    try:
        with Path(path).open("rb") as src:
            header = src.read(16)
            if len(header) != 16 or header[:4] != b"Xcur":
                raise SettingsError("This file is not an Xcursor image")
            magic, header_size, version, count = struct.unpack("<4I", header)
            if not 16 <= header_size <= 4096 or not 1 <= count <= 4096:
                raise SettingsError("Invalid Xcursor header")
            src.seek(header_size)
            toc = src.read(count * 12)
            if len(toc) != count * 12:
                raise SettingsError("Incomplete Xcursor table")
            images = [entry for entry in struct.iter_unpack("<3I", toc) if entry[0] == 0xFFFD0002]
            if not images:
                raise SettingsError("No cursor image frames found")
            typ, nominal, position = min(images, key=lambda entry: abs(entry[1] - size))
            if position < header_size + count * 12 or position > 16 * 1024 * 1024:
                raise SettingsError("Invalid Xcursor frame offset")
            src.seek(position)
            data = src.read(36)
            if len(data) != 36:
                raise SettingsError("Incomplete Xcursor frame")
            chunk_size, chunk_type, subtype, version, width, height, xhot, yhot, delay = struct.unpack("<9I", data)
            if chunk_type != typ or subtype != nominal or not 36 <= chunk_size <= 4096 or not 1 <= width <= 512 or not 1 <= height <= 512 or xhot >= width or yhot >= height:
                raise SettingsError("Invalid Xcursor frame geometry")
            src.seek(position + chunk_size)
            pixels = src.read(width * height * 4)
            if len(pixels) != width * height * 4:
                raise SettingsError("Incomplete cursor pixels")
            return CursorImage(width, height, xhot, yhot, pixels)
    except OSError as exc:
        raise SettingsError(f"Could not read cursor image: {exc.strerror}") from exc


def cursor_image(theme, name="left_ptr", size=32):
    directory = theme_directory(theme)
    if directory is None:
        return None
    try:
        return read_cursor(directory / "cursors" / name, size)
    except SettingsError:
        return None


def digest(path):
    checksum = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            checksum.update(chunk)
    return checksum.hexdigest()


def download_collection(progress=None, cache_dir=None):
    cache = Path(cache_dir) if cache_dir else Path(GLib.get_user_cache_dir()) / "desktop-studio/cursors"
    cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination = cache / f"Bibata-{VERSION}.tar.xz"
    if destination.is_file() and digest(destination) == SHA256:
        return destination
    partial = cache / ("download-" + uuid.uuid4().hex)
    try:
        request = urllib.request.Request(URL, headers={"User-Agent": "Desktop-Studio/1.0"})
        with urllib.request.urlopen(request, timeout=30) as response, partial.open("xb") as out:
            total = int(response.headers.get("Content-Length", 0))
            downloaded = 0
            while chunk := response.read(1024 * 256):
                downloaded += len(chunk)
                if downloaded > 32 * 1024 * 1024:
                    raise SettingsError("The cursor archive exceeds its expected download size")
                out.write(chunk)
                if progress:
                    progress("download", downloaded, total)
        if digest(partial) != SHA256:
            raise SettingsError("The cursor download did not match Ryoku’s pinned SHA-256 checksum; nothing was installed")
        os.replace(partial, destination)
        return destination
    except (OSError, ValueError) as exc:
        raise SettingsError(f"Could not download the cursor collection: {exc}") from exc
    finally:
        partial.unlink(missing_ok=True)


def _members(tar):
    members = tar.getmembers()
    if len(members) > 5000 or sum(m.size for m in members) > 512 * 1024 * 1024:
        raise SettingsError("The cursor archive exceeds its expected extracted size")
    seen = set()
    selected = []
    for member in members:
        path = PurePosixPath(member.name)
        parts = path.parts
        if not parts and member.isdir():
            continue
        if path.is_absolute() or ".." in parts or not parts:
            raise SettingsError("Invalid path in cursor archive")
        if str(path) in seen:
            raise SettingsError("Duplicate path in cursor archive")
        seen.add(str(path))
        if parts == ("LICENSE",) and member.isfile():
            selected.append((member, parts)); continue
        if parts[0] not in THEMES:
            raise SettingsError("Unexpected theme in cursor archive")
        allowed = (len(parts) == 1 and member.isdir() or
                   len(parts) == 2 and parts[1] == "cursors" and member.isdir() or
                   len(parts) == 2 and parts[1] in ("index.theme", "cursor.theme") and member.isfile() or
                   len(parts) == 3 and parts[1] == "cursors" and (member.isfile() or member.issym()))
        if not allowed or member.size < 0 or member.size > 16 * 1024 * 1024:
            raise SettingsError("Unexpected file in cursor archive")
        if member.issym():
            # All upstream aliases are filenames in their own cursors folder.
            target = PurePosixPath(member.linkname)
            if len(target.parts) != 1 or target.parts[0] in (".", "..") or target.is_absolute():
                raise SettingsError("A cursor alias points outside its theme")
        selected.append((member, parts))
    return selected


def install_archive(archive, icons_dir=None, expected_digest=SHA256, progress=None):
    """Validate and stage the entire collection before publishing any new theme.

    Existing theme directories, including user-modified copies, are preserved.
    expected_digest is injectable for tests; the online installer always pins it.
    """
    archive = Path(archive)
    if archive.stat().st_size > 32 * 1024 * 1024 or digest(archive) != expected_digest:
        raise SettingsError("The cursor archive checksum is incorrect; nothing was installed")
    icons = Path(icons_dir) if icons_dir else Path(GLib.get_user_data_dir()) / "icons"
    icons.mkdir(parents=True, exist_ok=True)
    created, skipped = [], []
    with (icons / ".desktop-studio-cursor-install.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with tempfile.TemporaryDirectory(prefix=".desktop-studio-cursors-", dir=icons) as temp:
            stage = Path(temp)
            try:
                with tarfile.open(archive, "r:xz") as tar:
                    members = _members(tar)
                    required = sum(m.size for m, _parts in members)
                    if shutil.disk_usage(icons).free < required + 16 * 1024 * 1024:
                        raise SettingsError("There is not enough space to install the cursor collection")
                    for index, (member, parts) in enumerate(members):
                        dest = stage.joinpath(*parts)
                        if member.isdir():
                            dest.mkdir(parents=True, exist_ok=True)
                        elif member.isfile():
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            with tar.extractfile(member) as src, dest.open("xb") as out:
                                shutil.copyfileobj(src, out)
                            dest.chmod(0o644)
                        if progress and index % 80 == 0:
                            progress("extract", index, len(members))
                    for member, parts in members:
                        if member.issym():
                            dest = stage.joinpath(*parts)
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            dest.symlink_to(member.linkname)
                    for member, parts in members:
                        if member.issym():
                            dest = stage.joinpath(*parts)
                            try:
                                if not dest.resolve(strict=True).is_relative_to(dest.parent):
                                    raise SettingsError("A cursor alias leaves its theme directory")
                            except (OSError, RuntimeError) as exc:
                                raise SettingsError("An invalid cursor alias was found") from exc
                license_file = stage / "LICENSE"
                if not license_file.is_file() or not license_file.stat().st_size:
                    raise SettingsError("The cursor archive is missing its license")
                # Check every theme, not just the first, before installing any.
                for name in THEMES:
                    directory = stage / name
                    if not (directory / "index.theme").is_file():
                        raise SettingsError(f"The cursor archive is missing {name}")
                    read_cursor(directory / "cursors/left_ptr")
                    shutil.copyfile(license_file, directory / "LICENSE")
                    (directory / "desktop-studio-source.json").write_text(json.dumps({"upstream": UPSTREAM, "version": VERSION, "sha256": expected_digest, "ryoku_package": SOURCE}, indent=2) + "\n")
                for name in THEMES:
                    destination = icons / name
                    if destination.exists() or destination.is_symlink():
                        skipped.append(name)
                        continue
                    # mkdir is exclusive, so another installer cannot have its
                    # files overwritten between a check and a directory rename.
                    try:
                        destination.mkdir()
                    except FileExistsError:
                        skipped.append(name); continue
                    created.append(destination)
                    # Staging is on the same filesystem. Move the prepared
                    # data into our exclusively created directory without a
                    # second full copy of the collection on disk.
                    for child in (stage / name).iterdir():
                        child.rename(destination / child.name)
            except Exception:
                for directory in reversed(created):
                    shutil.rmtree(directory)
                raise
    return {"installed": [p.name for p in created], "preserved": skipped}


def install_collection(progress=None):
    archive = download_collection(progress)
    return install_archive(archive, progress=progress)
