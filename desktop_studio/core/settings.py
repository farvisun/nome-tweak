"""Schema discovery, validated settings, optimistic concurrency, and reversible edits.

This module never writes settings during construction or discovery. The UI and CLI
share this adapter so policy locks and validation apply to every editing surface.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import logging
import math
import os
import re
import xml.etree.ElementTree as ET

from gi.repository import Gio, GLib, GObject

log = logging.getLogger(__name__)


class SettingsError(Exception):
    pass


class ConflictError(SettingsError):
    pass


@dataclass(frozen=True, order=True)
class Ref:
    schema: str
    key: str
    path: str = ""

    @property
    def token(self):
        return "|".join((self.schema, self.path, self.key))

    def to_dict(self):
        return {"schema": self.schema, "key": self.key, "path": self.path}

    @classmethod
    def from_dict(cls, obj):
        if not isinstance(obj, dict) or not all(isinstance(obj.get(k, ""), str) for k in ("schema", "key", "path")):
            raise SettingsError("Invalid setting reference")
        if not obj.get("schema") or not obj.get("key"):
            raise SettingsError("A setting needs a schema and key")
        return cls(obj["schema"], obj["key"], obj.get("path", ""))


SENSITIVE = re.compile(r"password|passwd|secret|token|credential|private.key|api.key|authorization|cookie|command|account|oauth", re.I)


def exportable(ref: Ref, value: str = "") -> bool:
    # Exclude credentials, commands (which can embed credentials), and known
    # identity/connection stores. Exports never include remapper source files.
    if SENSITIVE.search(ref.schema + "/" + ref.key):
        return False
    if any(x in ref.schema for x in ("remote-desktop", "proxy", "crypto", "seahorse", "Evolution", "evolution", "smb")):
        return False
    if re.search(r"(?i)(password|secret|token|bearer|api[_-]?key)\s*[:=]|://[^/\s]+:[^/\s]+@|-----BEGIN .*PRIVATE KEY", value):
        return False
    return True


class Registry:
    def __init__(self, source=None, extension_roots=None, active_extensions=None):
        self.default_source = source or Gio.SettingsSchemaSource.get_default()
        self.schemas = {}
        self.schema_origins = {}
        self.extension_schema_ids = {}
        self.known_paths: dict[str, set[str]] = {}
        self._settings = {}
        self.discovery_errors = []
        fixed, reloc = self.default_source.list_schemas(True)
        for name in fixed + reloc:
            self.schemas[name] = self.default_source.lookup(name, True)
            self.schema_origins[name] = "System"
        enabled_extensions = set()
        active_extensions = set(active_extensions or [])
        shell = self.schemas.get("org.gnome.shell")
        if shell and shell.has_key("enabled-extensions"):
            enabled_extensions = set(Gio.Settings.new_full(shell, None, None).get_strv("enabled-extensions"))
        roots = extension_roots if extension_roots is not None else [
            Path(GLib.get_user_data_dir()) / "gnome-shell/extensions",
            *(Path(p) / "gnome-shell/extensions" for p in GLib.get_system_data_dirs()),
        ]
        # User extensions take precedence. Read schemas from their installed
        # compiled sources; never modify or compile in an installed extension.
        for root in reversed(roots):
            if not Path(root).is_dir():
                continue
            # Old extension copies can share a schema ID. Prefer the registered
            # enabled installation over an inactive leftover in the same root.
            for directory in sorted(Path(root).glob("*/schemas"), key=lambda p: (p.parent.name in active_extensions, p.parent.name in enabled_extensions, p.parent.name)):
                if not (directory / "gschemas.compiled").exists():
                    continue
                try:
                    src = Gio.SettingsSchemaSource.new_from_directory(str(directory), self.default_source, False)
                    names = sum((list(x) for x in src.list_schemas(False)), [])
                    self.extension_schema_ids.setdefault(directory.parent.name, set()).update(names)
                    for name in names:
                        self.schemas[name] = src.lookup(name, False)
                        self.schema_origins[name] = directory.parent.name
                except GLib.Error as exc:
                    self.discovery_errors.append(f"{directory}: {exc.message}")
        self.refresh_paths()

    def refresh_paths(self):
        # These paths are explicitly registered by GNOME in an installed fixed
        # schema. A relocatable schema is never opened at a guessed path.
        sid = "org.gnome.settings-daemon.plugins.media-keys"
        target = sid + ".custom-keybinding"
        if sid in self.schemas and target in self.schemas:
            paths = self.settings(Ref(sid, "custom-keybindings")).get_strv("custom-keybindings")
            self.known_paths[target] = {p for p in paths if self.valid_path(p)}
        sid = "org.gnome.desktop.notifications"
        target = sid + ".application"
        if sid in self.schemas and target in self.schemas:
            # The instance path contract is declared by GNOME's notifications
            # schema: application-children are the registered dconf children.
            st = self.settings(Ref(sid, "application-children"))
            children = st.get_strv("application-children")
            self.known_paths[target] = {
                "/org/gnome/desktop/notifications/application/" + c + "/"
                for c in children if re.fullmatch(r"[a-zA-Z0-9_-]+", c)
            }
        sid = "org.gnome.desktop.app-folders"
        target = sid + ".folder"
        if sid in self.schemas and target in self.schemas:
            children = self.settings(Ref(sid, "folder-children")).get_strv("folder-children")
            self.known_paths[target] = {
                "/org/gnome/desktop/app-folders/folders/" + c + "/"
                for c in children if re.fullmatch(r"[a-zA-Z0-9_-]+", c)
            }

    @staticmethod
    def valid_path(path):
        return isinstance(path, str) and bool(re.fullmatch(r"/(?:[A-Za-z0-9_-]+/)+", path))

    def register_created_path(self, schema, path):
        """Only the custom-shortcut creation operation calls this method."""
        if schema != "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding" or not self.valid_path(path):
            raise SettingsError("Unsupported instance registration")
        self.known_paths.setdefault(schema, set()).add(path)

    def schema_key(self, ref):
        schema = self.schemas.get(ref.schema)
        if not schema or not schema.has_key(ref.key):
            raise SettingsError(f"Unavailable setting: {ref.schema} / {ref.key}")
        if schema.get_path() is None and ref.path not in self.known_paths.get(ref.schema, set()):
            raise SettingsError("This relocatable schema has no registered instance at that path")
        if schema.get_path() and ref.path and ref.path != schema.get_path():
            raise SettingsError("A fixed schema cannot use another path")
        return schema.get_key(ref.key)

    def settings(self, ref):
        self.schema_key(ref)
        cache_key = (ref.schema, ref.path)
        if cache_key not in self._settings:
            self._settings[cache_key] = Gio.Settings.new_full(self.schemas[ref.schema], None, ref.path or None)
        return self._settings[cache_key]

    def exists(self, ref):
        try:
            self.schema_key(ref)
            return True
        except SettingsError:
            return False

    def refs(self, schema_id=None):
        for name in sorted([schema_id] if schema_id else self.schemas):
            sc = self.schemas[name]
            paths = [""] if sc.get_path() else sorted(self.known_paths.get(name, []))
            for path in paths:
                for key in sorted(sc.list_keys()):
                    yield Ref(name, key, path)

    def value(self, ref):
        return self.settings(ref).get_value(ref.key)

    def state(self, ref):
        st = self.settings(ref)
        user = st.get_user_value(ref.key)
        return {"value": st.get_value(ref.key).print_(True), "user": user.print_(True) if user is not None else None}

    def validate(self, ref, text):
        key = self.schema_key(ref)
        if not isinstance(text, str) or len(text) > 1_000_000:
            raise SettingsError("The value must be GVariant text smaller than 1 MB")
        try:
            value = GLib.Variant.parse(key.get_value_type(), text, None, None)
        except GLib.Error as exc:
            raise SettingsError(f"Invalid {key.get_value_type().dup_string()} value: {exc.message}") from exc
        # GLib range comparisons can accept NaN. Desktop rendering, pointer,
        # and scaling preferences need finite numbers, including nested values.
        pending = [value.unpack()]
        while pending:
            part = pending.pop()
            if isinstance(part, float) and not math.isfinite(part):
                raise SettingsError("Numbers must be finite; NaN and infinity are not valid desktop preferences")
            if isinstance(part, (list, tuple)):
                pending.extend(part)
            elif isinstance(part, dict):
                pending.extend(part.keys()); pending.extend(part.values())
        if not key.range_check(value):
            raise SettingsError(f"Value is outside the allowed range: {key.get_range().print_(False)}")
        return value


class SettingsStore(GObject.Object):
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, (str,))}

    def __init__(self, registry, history=None):
        super().__init__()
        self.registry = registry
        self.history = history
        self._subscriptions = {}

    def watch(self, ref):
        ident = (ref.schema, ref.path)
        if ident not in self._subscriptions:
            st = self.registry.settings(ref)
            self._subscriptions[ident] = st.connect("changed", lambda _s, key: self.emit("changed", Ref(ref.schema, key, ref.path).token))
            st.connect("writable-changed", lambda _s, key: self.emit("changed", Ref(ref.schema, key, ref.path).token))

    def current(self, ref):
        self.watch(ref)
        return self.registry.value(ref)

    def apply(self, edits, label="Change settings", backup=None):
        """edits: [(Ref, new GVariant text or None for reset, expected state)].

        Validate all edits and compare snapshots before the first write. Roll
        back a partial failure only if its values still belong to this operation.
        Dconf does not provide cross-process compare-and-swap; checking just
        before each write is the strongest available Gio.Settings guarantee.
        """
        prepared = []
        seen = set()
        for ref, text, expected in edits:
            if ref in seen:
                raise SettingsError("Duplicate setting in one operation")
            seen.add(ref)
            st = self.registry.settings(ref)
            if not st.is_writable(ref.key):
                raise SettingsError(f"Locked by administrator policy: {ref.key}")
            value = self.registry.validate(ref, text) if text is not None else st.get_default_value(ref.key)
            before = self.registry.state(ref)
            if expected is None or before != expected:
                raise ConflictError(f"{ref.key} changed elsewhere. Reload and review the current value before applying.")
            after = {"value": value.print_(True), "user": value.print_(True) if text is not None else None}
            if before != after:
                prepared.append((ref, text, value, before, after))
        if not prepared:
            return []
        if backup:
            backup([x[0] for x in prepared])
        # Reserve a durable write-ahead journal before touching settings.
        changes = [{**ref.to_dict(), "before": old, "after": new} for ref, _, _, old, new in prepared]
        ticket = self.history.begin(label, changes) if self.history else None
        completed = []
        try:
            for ref, text, value, before, after in prepared:
                if self.registry.state(ref) != before:
                    raise ConflictError(f"{ref.key} changed during this operation")
                st = self.registry.settings(ref)
                if text is None:
                    st.reset(ref.key)
                elif not st.set_value(ref.key, value):
                    raise SettingsError(f"GNOME rejected {ref.key}")
                completed.append((ref, before, after))
                if self.registry.state(ref) != after:
                    raise SettingsError(f"The backend did not accept {ref.key}")
            Gio.Settings.sync()
        except Exception:
            for ref, before, after in reversed(completed):
                if self.registry.state(ref) == after:
                    st = self.registry.settings(ref)
                    if before["user"] is None:
                        st.reset(ref.key)
                    else:
                        st.set_value(ref.key, self.registry.validate(ref, before["user"]))
            Gio.Settings.sync()
            if self.history:
                self.history.finish(ticket, "failed")
            raise
        if self.history:
            self.history.finish(ticket, "applied")
        log.info("Applied %s (%d settings)", label, len(changes))
        return changes

    def set(self, ref, text, expected, label=None):
        return self.apply([(ref, text, expected)], label or ref.key)


def choices(key):
    kind, values = key.get_range().unpack()
    return list(values) if kind in ("enum", "flags") else []


def numeric_range(key):
    kind, values = key.get_range().unpack()
    return tuple(values) if kind == "range" else None
