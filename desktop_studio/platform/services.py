"""Small, bounded platform operations; never run the application as root."""
from pathlib import Path
import json
import hashlib
from functools import lru_cache
import re
import os
import shutil
import subprocess
import threading

from gi.repository import Gio, GLib
try:
    from gi.repository import GioUnix
    DesktopAppInfo = GioUnix.DesktopAppInfo
except ImportError:
    DesktopAppInfo = Gio.DesktopAppInfo

from ..core.settings import SettingsError


def run(argv, timeout=12):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode:
        raise SettingsError((result.stderr or result.stdout or f"{argv[0]} failed").strip()[:1800])
    return result.stdout.strip()


def background(work, done, error):
    def worker():
        try:
            result = work()
            GLib.idle_add(lambda: (done(result), False)[1])
        except Exception as exc:
            message = str(exc)
            GLib.idle_add(lambda: (error(message), False)[1])
    threading.Thread(target=worker, daemon=True).start()


@lru_cache(maxsize=1)
def settings_panels():
    if not shutil.which("gnome-control-center"):
        raise SettingsError("GNOME Settings is not installed")
    output = run(["gnome-control-center", "--list"], timeout=5)
    return {line.strip() for line in output.splitlines() if re.fullmatch(r"[a-z][a-z0-9-]*", line.strip())}


def settings_argv(panel, available=None):
    available = settings_panels() if available is None else available
    if panel in available:
        return ["gnome-control-center", panel]
    if panel in ("region", "datetime") and "system" in available:
        return ["gnome-control-center", "system", panel]
    if panel == "default-apps" and "applications" in available:
        return ["gnome-control-center", "applications"]
    raise SettingsError(f"This GNOME Settings installation has no {panel} page")


def open_settings(panel):
    # GNOME 50 moved region/date pages into System, and default apps into
    # Applications. Inspect installed panel IDs instead of assuming old routes.
    Gio.Subprocess.new(settings_argv(panel), Gio.SubprocessFlags.NONE)


def open_uri(uri):
    Gio.AppInfo.launch_default_for_uri(str(uri), None)


def launch(argv):
    if not shutil.which(argv[0]):
        raise SettingsError(f"{argv[0]} is not installed")
    Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE)


def dbus_proxy(name, path, interface, system=False):
    return Gio.DBusProxy.new_for_bus_sync(
        Gio.BusType.SYSTEM if system else Gio.BusType.SESSION,
        Gio.DBusProxyFlags.NONE if name == "org.gnome.Shell.Extensions" else Gio.DBusProxyFlags.DO_NOT_AUTO_START,
        None, name, path, interface, None,
    )


def call(proxy, method, signature=None, args=(), timeout=5000):
    if not proxy.get_name_owner() and proxy.get_name() != "org.gnome.Shell.Extensions":
        raise SettingsError(f"{proxy.get_interface_name()} is not running")
    try:
        result = proxy.call_sync(method, GLib.Variant(signature, args) if signature else None, Gio.DBusCallFlags.NONE, timeout, None)
        return result.unpack() if result else ()
    except GLib.Error as exc:
        raise SettingsError(exc.message) from exc


class Environment:
    def __init__(self):
        self.os = GLib.get_os_info("PRETTY_NAME") or "Linux"
        self.session = os.environ.get("XDG_SESSION_TYPE", "unknown")
        self.desktop = os.environ.get("XDG_CURRENT_DESKTOP", "unknown")
        self.shell_version = "Unknown"
        try:
            ext = dbus_proxy("org.gnome.Shell.Extensions", "/org/gnome/Shell/Extensions", "org.gnome.Shell.Extensions")
            value = ext.get_cached_property("ShellVersion")
            if value:
                self.shell_version = value.unpack()
        except GLib.Error:
            pass
        self.input_devices = []
        # udev properties can be read without opening privileged input devices.
        for path in Path("/run/udev/data").glob("c13:*"):
            try:
                props = dict(line[2:].split("=", 1) for line in path.read_text().splitlines() if line.startswith("E:") and "=" in line)
                if any(props.get(k) == "1" for k in ("ID_INPUT_MOUSE", "ID_INPUT_TOUCHPAD", "ID_INPUT_KEYBOARD")):
                    self.input_devices.append(props)
            except OSError:
                pass

    def has_input(self, kind):
        return any(p.get("ID_INPUT_" + kind.upper()) == "1" for p in self.input_devices)


