from pathlib import Path
import ast
import hashlib
import os
import re
import shutil
import uuid
import xml.etree.ElementTree as ET

from gi.repository import GLib

from ..core.settings import Ref, SettingsError
from ..core.profiles import atomic_json
from .services import run

INPUT = "org.gnome.desktop.input-sources"
CUSTOM = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
MEDIA = "org.gnome.settings-daemon.plugins.media-keys"


def canonical_shortcut(text):
    """Normalize GNOME accelerator aliases without depending on a display."""
    aliases = {"primary": "control", "ctrl": "control", "ctl": "control", "mod1": "alt", "mod4": "super", "meta": "meta"}
    modifiers = {aliases.get(x.lower(), x.lower()) for x in re.findall(r"<([^>]+)>", text)}
    key = re.sub(r"<[^>]+>", "", text).strip().lower()
    key = {"iso_left_tab": "tab", "return": "enter", "kp_enter": "kp_enter", "esc": "escape", "space": "space"}.get(key, key)
    if "iso_left_tab" in text.lower():
        modifiers.add("shift")
    if not key or key in ("disabled", "none"):
        return ""
    return "+".join(sorted(modifiers) + [key])


def shortcut_refs(registry):
    for ref in registry.refs():
        if ("keybindings" in ref.schema or ref.schema in (MEDIA, CUSTOM) or ".extensions." in ref.schema) and ref.key != "custom-keybindings":
            typ = registry.schema_key(ref).get_value_type().dup_string()
            if typ == "as" and ("keybindings" in ref.schema or ref.schema == MEDIA or any(x in ref.key for x in ("shortcut", "hotkey", "keybinding"))):
                yield ref
            elif ref.schema == CUSTOM and ref.key == "binding":
                yield ref


def conflicts(registry, accelerators, exclude=None):
    wanted = {canonical_shortcut(x) for x in accelerators} - {""}
    result = []
    for ref in shortcut_refs(registry):
        if ref == exclude:
            continue
        current = registry.value(ref).unpack()
        current = current if isinstance(current, list) else [current]
        matches = [x for x in current if canonical_shortcut(x) in wanted]
        if matches:
            result.append((ref, matches))
    return result


def layouts():
    result = []
    path = Path("/usr/share/X11/xkb/rules/evdev.xml")
    if not path.exists():
        return result
    for layout in ET.parse(path).getroot().findall(".//layoutList/layout"):
        name = layout.findtext("configItem/name")
        description = layout.findtext("configItem/description") or name
        result.append((name, description))
        for variant in layout.findall("variantList/variant"):
            vname = variant.findtext("configItem/name")
            desc = variant.findtext("configItem/description") or vname
            result.append((name + "+" + vname, desc))
    return sorted(result, key=lambda x: x[1].casefold())


def xkb_options():
    path = Path("/usr/share/X11/xkb/rules/evdev.xml")
    if not path.exists():
        return set()
    return {node.text for node in ET.parse(path).getroot().findall(".//optionList/group/option/configItem/name") if node.text}


def validate_xkb_options(options):
    caps_roles = [x for x in options if x.startswith("caps:") or x in ("grp:caps_toggle", "compose:caps", "ctrl:nocaps", "ctrl:swapcaps")]
    if len(caps_roles) > 1:
        raise SettingsError("Caps Lock has more than one role: " + ", ".join(caps_roles) + ". Choose another switching, Compose, or modifier key first.")


def create_custom_shortcut(registry, store, name, command, binding):
    if not name.strip() or not command.strip() or "\x00" in command:
        raise SettingsError("A name and a valid command are required")
    if not binding or conflicts(registry, [binding]):
        raise SettingsError("Choose a shortcut that is not already assigned")
    master = Ref(MEDIA, "custom-keybindings")
    expected = registry.state(master)
    paths = registry.value(master).unpack()
    # This is an explicit creation operation, not schema discovery. Allocate a
    # new instance and register its real path before editing it.
    path = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/desktop-studio-" + uuid.uuid4().hex + "/"
    registry.register_created_path(CUSTOM, path)
    fields = {"name": name.strip(), "command": command.strip(), "binding": binding}
    edits = []
    for key, value in fields.items():
        ref = Ref(CUSTOM, key, path)
        edits.append((ref, GLib.Variant("s", value).print_(True), registry.state(ref)))
    edits.append((master, GLib.Variant("as", paths + [path]).print_(True), expected))
    return store.apply(edits, "Add custom shortcut")


