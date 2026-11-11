import hashlib
import contextlib
import io
import json
from pathlib import Path
import subprocess
import shutil
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from build_release import build_user_archive, write_checksums, verify_tag
from build_deb import build as build_deb


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "desktop_studio").mkdir()
        (self.source / "desktop_studio/__init__.py").write_text('__version__ = "1.2.3"\n')
        (self.source / "data").mkdir()
        (self.source / "data/update-source.json").write_text('{"version":1,"repository":""}')
        (self.source / "scripts").mkdir()
        (self.source / "scripts/install.py").write_text('# a user installer\n')
        (self.source / "README.md").write_text('Fixture release\n')
        (self.source / ".gitignore").write_text('.env\n__pycache__/\nartifacts/\ndist/\n')
        subprocess.run(["git", "init", "--quiet", str(self.source)], check=True)
        subprocess.run(["git", "-C", str(self.source), "add", "."], check=True)

    def tearDown(self):
        self.temp.cleanup()

    def test_source_archive_contains_bound_installer_and_omits_private_files(self):
        (self.source / "desktop_studio/.env").write_text('secret-do-not-package')
        (self.source / "scripts/.env").write_text('secret-do-not-package')
        (self.source / "scripts/local-untracked.py").write_text('private-untracked-file')
        (self.source / "artifacts").mkdir()
        (self.source / "artifacts/private.json").write_text('private-local-config')
        archive = build_user_archive(self.root / "out", "example/desktop-studio", root=self.source, version="1.2.3")
        self.assertEqual(archive.name, "desktop-studio-1.2.3-linux.tar.gz")
        with tarfile.open(archive) as tar:
            names = tar.getnames()
            self.assertIn("desktop-studio-1.2.3/scripts/install.py", names)
            self.assertFalse(any(".env" in name or "local-untracked" in name or "/.git/" in name or "/artifacts/" in name for name in names))
            data = json.load(tar.extractfile("desktop-studio-1.2.3/data/update-source.json"))
            self.assertEqual(data["repository"], "example/desktop-studio")
        self.assertEqual(json.loads((self.source / "data/update-source.json").read_text())["repository"], "")

    def test_release_checksums_cover_exact_artifact_bytes(self):
        one = self.root / "package.deb"; one.write_bytes(b"package")
        two = self.root / "source.tar.gz"; two.write_bytes(b"installer")
        output = write_checksums([one, two], self.root)
        self.assertEqual(output.read_text().splitlines(), [hashlib.sha256(b"package").hexdigest() + "  package.deb", hashlib.sha256(b"installer").hexdigest() + "  source.tar.gz"])

    def test_release_tag_must_match_version_and_clean_commit(self):
        from desktop_studio import __version__
        with self.assertRaises(ValueError): verify_tag("v999.0.0", self.source)
        with self.assertRaises(ValueError): verify_tag("v" + __version__, self.source)

    def test_tagged_release_requires_unchanged_matching_head(self):
        from desktop_studio import __version__
        git = ["git", "-C", str(self.source)]
        subprocess.run([*git, "-c", "commit.gpgsign=false", "-c", "user.name=Tests", "-c", "user.email=tests@example.invalid", "commit", "--quiet", "-m", "Fixture"], check=True)
        subprocess.run([*git, "-c", "tag.gpgsign=false", "tag", "v" + __version__], check=True)
        verify_tag("v" + __version__, self.source)
        (self.source / "README.md").write_text("Uncommitted change\n")
        with self.assertRaises(ValueError): verify_tag("v" + __version__, self.source)

    @unittest.skipUnless(shutil.which("dpkg-deb"), "dpkg-deb is required for Debian package inspection")
    def test_debian_permissions_version_and_release_source(self):
        from desktop_studio import __version__
        with contextlib.redirect_stdout(io.StringIO()):
            package = build_deb(self.root / "debian", "example/desktop-studio")
        self.assertEqual(subprocess.check_output(["dpkg-deb", "--field", str(package), "Version"], text=True).strip(), __version__)
        raw = subprocess.check_output(["dpkg-deb", "--fsys-tarfile", str(package)])
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
            self.assertEqual(archive.getmember(".").mode, 0o755)
            self.assertEqual(archive.getmember("./usr/bin/desktop-studio").mode, 0o755)
            for member in archive.getmembers():
                self.assertEqual((member.uid, member.gid), (0, 0))
                self.assertFalse(member.mode & 0o022)
            source = json.load(archive.extractfile("./usr/lib/desktop-studio/data/update-source.json"))
            self.assertEqual(source["repository"], "example/desktop-studio")


if __name__ == "__main__":
    unittest.main()
