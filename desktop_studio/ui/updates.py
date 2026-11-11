"""GitHub Release checks and user-controlled downloads."""
from datetime import datetime

from gi.repository import Gtk

from .. import __version__
from ..i18n import _
from ..platform.services import open_uri
from .widgets import action_row, button, dialog, group, info_box, label, text_editor


def updates_dialog(window):
    app = window.get_application()
    prefs = app.update_checker.preferences
    prefs.reload()
    d, content, header = dialog(window, _("Software Updates"), 780, 720)
    content.append(label(_("Keep Desktop Studio up to date"), "title-2"))
    content.append(info_box(_("Updates are checked against stable published GitHub Releases. Downloads and installation are always your choice. Desktop settings, profiles, remapping configuration, and installed cursor themes are preserved.")))
    status = group(_("Installed version"))
    status.add(action_row(_("Desktop Studio"), __version__))
    content.append(status)
    source = group(_("Release source"), _("Enter owner/repository or its GitHub URL. Private repositories need GitHub CLI sign-in on this computer; credentials are never stored in Desktop Studio."))
    repository = Gtk.Entry(text=prefs.repository, hexpand=True, placeholder_text=_("owner/repository"))
    repository.update_property([Gtk.AccessibleProperty.LABEL], [_("GitHub release repository")])
    source_row = action_row(_("GitHub repository"))
    source_row.add_suffix(repository)
    save = button(label=_("Save source"))
    source_row.add_suffix(save)
    source.add(source_row)
    automatic = Gtk.Switch(active=prefs.automatic, valign=Gtk.Align.CENTER)
    auto_row = action_row(_("Check automatically"), _("At most once per day while Desktop Studio is open. No background service is installed."))
    auto_row.add_suffix(automatic)
    source.add(auto_row)
    content.append(source)
    error = label(prefs.warning, "error")
    content.append(error)
    result_group = group(_("Update status"))
    content.append(result_group)
    rows = []
    state = {"revision": prefs.revision, "freeze": False, "closed": False}
    check = button(label=_("Check now"), css="suggested-action")
    header.pack_end(check)
    notes_box, notes = text_editor("", monospace=False, height=150)
    notes.set_editable(False)
    notes.set_cursor_visible(False)
    notes.update_property([Gtk.AccessibleProperty.LABEL], [_("Release notes")])
    notes_box.set_visible(False)
    content.append(notes_box)

    def render(*_args):
        for row in rows:
            result_group.remove(row)
        rows.clear()
        notes_box.set_visible(False)
        check.set_sensitive(bool(prefs.repository) and not app.update_busy)
        save.set_sensitive(not app.update_busy)
        automatic.set_sensitive(not app.update_busy)
        result = app.update_result
        if result is not None and result.repository != prefs.repository:
            result = None
        if app.update_busy:
            row = action_row(_("Checking GitHub…"), _("You can continue using the application."))
            spinner = Gtk.Spinner(spinning=True, valign=Gtk.Align.CENTER)
            row.add_suffix(spinner)
        elif not prefs.repository:
            row = action_row(_("Choose a release source"), _("Save the GitHub repository that publishes Desktop Studio releases, then check for updates."))
        elif result is None:
            last = app.update_checker.last_state().get("last_attempt")
            try:
                description = _("Last check: ") + datetime.fromtimestamp(last).strftime("%Y-%m-%d %H:%M") if isinstance(last, (int, float)) else _("No release check has run in this session.")
            except (ValueError, OSError, OverflowError):
                description = _("No valid previous check time.")
            row = action_row(_("Ready to check"), description)
        elif result.available:
            row = action_row(_("Desktop Studio {version} is available").format(version=result.release.version), _("Installed: ") + result.current + "\n" + _("Published: ") + result.release.published)
        elif result.status == "up-to-date":
            row = action_row(_("You’re up to date"), _("Latest stable release: ") + result.release.version)
        else:
            row = action_row(_("Update check needs attention"), result.message)
        result_group.add(row); rows.append(row)
        if result and result.release and not app.update_busy:
            release = result.release
            links = action_row(_("GitHub Release"), release.tag)
            links.add_suffix(button(label=_("View release"), callback=lambda: window.safe(lambda: open_uri(release.url))))
            # Prefer the format for the active installation so a user install
            # does not accidentally shadow a newly installed system package.
            from ..app import ROOT
            user_install = (ROOT / ".desktop-studio-install").exists()
            if user_install and release.archive_url:
                links.add_suffix(button(label=_("Download user installer"), callback=lambda: window.safe(lambda: open_uri(release.archive_url))))
            elif release.deb_url:
                links.add_suffix(button(label=_("Download .deb"), callback=lambda: window.safe(lambda: open_uri(release.deb_url))))
            elif release.archive_url:
                links.add_suffix(button(label=_("Download user installer"), callback=lambda: window.safe(lambda: open_uri(release.archive_url))))
            result_group.add(links); rows.append(links)
            if release.notes:
                notes.get_buffer().set_text(release.notes)
                notes_box.set_visible(True)
    def save_source():
        try:
            prefs.save(repository.get_text(), prefs.automatic, state["revision"])
            state["revision"] = prefs.revision
            repository.set_text(prefs.repository)
            error.set_label("")
            app.update_result = None
            render()
            window.toast(_("Release source saved"))
        except Exception as exc:
            error.set_label(str(exc))
    def toggle(s, _param):
        if state["freeze"]:
            return
        try:
            prefs.save(prefs.repository, s.get_active(), state["revision"])
            state["revision"] = prefs.revision
            error.set_label("")
        except Exception as exc:
            state["freeze"] = True
            s.set_active(prefs.automatic)
            state["freeze"] = False
            error.set_label(str(exc))
    automatic.connect("notify::active", toggle)
    save.connect("clicked", lambda _b: save_source())
    repository.connect("activate", lambda _e: save_source())
    check.connect("clicked", lambda _b: app.check_software_updates(manual=True))
    content.append(info_box(_("For a user installation, extract the downloaded Linux archive and run /usr/bin/python3 scripts/install.py from it. For a Debian package installation, open the .deb with Ubuntu’s package installer. Restart Desktop Studio after upgrading.")))
    handler = app.connect("updates-checked", render)
    def closed(_d):
        state["closed"] = True
        app.disconnect(handler)
    d.connect("closed", closed)
    render()
    d.present(window)
    return d