class Extensions:
    STATES = {1: "Enabled", 2: "Disabled", 3: "Runtime error", 4: "Incompatible", 5: "Downloading", 6: "Initialized", 99: "Not installed"}

    def __init__(self):
        self.proxy = dbus_proxy("org.gnome.Shell.Extensions", "/org/gnome/Shell/Extensions", "org.gnome.Shell.Extensions")

    def list(self):
        return call(self.proxy, "ListExtensions")[0]

    def enable(self, uuid, enabled, expected):
        current = self.list().get(uuid, {})
        if current.get("state") != expected:
            raise SettingsError("Extension state changed elsewhere; refresh before changing it")
        accepted = call(self.proxy, "EnableExtension" if enabled else "DisableExtension", "(s)", (uuid,))
        if not accepted[0]:
            raise SettingsError("GNOME Shell rejected this extension change. Check its compatibility and errors.")

    def preferences(self, uuid):
        call(self.proxy, "OpenExtensionPrefs", "(ssa{sv})", (uuid, "", {}))

    def errors(self, uuid):
        return call(self.proxy, "GetExtensionErrors", "(s)", (uuid,))[0]


class Connections:
    def __init__(self):
        self.network_proxy = None
        self.bluetooth_proxy = None

    def network(self):
        if self.network_proxy is None:
            self.network_proxy = dbus_proxy("org.freedesktop.NetworkManager", "/org/freedesktop/NetworkManager", "org.freedesktop.NetworkManager", True)
        proxy = self.network_proxy
        if not proxy.get_name_owner():
            raise SettingsError("NetworkManager is not available")
        return {name: proxy.get_cached_property(name).unpack() for name in ("NetworkingEnabled", "WirelessEnabled", "State") if proxy.get_cached_property(name) is not None}

    def set_network(self, field, enabled, expected):
        if self.network().get(field) != expected:
            raise SettingsError("Network state changed elsewhere; refresh first")
        proxy = dbus_proxy("org.freedesktop.NetworkManager", "/org/freedesktop/NetworkManager", "org.freedesktop.NetworkManager", True)
        if field == "NetworkingEnabled":
            call(proxy, "Enable", "(b)", (enabled,))
        elif field == "WirelessEnabled":
            props = dbus_proxy("org.freedesktop.NetworkManager", "/org/freedesktop/NetworkManager", "org.freedesktop.DBus.Properties", True)
            call(props, "Set", "(ssv)", ("org.freedesktop.NetworkManager", field, GLib.Variant("b", enabled)))

    def bluetooth(self):
        if self.bluetooth_proxy is None:
            self.bluetooth_proxy = dbus_proxy("org.bluez", "/", "org.freedesktop.DBus.ObjectManager", True)
        proxy = self.bluetooth_proxy
        objects = call(proxy, "GetManagedObjects")[0]
        return [(path, interfaces["org.bluez.Adapter1"]) for path, interfaces in objects.items() if "org.bluez.Adapter1" in interfaces]

    def set_bluetooth(self, path, enabled, expected):
        adapters = dict(self.bluetooth())
        if adapters.get(path, {}).get("Powered") != expected:
            raise SettingsError("Bluetooth state changed elsewhere; refresh first")
        props = dbus_proxy("org.bluez", path, "org.freedesktop.DBus.Properties", True)
        call(props, "Set", "(ssv)", ("org.bluez.Adapter1", "Powered", GLib.Variant("b", enabled)))


class Audio:
    @property
    def available(self):
        return shutil.which("wpctl") is not None

    def volume(self):
        return run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])

    def set_volume(self, fraction, expected):
        if self.volume() != expected:
            raise SettingsError("Volume changed elsewhere; refresh first")
        if not 0 <= fraction <= 1:
            raise SettingsError("Volume must be between 0 and 100%")
        run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", str(fraction)])

    def mute(self, muted, expected):
        if self.volume() != expected:
            raise SettingsError("Volume changed elsewhere; refresh first")
        run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1" if muted else "0"])


def theme_names(kind):
    names = set()
    if kind in ("icons", "cursors"):
        roots = [Path.home() / ".icons", Path(GLib.get_user_data_dir()) / "icons", *(Path(p) / "icons" for p in GLib.get_system_data_dirs())]
    else:
        roots = [Path.home() / ".themes", Path(GLib.get_user_data_dir()) / "themes", *(Path(p) / "themes" for p in GLib.get_system_data_dirs())]
    for root in roots:
        if not root.exists():
            continue
        for path in root.iterdir():
            if not path.is_dir():
                continue
            marker = "cursors" if kind == "cursors" else "gnome-shell" if kind == "shell-themes" else "gtk-3.0" if kind == "themes" else "index.theme"
            if (path / marker).exists():
                names.add(path.name)
    return sorted(names, key=str.casefold)


