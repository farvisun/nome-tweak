import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from . import APP_ID, __version__
from .catalog import CATEGORIES, CATEGORY_MAP, SPECS, Spec, category_for, profile_refs
from .core.profiles import History, Profiles, atomic_json
from .core.settings import Registry, SettingsStore, Ref
from .i18n import _, is_rtl
from .platform.displays import Displays
from .platform.keyboard import Toshy
from .platform.services import Environment, Extensions, open_settings, open_uri
from .ui.widgets import SettingRow, action_row, button, group, info_box, label, dialog

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent


class StudioWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=_("Desktop Studio"), default_width=1180, default_height=860)
        self.set_size_request(560, 440)
        close = Gio.SimpleAction.new("close", None)
        close.connect("activate", lambda *_args: self.close())
        self.add_action(close)
        self.registry = app.registry
        self.store = app.store
        self.history = app.history
        self.profiles = app.profiles
        self.env = app.env
        self.displays = app.displays
        self.toshy = app.toshy
        self.extensions = app.extensions
        self.current_page = "overview"
        self.page_signals = []
        self.search_timeout = None
        self.search_index = None
        self.last_error = None
        self.build_shell()
        self.navigate("overview")
        self.connect("close-request", self.on_close)

    def build_shell(self):
        self.toasts = Adw.ToastOverlay()
        self.split = Adw.OverlaySplitView(min_sidebar_width=230, max_sidebar_width=250, sidebar_width_fraction=0.22)
        self.toasts.set_child(self.split)
        self.set_content(self.toasts)
        breakpoint = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 800sp"))
        breakpoint.add_setter(self.split, "collapsed", True)
        self.add_breakpoint(breakpoint)
        sidebar = Adw.ToolbarView()
        sidebar.add_css_class("studio-sidebar")
        side_header = Adw.HeaderBar(show_end_title_buttons=False)
        brand = Gtk.Box(spacing=10)
        brand.append(Gtk.Image(icon_name=APP_ID, pixel_size=28))
        brand.append(label(_("Desktop Studio"), "heading", False))
        side_header.set_title_widget(brand)
        sidebar.add_top_bar(side_header)
        side_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        nav_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.nav = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE, margin_start=10, margin_end=10, margin_top=12)
        self.nav.add_css_class("navigation-sidebar")
        self.nav_rows = {}
        for cat in CATEGORIES:
            r = Gtk.ListBoxRow()
            r.category = cat.id
            box = Gtk.Box(spacing=12, margin_top=10, margin_bottom=10, margin_start=12, margin_end=10)
            box.append(Gtk.Image(icon_name=cat.icon, pixel_size=18))
            box.append(label(cat.title, wrap=False))
            r.set_child(box)
            r.update_property([Gtk.AccessibleProperty.LABEL], [cat.title])
            self.nav.append(r)
            self.nav_rows[cat.id] = r
        self.nav.connect("row-selected", lambda _n, row: self.select_category(row.category) if row else None)
        nav_scroll.set_child(self.nav)
        side_box.append(nav_scroll)
        footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=22, margin_end=18, margin_bottom=20)
        status = Gtk.Box(spacing=7)
        dot = label("●", "success", False)
        status.append(dot)
        status.append(label(_("Connected to your desktop"), "caption", False))
        footer.append(status)
        footer.append(label(f"GNOME {self.env.shell_version} · {self.env.session.capitalize()}", "dim-label", False))
        side_box.append(footer)
        sidebar.set_content(side_box)
        self.split.set_sidebar(sidebar)
        main = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.back = button(icon="sidebar-show-symbolic", callback=lambda: self.split.set_show_sidebar(True), tooltip=_("Show categories"))
        header.pack_start(self.back)
        self.split.connect("notify::collapsed", lambda *_a: self.back.set_visible(self.split.get_collapsed()))
        self.back.set_visible(False)
        self.header_title = Adw.WindowTitle(title=_("Desktop Studio"), subtitle=_("Your desktop, thoughtfully configured"))
        header.set_title_widget(self.header_title)
        header.pack_end(button(icon="system-search-symbolic", callback=self.focus_search, tooltip=_("Search settings (Ctrl+F)")))
        menu = Gio.Menu()
        appearance = Gio.Menu()
        for name, val in ((_("Follow System"), "system"), (_("Light"), "light"), (_("Dark"), "dark")):
            appearance.append(name, f"app.appearance::{val}")
        menu.append_submenu(_("Application Appearance"), appearance)
        menu.append(_("Ryoku cursor collection"), "app.cursors")
        menu.append(_("Diagnostics"), "app.diagnostics")
        menu.append(_("About Desktop Studio"), "app.about")
        menu.append(_("Quit"), "app.quit")
        mb = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, tooltip_text=_("Main menu"))
        header.pack_end(mb)
        main.add_top_bar(header)
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        search_box = Gtk.Box(margin_start=28, margin_end=28, margin_top=10, margin_bottom=10)
        self.search = Gtk.SearchEntry(placeholder_text=_("Search settings, descriptions, and keywords…"), hexpand=True)
        self.search.update_property([Gtk.AccessibleProperty.LABEL], [_("Global settings search")])
        self.search.connect("search-changed", self.search_changed)
        self.search.connect("stop-search", lambda _e: self.search.set_text(""))
        search_box.append(self.search)
        container.append(search_box)
        self.scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.clamp = Adw.Clamp(maximum_size=1020, tightening_threshold=760)
        self.scroll.set_child(self.clamp)
        container.append(self.scroll)
        main.set_content(container)
        self.split.set_content(main)

    def focus_search(self):
        self.search.grab_focus()

    def select_category(self, category):
        if self.search.get_text():
            self.search.set_text("")
        self.navigate(category)

    def navigate(self, category):
        self.current_page = category
        if self.nav.get_selected_row() is not self.nav_rows[category]:
            self.nav.select_row(self.nav_rows[category])
            return
        self.render(category)
        if self.split.get_collapsed():
            self.split.set_show_sidebar(False)

    def page(self, title, description, icon=None):
        for obj, handler in self.page_signals:
            obj.disconnect(handler)
        self.page_signals.clear()
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=26, margin_start=28, margin_end=28, margin_top=22, margin_bottom=40)
        heading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        heading.append(label(title, "title-1"))
        heading.append(label(description, "dim-label"))
        content.append(heading)
        self.clamp.set_child(content)
        self.scroll.get_vadjustment().set_value(0)
        self.header_title.set_subtitle(title)
        return content

    def render(self, category):
        from .ui import pages
        cat = CATEGORY_MAP[category]
        content = self.page(cat.title, cat.description, cat.icon)
        builder = getattr(pages, "build_" + category, None)
        if builder:
            builder(self, content)
        else:
            self.add_specs(content, category)

    def add_specs(self, content, category, exclude=()):
        groups = {}
        for spec in SPECS:
            if spec.category != category or spec.ref.key in exclude or not self.registry.exists(spec.ref):
                continue
            if spec.group not in groups:
                groups[spec.group] = group(spec.group)
                content.append(groups[spec.group])
            groups[spec.group].add(SettingRow(self, spec))
        return groups

    def subscribe(self, obj, signal, callback):
        self.page_signals.append((obj, obj.connect(signal, callback)))

    def safe(self, work, success=None):
        try:
            result = work()
            if success:
                success(result)
            return result
        except Exception as exc:
            log.warning("Operation failed (%s)", type(exc).__name__)
            self.error(str(exc))
            return None

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=text, timeout=3))

    def error(self, message):
        self.last_error = message
        log.warning("An operation error was shown to the user")
        d = Adw.AlertDialog(heading=_("Couldn’t apply this change"), body=message)
        d.add_response("close", _("Close"))
        d.set_default_response("close")
        d.present(self)

    def system_link(self, content, title, subtitle, panel, badge=""):
        g = group(title)
        row = action_row(_("Open ") + title, subtitle, lambda: self.safe(lambda: open_settings(panel)), "preferences-system-symbolic")
        if badge:
            row.add_prefix(label(badge, "badge", False))
        g.add(row)
        content.append(g)

    def search_changed(self, _entry):
        if self.search_timeout:
            GLib.source_remove(self.search_timeout)
        self.search_timeout = GLib.timeout_add(180, self.run_search)

    def run_search(self):
        self.search_timeout = None
        query = self.search.get_text().strip().casefold()
        if not query:
            self.render(self.current_page)
            return False
        if self.search_index is None:
            curated = {s.ref: s for s in SPECS if self.registry.exists(s.ref)}
            index = []
            for ref in self.registry.refs():
                key = self.registry.schema_key(ref)
                spec = curated.get(ref) or Spec(category_for(ref), _("Advanced settings"), ref, key.get_summary() or ref.key, key.get_description() or "")
                haystack = " ".join((spec.title, spec.description, spec.keywords, ref.schema, ref.key, key.get_description() or "")).casefold()
                index.append((spec, haystack, ref in curated))
            self.search_index = index
        words = query.split()
        matches = [(s, c) for s, hay, c in self.search_index if all(w in hay for w in words)]
        matches.sort(key=lambda x: (not x[1], x[0].category, x[0].title))
        content = self.page(_("Search"), _("{count} settings found").format(count=len(matches)))
        groups = {}
        for spec, curated in matches[:100]:
            cat = CATEGORY_MAP.get(spec.category, CATEGORY_MAP["advanced"])
            if cat.id not in groups:
                groups[cat.id] = group(cat.title)
                content.append(groups[cat.id])
            groups[cat.id].add(SettingRow(self, spec, advanced=not curated))
        if len(matches) > 100:
            content.append(info_box(_("Showing the first 100 results. Add a schema name or another keyword to narrow the search.")))
        if not matches:
            content.append(Adw.StatusPage(title=_("No matching settings"), description=_("Try a feature, description, or GSettings key."), icon_name="system-search-symbolic"))
        return False

    def on_close(self, _window):
        app = self.get_application()
        atomic_json(app.state_dir / "window.json", {"width": self.get_width(), "height": self.get_height()})
        return False


