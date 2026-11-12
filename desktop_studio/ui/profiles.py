from pathlib import Path
import re

from gi.repository import Adw, Gio, GLib, Gtk

from ..catalog import CATEGORIES, CATEGORY_MAP, SPECS, category_for, profile_refs
from ..core.settings import Ref, SettingsError
from ..core.profiles import atomic_json
from ..i18n import _, n_
from ..platform.services import open_uri
from .widgets import action_row, button, clock_time, day_heading, dialog, friendly_time, group, info_box, label, pill

PROFILE_CATEGORIES = [c for c in CATEGORIES if c.id not in ("overview", "advanced", "profiles", "history")]


def category_chooser(content, selected=None, changed=None):
    g = group(_("Include categories"))
    content.append(g)
    boxes = {}
    flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, min_children_per_line=1, max_children_per_line=3, column_spacing=18, row_spacing=10, margin_top=10)
    for cat in PROFILE_CATEGORIES:
        cb = Gtk.CheckButton(label=cat.title, active=selected is None or cat.id in selected)
        flow.append(cb); boxes[cat.id] = cb
        if changed:
            cb.connect("toggled", lambda *_a: changed())
    g.add(flow)
    return lambda: {k for k, cb in boxes.items() if cb.get_active()}


def build(w, content):
    content.append(info_box(_("Profiles contain versioned GSettings values and override state. Selecting one opens a comparison; nothing applies automatically. Commands, credentials, connection stores, and Toshy source are excluded. Hardware displays and service state are managed separately.")))
    g = group(_("Create & import"))
    g.add(action_row(_("Save current configuration"), _("Name a profile and choose the categories to include."), lambda: save_current(w), "document-save-symbolic"))
    g.add(action_row(_("Import a profile"), _("Open a Desktop Studio JSON file for review. Unavailable settings are skipped with an explanation."), lambda: import_profile(w), "document-open-symbolic"))
    content.append(g)
    optional = group(_("Optional starting points"), _("Presets are previews. Your keyboard layouts and remapping setup are not changed by the Mac-style preset."))
    optional.add(action_row(_("Mac-style desktop"), _("Bottom dock, always visible, compact length, and title-bar buttons on the left."), lambda: review_dialog(w, w.profiles.mac_style())))
    def defaults():
        refs = [s.ref for s in SPECS if w.registry.exists(s.ref)]
        review_dialog(w, w.profiles.defaults(refs), selected={"appearance", "windows"})
    optional.add(action_row(_("GNOME schema defaults"), _("Defaults from your installed schemas, which may include Ubuntu adjustments. Choose categories before applying."), defaults))
    content.append(optional)
    saved = group(_("Saved profiles"), _("Compare a profile with your current desktop before applying any of it."))
    saved.set_header_suffix(button(icon="folder-open-symbolic", callback=lambda: w.safe(lambda: open_uri(w.profiles.directory.as_uri())), tooltip=_("Open profile folder"), css="flat"))
    content.append(saved)
    profiles = w.profiles.list()
    backups = [(path, p) for path, p in profiles if p["name"].startswith("Automatic backup")]
    named = [(path, p) for path, p in profiles if not p["name"].startswith("Automatic backup")]
    for path, profile in named:
        saved.add(profile_row(w, path, profile))
    if not named:
        saved.add(action_row(_("No saved profiles"), _("Use Save current configuration to create one.")))
    if backups:
        history = group(_("Automatic backups"), _("Created before every grouped change, profile application, and undo."))
        expander = Adw.ExpanderRow(title=n_("{count} backup", "{count} backups", len(backups)).format(count=len(backups)), subtitle=_("Latest: ") + friendly_time(backups[0][1].get("created", "")))
        for path, profile in backups[:30]:
            expander.add_row(profile_row(w, path, profile, backup=True))
        history.add(expander)
        content.append(history)


def profile_row(w, path, profile, backup=False):
    initial = path.name == "initial-snapshot.json"
    title = friendly_time(profile.get("created", "")) if backup else profile["name"]
    count = len(profile["settings"])
    subtitle = n_("{count} setting", "{count} settings", count).format(count=count)
    if not backup:
        subtitle += " · " + friendly_time(profile.get("created", ""))
    row = action_row(title, subtitle, icon=None if backup else ("security-high-symbolic" if initial else "document-save-symbolic"))
    if initial:
        row.add_suffix(pill(_("Restore point"), "accent", _("Captured the first time Desktop Studio opened")))
    review = button(label=_("Compare…"), callback=lambda: review_dialog(w, profile), css="flat")
    row.add_suffix(review); row.set_activatable_widget(review)
    row.add_suffix(button(icon="document-send-symbolic", callback=lambda: export_profile(w, profile), tooltip=_("Export…"), css="flat circular row-action"))
    if not initial:
        row.add_suffix(button(icon="user-trash-symbolic", callback=lambda: delete_profile(w, path, title), tooltip=_("Delete…"), css="flat circular row-action"))
    return row


