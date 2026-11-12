from datetime import datetime, timedelta
from pathlib import Path
import math
import re

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from ..catalog import Spec
from ..core.settings import SettingsError, choices, numeric_range
from ..i18n import _
from ..platform.services import theme_names


def button(label=None, icon=None, callback=None, tooltip=None, css=None):
    widget = Gtk.Button(label=label) if label else Gtk.Button(icon_name=icon)
    widget.set_valign(Gtk.Align.CENTER)
    if tooltip:
        widget.set_tooltip_text(tooltip)
        widget.update_property([Gtk.AccessibleProperty.LABEL], [tooltip])
    for name in (css.split() if css else ()):
        widget.add_css_class(name)
    if callback:
        widget.connect("clicked", lambda _b: callback())
    return widget


def label(text, css=None, wrap=True, xalign=0):
    w = Gtk.Label(label=text, xalign=xalign, wrap=wrap, selectable=False)
    if wrap:
        w.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    for name in (css.split() if css else ()):
        w.add_css_class(name)
    return w


def pill(text, kind="accent", tooltip=None):
    """A compact status label; kind is accent, success, warning, error or neutral."""
    w = label(text, f"pill pill-{kind}", False)
    w.set_valign(Gtk.Align.CENTER)
    if tooltip:
        w.set_tooltip_text(tooltip)
    return w


def group(title, description=None):
    return Adw.PreferencesGroup(title=GLib.markup_escape_text(title), description=GLib.markup_escape_text(description or ""))


class PlainActionRow(Adw.ActionRow):
    """An action row whose title and subtitle are always plain text.

    Older libadwaita parses subtitles as markup regardless of use-markup, newer
    releases honor use-markup for both. Enabling markup and escaping both
    strings renders literally on every supported version.
    """
    def __init__(self, title="", subtitle="", **kwargs):
        super().__init__(use_markup=True, **kwargs)
        self.set_title(title)
        self.set_subtitle(subtitle)

    def set_title(self, text):
        self._plain_title = text or ""
        Adw.ActionRow.set_title(self, GLib.markup_escape_text(self._plain_title))

    def get_title(self):
        return getattr(self, "_plain_title", "")

    def set_subtitle(self, text):
        self._plain_subtitle = text or ""
        Adw.ActionRow.set_subtitle(self, GLib.markup_escape_text(self._plain_subtitle))

    def get_subtitle(self):
        return getattr(self, "_plain_subtitle", "")

    def add_suffix(self, widget):
        if isinstance(widget, (Gtk.Switch, Gtk.DropDown, Gtk.SpinButton, Gtk.Scale, Gtk.CheckButton)):
            widget.update_property([Gtk.AccessibleProperty.LABEL], [self.get_title()])
        Adw.ActionRow.add_suffix(self, widget)


def action_row(title, subtitle="", callback=None, icon=None, external=False):
    """A row; with a callback the whole row is activatable and shows a chevron."""
    row = PlainActionRow(title=title, subtitle=subtitle)
    row.set_subtitle_lines(3)
    if icon:
        image = Gtk.Image(icon_name=icon)
        image.add_css_class("row-icon")
        row.add_prefix(image)
    if callback:
        row.set_activatable(True)
        row.connect("activated", lambda _r: callback())
        hint = Gtk.Image(icon_name="adw-external-link-symbolic" if external else "go-next-symbolic")
        hint.add_css_class("dim-label")
        hint.set_tooltip_text(_("Opens in GNOME Settings") if external else None)
        Adw.ActionRow.add_suffix(row, hint)
    return row


def info_box(text, icon=None, kind="info"):
    """An inline notice. kind is info or warning."""
    box = Gtk.Box(spacing=12)
    box.add_css_class("info-box")
    box.add_css_class(f"info-{kind}")
    image = Gtk.Image(icon_name=icon or ("dialog-warning-symbolic" if kind == "warning" else "dialog-information-symbolic"), valign=Gtk.Align.START, margin_top=1)
    image.add_css_class("info-icon")
    box.append(image)
    text_label = label(text, "info-text")
    text_label.set_hexpand(True)
    box.append(text_label)
    return box


