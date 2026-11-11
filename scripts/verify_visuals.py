#!/usr/bin/python3
"""Capture light, dark, and narrow GTK layouts without changing the desktop."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1"); gi.require_version("Gsk", "4.0")
from gi.repository import Adw, Gio, GLib, Gsk, Gtk
from desktop_studio.app import DesktopStudio
from desktop_studio.i18n import is_rtl

app = DesktopStudio()
app.set_application_id("io.github.desktopstudio.VisualVerification")
app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
outdir = Path(__file__).resolve().parent.parent / "artifacts"
outdir.mkdir(exist_ok=True)
captures = iter([
    ("appearance", "dark-appearance.png", Adw.ColorScheme.FORCE_DARK, 1180),
    ("dock", "dock.png", Adw.ColorScheme.FORCE_LIGHT, 1180),
    ("keyboard", "keyboard.png", Adw.ColorScheme.FORCE_LIGHT, 1180),
    ("displays", "displays.png", Adw.ColorScheme.FORCE_LIGHT, 1180),
    ("advanced", "advanced.png", Adw.ColorScheme.FORCE_LIGHT, 1180),
    ("profiles", "profiles.png", Adw.ColorScheme.FORCE_LIGHT, 1180),
    ("appearance", "narrow-appearance.png", Adw.ColorScheme.FORCE_LIGHT, 640),
])
failures = []


def capture(filename):
    try:
        w = app.window
        paintable = Gtk.WidgetPaintable.new(w)
        snap = Gtk.Snapshot()
        paintable.snapshot(snap, w.get_width(), w.get_height())
        node = snap.to_node()
        texture = w.get_renderer().render_texture(node, None)
        texture.save_to_png(str(outdir / (("fa-" if is_rtl() else "") + filename)))
        print(filename, w.get_width(), w.get_height(), "collapsed", w.split.get_collapsed(), flush=True)
    except Exception as exc:
        failures.append(str(exc))
    GLib.idle_add(next_capture)
    return False


def next_capture():
    try:
        page, filename, scheme, width = next(captures)
    except StopIteration:
        app.quit(); return False
    app.get_style_manager().set_color_scheme(scheme)
    app.window.set_default_size(width, 860)
    app.window.navigate(page)
    GLib.timeout_add(450, lambda: capture(filename))
    return False


app.connect("activate", lambda _a: GLib.timeout_add(300, next_capture))
app.run(["verify_visuals"])
print("Visual errors:", failures)
raise SystemExit(bool(failures))
