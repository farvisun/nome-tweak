import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk

from . import APP_ID, __version__
from .catalog import CATEGORIES, CATEGORY_MAP, SECTIONS, SPECS, Spec, category_for, profile_refs
from .core.profiles import History, Profiles, atomic_json
from .core.settings import Registry, SettingsStore, Ref
from .i18n import _, n_, is_rtl
from .platform.displays import Displays
from .platform.keyboard import Toshy
from .platform.services import Environment, Extensions, background, open_settings, open_uri
from .platform.updates import UpdateChecker, UpdateResult
from .ui.widgets import SettingRow, action_row, button, group, info_box, label, dialog, pill

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
        self.split = Adw.OverlaySplitView(min_sidebar_width=240, max_sidebar_width=272, sidebar_width_fraction=0.23)
        self.toasts.set_child(self.split)
        self.set_content(self.toasts)
        breakpoint = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 800sp"))
        breakpoint.add_setter(self.split, "collapsed", True)
        self.add_breakpoint(breakpoint)
        self.split.set_sidebar(self.build_sidebar())
        main = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.back = button(icon="sidebar-show-symbolic", callback=lambda: self.split.set_show_sidebar(True), tooltip=_("Show categories"))
        header.pack_start(self.back)
        self.split.connect("notify::collapsed", lambda *_a: self.back.set_visible(self.split.get_collapsed()))
        self.back.set_visible(False)
        self.search = Gtk.SearchEntry(placeholder_text=_("Search settings, descriptions, and keys"), hexpand=True)
        self.search.set_tooltip_text(_("Search settings (Ctrl+F)"))
        self.search.update_property([Gtk.AccessibleProperty.LABEL], [_("Global settings search")])
        self.search.connect("search-changed", self.search_changed)
        self.search.connect("stop-search", lambda _e: self.search.set_text(""))
        self.search.connect("activate", self.search_activate)
        header.set_title_widget(Adw.Clamp(maximum_size=520, tightening_threshold=360, child=self.search, hexpand=True))
        menu = Gio.Menu()
        appearance = Gio.Menu()
        for name, val in ((_("Follow System"), "system"), (_("Light"), "light"), (_("Dark"), "dark")):
            appearance.append(name, f"app.appearance::{val}")
        section = Gio.Menu()
        section.append_submenu(_("Application Appearance"), appearance)
        section.append(_("Ryoku Cursor Collection"), "app.cursors")
        menu.append_section(None, section)
        section = Gio.Menu()
        section.append(_("Software Updates"), "app.updates")
        section.append(_("Diagnostics"), "app.diagnostics")
        menu.append_section(None, section)
        section = Gio.Menu()
        section.append(_("About Desktop Studio"), "app.about")
        section.append(_("Quit"), "app.quit")
        menu.append_section(None, section)
        mb = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, tooltip_text=_("Main menu"), primary=True)
        header.pack_end(mb)
        main.add_top_bar(header)
        self.scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.clamp = Adw.Clamp(maximum_size=980, tightening_threshold=720)
        self.scroll.set_child(self.clamp)
        main.set_content(self.scroll)
        self.split.set_content(main)

    def build_sidebar(self):
        sidebar = Adw.ToolbarView()
        sidebar.add_css_class("studio-sidebar")
        side_header = Adw.HeaderBar(show_end_title_buttons=False)
        brand = Gtk.Box(spacing=10)
        brand.append(Gtk.Image(icon_name=APP_ID, pixel_size=24))
        brand.append(label(_("Desktop Studio"), "heading", False))
        side_header.set_title_widget(brand)
        sidebar.add_top_bar(side_header)
        nav_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.nav = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE, margin_start=8, margin_end=8, margin_top=6, margin_bottom=8)
        self.nav.add_css_class("navigation-sidebar")
        self.nav.update_property([Gtk.AccessibleProperty.LABEL], [_("Categories")])
        self.nav_rows = {}
        for cat in CATEGORIES:
            r = Gtk.ListBoxRow()
            r.category = cat.id
            r.section = cat.section
            box = Gtk.Box(spacing=12, margin_top=7, margin_bottom=7, margin_start=8, margin_end=8)
            box.append(Gtk.Image(icon_name=cat.icon))
            box.append(label(cat.title, wrap=False))
            r.set_child(box)
            r.set_tooltip_text(cat.description)
            r.update_property([Gtk.AccessibleProperty.LABEL], [cat.title])
            self.nav.append(r)
            self.nav_rows[cat.id] = r
        def header(row, before):
            if row.section and (before is None or before.section != row.section):
                heading = label(SECTIONS[row.section], "nav-section", False)
                row.set_header(heading)
            else:
                row.set_header(None)
        self.nav.set_header_func(header)
        self.nav.connect("row-selected", lambda _n, row: self.select_category(row.category) if row else None)
        nav_scroll.set_child(self.nav)
        sidebar.set_content(nav_scroll)
        footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_start=20, margin_end=16, margin_top=10, margin_bottom=14)
        footer.add_css_class("sidebar-footer")
        status = Gtk.Box(spacing=8)
        dot = Gtk.Box(valign=Gtk.Align.CENTER)
        dot.add_css_class("status-dot")
        status.append(dot)
        status.append(label(f"GNOME {self.env.shell_version} · {self.env.session.capitalize()}", "caption", False))
        footer.append(status)
        footer.append(label(_("Version {version}").format(version=__version__), "caption dim-label", False))
        self.update_badge = Gtk.Button(halign=Gtk.Align.START, margin_top=8, visible=False)
        self.update_badge.add_css_class("update-badge")
        self.update_badge.set_action_name("app.updates")
        footer.append(self.update_badge)
        sidebar.add_bottom_bar(footer)
        return sidebar

    def show_update(self, version):
        self.update_badge.set_label(_("Update available · {version}").format(version=version) if version else "")
        self.update_badge.set_visible(bool(version))

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
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24, margin_start=24, margin_end=24, margin_top=24, margin_bottom=48)
        content.add_css_class("page")
        heading = Gtk.Box(spacing=16)
        heading.add_css_class("page-header")
        if icon:
            tile = Gtk.Image(icon_name=icon, pixel_size=24, valign=Gtk.Align.CENTER)
            tile.add_css_class("page-icon")
            heading.append(tile)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.CENTER, hexpand=True)
        title_label = label(title, "title-2")
        text.append(title_label)
        if description:
            text.append(label(description, "dim-label"))
        heading.append(text)
        content.append(heading)
        self.page_heading = heading
        self.clamp.set_child(content)
        self.scroll.get_vadjustment().set_value(0)
        self.set_title(title + " · " + _("Desktop Studio") if title else _("Desktop Studio"))
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
        """Collect GNOME Settings links into one trailing group per page."""
        g = getattr(content, "system_links", None)
        if g is None or g.get_parent() is not content:
            g = group(_("More in GNOME Settings"), _("Hardware and system options managed by GNOME Settings."))
            content.system_links = g
            content.append(g)
        else:
            # Keep the group last even when page content was appended after it.
            content.reorder_child_after(g, content.get_last_child())
        row = action_row(title, subtitle, lambda: self.safe(lambda: open_settings(panel)), "preferences-system-symbolic", external=True)
        if badge:
            row.add_suffix(pill(badge, "neutral"))
        g.add(row)

    def search_activate(self, _entry):
        if self.search_timeout:
            GLib.source_remove(self.search_timeout)
            self.run_search()
        results = getattr(self, "search_results", None)
        if self.search.get_text().strip() and results:
            from .ui.widgets import show_setting_dialog
            if len(results) == 1:
                show_setting_dialog(self, results[0])

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
        content = self.page(_("Search results"), n_("{count} setting matches “{query}”", "{count} settings match “{query}”", len(matches)).format(count=len(matches), query=self.search.get_text().strip()), "system-search-symbolic")
        self.search_results = [spec for spec, _curated in matches[:100]]
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
            empty = Adw.StatusPage(title=_("No matching settings"), description=_("Try a feature name, a description, or a GSettings key such as “cursor-size”."), icon_name="system-search-symbolic")
            empty.add_css_class("compact")
            content.append(empty)
        return False

    def on_close(self, _window):
        app = self.get_application()
        atomic_json(app.state_dir / "window.json", {"width": self.get_width(), "height": self.get_height()})
        return False


