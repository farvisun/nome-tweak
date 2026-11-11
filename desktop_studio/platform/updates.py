"""Check published GitHub Releases without changing application or desktop files."""
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from gi.repository import GLib

from .. import __version__
from ..core.profiles import atomic_json
from ..core.settings import ConflictError, SettingsError
from ..core.versions import Version

ROOT = Path(__file__).resolve().parents[2]
API_VERSION = "2026-03-10"
CHECK_INTERVAL = 24 * 60 * 60
MAX_RESPONSE = 2 * 1024 * 1024


class UpdateError(SettingsError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def normalize_repository(value):
    if not isinstance(value, str):
        raise SettingsError("Enter a GitHub repository as owner/name")
    value = value.strip()
    if not value:
        return ""
    if value.startswith("https://"):
        parsed = urllib.parse.urlsplit(value)
        if parsed.netloc.lower() != "github.com" or parsed.query or parsed.fragment:
            raise SettingsError("Use an https://github.com/owner/name URL without credentials or query parameters")
        value = parsed.path.strip("/")
    elif value.startswith("git@github.com:"):
        value = value.removeprefix("git@github.com:")
    value = value.removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}", value) or value.split("/")[1] in (".", ".."):
        raise SettingsError("Enter a GitHub repository as owner/name, without a branch or extra path")
    return value


def shipped_repository(source_file=None):
    source = Path(source_file) if source_file else ROOT / "data/update-source.json"
    if not source.exists():
        return ""
    try:
        data = json.loads(source.read_text())
        if data.get("version") != 1:
            raise ValueError("version")
        return normalize_repository(data.get("repository", ""))
    except (OSError, ValueError, AttributeError, SettingsError) as exc:
        raise SettingsError("The installed GitHub update-source configuration is invalid") from exc


def file_revision(path):
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


class UpdatePreferences:
    def __init__(self, config_dir=None, source_file=None):
        self.path = (Path(config_dir) if config_dir else Path(GLib.get_user_config_dir()) / "desktop-studio") / "updates.json"
        self.source_file = source_file
        self.repository = ""
        self.automatic = True
        self.revision = None
        self.warning = ""
        self.reload()

    def reload(self):
        self.warning = ""
        self.repository = ""
        self.automatic = True
        try:
            self.repository = shipped_repository(self.source_file)
            self.revision = file_revision(self.path)
            if self.path.exists():
                if self.path.stat().st_size > 16_384:
                    raise ValueError("size")
                data = json.loads(self.path.read_text())
                if data.get("version") != 1 or type(data.get("automatic", True)) is not bool:
                    raise ValueError("format")
                if "repository" in data:
                    self.repository = normalize_repository(data["repository"])
                self.automatic = data.get("automatic", True)
        except (OSError, ValueError, AttributeError, SettingsError):
            self.warning = "The update preferences could not be read. Automatic checks are disabled until you save valid preferences."
            self.automatic = False

    def save(self, repository, automatic, expected_revision):
        repository = normalize_repository(repository)
        if type(automatic) is not bool:
            raise SettingsError("The automatic-check preference must be true or false")
        if file_revision(self.path) != expected_revision:
            raise ConflictError("Update preferences changed elsewhere. Reopen Software Updates before saving.")
        atomic_json(self.path, {"version": 1, "repository": repository, "automatic": automatic})
        self.repository, self.automatic = repository, automatic
        self.revision = file_revision(self.path)
        self.warning = ""


@dataclass(frozen=True)
class Release:
    tag: str
    version: str
    url: str
    published: str
    notes: str
    deb_url: str = ""
    archive_url: str = ""

    @classmethod
    def from_payload(cls, repository, payload):
        repository = normalize_repository(repository)
        if not repository or not isinstance(payload, dict):
            raise UpdateError("invalid-response", "GitHub returned an invalid release response")
        if type(payload.get("draft")) is not bool or type(payload.get("prerelease")) is not bool:
            raise UpdateError("invalid-response", "GitHub returned incomplete release metadata")
        if payload["draft"] or payload["prerelease"]:
            raise UpdateError("not-stable", "The returned release is a draft or prerelease. Desktop Studio checks stable published releases only.")
        tag = payload.get("tag_name")
        try:
            version = Version.parse(tag)
        except ValueError as exc:
            raise UpdateError("invalid-version", "The release tag must be a semantic version such as v1.2.3") from exc
        if version.prerelease:
            raise UpdateError("not-stable", "Prerelease version tags are excluded from stable update checks")
        notes = payload.get("body") or ""
        published = payload.get("published_at") or ""
        if not isinstance(notes, str) or not isinstance(published, str):
            raise UpdateError("invalid-response", "GitHub returned invalid release details")
        tag_path = urllib.parse.quote(tag, safe="")
        base = f"https://github.com/{repository}/releases"
        expected_names = {
            "deb_url": f"desktop-studio_{version}_all.deb",
            "archive_url": f"desktop-studio-{version}-linux.tar.gz",
        }
        downloads = {key: "" for key in expected_names}
        assets = payload.get("assets", [])
        if not isinstance(assets, list):
            raise UpdateError("invalid-response", "GitHub returned invalid release assets")
        for asset in assets[:100]:
            if not isinstance(asset, dict) or asset.get("state") != "uploaded":
                continue
            for kind, name in expected_names.items():
                expected_url = f"{base}/download/{tag_path}/{urllib.parse.quote(name, safe='')}"
                if asset.get("name") == name and asset.get("browser_download_url") == expected_url:
                    downloads[kind] = expected_url
        return cls(tag, str(version), f"{base}/tag/{tag_path}", published, notes[:20_000], **downloads)


