"""Wayland display configuration through Mutter's discovered D-Bus interface.

Persistent method 2 invokes GNOME Shell's compositor-owned confirmation dialog
and automatic timeout/revert. It remains safe if Desktop Studio exits or crashes.
"""
from copy import deepcopy

from gi.repository import GLib

from ..core.settings import ConflictError, SettingsError
from .services import dbus_proxy, call


class Displays:
    def __init__(self, proxy=None):
        self.proxy = proxy or dbus_proxy("org.gnome.Mutter.DisplayConfig", "/org/gnome/Mutter/DisplayConfig", "org.gnome.Mutter.DisplayConfig")

    def read(self):
        return call(self.proxy, "GetCurrentState")

    @staticmethod
    def draft(state):
        serial, monitors, logicals, properties = state
        monitor_map = {m[0][0]: m for m in monitors}
        groups = []
        for x, y, scale, transform, primary, specs, props in logicals:
            members = []
            for spec in specs:
                _, modes, mprops = monitor_map[spec[0]]
                current = next((m for m in modes if m[6].get("is-current")), None)
                if not current:
                    raise SettingsError(f"No current mode reported for {spec[0]}")
                keep = {}
                for prop, typ in (("color-mode", "u"), ("underscanning", "b"), ("rgb-range", "u")):
                    if prop in mprops:
                        keep[prop] = GLib.Variant(typ, mprops[prop])
                members.append((spec[0], current[0], keep))
            groups.append([x, y, scale, transform, primary, members])
        return groups

    @staticmethod
    def validate_draft(state, draft):
        monitors = {m[0][0]: m for m in state[1]}
        if not draft or sum(bool(g[4]) for g in draft) != 1:
            raise SettingsError("Enable at least one display and choose exactly one primary display")
        used = set()
        for x, y, scale, transform, primary, members in draft:
            if not isinstance(x, int) or not isinstance(y, int) or x < 0 or y < 0 or x > 65535 or y > 65535:
                raise SettingsError("Display coordinates must be whole numbers from 0 to 65535")
            if transform not in range(8) or not members:
                raise SettingsError("Invalid display orientation or empty monitor group")
            for connector, mode_id, props in members:
                if connector in used or connector not in monitors:
                    raise SettingsError("A display is repeated or no longer connected")
                used.add(connector)
                mode = next((m for m in monitors[connector][1] if m[0] == mode_id), None)
                if mode is None or not any(abs(scale - s) < 0.00001 for s in mode[5]):
                    raise SettingsError(f"Unsupported mode or scaling for {connector}")
        if state[3].get("global-scale-required") and len({g[2] for g in draft}) > 1:
            raise SettingsError("This session requires the same scale on every display")

    def verify(self, state, draft):
        return self._apply(state, draft, 0)

    def apply_with_confirmation(self, state, draft):
        allowed = self.proxy.get_cached_property("ApplyMonitorsConfigAllowed")
        if allowed is not None and not allowed.unpack():
            raise SettingsError("Display changes are disabled by policy")
        self.verify(state, draft)
        # Re-read the serial after verification, never overwrite a newer layout.
        return self._apply(state, draft, 2)

    def _apply(self, state, draft, method):
        if self.read()[0] != state[0]:
            raise ConflictError("Display configuration changed elsewhere. Reload before applying.")
        self.validate_draft(state, draft)
        properties = {}
        if state[3].get("supports-changing-layout-mode") and "layout-mode" in state[3]:
            properties["layout-mode"] = GLib.Variant("u", state[3]["layout-mode"])
        return call(self.proxy, "ApplyMonitorsConfig", "(uua(iiduba(ssa{sv}))a{sv})", (state[0], method, draft, properties), 10000)