class DesktopStudio(Adw.Application):
    __gsignals__ = {"updates-checked": (GObject.SignalFlags.RUN_FIRST, None, ())}

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
        self.update_checker = UpdateChecker()
        self.update_busy = False
        self.update_result = None
        self.update_timer = None
        self.notified_update = None
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
        for name, callback in (("quit", lambda *_a: self.quit()), ("search", lambda *_a: self.window.focus_search()), ("about", self.about), ("diagnostics", self.diagnostics), ("cursors", self.cursor_collection), ("updates", self.software_updates)):
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
        if self.get_application_id() == APP_ID and self.update_timer is None:
            def first_check():
                self.check_software_updates(manual=False)
                self.update_timer = GLib.timeout_add_seconds(3600, self.automatic_update_check)
                return False
            self.update_timer = GLib.timeout_add_seconds(5, first_check)

    def automatic_update_check(self):
        self.check_software_updates(manual=False)
        # The timer lives only in this regular application process.
        return True

    def check_software_updates(self, manual=False):
        if self.update_busy:
            return
        if not manual and not self.update_checker.should_check():
            return
        repository = self.update_checker.preferences.repository
        self.update_busy = True
        self.emit("updates-checked")
        def complete(result):
            self.update_busy = False
            if repository == self.update_checker.preferences.repository:
                self.update_result = result
                if self.window:
                    self.window.show_update(result.release.version if result.available else None)
                if result.available and self.notified_update != result.release.version:
                    self.notified_update = result.release.version
                    toast = Adw.Toast(title=_("Desktop Studio {version} is available").format(version=result.release.version), button_label=_("View update"), timeout=8)
                    toast.connect("button-clicked", self.software_updates)
                    self.window.toasts.add_toast(toast)
            self.emit("updates-checked")
            log.info("Software update check completed: %s", result.status)
        def failed(_message):
            import time
            complete(UpdateResult(repository, __version__, time.time(), "check-failed", message=_("The update check could not complete. Check the network and whether the application’s state folder is writable, then try again.")))
        background(lambda: self.update_checker.check(repository), complete, failed)

    def software_updates(self, *_args):
        if self.window:
            from .ui.updates import updates_dialog
            updates_dialog(self.window)

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