class DesktopStudio(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.state_dir = Path(GLib.get_user_state_dir()) / "desktop-studio"
        self.data_dir = Path(GLib.get_user_data_dir()) / "desktop-studio"
        self.state_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.data_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        handler = RotatingFileHandler(self.state_dir / "desktop-studio.log", maxBytes=1_000_000, backupCount=2)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        handler.setLevel(logging.INFO)
        logging.basicConfig(level=logging.INFO, handlers=[handler, logging.StreamHandler()])
        (self.state_dir / "desktop-studio.log").chmod(0o600)
        self.env = Environment()
        self.extensions = Extensions()
        try:
            active_extensions = {uuid for uuid, data in self.extensions.list().items() if data.get("state") == 1}
        except Exception:
            active_extensions = set()
        self.registry = Registry(active_extensions=active_extensions)
        self.history = History(self.state_dir)
        self.store = SettingsStore(self.registry, self.history)
        self.profiles = Profiles(self.data_dir / "profiles", self.registry, category_for)
        self.initial_error = None
        try:
            self.profiles.initial(profile_refs(self.registry))
        except Exception as exc:
            self.initial_error = str(exc)
            log.exception("Could not create initial snapshot")
        self.displays = Displays()
        self.toshy = Toshy(self.data_dir / "backups")
        log.info("Session detected: %s; GNOME %s; %s; %d schemas", self.env.os, self.env.shell_version, self.env.session, len(self.registry.schemas))
        self.window = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        if is_rtl():
            Gtk.Widget.set_default_direction(Gtk.TextDirection.RTL)
        Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_search_path(str(ROOT / "data/icons"))
        provider = Gtk.CssProvider()
        provider.load_from_path(str(ROOT / "data/style.css"))
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        for name, callback in (("quit", lambda *_a: self.quit()), ("search", lambda *_a: self.window.focus_search()), ("about", self.about), ("diagnostics", self.diagnostics), ("cursors", self.cursor_collection)):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)
        self.set_accels_for_action("app.search", ["<Primary>f", "<Primary>k"])
        self.set_accels_for_action("app.quit", ["<Primary>q"])
        self.set_accels_for_action("win.close", ["<Primary>w"])
        action = Gio.SimpleAction.new_stateful("appearance", GLib.VariantType.new("s"), GLib.Variant("s", "system"))
        def appearance(a, value):
            a.set_state(value)
            schemes = {"system": Adw.ColorScheme.DEFAULT, "light": Adw.ColorScheme.FORCE_LIGHT, "dark": Adw.ColorScheme.FORCE_DARK}
            self.get_style_manager().set_color_scheme(schemes.get(value.unpack(), Adw.ColorScheme.DEFAULT))
        action.connect("activate", appearance)
        self.add_action(action)

    def do_activate(self):
        if not self.window:
            self.window = StudioWindow(self)
            if self.initial_error:
                GLib.idle_add(lambda: (self.window.error(_("Initial snapshot could not be saved: ") + self.initial_error), False)[1])
        self.window.present()

    def about(self, *_args):
        d = Adw.AboutDialog(application_name=_("Desktop Studio"), application_icon=APP_ID, developer_name="Desktop Studio contributors", version=__version__, comments=_("A thoughtful home for your GNOME desktop preferences."), license_type=Gtk.License.MIT_X11)
        d.present(self.window)

    def cursor_collection(self, *_args):
        from .ui.cursors import collection_dialog
        if self.window:
            self.window.navigate("appearance")
            collection_dialog(self.window)

    def diagnostics(self, *_args):
        from .diagnostics import report
        d, content, header = dialog(self.window, _("Diagnostics"), 720, 600)
        text = json.dumps(report(self.registry, self.env), indent=2, ensure_ascii=False)
        value = Gtk.Label(label=text, selectable=True, wrap=True, xalign=0)
        value.add_css_class("monospace")
        content.append(value)
        content.append(button(label=_("Copy diagnostics"), callback=lambda: self.window.get_clipboard().set(text)))
        content.append(button(label=_("Open log folder"), callback=lambda: self.window.safe(lambda: open_uri(self.state_dir.as_uri()))))
        d.present(self.window)


def main(argv=None):
    app = DesktopStudio()
    return app.run(argv or [sys.argv[0]])