def delete_profile(w, path, title):
    d = Adw.AlertDialog(heading=_("Delete “{name}”?").format(name=title), body=_("The profile file is removed. Your current desktop settings are not changed."))
    d.add_response("cancel", _("Cancel"))
    d.add_response("delete", _("Delete"))
    d.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
    d.set_default_response("cancel"); d.set_close_response("cancel")
    def response(_d, answer):
        if answer == "delete":
            w.safe(lambda: w.profiles.delete(path), lambda _r: (w.toast(_("Profile deleted")), w.render("profiles")))
    d.connect("response", response)
    d.present(w)


def save_current(w):
    d, content, header = dialog(w, _("Save current configuration"), 760, 540)
    g = group(_("Profile"))
    name = Adw.EntryRow(title=_("Name"), text=_("My desktop")); g.add(name); content.append(g)
    categories = category_chooser(content)
    error = label("", "error"); content.append(error)
    def save():
        try:
            refs = [r for r in profile_refs(w.registry) if category_for(r) in categories()]
            if not refs:
                raise SettingsError(_("Select at least one category."))
            profile = w.profiles.snapshot(name.get_text().strip(), refs)
            w.profiles.save(profile)
            d.close(); w.toast(_("Profile saved")); w.render("profiles")
        except Exception as exc:
            error.set_label(str(exc))
    header.pack_end(button(label=_("Save profile"), callback=save, css="suggested-action")); d.present(w)


def import_profile(w):
    chooser = Gtk.FileDialog(title=_("Import Desktop Studio profile"))
    filters = Gio.ListStore.new(Gtk.FileFilter)
    f = Gtk.FileFilter(name=_("JSON profiles")); f.add_pattern("*.json"); filters.append(f)
    chooser.set_filters(filters)
    def selected(d, result):
        try:
            file = d.open_finish(result)
            if file:
                path = file.get_path()
                if not path:
                    raise SettingsError(_("Choose a local profile file."))
                profile = w.profiles.load(path)
                review_dialog(w, profile, imported=True)
        except GLib.Error as exc:
            if not exc.matches(Gtk.DialogError.quark(), Gtk.DialogError.DISMISSED):
                w.error(exc.message)
        except Exception as exc:
            w.error(str(exc))
    chooser.open(w, None, selected)


def export_profile(w, profile):
    d, content, header = dialog(w, _("Export profile"), 760, 480)
    content.append(label(profile["name"], "title-2"))
    categories = category_chooser(content)
    content.append(info_box(_("Only the selected categories are exported. Credentials, command strings, and remapping source are excluded by the profile format.")))
    def export():
        document = dict(profile)
        document["settings"] = [e for e in profile["settings"] if category_for(Ref.from_dict(e)) in categories()]
        chooser = Gtk.FileDialog(title=_("Export profile"), initial_name=(re.sub(r"[^\w-]+", "-", profile["name"]).strip("-")[:70] or "desktop-profile") + ".json")
        def chosen(c, result):
            try:
                file = c.save_finish(result)
                if file:
                    path = file.get_path()
                    if not path:
                        raise SettingsError(_("Choose a local destination."))
                    w.profiles.save(document, path)
                    d.close(); w.toast(_("Profile exported"))
            except GLib.Error as exc:
                if not exc.matches(Gtk.DialogError.quark(), Gtk.DialogError.DISMISSED):
                    w.error(exc.message)
            except Exception as exc:
                w.error(str(exc))
        chooser.save(w, None, chosen)
    header.pack_end(button(label=_("Choose destination…"), callback=export, css="suggested-action")); d.present(w)