def friendly_time(iso):
    """Render an ISO timestamp as local, human-friendly text."""
    try:
        moment = datetime.fromisoformat(iso).astimezone()
    except (TypeError, ValueError):
        return iso or ""
    today = datetime.now().astimezone().date()
    clock = moment.strftime("%H:%M")
    if moment.date() == today:
        return _("Today at {time}").format(time=clock)
    if moment.date() == today - timedelta(days=1):
        return _("Yesterday at {time}").format(time=clock)
    if moment.year == today.year:
        return moment.strftime("%b %-d") + " · " + clock
    return moment.strftime("%b %-d, %Y") + " · " + clock


def clock_time(iso):
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%H:%M")
    except (TypeError, ValueError):
        return iso or ""


def day_heading(iso):
    try:
        day = datetime.fromisoformat(iso).astimezone().date()
    except (TypeError, ValueError):
        return _("Earlier")
    today = datetime.now().astimezone().date()
    if day == today:
        return _("Today")
    if day == today - timedelta(days=1):
        return _("Yesterday")
    return day.strftime("%A, %B %-d") if day.year == today.year else day.strftime("%B %-d, %Y")


def dialog(parent, title, width=650, height=520):
    d = Adw.Dialog(title=title, content_width=width, content_height=height)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    toolbar.add_top_bar(header)
    scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
    content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin_top=18, margin_bottom=24, margin_start=24, margin_end=24)
    scroll.set_child(content)
    toolbar.set_content(scroll)
    d.set_child(toolbar)
    return d, content, header


def text_editor(text="", monospace=True, height=160):
    view = Gtk.TextView(monospace=monospace, wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=12, bottom_margin=12, left_margin=12, right_margin=12)
    view.get_buffer().set_text(text)
    scroll = Gtk.ScrolledWindow(min_content_height=height, hexpand=True, vexpand=True, child=view)
    scroll.add_css_class("card")
    return scroll, view


def buffer_text(view):
    buf = view.get_buffer()
    return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)


# Schema descriptions often list raw enum values that the dropdown already shows.
ENUM_LISTING = re.compile(r"\s*(Valid|Possible|Allowed) values (are|include)\b.*$", re.I | re.S)


def tidy_description(text):
    text = ENUM_LISTING.sub("", text.strip()).strip()
    return re.sub(r"\s+", " ", text)


def display_value(value):
    """A readable value for subtitles: strings unquoted, empty values named."""
    typ = value.get_type_string()
    if typ == "s":
        text = value.unpack()
        if not text:
            return _("Not set (system default)")
        if text.startswith("file://"):
            text = Gio.File.new_for_uri(text).get_path() or text
    elif typ == "as":
        items = value.unpack()
        text = ", ".join(items) if items else _("None")
    else:
        text = value.print_(False)
    return text if len(text) <= 180 else text[:177] + "…"


