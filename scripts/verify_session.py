#!/usr/bin/python3
"""Read-only live GTK/GNOME integration smoke test; never sets a preference."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gsk", "4.0")
from gi.repository import Adw, Gio, GLib, Gtk, Gsk
from desktop_studio.app import DesktopStudio
from desktop_studio.catalog import CATEGORIES, profile_refs
from desktop_studio.core.settings import Ref
from desktop_studio.ui.widgets import show_setting_dialog
from desktop_studio.ui.profiles import review_dialog


app = DesktopStudio()
app.set_application_id("io.github.desktopstudio.Verification")
app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
refs = profile_refs(app.registry)
before = {r.token: app.registry.state(r) for r in refs}
toshy_before = app.toshy.read()[1] if app.toshy.available else None
display_before = app.displays.read()[0]
extensions_before = {k: v.get("enabled") for k, v in app.extensions.list().items()}
errors = []
changes_detected = False
outdir = Path(__file__).resolve().parent.parent / "artifacts"
outdir.mkdir(exist_ok=True)
original_excepthook = sys.excepthook
def exception_hook(typ, value, traceback):
    errors.append(str(value)); original_excepthook(typ, value, traceback)
sys.excepthook = exception_hook
pages = iter(CATEGORIES)


def screenshot(name):
    try:
        window = app.window
        paintable = Gtk.WidgetPaintable.new(window)
        snap = Gtk.Snapshot()
        paintable.snapshot(snap, window.get_width(), window.get_height())
        node = snap.to_node()
        if node:
            texture = window.get_renderer().render_texture(node, None)
            texture.save_to_png(str(outdir / name))
    except Exception as exc:
        print("Screenshot:", exc)


def next_page():
    try:
        cat = next(pages)
        app.window.navigate(cat.id)
        print("PAGE", cat.id, flush=True)
        if cat.id == "appearance":
            GLib.timeout_add(180, lambda: (screenshot("appearance.png"), False)[1])
        if cat.id == "overview":
            GLib.timeout_add(180, lambda: (screenshot("overview.png"), False)[1])
        return True
    except StopIteration:
        try:
            state = app.displays.read()
            app.displays.verify(state, app.displays.draft(state))
            print("DISPLAY current layout verified without applying")
            extensions = app.extensions.list()
            print("EXTENSIONS", len(extensions))
            print("TOSHY", app.toshy.status(), "literal mappings", len(app.toshy.literal_mappings()))
            app.window.search.set_text("Persian")
            app.window.run_search()
            print("GLOBAL SEARCH rendered")
            from desktop_studio.catalog import Spec
            ref = Ref("org.gnome.desktop.interface", "color-scheme")
            d = show_setting_dialog(app.window, Spec("appearance", "", ref, "Appearance"))
            d.close()
            d = review_dialog(app.window, app.profiles.mac_style())
            d.close()
            print("EDIT AND PROFILE REVIEW opened and closed without applying")
        except Exception as exc:
            errors.append(str(exc))
        GLib.timeout_add(600, finish)
        return False
    except Exception as exc:
        errors.append(str(exc)); return True


def finish():
    global changes_detected
    after = {r.token: app.registry.state(r) for r in refs}
    changes = [key for key in before if before[key] != after.get(key)]
    toshy_after = app.toshy.read()[1] if app.toshy.available else None
    extension_after = {k: v.get("enabled") for k, v in app.extensions.list().items()}
    report = {"pages": len(CATEGORIES), "errors": errors, "settings_checked": len(refs), "settings_changed": changes, "shell": app.env.shell_version,
              "toshy_config_unchanged": toshy_before == toshy_after,
              "display_serial_unchanged": display_before == app.displays.read()[0],
              "extensions_unchanged": extensions_before == extension_after}
    changes_detected = bool(changes) or not all(report[k] for k in ("toshy_config_unchanged", "display_serial_unchanged", "extensions_unchanged"))
    (outdir / "session-verification.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2), flush=True)
    app.quit()
    return False


def activated(_a):
    GLib.timeout_add(450, next_page)
app.connect("activate", activated)
app.run(["verify_session"])
raise SystemExit(1 if errors or changes_detected else 0)
