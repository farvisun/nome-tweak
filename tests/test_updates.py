import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from desktop_studio.core.settings import ConflictError, SettingsError
from desktop_studio.core.versions import Version
from desktop_studio.platform.updates import CHECK_INTERVAL, MAX_RESPONSE, Release, UpdateChecker, UpdateError, UpdatePreferences, fetch_latest_release, normalize_repository

REPO = "example/desktop-studio"


def payload(version="1.1.0"):
    tag = "v" + version
    base = f"https://github.com/{REPO}/releases/download/{tag}"
    return {"tag_name": tag, "draft": False, "prerelease": False, "published_at": "2026-11-12T10:00:00Z", "body": "Release notes\n• Improvements", "html_url": f"https://github.com/{REPO}/releases/tag/{tag}", "assets": [
        {"name": f"desktop-studio_{version}_all.deb", "state": "uploaded", "browser_download_url": f"{base}/desktop-studio_{version}_all.deb"},
        {"name": f"desktop-studio-{version}-linux.tar.gz", "state": "uploaded", "browser_download_url": f"{base}/desktop-studio-{version}-linux.tar.gz"},
    ]}


class VersionTests(unittest.TestCase):
    def test_numeric_versions_and_release_order(self):
        ordered = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2", "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0", "1.2.0", "1.10.0", "2.0.0"]
        versions = [Version.parse(x) for x in ordered]
        self.assertEqual(sorted(reversed(versions)), versions)
        self.assertEqual(Version.parse("v1.0.0+build.2"), Version.parse("1.0.0+build.3"))
        self.assertEqual(str(Version.parse("v1.2.3")), "1.2.3")

    def test_invalid_and_leading_zero_versions_are_rejected(self):
        for version in (None, "latest", "1.2", "01.0.0", "1.0.0-01", "1.0.0-alpha..2", "1.0.0+bad..id", "v1.2.3/evil", "1.0.0\n"):
            with self.assertRaises(ValueError, msg=version):
                Version.parse(version)


class ReleaseTests(unittest.TestCase):
    def test_repository_urls_are_normalized_without_credentials(self):
        for source in (REPO, "https://github.com/" + REPO, "git@github.com:" + REPO + ".git"):
            self.assertEqual(normalize_repository(source), REPO)
        for source in ("https://github.com.attacker.test/" + REPO, "https://token@github.com/" + REPO, "https://github.com/" + REPO + "?token=secret", "../../repo", REPO + "/tree/main", "https://gitlab.com/owner/repo"):
            with self.assertRaises(SettingsError):
                normalize_repository(source)

    def test_release_downloads_must_match_repo_tag_and_version(self):
        data = payload()
        release = Release.from_payload(REPO, data)
        self.assertTrue(release.deb_url.endswith("desktop-studio_1.1.0_all.deb"))
        self.assertTrue(release.archive_url.endswith("desktop-studio-1.1.0-linux.tar.gz"))
        data["html_url"] = "https://attacker.test/phishing"
        data["assets"][0]["browser_download_url"] = "https://attacker.test/installer.deb"
        data["assets"][1]["browser_download_url"] = f"https://github.com/someone/another-repo/releases/download/v1.1.0/desktop-studio-1.1.0-linux.tar.gz"
        release = Release.from_payload(REPO, data)
        self.assertEqual(release.url, f"https://github.com/{REPO}/releases/tag/v1.1.0")
        self.assertFalse(release.deb_url)
        self.assertFalse(release.archive_url)

    def test_drafts_prereleases_and_bad_versions_are_not_updates(self):
        for field in ("draft", "prerelease"):
            data = payload(); data[field] = True
            with self.assertRaises(UpdateError): Release.from_payload(REPO, data)
        for tag in ("latest", "v1.2", "v1.3.0-rc.1"):
            data = payload(); data["tag_name"] = tag
            with self.assertRaises(UpdateError): Release.from_payload(REPO, data)

    def test_malformed_metadata_is_reported(self):
        for data in ([], {}, {**payload(), "body": ["not text"]}, {**payload(), "assets": "not a list"}):
            with self.assertRaises(UpdateError): Release.from_payload(REPO, data)


class CheckerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "update-source.json"
        self.source.write_text(json.dumps({"version": 1, "repository": REPO}))
        self.prefs = UpdatePreferences(self.root / "config", self.source)

    def tearDown(self):
        self.temp.cleanup()

    def checker(self, data=None, current="1.0.0", transport=None):
        return UpdateChecker(self.prefs, self.root / "state", current, transport=transport or (lambda _repo: payload() if data is None else data))

    def test_newer_release_available_and_no_downgrade(self):
        self.assertTrue(self.checker().check(now=100).available)
        for current in ("1.1.0", "1.2.0", "2.0.0"):
            result = self.checker(current=current).check(now=200)
            self.assertEqual(result.status, "up-to-date")
            self.assertFalse(result.available)

    def test_automatic_checks_are_daily_but_manual_checks_work(self):
        calls = []
        checker = self.checker(transport=lambda repo: (calls.append(repo), payload())[1])
        self.assertTrue(checker.should_check(now=100))
        checker.check(now=100)
        self.assertFalse(checker.should_check(now=100 + CHECK_INTERVAL - 1))
        self.assertTrue(checker.should_check(now=100 + CHECK_INTERVAL))
        checker.check(now=105)
        self.assertEqual(calls, [REPO, REPO])
        self.assertEqual(checker.path.stat().st_mode & 0o777, 0o600)

    def test_failures_are_visible_and_do_not_retry_each_launch(self):
        def offline(_repo): raise UpdateError("offline", "No network")
        checker = self.checker(transport=offline)
        result = checker.check(now=100)
        self.assertEqual(result.status, "offline")
        self.assertEqual(result.message, "No network")
        self.assertFalse(checker.should_check(now=105))
        self.assertEqual(checker.last_state()["result"]["status"], "offline")

    def test_missing_source_never_calls_network(self):
        self.prefs.save("", True, self.prefs.revision)
        checker = self.checker(transport=lambda _repo: self.fail("must not request an invented repository"))
        self.assertFalse(checker.should_check())
        self.assertEqual(checker.check().status, "not-configured")

    def test_preferences_and_source_change_reset_the_daily_limit(self):
        checker = self.checker()
        checker.check(now=100)
        self.prefs.save("another/desktop-studio", True, self.prefs.revision)
        self.assertTrue(checker.should_check(now=101))
        self.prefs.save(REPO, False, self.prefs.revision)
        self.assertFalse(checker.should_check(now=200000))

    def test_stale_preferences_are_not_overwritten(self):
        self.prefs.save(REPO, True, None)
        second = UpdatePreferences(self.root / "config", self.source)
        second.save(REPO, False, second.revision)
        with self.assertRaises(ConflictError): self.prefs.save("another/repo", True, self.prefs.revision)
        self.assertFalse(json.loads(self.prefs.path.read_text())["automatic"])

    def test_bad_preference_file_is_not_silently_replaced(self):
        self.prefs.path.parent.mkdir(parents=True)
        self.prefs.path.write_text("not json")
        self.prefs.reload()
        self.assertFalse(self.prefs.automatic)
        self.assertTrue(self.prefs.warning)
        self.assertEqual(self.prefs.path.read_text(), "not json")

    def test_clock_rollback_and_corrupt_cache_allow_a_new_check(self):
        checker = self.checker()
        checker.check(now=200)
        self.assertTrue(checker.should_check(now=100))
        checker.path.write_text("not json")
        self.assertTrue(checker.should_check(now=201))


class TransportTests(unittest.TestCase):
    def test_public_api_is_bounded_and_parsed(self):
        response = io.BytesIO(json.dumps(payload()).encode())
        with patch("desktop_studio.platform.updates.urllib.request.urlopen", return_value=response) as request:
            self.assertEqual(fetch_latest_release(REPO)["tag_name"], "v1.1.0")
            self.assertEqual(request.call_args.args[0].full_url, f"https://api.github.com/repos/{REPO}/releases/latest")
        with patch("desktop_studio.platform.updates.urllib.request.urlopen", return_value=io.BytesIO(b"x" * (MAX_RESPONSE + 1))):
            with self.assertRaises(UpdateError): fetch_latest_release(REPO)

    def test_private_releases_can_reuse_github_cli_authentication(self):
        error = urllib.error.HTTPError("url", 404, "Not found", {}, None)
        with patch("desktop_studio.platform.updates.urllib.request.urlopen", side_effect=error), patch("desktop_studio.platform.updates._authenticated_release", return_value=payload()) as auth:
            self.assertEqual(fetch_latest_release(REPO)["tag_name"], "v1.1.0")
            auth.assert_called_once_with(REPO)

    def test_http_rate_limit_and_offline_are_not_reported_up_to_date(self):
        for code, status in ((404, "no-release"), (403, "rate-limited"), (401, "authentication"), (500, "server-error")):
            error = urllib.error.HTTPError("url", code, "Error", {}, None)
            with patch("desktop_studio.platform.updates.urllib.request.urlopen", side_effect=error), patch("desktop_studio.platform.updates._authenticated_release", return_value=None):
                with self.assertRaises(UpdateError) as caught: fetch_latest_release(REPO)
                self.assertEqual(caught.exception.code, status)
        with patch("desktop_studio.platform.updates.urllib.request.urlopen", side_effect=OSError("offline")):
            with self.assertRaises(UpdateError) as caught: fetch_latest_release(REPO)
            self.assertEqual(caught.exception.code, "offline")


if __name__ == "__main__":
    unittest.main()
