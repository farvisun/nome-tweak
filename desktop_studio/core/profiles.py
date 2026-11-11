"""Private versioned snapshots and reviewable, selective profile operations."""
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import uuid

from .settings import Ref, SettingsError, exportable

FORMAT = "desktop-studio-profile"
VERSION = 1


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def atomic_json(path, obj):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(obj, out, ensure_ascii=False, indent=2)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


class History:
    def __init__(self, directory):
        self.path = Path(directory) / "history.json"
        self.entries = []
        if self.path.exists():
            try:
                self.entries = json.loads(self.path.read_text())[-200:]
                if not isinstance(self.entries, list):
                    raise ValueError("Invalid history")
            except (ValueError, OSError):
                self.entries = []

    def save(self):
        atomic_json(self.path, self.entries[-200:])

    def begin(self, label, changes):
        safe = [x for x in changes if exportable(Ref.from_dict(x), x["before"]["value"]) and exportable(Ref.from_dict(x), x["after"]["value"])]
        entry = {"id": uuid.uuid4().hex, "time": timestamp(), "label": label, "status": "pending", "changes": safe, "excluded": len(changes) - len(safe)}
        self.entries.append(entry)
        self.save()
        return entry["id"]

    def finish(self, ticket, status):
        for entry in self.entries:
            if entry["id"] == ticket:
                entry["status"] = status
        self.save()

    def undo(self, entry, store):
        if entry["status"] != "applied" or not entry["changes"] or entry.get("excluded"):
            raise SettingsError("This change cannot be undone")
        edits = [(Ref.from_dict(x), x["before"]["user"], x["after"]) for x in entry["changes"]]
        result = store.apply(edits, "Undo: " + entry["label"])
        self.finish(entry["id"], "undone")
        return result


class Profiles:
    def __init__(self, directory, registry, category_for):
        self.directory = Path(directory)
        self.registry = registry
        self.category_for = category_for
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)

    def snapshot(self, name, refs):
        entries = []
        for ref in refs:
            state = self.registry.state(ref)
            if exportable(ref, state["value"]):
                entries.append({**ref.to_dict(), "type": self.registry.value(ref).get_type_string(), "category": self.category_for(ref), **state})
        return {"format": FORMAT, "version": VERSION, "name": name, "created": timestamp(), "settings": entries}

    def initial(self, refs):
        path = self.directory / "initial-snapshot.json"
        if not path.exists():
            atomic_json(path, self.snapshot("Initial configuration", refs))
        return path

    def save(self, profile, path=None):
        self.validate_document(profile)
        path = Path(path) if path else self.directory / (uuid.uuid4().hex + ".json")
        atomic_json(path, profile)
        return path

    def backup(self, refs):
        return self.save(self.snapshot("Automatic backup · " + timestamp(), refs))

    def list(self):
        result = []
        for path in self.directory.glob("*.json"):
            try:
                profile = self.load(path)
                result.append((path, profile))
            except (SettingsError, OSError):
                pass
        return sorted(result, key=lambda x: x[1].get("created", ""), reverse=True)

    @staticmethod
    def validate_document(profile):
        if not isinstance(profile, dict) or profile.get("format") != FORMAT or type(profile.get("version")) is not int or profile["version"] != VERSION:
            raise SettingsError("Unsupported profile format or version (expected Desktop Studio version 1)")
        if not isinstance(profile.get("name"), str) or not profile["name"].strip() or len(profile["name"]) > 200:
            raise SettingsError("A profile needs a name of 1–200 characters")
        entries = profile.get("settings")
        if not isinstance(entries, list) or len(entries) > 15000:
            raise SettingsError("Invalid profile settings list")
        seen = set()
        for entry in entries:
            ref = Ref.from_dict(entry)
            if ref in seen:
                raise SettingsError("Duplicate profile setting")
            seen.add(ref)
            if not isinstance(entry.get("value"), str) or len(entry["value"]) > 1_000_000 or not isinstance(entry.get("type"), str):
                raise SettingsError("Invalid profile value")
            if "user" not in entry or (entry["user"] is not None and not isinstance(entry["user"], str)):
                raise SettingsError("Invalid restoration state")
            if not exportable(ref, entry["value"]) or (entry["user"] is not None and not exportable(ref, entry["user"])):
                raise SettingsError(f"Sensitive setting excluded from profiles: {ref.key}")

    def load(self, path):
        path = Path(path)
        if path.stat().st_size > 12_000_000:
            raise SettingsError("Profile exceeds 12 MB")
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise SettingsError("This is not a valid JSON profile") from exc
        self.validate_document(profile)
        return profile

    def compare(self, profile, categories=None):
        self.validate_document(profile)
        changes, skipped = [], []
        for entry in profile["settings"]:
            ref = Ref.from_dict(entry)
            # Trust the local category, never category labels in imported data.
            if categories is not None and self.category_for(ref) not in categories:
                continue
            try:
                key = self.registry.schema_key(ref)
                if key.get_value_type().dup_string() != entry["type"]:
                    raise SettingsError("Type differs on this system")
                value = self.registry.validate(ref, entry["value"])
                if entry["user"] is not None:
                    user = self.registry.validate(ref, entry["user"])
                    if not user.equal(value):
                        raise SettingsError("Profile value and restoration state disagree")
                if not self.registry.settings(ref).is_writable(ref.key):
                    raise SettingsError("Locked by policy")
                before = self.registry.state(ref)
                # A reset restores the actual local schema default; show that
                # effective value, including when defaults changed after upgrade.
                after_value = self.registry.settings(ref).get_default_value(ref.key) if entry["user"] is None else value
                after = {"value": after_value.print_(True), "user": entry["user"]}
                if before != after:
                    changes.append({"ref": ref, "before": before, "after": after})
            except SettingsError as exc:
                skipped.append((ref, str(exc)))
        return changes, skipped

    def apply_review(self, review, store, name):
        return store.apply([(x["ref"], x["after"]["user"], x["before"]) for x in review], "Profile: " + name, backup=self.backup)

    def defaults(self, refs):
        profile = self.snapshot("GNOME defaults · selected settings", refs)
        for entry in profile["settings"]:
            ref = Ref.from_dict(entry)
            entry["value"] = self.registry.settings(ref).get_default_value(ref.key).print_(True)
            entry["user"] = None
        return profile

    def mac_style(self):
        # A small optional preset. It does not change keyboard sources, XKB
        # options, Toshy, extensions, or unrelated desktop preferences.
        candidates = [
            (Ref("org.gnome.desktop.wm.preferences", "button-layout"), "'close,minimize,maximize:'"),
            (Ref("org.gnome.shell.extensions.dash-to-dock", "dock-position"), "'BOTTOM'"),
            (Ref("org.gnome.shell.extensions.dash-to-dock", "extend-height"), "false"),
            (Ref("org.gnome.shell.extensions.dash-to-dock", "dock-fixed"), "true"),
            (Ref("org.gnome.shell.extensions.dash-to-dock", "autohide"), "false"),
            (Ref("org.gnome.shell.extensions.dash-to-dock", "intellihide"), "false"),
        ]
        profile = self.snapshot("Mac-style desktop", [r for r, v in candidates if self.registry.exists(r)])
        targets = dict(candidates)
        for entry in profile["settings"]:
            entry["value"] = entry["user"] = targets[Ref.from_dict(entry)]
        return profile