@dataclass(frozen=True)
class UpdateResult:
    repository: str
    current: str
    checked_at: float
    status: str
    release: Release | None = None
    message: str = ""

    @property
    def available(self):
        return self.status == "available"

    def to_dict(self):
        return asdict(self)


def _decode(data):
    if len(data) > MAX_RESPONSE:
        raise UpdateError("invalid-response", "The GitHub release response is too large")
    try:
        return json.loads(data)
    except (ValueError, UnicodeError) as exc:
        raise UpdateError("invalid-response", "GitHub did not return valid release JSON") from exc


def _authenticated_release(repository):
    # Reuse GitHub CLI's supported credential store. Tokens are never read,
    # printed, persisted, or bundled by this application.
    executable = shutil.which("gh")
    if not executable:
        return None
    try:
        result = subprocess.run([executable, "api", "--hostname", "github.com", "--method", "GET", "-H", "Accept: application/vnd.github+json", "-H", f"X-GitHub-Api-Version: {API_VERSION}", f"repos/{repository}/releases/latest"], capture_output=True, timeout=20)
        if result.returncode == 0:
            return _decode(result.stdout)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def fetch_latest_release(repository):
    repository = normalize_repository(repository)
    if not repository:
        raise UpdateError("not-configured", "Configure a GitHub release repository first")
    request = urllib.request.Request(f"https://api.github.com/repos/{repository}/releases/latest", headers={"User-Agent": f"Desktop-Studio/{__version__}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": API_VERSION})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return _decode(response.read(MAX_RESPONSE + 1))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 404, 429):
            authenticated = _authenticated_release(repository)
            if authenticated is not None:
                return authenticated
        if exc.code in (403, 429):
            raise UpdateError("rate-limited", "GitHub denied or rate-limited this check. Try later; a signed-in GitHub CLI can provide authenticated access.") from exc
        if exc.code == 404:
            raise UpdateError("no-release", "No published release was found. Check the repository name and publish a stable GitHub Release. For a private repository, sign in with gh auth login on this computer.") from exc
        if exc.code == 401:
            raise UpdateError("authentication", "GitHub authentication is required. Sign in with gh auth login; do not place tokens in the application or repository.") from exc
        raise UpdateError("server-error", f"GitHub returned HTTP {exc.code}. Try again later.") from exc
    except (OSError, ValueError) as exc:
        raise UpdateError("offline", "Could not reach GitHub. Check the connection and try again; your application and desktop configuration were not changed.") from exc


class UpdateChecker:
    def __init__(self, preferences=None, state_dir=None, current_version=__version__, transport=None):
        self.preferences = preferences or UpdatePreferences()
        self.current_version = str(Version.parse(current_version))
        self.path = (Path(state_dir) if state_dir else Path(GLib.get_user_state_dir()) / "desktop-studio") / "updates.json"
        self.transport = transport or fetch_latest_release
        self.lock = threading.Lock()

    def last_state(self):
        try:
            if self.path.stat().st_size > 100_000:
                return {}
            state = json.loads(self.path.read_text())
            if not isinstance(state, dict) or state.get("version") != 1 or state.get("repository") != self.preferences.repository:
                return {}
            return state
        except (OSError, ValueError):
            return {}

    def should_check(self, now=None):
        if not self.preferences.repository or not self.preferences.automatic or self.preferences.warning:
            return False
        now = time.time() if now is None else now
        last = self.last_state().get("last_attempt")
        if not isinstance(last, (float, int)) or isinstance(last, bool):
            return True
        return not 0 <= now - last < CHECK_INTERVAL

    def check(self, repository=None, now=None):
        repository = normalize_repository(self.preferences.repository if repository is None else repository)
        checked_at = time.time() if now is None else now
        if not repository:
            return UpdateResult("", self.current_version, checked_at, "not-configured", message="Choose the GitHub repository that publishes Desktop Studio releases.")
        with self.lock:
            # Record attempts before network I/O so repeated offline launches
            # respect the daily limit too. Manual checks remain available.
            state = {"version": 1, "repository": repository, "last_attempt": checked_at}
            atomic_json(self.path, state)
            try:
                release = Release.from_payload(repository, self.transport(repository))
                status = "available" if Version.parse(release.version) > Version.parse(self.current_version) else "up-to-date"
                result = UpdateResult(repository, self.current_version, checked_at, status, release)
            except UpdateError as exc:
                result = UpdateResult(repository, self.current_version, checked_at, exc.code, message=str(exc))
            state["result"] = result.to_dict()
            atomic_json(self.path, state)
            return result
