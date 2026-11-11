from pathlib import Path
import math

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
    if css:
        widget.add_css_class(css)
    if callback:
        widget.connect("clicked", lambda _b: callback())
    return widget


def label(text, css=None, wrap=True, xalign=0):
    w = Gtk.Label(label=text, xalign=xalign, wrap=wrap, selectable=False)
    if css:
        w.add_css_class(css)
    return w


def group(title, description=None):
    return Adw.PreferencesGroup(title=GLib.markup_escape_text(title), description=GLib.markup_escape_text(description or ""))


class PlainActionRow(Adw.ActionRow):
    """Adw.ActionRow subtitles always accept markup, unlike their titles."""
    def __init__(self, title="", subtitle="", **kwargs):
        super().__init__(title=title, use_markup=False, **kwargs)
        self.set_subtitle(subtitle)

    def set_subtitle(self, text):
        self._plain_subtitle = text
        Adw.ActionRow.set_subtitle(self, GLib.markup_escape_text(text))

    def get_subtitle(self):
        return getattr(self, "_plain_subtitle", "")

    def add_suffix(self, widget):
        if isinstance(widget, (Gtk.Switch, Gtk.DropDown, Gtk.SpinButton, Gtk.Scale, Gtk.CheckButton)):
            widget.update_property([Gtk.AccessibleProperty.LABEL], [self.get_title()])
        Adw.ActionRow.add_suffix(self, widget)


def action_row(title, subtitle="", callback=None, icon=None):
    row = PlainActionRow(title=title, subtitle=subtitle)
    row.set_subtitle_lines(3)
    if icon:
        row.add_prefix(Gtk.Image(icon_name=icon))
    if callback:
        b = button(icon="go-next-symbolic", callback=callback, tooltip=title)
        row.add_suffix(b)
        row.set_activatable_widget(b)
    return row


def info_box(text, icon="dialog-information-symbolic"):
    box = Gtk.Box(spacing=12)
    box.add_css_class("info-box")
    box.append(Gtk.Image(icon_name=icon, valign=Gtk.Align.START, margin_top=2))
    box.append(label(text, "caption"))
    return box


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
            tag = label(spec.badge, "badge", False)
            tag.set_valign(Gtk.Align.CENTER)
            self.add_prefix(tag)
        self.make_control()
        reset = button(icon="edit-undo-symbolic", callback=self.reset, tooltip=_("Reset to default"), css="flat")
        self.reset_button = reset
        self.add_suffix(reset)
        more = button(icon="dialog-information-symbolic", callback=self.details, tooltip=_("Details, copy value, and typed editor"), css="flat")
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
        current = value.print_(False)
        if len(current) > 180:
            current = current[:177] + "…"
        suffix = _("Locked by administrator policy") if not writable else ""
        if self.advanced:
            parts = [self.ref.schema + " · " + value.get_type_string(), _("Current: ") + current, suffix or description]
        else:
            parts = [p for p in (description, (_("Current: ") + current) if not isinstance(self.control, (Gtk.Switch, Gtk.SpinButton, Gtk.DropDown, Gtk.FontDialogButton, Gtk.ColorDialogButton)) else "", suffix) if p]
        self.set_subtitle("\n".join(parts))
        self.control.set_sensitive(writable)
        self.reset_button.set_sensitive(writable and self.expected["user"] is not None)
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