def review_dialog(w, profile, selected=None, imported=False):
    d, content, header = dialog(w, _("Compare profile"), 900, 760)
    content.append(label(profile["name"], "title-2"))
    content.append(info_box(_("Review the exact differences below. Applying creates an automatic backup first. Values changed by another application after this comparison will block the operation. No settings outside the selected categories are touched.")))
    state = {"review": [], "skipped": []}
    differences = group(_("Changes"))
    rows = []
    apply = button(label=_("Apply changes"), css="suggested-action")
    header.pack_end(apply)
    def render():
        for row in rows:
            differences.remove(row)
        rows.clear()
        try:
            review, skipped = w.profiles.compare(profile, categories())
            state.update(review=review, skipped=skipped)
            differences.set_title(_("{count} changes · {skipped} unavailable or locked").format(count=len(review), skipped=len(skipped)))
            for change in review:
                ref = change["ref"]
                before, after = change["before"]["value"], change["after"]["value"]
                row = action_row(ref.key, f"{ref.schema}\n" + _("Current: ") + before[:260] + "\n" + _("Profile: ") + after[:260] + (_(" · reset to local default") if change["after"]["user"] is None else ""))
                differences.add(row); rows.append(row)
            for ref, reason in skipped:
                row = action_row(_("Skipped: ") + ref.key, reason); differences.add(row); rows.append(row)
            if not review and not skipped:
                row = action_row(_("Everything selected already matches")); differences.add(row); rows.append(row)
            apply.set_label(_("Apply {count} changes").format(count=len(review)))
            apply.set_sensitive(bool(review))
        except Exception as exc:
            apply.set_sensitive(False)
            row = action_row(_("Could not compare profile"), str(exc)); differences.add(row); rows.append(row)
    categories = category_chooser(content, selected, changed=render)
    content.append(differences)
    error = label("", "error"); content.append(error)
    def commit():
        try:
            w.profiles.apply_review(state["review"], w.store, profile["name"])
            d.close(); w.toast(_("Profile applied · previous values backed up"))
            if w.current_page == "profiles":
                w.render("profiles")
        except Exception as exc:
            error.set_label(str(exc))
    apply.connect("clicked", lambda _b: commit())
    if imported:
        def save_copy():
            w.safe(lambda: w.profiles.save(profile), lambda _r: (w.toast(_("Imported profile saved without applying")), d.close(), w.render("profiles")))
        content.append(button(label=_("Save imported profile without applying"), callback=save_copy))
    render(); d.present(w)
    return d


STATUS = {"applied": ("Applied", "success"), "undone": ("Undone", "neutral"), "pending": ("Interrupted", "warning"), "failed": ("Failed", "error")}


def build_history(w, content):
    content.append(info_box(_("Recent GSettings changes made in Desktop Studio are recorded here. Undo checks that every value still matches that change. Sensitive values and operations on external services are not recorded for replay.")))
    entries = list(reversed(w.history.entries))[:100]
    current, g = None, None
    for entry in entries:
        heading = day_heading(entry["time"])
        if heading != current:
            current, g = heading, group(heading)
            content.append(g)
        count = len(entry["changes"])
        subtitle = clock_time(entry["time"]) + " · " + n_("{count} setting", "{count} settings", count).format(count=count)
        if entry.get("excluded"):
            subtitle += "\n" + _("Contains private values; full undo is unavailable.")
        if entry["status"] == "pending":
            subtitle += "\n" + _("An interrupted operation was recorded. Inspect current values and restore its automatic backup if needed.")
        row = action_row(entry["label"], subtitle, lambda e=entry: history_details(w, e))
        text, kind = STATUS.get(entry["status"], (entry["status"].capitalize(), "neutral"))
        row.add_prefix(pill(_(text), kind))
        if entry["status"] == "applied" and entry["changes"] and not entry.get("excluded"):
            row.add_suffix(button(icon="edit-undo-symbolic", callback=lambda e=entry: history_details(w, e, undo=True), tooltip=_("Undo…"), css="flat circular row-action"))
        g.add(row)
    if not entries:
        empty = Adw.StatusPage(title=_("No changes yet"), description=_("Settings you change in Desktop Studio appear here, with a way to undo them."), icon_name="document-open-recent-symbolic")
        empty.add_css_class("compact")
        content.append(empty)


def history_details(w, entry, undo=False):
    d, content, header = dialog(w, _("Undo change") if undo else _("Change details"), 850, 650)
    content.append(label(entry["label"], "title-2"))
    g = group(friendly_time(entry["time"]))
    content.append(g)
    for change in entry["changes"]:
        ref = Ref.from_dict(change)
        row = action_row(ref.key, ref.schema + "\n" + _("Before: ") + change["before"]["value"][:350] + "\n" + _("After: ") + change["after"]["value"][:350])
        g.add(row)
    error = label("", "error"); content.append(error)
    if undo:
        content.append(info_box(_("This restores the original values and whether they were overrides or schema defaults. A later external change blocks undo.")))
        def commit():
            try:
                w.history.undo(entry, w.store)
                d.close(); w.toast(_("Change undone")); w.render("history")
            except Exception as exc:
                error.set_label(str(exc))
        header.pack_end(button(label=_("Undo this change"), callback=commit, css="suggested-action"))
    d.present(w)
