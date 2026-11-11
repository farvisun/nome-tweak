#!/usr/bin/python3
"""Exercise the installed cursor gallery using temporary settings and history."""
import os
from pathlib import Path
import sys
import tempfile

real_icons = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "icons"
private = tempfile.TemporaryDirectory(prefix="desktop-studio-cursor-ui-")
os.environ["GSETTINGS_BACKEND"] = "memory"
os.environ["XDG_DATA_HOME"] = private.name + "/data"
os.environ["XDG_STATE_HOME"] = private.name + "/state"
os.environ["XDG_CONFIG_HOME"] = private.name + "/config"
Path(os.environ["XDG_DATA_HOME"]).mkdir()
(Path(os.environ["XDG_DATA_HOME"]) / "icons").symlink_to(real_icons, target_is_directory=True)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1"); gi.require_version("Gsk", "4.0")
from gi.repository import Gio, GLib, Gsk, Gtk
from desktop_studio.app import DesktopStudio
from desktop_studio.core.settings import Ref
from desktop_studio.platform.cursors import THEMES
from desktop_studio.ui.cursors import collection_dialog
from desktop_studio.ui.widgets import SettingRow

app = DesktopStudio()
app.set_application_id("io.github.desktopstudio.CursorVerification")
app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
errors = []
checks = []
original_hook = sys.excepthook
def hook(typ, value, tb):
    errors.append(str(value)); original_hook(typ, value, tb)
sys.excepthook = hook


def descendants(widget):
    yield widget
    child = widget.get_first_child()
    while child:
        yield from descendants(child)
        child = child.get_next_sibling()


def process():
    while GLib.MainContext.default().pending():
        GLib.MainContext.default().iteration(False)


def exercise():
    try:
        w = app.window
        ref = Ref("org.gnome.desktop.interface", "cursor-theme")
        w.navigate("appearance")
        row = next(x for x in descendants(w) if isinstance(x, SettingRow) and x.ref == ref)
        assert all(name in row.choice_values for name in THEMES)
        checks.append("all 12 installed themes appear in the native selector")
        before = app.registry.state(ref)
        d = collection_dialog(w)
        assert app.registry.state(ref) == before
        assert sum(isinstance(x, Gtk.Picture) for x in descendants(d)) == 36
        checks.append("gallery opens with 36 real cursor images and preserves selection")
        use = next(x for x in descendants(d) if isinstance(x, Gtk.Button) and x.get_label() == "Use this cursor")
        use.emit("clicked"); process()
        assert app.registry.value(ref).unpack() == "Bibata-Modern-Ice"
        assert row.choice_values[row.control.get_selected()] == "Bibata-Modern-Ice"
        checks.append("explicit gallery selection applies and synchronizes the native chooser")
        app.registry.settings(ref).set_string(ref.key, "Bibata-Original-Classic")
        process()
        assert row.choice_values[row.control.get_selected()] == "Bibata-Original-Classic"
        assert sum(isinstance(x, Gtk.Button) and x.get_label() == "Selected" for x in descendants(d)) == 1
        checks.append("external theme edits synchronize the gallery selection")
        GLib.timeout_add(400, lambda: capture(d))
    except Exception as exc:
        import traceback
        traceback.print_exc(); errors.append(str(exc)); app.quit()
    return False


def capture(d):
    try:
        w = app.window
        paintable = Gtk.WidgetPaintable.new(w)
        snap = Gtk.Snapshot()
        paintable.snapshot(snap, w.get_width(), w.get_height())
        texture = w.get_renderer().render_texture(snap.to_node(), None)
        path = Path(__file__).resolve().parent.parent / "artifacts/ryoku-cursor-gallery.png"
        path.parent.mkdir(exist_ok=True)
        texture.save_to_png(str(path))
        d.close()
    except Exception as exc:
        errors.append(str(exc))
    print("Cursor GTK checks:", checks, "Errors:", errors, flush=True)
    app.quit()
    return False


app.connect("activate", lambda _a: GLib.timeout_add(300, exercise))
app.run(["verify_cursors"])
private.cleanup()
raise SystemExit(bool(errors))
