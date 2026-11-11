#!/usr/bin/python3
"""Exercise actual GTK controls against a memory backend, never the user DB."""
import os
from pathlib import Path
import sys
import tempfile

private = tempfile.TemporaryDirectory(prefix="desktop-studio-ui-")
os.environ["GSETTINGS_BACKEND"] = "memory"
os.environ["XDG_DATA_HOME"] = private.name + "/data"
os.environ["XDG_STATE_HOME"] = private.name + "/state"
os.environ["XDG_CONFIG_HOME"] = private.name + "/config"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1"); gi.require_version("Gsk", "4.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gsk, Gtk
from desktop_studio.app import DesktopStudio
from desktop_studio.core.settings import Ref
from desktop_studio.catalog import SPECS
from desktop_studio.ui.widgets import PlainActionRow, SettingRow
from desktop_studio.ui.profiles import review_dialog
from desktop_studio.ui.keyboard import shortcut_dialog, custom_dialog

app = DesktopStudio()
app.set_application_id("io.github.desktopstudio.ControlVerification")
app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
failures = []
checks = []
original_excepthook = sys.excepthook
def exception_hook(typ, value, traceback):
    failures.append(str(value)); original_excepthook(typ, value, traceback)
sys.excepthook = exception_hook


def descendants(widget):
    yield widget
    child = widget.get_first_child()
    while child:
        yield from descendants(child)
        child = child.get_next_sibling()


def find(root, predicate):
    return next(x for x in descendants(root) if predicate(x))


def click(root, text):
    find(root, lambda x: isinstance(x, Gtk.Button) and x.get_label() == text).emit("clicked")


def process():
    while GLib.MainContext.default().pending():
        GLib.MainContext.default().iteration(False)


def test_controls():
    w = app.window
    try:
        w.navigate("appearance")
        ref = Ref("org.gnome.desktop.interface", "color-scheme")
        row = find(w, lambda x: isinstance(x, SettingRow) and x.ref == ref)
        row.control.set_selected(row.choice_values.index("prefer-dark"))
        assert app.registry.value(ref).unpack() == "prefer-dark"
        checks.append("appearance dropdown applies")
        app.registry.settings(ref).set_string(ref.key, "prefer-light")
        process()
        assert row.choice_values[row.control.get_selected()] == "prefer-light"
        checks.append("external Gio.Settings changes synchronize controls")
        row.reset()
        assert app.registry.state(ref)["user"] is None
        checks.append("reset removes an override")

        w.navigate("dock")
        dropdown = find(w, lambda x: isinstance(x, Gtk.DropDown) and x.get_model().get_item(0).get_string() == "Always visible")
        before = [app.registry.state(Ref("org.gnome.shell.extensions.dash-to-dock", k)) for k in ("dock-fixed", "autohide", "intellihide")]
        dropdown.set_selected(1)
        assert before == [app.registry.state(Ref("org.gnome.shell.extensions.dash-to-dock", k)) for k in ("dock-fixed", "autohide", "intellihide")]
        click(w, "Apply"); process()
        assert [app.registry.value(Ref("org.gnome.shell.extensions.dash-to-dock", k)).unpack() for k in ("dock-fixed", "autohide", "intellihide")] == [False, True, False]
        checks.append("dock grouped changes wait for Apply")

        ref = Ref("org.gnome.desktop.interface", "cursor-size")
        profile = app.profiles.snapshot("Restore appearance", [ref])
        app.registry.settings(ref).set_int(ref.key, 48)
        w.navigate("profiles")
        review = review_dialog(w, profile)
        assert app.registry.value(ref).unpack() == 48
        click(review, "Apply 1 changes"); process()
        assert app.registry.state(ref)["user"] is None
        checks.append("profile preview is inert and Apply restores default state")

        sources = Ref("org.gnome.desktop.input-sources", "sources")
        options = Ref("org.gnome.desktop.input-sources", "xkb-options")
        app.registry.settings(sources).set_value(sources.key, GLib.Variant("a(ss)", [("xkb", "us"), ("xkb", "ir+winkeys")]))
        app.registry.settings(options).set_strv(options.key, ["grp_led:scroll", "grp:caps_toggle"])
        w.navigate("keyboard")
        layout_row = find(w, lambda x: isinstance(x, PlainActionRow) and x.get_subtitle() == "xkb · us")
        find(layout_row, lambda x: isinstance(x, Gtk.Button) and x.get_tooltip_text() == "Move layout down").emit("clicked")
        assert app.registry.value(sources).unpack() == [("xkb", "ir+winkeys"), ("xkb", "us")]
        checks.append("layout reordering preserves English and Persian variants")
        compose_row = find(w, lambda x: isinstance(x, PlainActionRow) and x.get_title() == "Compose key")
        compose = find(compose_row, lambda x: isinstance(x, Gtk.DropDown))
        index = next(i for i in range(compose.get_model().get_n_items()) if compose.get_model().get_item(i).get_string() == "Right Alt")
        compose.set_selected(index); process()
        assert app.registry.value(options).unpack() == ["grp_led:scroll", "grp:caps_toggle", "compose:ralt"]
        checks.append("Compose editing preserves Caps layout switching and other options")
        ref = Ref("org.gnome.desktop.wm.keybindings", "switch-applications")
        shortcut_dialog(w, ref, "Application switching")
        d = w.get_visible_dialog()
        entry = find(d, lambda x: isinstance(x, Adw.EntryRow))
        entry.set_text("")
        click(d, "Record…")
        recording = w.get_visible_dialog()
        receiver = find(recording, lambda x: isinstance(x, Gtk.Box) and x.get_focusable())
        controllers = receiver.observe_controllers()
        controller = next(controllers.get_item(i) for i in range(controllers.get_n_items()) if isinstance(controllers.get_item(i), Gtk.EventControllerKey))
        controller.emit("key-pressed", Gdk.KEY_F11, 0, Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK | Gdk.ModifierType.SHIFT_MASK)
        process()
        assert entry.get_text() == "<Shift><Control><Alt>F11"
        checks.append("shortcut recorder captures and normalizes key events")
        click(d, "Apply"); process()
        assert app.registry.value(ref).unpack() == ["<Shift><Control><Alt>F11"]
        checks.append("shortcut editing applies valid combinations")
        shortcut_dialog(w, ref, "Application switching")
        d = w.get_visible_dialog()
        entry = find(d, lambda x: isinstance(x, Adw.EntryRow))
        entry.set_text("<Alt>F4"); click(d, "Apply")
        assert app.registry.value(ref).unpack() == ["<Shift><Control><Alt>F11"]
        d.close(); process()
        checks.append("shortcut editor rejects conflicts")
        custom_dialog(w)
        d = w.get_visible_dialog()
        entries = {x.get_title(): x for x in descendants(d) if isinstance(x, Adw.EntryRow)}
        entries["Name"].set_text("Test command")
        entries["Command"].set_text("echo desktop-studio")
        entries["Shortcut"].set_text("<Control><Alt><Shift>F10")
        click(d, "Save"); process()
        master = Ref("org.gnome.settings-daemon.plugins.media-keys", "custom-keybindings")
        assert len(app.registry.value(master).unpack()) == 1
        checks.append("custom shortcut creation registers a real instance")
    except Exception as exc:
        import traceback
        traceback.print_exc(); failures.append(str(exc))
    print("CONTROL CHECKS:", *checks, sep="\n- ", flush=True)
    print("FAILURES:", failures, flush=True)
    app.quit()
    return False


app.connect("activate", lambda _a: GLib.timeout_add(250, test_controls))
app.run(["verify_controls"])
private.cleanup()
raise SystemExit(bool(failures))