class Toshy:
    START = "###  SLICE_MARK_START: user_apps"
    END = "###  SLICE_MARK_END: user_apps"

    def __init__(self, backup_dir, config=None):
        self.config = Path(config) if config else Path(GLib.get_user_config_dir()) / "toshy/toshy_config.py"
        self.backup_dir = Path(backup_dir) / "toshy"

    @property
    def available(self):
        return self.config.is_file()

    def status(self):
        try:
            return run(["systemctl", "--user", "is-active", "toshy-config.service"])
        except SettingsError:
            return "Inactive or manually managed"

    def service(self, action):
        if action not in ("start", "stop", "restart"):
            raise SettingsError("Unsupported Toshy action")
        # Use Toshy's own service orchestration, preserving its session monitor
        # and compositor-specific helper services.
        executable = shutil.which("toshy-services-" + action)
        if not executable:
            raise SettingsError("Toshy's supported service command is unavailable; open Toshy preferences")
        return run([executable], timeout=30)

    def read(self):
        data = self.config.read_text(encoding="utf-8")
        return data, hashlib.sha256(data.encode()).hexdigest()

    def slice(self):
        data, digest = self.read()
        a, b = self.slice_bounds(data)
        return data[a:b], digest

    @classmethod
    def slice_bounds(cls, data):
        starts = [m for m in re.finditer(r"(?m)^" + re.escape(cls.START) + r"[^\n]*\n", data)]
        ends = [m for m in re.finditer(r"(?m)^" + re.escape(cls.END) + r"[^\n]*", data)]
        if len(starts) != 1 or len(ends) != 1 or starts[0].end() >= ends[0].start():
            raise SettingsError("This Toshy configuration has no unique supported User Apps slice")
        return starts[0].end(), ends[0].start()

    def save_slice(self, text, expected_digest):
        data, digest = self.read()
        if digest != expected_digest:
            raise SettingsError("Toshy configuration changed elsewhere. Reopen the editor before saving.")
        if "SLICE_MARK_" in text:
            raise SettingsError("Slice boundary markers cannot be included inside the slice")
        a, b = self.slice_bounds(data)
        new = data[:a] + "\n" + text.strip("\n") + "\n\n" + data[b:]
        try:
            ast.parse(new)
        except SyntaxError as exc:
            raise SettingsError(f"Python syntax error on line {exc.lineno}: {exc.msg}") from exc
        self.backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        backup = self.backup_dir / (uuid.uuid4().hex + ".py")
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        # Recheck after the durable backup and before atomic replacement.
        if self.read()[1] != expected_digest:
            raise SettingsError("Toshy configuration changed while preparing the backup")
        target = self.config.resolve()
        temp = target.with_name(target.name + ".desktop-studio-" + uuid.uuid4().hex)
        try:
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, target.stat().st_mode & 0o777)
            with os.fdopen(fd, "w") as out:
                out.write(new)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)
        return backup, hashlib.sha256(new.encode()).hexdigest()

    def restore(self, backup, expected_digest):
        if self.read()[1] != expected_digest:
            raise SettingsError("Toshy configuration changed since this backup was created")
        data = Path(backup).read_text()
        a, b = self.slice_bounds(data)
        return self.save_slice(data[a:b], expected_digest)

    @staticmethod
    def mapping(source, target, app):
        # Toshy combo notation, not GNOME accelerator notation. Keep code
        # generation constrained and quote all user-provided strings with repr.
        combo = r"(?:[A-Za-z0-9_]+-)*[A-Za-z0-9_]+"
        if not re.fullmatch(combo, source) or not re.fullmatch(combo, target):
            raise SettingsError("Use Toshy combinations such as RC-c or C-Shift-v")
        if not app.strip():
            raise SettingsError("An application class pattern is required")
        try:
            re.compile(app)
        except re.error as exc:
            raise SettingsError(f"Invalid application pattern: {exc}") from exc
        return (f'\n# Added by Desktop Studio — application-specific mapping\n'
                f'keymap("Desktop Studio: " + {app!r}, {{\n'
                f'    C({source!r}): C({target!r}),\n'
                f'}}, when=lambda ctx: cnfg.screen_has_focus and matchProps(cls={app!r})(ctx))\n')

    def literal_mappings(self):
        """Conservative static scan; never import or execute remapping code."""
        if not self.available:
            return []
        tree = ast.parse(self.read()[0])
        mappings = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "keymap" or len(node.args) < 2:
                continue
            name = node.args[0].value if isinstance(node.args[0], ast.Constant) else "Dynamic keymap"
            if not isinstance(node.args[1], ast.Dict):
                continue
            for key in node.args[1].keys:
                if isinstance(key, ast.Call) and isinstance(key.func, ast.Name) and key.func.id == "C" and key.args and isinstance(key.args[0], ast.Constant) and isinstance(key.args[0].value, str):
                    mappings.append((str(name), key.args[0].value, node.lineno))
        return mappings


def toshy_to_gnome(combo):
    parts = combo.split("-")
    aliases = {"c": "Control", "lc": "Control", "rc": "Control", "ctrl": "Control", "s": "Shift", "shift": "Shift", "a": "Alt", "la": "Alt", "ra": "Alt", "alt": "Alt", "super": "Super", "meta": "Super"}
    mods = []
    for part in parts[:-1]:
        mod = aliases.get(part.lower())
        if not mod:
            return ""
        mods.append("<" + mod + ">")
    return "".join(mods) + parts[-1]
