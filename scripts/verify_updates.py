#!/usr/bin/python3
"""Exercise update UI with simulated releases and private temporary app state."""
import json
import os
from pathlib import Path
import sys
import tempfile

private = tempfile.TemporaryDirectory(prefix="desktop-studio-updates-ui-")
os.environ["GSETTINGS_BACKEND"] = "memory"
for key, subdir in (("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state"), ("XDG_CONFIG_HOME", "config")):
    os.environ[key] = private.name + "/" + subdir
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1"); gi.require_version("Gsk", "4.0")
from gi.repository import Gio, GLib, Gsk, Gtk
from desktop_studio.app import DesktopStudio
from desktop_studio.platform.updates import UpdateChecker, UpdateError, UpdatePreferences
from desktop_studio.ui.updates import updates_dialog
from desktop_studio.ui.widgets import PlainActionRow

app = DesktopStudio()
app.set_application_id("io.github.desktopstudio.UpdateVerification")
app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
source = Path(private.name) / "source.json"
source.write_text(json.dumps({"version": 1, "repository": "example/desktop-studio"}))
prefs = UpdatePreferences(Path(private.name) / "preferences", source)
calls = []
response = {"tag_name": "v9.0.0", "draft": False, "prerelease": False, "published_at": "2026-11-12T00:00:00Z", "body": "A simulated newer release for GTK verification.", "assets": []}
def transport(repo):
    calls.append(repo)
    return response
app.update_checker = UpdateChecker(prefs, Path(private.name) / "update-state", transport=transport)
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


def click(root, text):
    next(w for w in descendants(root) if isinstance(w, Gtk.Button) and w.get_label() == text).emit("clicked")


def started():
    try:
        app.test_dialog = updates_dialog(app.window)
        assert not calls
        checks.append("opening Software Updates does not initiate a network request")
        click(app.test_dialog, "Check now")
        assert app.update_busy
        GLib.timeout_add(400, available)
    except Exception as exc:
        errors.append(str(exc)); app.quit()
    return False


def available():
    try:
        assert not app.update_busy
        assert app.update_result.available
        assert len(calls) == 1
        assert any(isinstance(w, PlainActionRow) and w.get_title() == "Desktop Studio 9.0.0 is available" for w in descendants(app.test_dialog))
        checks.append("Check now renders a newer release and release notes")
        paintable = Gtk.WidgetPaintable.new(app.window)
        snap = Gtk.Snapshot()
        paintable.snapshot(snap, app.window.get_width(), app.window.get_height())
        image = app.window.get_renderer().render_texture(snap.to_node(), None)
        dest = Path(__file__).resolve().parent.parent / "artifacts/software-updates.png"
        dest.parent.mkdir(exist_ok=True)
        image.save_to_png(str(dest))
        def offline(_repo): raise UpdateError("offline", "Simulated offline check")
        app.update_checker.transport = offline
        click(app.test_dialog, "Check now")
        GLib.timeout_add(400, offline_finished)
    except Exception as exc:
        errors.append(str(exc)); app.quit()
    return False


def offline_finished():
    try:
        assert app.update_result.status == "offline"
        assert any(isinstance(w, PlainActionRow) and w.get_title() == "Update check needs attention" for w in descendants(app.test_dialog))
        checks.append("offline errors are visible and cannot appear as up to date")
        row = next(w for w in descendants(app.test_dialog) if isinstance(w, PlainActionRow) and w.get_title() == "Check automatically")
        toggle = next(w for w in descendants(row) if isinstance(w, Gtk.Switch))
        toggle.set_active(False)
        assert not prefs.automatic
        assert not json.loads(prefs.path.read_text())["automatic"]
        checks.append("automatic checks can be disabled without changing GNOME settings")
        app.test_dialog.close()
    except Exception as exc:
        errors.append(str(exc))
    print("Update GTK checks:", checks, "Errors:", errors, flush=True)
    app.quit()
    return False


app.connect("activate", lambda _a: GLib.timeout_add(250, started))
app.run(["verify_updates"])
private.cleanup()
raise SystemExit(bool(errors))