class StartupApps:
    def __init__(self):
        self.user = Path(GLib.get_user_config_dir()) / "autostart"

    def list(self):
        files = {}
        for root in [*(Path(x) / "autostart" for x in GLib.get_system_config_dirs()), self.user]:
            for path in root.glob("*.desktop"):
                files[path.name] = path
        apps = []
        for name, path in sorted(files.items()):
            kf = GLib.KeyFile()
            try:
                kf.load_from_file(str(path), GLib.KeyFileFlags.KEEP_COMMENTS | GLib.KeyFileFlags.KEEP_TRANSLATIONS)
                group = "Desktop Entry"
                keys = kf.get_keys(group)[0]
                title = kf.get_locale_string(group, "Name", None)
                hidden = "Hidden" in keys and kf.get_boolean(group, "Hidden")
                enabled = not hidden and ("X-GNOME-Autostart-enabled" not in keys or kf.get_boolean(group, "X-GNOME-Autostart-enabled"))
                only = kf.get_string_list(group, "OnlyShowIn") if "OnlyShowIn" in keys else []
                desktop = set(os.environ.get("XDG_CURRENT_DESKTOP", "").split(":"))
                if only and not desktop.intersection(only):
                    continue
                apps.append((path, title, enabled, path.read_bytes()))
            except (GLib.Error, OSError):
                continue
        return apps

    def set_enabled(self, path, enabled, expected_bytes, backup_dir):
        if path.read_bytes() != expected_bytes:
            raise SettingsError("This startup entry changed elsewhere; refresh first")
        self.user.mkdir(parents=True, exist_ok=True)
        destination = self.user / path.name
        if destination != path and destination.exists():
            raise SettingsError("A user override was created elsewhere; refresh first")
        kf = GLib.KeyFile()
        kf.load_from_data(expected_bytes.decode("utf-8"), len(expected_bytes), GLib.KeyFileFlags.KEEP_COMMENTS | GLib.KeyFileFlags.KEEP_TRANSLATIONS)
        kf.set_boolean("Desktop Entry", "Hidden", not enabled)
        kf.set_boolean("Desktop Entry", "X-GNOME-Autostart-enabled", enabled)
        data = kf.to_data()[0]
        return self._write(destination, data, expected_bytes if destination == path else None, backup_dir)

    def add(self, app, backup_dir):
        if not isinstance(app, DesktopAppInfo) or not app.get_filename():
            raise SettingsError("This application has no desktop launcher")
        destination = self.user / ("desktop-studio-" + Path(app.get_filename()).name)
        if destination.exists():
            raise SettingsError("This application already has a Desktop Studio startup entry")
        kf = GLib.KeyFile()
        kf.load_from_file(app.get_filename(), GLib.KeyFileFlags.KEEP_TRANSLATIONS)
        kf.set_boolean("Desktop Entry", "Hidden", False)
        kf.set_boolean("Desktop Entry", "X-GNOME-Autostart-enabled", True)
        return self._write(destination, kf.to_data()[0], None, backup_dir)

    def _write(self, destination, data, original, backup_dir):
        from ..core.profiles import atomic_json
        import uuid
        self.user.mkdir(parents=True, exist_ok=True)
        backup = Path(backup_dir) / ("startup-" + uuid.uuid4().hex + ".json")
        atomic_json(backup, {"path": str(destination), "original": original.decode("utf-8") if original is not None else None, "applied_sha256": hashlib.sha256(data.encode()).hexdigest()})
        actual = destination.read_bytes() if destination.exists() else None
        if actual != original:
            raise SettingsError("The startup entry changed while preparing the backup")
        temp = destination.with_suffix(".desktop.tmp")
        temp.write_text(data)
        temp.chmod(0o600)
        os.replace(temp, destination)
        return backup

    def restore(self, backup):
        document = json.loads(Path(backup).read_text())
        destination = Path(document["path"])
        if destination.parent != self.user or destination.suffix != ".desktop":
            raise SettingsError("This backup is not a user startup entry")
        actual = destination.read_bytes() if destination.exists() else b""
        if hashlib.sha256(actual).hexdigest() != document["applied_sha256"]:
            raise SettingsError("This startup entry changed after the recorded operation")
        if document["original"] is None:
            destination.unlink()
        else:
            temp = destination.with_suffix(".desktop.tmp")
            temp.write_text(document["original"])
            temp.chmod(0o600)
            os.replace(temp, destination)