class SettingRow(PlainActionRow):
    def __init__(self, window, spec, advanced=False):
        super().__init__(title=spec.title)
        self.window = window
        self.spec = spec
        self.ref = spec.ref
        self.registry = window.registry
        self.store = window.store
        self.key = self.registry.schema_key(self.ref)
        self.freeze = True
        self.signal_id = None
        self.control = None
        self.choice_values = []
        self.advanced = advanced
        self.set_title_lines(2)
        self.set_subtitle_lines(3)
        self.set_tooltip_text(f"{self.ref.schema}\n{self.ref.path or self.registry.schemas[self.ref.schema].get_path()}\n{self.ref.key}")
        self.store.watch(self.ref)
        self.expected = self.registry.state(self.ref)
        if spec.badge:
            self.add_suffix(pill(spec.badge, "neutral", _("Takes effect after: ") + spec.badge))
        self.make_control()
        # The reset button keeps its space when hidden so controls stay aligned.
        reset = button(icon="edit-undo-symbolic", callback=self.reset, tooltip=_("Reset to default"), css="flat circular row-action")
        self.reset_button = reset
        self.add_suffix(reset)
        if not advanced:
            # Advanced rows already open the same editor from their Edit button.
            more = button(icon="view-more-symbolic", callback=self.details, tooltip=_("Details, copy value, and typed editor"), css="flat circular row-action dim-label")
            self.add_suffix(more)
        self.update()

    def do_root(self):
        Adw.ActionRow.do_root(self)
        if self.signal_id is None:
            self.signal_id = self.store.connect("changed", self.external_change)

    def do_unroot(self):
        if self.signal_id is not None:
            self.store.disconnect(self.signal_id)
            self.signal_id = None
        Adw.ActionRow.do_unroot(self)

    def external_change(self, store, token):
        if token == self.ref.token:
            self.update()

    def make_control(self):
        value = self.registry.value(self.ref)
        typ = value.get_type_string()
        opts = choices(self.key) if typ == "s" else []
        if self.spec.options:
            self.choice_values = [x[0] for x in self.spec.options]
            names = [_(x[1]) for x in self.spec.options]
        elif self.spec.kind in ("icons", "cursors", "themes", "shell-themes"):
            self.choice_values = theme_names(self.spec.kind)
            names = self.choice_values[:]
        elif self.spec.kind == "monitor":
            try:
                self.choice_values = [m[0][0] for m in self.window.displays.read()[1]]
            except Exception:
                self.choice_values = []
            names = self.choice_values[:]
        elif opts:
            self.choice_values = opts
            names = [_(str(x).replace("-", " ").replace("_", " ").capitalize()) for x in opts]
        else:
            names = []
        if self.advanced:
            self.control = button(label=_("Edit"), callback=self.details)
        elif typ == "b":
            self.control = Gtk.Switch(valign=Gtk.Align.CENTER)
            self.control.connect("notify::active", lambda w, _p: self.commit(GLib.Variant("b", w.get_active())))
        elif self.choice_values or self.spec.kind in ("icons", "cursors", "themes", "shell-themes", "monitor"):
            current = value.unpack()
            if current not in self.choice_values:
                self.choice_values.insert(0, current)
                names.insert(0, str(current) or _("Default"))
            self.control = Gtk.DropDown(model=Gtk.StringList.new(names), enable_search=True, valign=Gtk.Align.CENTER)
            self.control.set_size_request(160, -1)
            self.control.connect("notify::selected", self.choose)
        elif typ in ("i", "u", "d", "n", "q", "x", "t", "y") and self.spec.kind != "variant":
            bounds = numeric_range(self.key)
            if self.spec.bounds:
                low, high, step = self.spec.bounds
                if bounds:
                    low, high = max(low, bounds[0]), min(high, bounds[1])
            else:
                low, high = bounds or ((0, 65535) if typ in ("u", "q", "t", "y") else (-10000, 10000))
                step = 0.05 if typ == "d" else 1
            # Keep unusual existing values visible without silently clamping.
            low, high = min(low, value.unpack()), max(high, value.unpack())
            self.control = Gtk.SpinButton.new_with_range(low, high, step)
            self.control.set_digits(2 if typ == "d" else 0)
            self.control.set_valign(Gtk.Align.CENTER)
            self.control.set_width_chars(6)
            self.control.connect("value-changed", lambda w: self.commit(GLib.Variant(typ, w.get_value() if typ == "d" else w.get_value_as_int())))
        elif self.spec.kind == "font":
            self.control = Gtk.FontDialogButton(dialog=Gtk.FontDialog(), valign=Gtk.Align.CENTER)
            self.control.set_use_size(True)
            self.control.connect("notify::font-desc", lambda w, _p: self.commit(GLib.Variant("s", w.get_font_desc().to_string())) if w.get_font_desc() else None)
        elif self.spec.kind == "color":
            self.control = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False), valign=Gtk.Align.CENTER)
            self.control.connect("notify::rgba", lambda w, _p: self.commit(GLib.Variant("s", "#{:02x}{:02x}{:02x}".format(*(round(c * 255) for c in (w.get_rgba().red, w.get_rgba().green, w.get_rgba().blue))))))
        elif self.spec.kind == "file":
            self.control = button(label=_("Choose…"), callback=self.choose_file)
        else:
            self.control = button(label=_("Edit…"), callback=self.details)
        self.control.update_property([Gtk.AccessibleProperty.LABEL], [self.spec.title])
        self.add_suffix(self.control)

    def update(self):
        self.freeze = True
        self.expected = self.registry.state(self.ref)
        value = self.registry.value(self.ref)
        val = value.unpack()
        writable = self.registry.settings(self.ref).is_writable(self.ref.key)
        description = self.spec.description or self.key.get_description() or ""
        if not description and self.key.get_summary() != self.spec.title:
            description = self.key.get_summary() or ""
        if not self.advanced:
            description = tidy_description(description)
        current = display_value(value)
        suffix = _("Locked by administrator policy") if not writable else ""
        if self.advanced:
            parts = [self.ref.schema + " · " + value.get_type_string(), _("Current: ") + current, suffix or description]
        else:
            parts = [p for p in (description, (_("Current: ") + current) if not isinstance(self.control, (Gtk.Switch, Gtk.SpinButton, Gtk.DropDown, Gtk.FontDialogButton, Gtk.ColorDialogButton)) else "", suffix) if p]
        self.set_subtitle("\n".join(parts))
        self.control.set_sensitive(writable)
        modified = writable and self.expected["user"] is not None
        self.reset_button.set_sensitive(modified)
        self.reset_button.set_opacity(1 if modified else 0)
        self.reset_button.set_can_target(modified)
        self.reset_button.set_can_focus(modified)
        if modified:
            self.add_css_class("modified")
        else:
            self.remove_css_class("modified")
        if not self.advanced:
            if isinstance(self.control, Gtk.Switch):
                self.control.set_active(val)
            elif isinstance(self.control, Gtk.DropDown):
                if val not in self.choice_values:
                    self.choice_values.append(val)
                    self.control.get_model().append(str(val) or _("Default"))
                self.control.set_selected(self.choice_values.index(val))
            elif isinstance(self.control, Gtk.SpinButton):
                adj = self.control.get_adjustment()
                adj.set_lower(min(adj.get_lower(), val))
                adj.set_upper(max(adj.get_upper(), val))
                self.control.set_value(val)
            elif isinstance(self.control, Gtk.FontDialogButton):
                self.control.set_font_desc(Pango.FontDescription.from_string(val))
            elif isinstance(self.control, Gtk.ColorDialogButton):
                rgba = Gdk.RGBA()
                if rgba.parse(val):
                    self.control.set_rgba(rgba)
        self.freeze = False

    def choose(self, widget, _prop):
        index = widget.get_selected()
        if index < len(self.choice_values):
            self.commit(GLib.Variant("s", self.choice_values[index]))

    def commit(self, value):
        if self.freeze:
            return
        try:
            self.store.set(self.ref, value.print_(True), self.expected, self.spec.title)
            self.window.toast(_("Saved · ") + self.spec.title)
        except Exception as exc:
            self.window.error(str(exc))
        finally:
            self.update()

    def reset(self):
        try:
            self.store.set(self.ref, None, self.expected, _("Reset: ") + self.spec.title)
            self.window.toast(_("Restored default · ") + self.spec.title)
        except Exception as exc:
            self.window.error(str(exc))
        self.update()

    def choose_file(self):
        chooser = Gtk.FileDialog(title=_("Choose background image"))
        filters = Gio.ListStore.new(Gtk.FileFilter)
        f = Gtk.FileFilter(name=_("Images and GNOME background slideshows"))
        f.add_mime_type("image/*")
        f.add_pattern("*.xml")
        filters.append(f)
        chooser.set_filters(filters)
        def selected(d, result):
            try:
                file = d.open_finish(result)
                if file:
                    self.commit(GLib.Variant("s", file.get_uri()))
            except GLib.Error as exc:
                if not exc.matches(Gtk.DialogError.quark(), Gtk.DialogError.DISMISSED):
                    self.window.error(exc.message)
        chooser.open(self.window, None, selected)

    def details(self):
        show_setting_dialog(self.window, self.spec)


