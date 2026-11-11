"""Cursor installation and previews use temporary, locally generated fixtures."""
import hashlib
import io
from pathlib import Path
import struct
import tarfile
import tempfile
import unittest

from desktop_studio.core.settings import SettingsError
from desktop_studio.platform.cursors import THEMES, install_archive, read_cursor


def cursor_bytes(width=2, height=1, xhot=0):
    typ = 0xFFFD0002
    return (struct.pack("<4I", 0x72756358, 16, 0x10000, 1) +
            struct.pack("<3I", typ, 32, 28) +
            struct.pack("<9I", 36, typ, 32, 1, width, height, xhot, 0, 0) +
            b"\x11\x22\x33\xff" * width * height)


class CursorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.icons = self.root / "icons"
        self.archive = self.root / "cursors.tar.xz"

    def tearDown(self):
        self.temp.cleanup()

    def make_archive(self, extra=None, invalid_theme=None):
        with tarfile.open(self.archive, "w:xz") as tar:
            def file(name, contents):
                entry = tarfile.TarInfo(name)
                entry.size = len(contents)
                tar.addfile(entry, io.BytesIO(contents))
            file("./LICENSE", b"GPL-3.0-or-later test fixture")
            for name in THEMES:
                file(f"./{name}/index.theme", f"[Icon Theme]\nName={name}\n".encode())
                file(f"./{name}/cursors/left_ptr", b"broken" if name == invalid_theme else cursor_bytes())
                # Reverse dependency order exercises valid alias chains.
                for alias, target in (("hand2", "arrow"), ("arrow", "left_ptr")):
                    entry = tarfile.TarInfo(f"./{name}/cursors/{alias}")
                    entry.type = tarfile.SYMTYPE
                    entry.linkname = target
                    tar.addfile(entry)
            if extra:
                extra(tar)
        return hashlib.sha256(self.archive.read_bytes()).hexdigest()

    def test_verified_collection_installs_all_variants_and_licenses(self):
        digest = self.make_archive()
        result = install_archive(self.archive, self.icons, digest)
        self.assertEqual(result["installed"], list(THEMES))
        self.assertFalse(result["preserved"])
        for name in THEMES:
            theme = self.icons / name
            self.assertEqual((theme / "LICENSE").read_bytes(), b"GPL-3.0-or-later test fixture")
            self.assertTrue((theme / "desktop-studio-source.json").is_file())
            self.assertTrue((theme / "cursors/arrow").is_symlink())
            self.assertEqual(read_cursor(theme / "cursors/hand2").width, 2)

    def test_existing_user_theme_is_preserved_and_repeat_is_idempotent(self):
        self.icons.mkdir()
        existing = self.icons / THEMES[0]
        existing.mkdir()
        (existing / "personal.txt").write_text("keep my cursor theme")
        digest = self.make_archive()
        result = install_archive(self.archive, self.icons, digest)
        self.assertEqual(result["preserved"], [THEMES[0]])
        self.assertEqual((existing / "personal.txt").read_text(), "keep my cursor theme")
        self.assertFalse((existing / "index.theme").exists())
        again = install_archive(self.archive, self.icons, digest)
        self.assertFalse(again["installed"])
        self.assertEqual(again["preserved"], list(THEMES))

    def test_checksum_failure_creates_no_theme_files(self):
        self.make_archive()
        with self.assertRaises(SettingsError):
            install_archive(self.archive, self.icons, "0" * 64)
        self.assertFalse(self.icons.exists())

    def test_archive_path_traversal_is_rejected(self):
        def extra(tar):
            entry = tarfile.TarInfo("../outside")
            entry.size = 4
            tar.addfile(entry, io.BytesIO(b"nope"))
        digest = self.make_archive(extra)
        with self.assertRaises(SettingsError):
            install_archive(self.archive, self.icons, digest)
        self.assertFalse((self.root / "outside").exists())
        self.assertFalse(any((self.icons / theme).exists() for theme in THEMES))

    def test_escaping_symlink_is_rejected(self):
        def extra(tar):
            entry = tarfile.TarInfo(f"{THEMES[0]}/cursors/escape")
            entry.type = tarfile.SYMTYPE
            entry.linkname = "../../outside"
            tar.addfile(entry)
        digest = self.make_archive(extra)
        with self.assertRaises(SettingsError):
            install_archive(self.archive, self.icons, digest)
        self.assertFalse(any((self.icons / theme).exists() for theme in THEMES))

    def test_invalid_last_theme_does_not_leave_partial_installation(self):
        digest = self.make_archive(invalid_theme=THEMES[-1])
        with self.assertRaises(SettingsError):
            install_archive(self.archive, self.icons, digest)
        self.assertFalse(any((self.icons / theme).exists() for theme in THEMES))
        self.assertFalse(list(self.icons.glob(".desktop-studio-cursors-*")))

    def test_xcursor_preview_rejects_corrupt_and_truncated_frames(self):
        path = self.root / "cursor"
        for data in (b"not a cursor", cursor_bytes()[:-2], cursor_bytes(xhot=3)):
            path.write_bytes(data)
            with self.assertRaises(SettingsError):
                read_cursor(path)
        path.write_bytes(cursor_bytes())
        image = read_cursor(path)
        self.assertEqual((image.width, image.height, image.xhot, image.yhot), (2, 1, 0, 0))
        self.assertEqual(image.pixels, b"\x11\x22\x33\xff" * 2)


if __name__ == "__main__":
    unittest.main()