def show_setting_dialog(window, spec):
    registry, store, ref = window.registry, window.store, spec.ref
    key = registry.schema_key(ref)
    expected = registry.state(ref)
    value = registry.value(ref)
    typ = value.get_type_string()
    d, content, header = dialog(window, spec.title, 720, 680)
    meta = group(_("Setting details"), key.get_description() or spec.description)
    for title, val in ((_("Schema"), ref.schema), (_("Key"), ref.key), (_("Path"), ref.path or registry.schemas[ref.schema].get_path()), (_("Type"), typ), (_("Allowed range"), key.get_range().print_(False)), (_("Default"), registry.settings(ref).get_default_value(ref.key).print_(True)), (_("Access"), _("Writable") if registry.settings(ref).is_writable(ref.key) else _("Locked by policy"))):
        row = action_row(title, str(val))
        row.set_subtitle_selectable(True)
        meta.add(row)
    content.append(meta)
    content.append(info_box(_("Changes are checked against the value shown when this editor opened. If another application changes it, reopen this editor before applying.")))
    editor_group = group(_("Value"))
    enum = choices(key) if typ == "s" else []
    editor = None
    if typ == "b":
        editor = Gtk.Switch(active=value.unpack(), valign=Gtk.Align.CENTER)
        row = action_row(_("Enabled")); row.add_suffix(editor); editor_group.add(row)
        get_value = lambda: GLib.Variant("b", editor.get_active()).print_(True)
    elif enum:
        editor = Gtk.DropDown(model=Gtk.StringList.new(enum), selected=enum.index(value.unpack()))
        row = action_row(_("Choice")); row.add_suffix(editor); editor_group.add(row)
        get_value = lambda: GLib.Variant("s", enum[editor.get_selected()]).print_(True)
    elif typ == "s":
        editor = Adw.EntryRow(title=_("Text"), text=value.unpack())
        editor_group.add(editor)
        get_value = lambda: GLib.Variant("s", editor.get_text()).print_(True)
    elif typ in ("i", "u", "d", "n", "q", "x", "t", "y"):
        # Entry preserves the exact integer precision of 64-bit GVariant values.
        editor = Adw.EntryRow(title=_("Number"), text=str(value.unpack()))
        editor_group.add(editor)
        get_value = lambda: editor.get_text().strip()
    else:
        content.append(label(_("Enter a typed GVariant value. Strings use quotes; arrays use [item, item]."), "caption"))
        sc, editor = text_editor(value.print_(True))
        content.append(sc)
        get_value = lambda: buffer_text(editor)
    content.append(editor_group)
    message = label("", "error")
    content.append(message)
    apply_btn = button(label=_("Apply"), css="suggested-action")
    header.pack_end(apply_btn)
    apply_btn.set_sensitive(registry.settings(ref).is_writable(ref.key))
    def apply(reset=False):
        try:
            store.set(ref, None if reset else get_value(), expected, spec.title)
            window.toast(_("Saved · ") + spec.title)
            d.close()
        except Exception as exc:
            message.set_label(str(exc))
    apply_btn.connect("clicked", lambda _b: apply())
    actions = Gtk.Box(spacing=8)
    reset = button(label=_("Reset to default"), callback=lambda: apply(True))
    reset.set_sensitive(registry.settings(ref).is_writable(ref.key))
    actions.append(reset)
    actions.append(button(label=_("Copy value"), callback=lambda: (window.get_clipboard().set(expected["value"]), window.toast(_("Value copied")))))
    content.append(actions)
    d.present(window)
    return d
