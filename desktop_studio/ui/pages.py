from collections import OrderedDict
from pathlib import Path
import datetime
import re
import shutil

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from .. import APP_ID
from ..catalog import CATEGORIES, CATEGORY_MAP, SECTIONS, SPECS, Spec
from ..core.settings import Ref, SettingsError
from ..i18n import _
from ..platform.services import Audio, Connections, DesktopAppInfo, StartupApps, background, launch, open_settings, open_uri, theme_names
from .widgets import SettingRow, action_row, button, dialog, friendly_time, group, info_box, label, pill


def value(w, schema, key, default=""):
    ref = Ref(schema, key)
    return w.registry.value(ref).unpack() if w.registry.exists(ref) else default


def desktop_preview(w):
    preview = Gtk.Overlay(height_request=220)
    preview.add_css_class("preview")
    preview.set_overflow(Gtk.Overflow.HIDDEN)
    background = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True)
    uri = value(w, "org.gnome.desktop.background", "picture-uri")
    if uri:
        file = Gio.File.new_for_uri(uri)
        path = file.get_path()
        if path and Path(path).suffix.lower() not in (".xml",):
            background.set_file(file)
    preview.set_child(background)
    frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    bar = Gtk.Box(spacing=10)
    bar.add_css_class("preview-bar")
    bar.append(label(_("Activities"), "caption", False))
    clock = label(datetime.datetime.now().strftime("%a %H:%M"), "caption", False)
    clock.set_hexpand(True); clock.set_halign(Gtk.Align.CENTER)
    bar.append(clock)
    bar.append(Gtk.Image(icon_name="network-wireless-signal-excellent-symbolic"))
    bar.append(Gtk.Image(icon_name="audio-volume-high-symbolic"))
    frame.append(bar)
    center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, vexpand=True, margin_top=20)
    center.add_css_class("preview-window")
    center.append(label(_("Hello, your desktop."), "title-3", False))
    center.append(label(_("A little more you."), "caption", False))
    frame.append(center)
    dock = Gtk.Box(spacing=14, halign=Gtk.Align.CENTER)
    dock.add_css_class("preview-dock")
    theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
    for candidates in (("org.gnome.Nautilus", "system-file-manager"), ("firefox", "web-browser"), ("org.gnome.Ptyxis", "org.gnome.Terminal", "utilities-terminal"), ("org.gnome.Settings", "preferences-system"), (APP_ID,)):
        icon = next((name for name in candidates if theme.has_icon(name)), candidates[-1])
        dock.append(Gtk.Image(icon_name=icon, pixel_size=30))
    frame.append(dock)
    preview.add_overlay(frame)
    preview.update_property([Gtk.AccessibleProperty.LABEL], [_("Desktop preview using your current background and icon theme")])
    return preview


def metric(icon, title, val, tooltip=None):
    box = Gtk.Box(spacing=14)
    box.add_css_class("metric")
    box.append(Gtk.Image(icon_name=icon, pixel_size=20, valign=Gtk.Align.START, margin_top=2))
    text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
    text.append(label(title, "metric-label", False))
    value_label = label(str(val), "metric-value", False)
    value_label.set_ellipsize(Pango.EllipsizeMode.END)
    value_label.set_max_width_chars(10)
    value_label.set_tooltip_text(str(val))
    text.append(value_label)
    box.append(text)
    if tooltip:
        box.set_tooltip_text(tooltip)
    return box


def category_tile(w, cat):
    tile = Gtk.Button()
    tile.add_css_class("flat")
    tile.add_css_class("tile")
    box = Gtk.Box(spacing=14)
    icon = Gtk.Image(icon_name=cat.icon, pixel_size=18, valign=Gtk.Align.CENTER)
    icon.add_css_class("tile-icon")
    box.append(icon)
    text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, valign=Gtk.Align.CENTER)
    text.append(label(cat.title, "heading", False))
    description = label(cat.description, "caption dim-label")
    description.set_lines(2); description.set_ellipsize(Pango.EllipsizeMode.END)
    text.append(description)
    box.append(text)
    tile.set_child(box)
    tile.update_property([Gtk.AccessibleProperty.LABEL], [cat.title])
    tile.connect("clicked", lambda _b: w.navigate(cat.id))
    return tile


def build_overview(w, content):
    customized = sum(1 for spec in SPECS if w.registry.exists(spec.ref) and w.registry.state(spec.ref)["user"] is not None)
    profiles = [p for _path, p in w.profiles.list() if not p["name"].startswith("Automatic backup")]
    last = w.history.entries[-1]["time"] if w.history.entries else None
    metrics = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=12, row_spacing=12, homogeneous=True, min_children_per_line=2, max_children_per_line=4)
    metrics.update_property([Gtk.AccessibleProperty.LABEL], [_("Desktop summary")])
    for item in (
        metric("video-display-symbolic", _("Session") + " · " + w.env.session.capitalize(), f"GNOME {w.env.shell_version}", w.env.os),
        metric("document-edit-symbolic", _("Customized settings"), str(customized), _("Curated settings that differ from their defaults")),
        metric("document-save-symbolic", _("Saved profiles"), str(len(profiles)), _("Initial snapshot saved") if not w.get_application().initial_error else _("Snapshot unavailable")),
        metric("document-open-recent-symbolic", _("Last change"), friendly_time(last) if last else _("None yet")),
    ):
        metrics.append(item)
        item.get_parent().set_focusable(False)
    content.append(metrics)
    content.append(desktop_preview(w))
    for section, title in SECTIONS.items():
        heading = Gtk.Box(margin_top=4)
        heading.append(label(title, "section-title", False))
        content.append(heading)
        tiles = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=10, row_spacing=10, homogeneous=True, min_children_per_line=1, max_children_per_line=2)
        for cat in CATEGORIES:
            if cat.section == section:
                tiles.append(category_tile(w, cat))
        content.append(tiles)
    content.append(info_box(_("Opening Desktop Studio and selecting a profile only read your configuration. Settings change when you use a control or explicitly apply a reviewed group.")))


def build_appearance(w, content):
    content.append(desktop_preview(w))
    groups = w.add_specs(content, "appearance")
    from .cursors import collection_dialog
    if _("Cursor") in groups:
        groups[_("Cursor")].set_header_suffix(button(label=_("Ryoku cursors…"), callback=lambda: collection_dialog(w), tooltip=_("Browse and install Ryoku’s Bibata cursor themes")))
    g = group(_("Live typography & cursor preview"))
    preview = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=16, margin_bottom=16, margin_start=18, margin_end=18)
    sample = label(_("The quick brown fox — سلام دنیا"), wrap=True)
    desc = Pango.FontDescription.from_string(value(w, "org.gnome.desktop.interface", "font-name", "Sans 11"))
    attrs = Pango.AttrList(); attrs.insert(Pango.attr_font_desc_new(desc)); sample.set_attributes(attrs)
    preview.append(sample)
    cursor = Gtk.Box(spacing=14)
    theme = value(w, "org.gnome.desktop.interface", "cursor-theme")
    size = value(w, "org.gnome.desktop.interface", "cursor-size", 24)
    target = Gtk.Button(label=_("Move the pointer here to preview the cursor"))
    target.set_cursor_from_name("default")
    cursor.append(target)
    cursor_label = label(f"{theme} · {size} px", "dim-label")
    cursor.append(cursor_label)
    preview.append(cursor)
    g.add(preview); content.append(g)
    def changed(_store, token):
        if token == Ref("org.gnome.desktop.interface", "font-name").token:
            attr = Pango.AttrList()
            attr.insert(Pango.attr_font_desc_new(Pango.FontDescription.from_string(value(w, "org.gnome.desktop.interface", "font-name"))))
            sample.set_attributes(attr)
        if token in {Ref("org.gnome.desktop.interface", key).token for key in ("cursor-theme", "cursor-size")}:
            cursor_label.set_label(f"{value(w, 'org.gnome.desktop.interface', 'cursor-theme')} · {value(w, 'org.gnome.desktop.interface', 'cursor-size')} px")
    w.subscribe(w.store, "changed", changed)
    content.append(info_box(_("GTK themes mainly affect GTK3 apps. GTK4 apps need compatible theme styling; libadwaita apps follow their own design and honor supported color, accent, font, and accessibility preferences. A GNOME Shell theme needs the User Themes extension. Effects beyond GNOME animations require a compatible extension.")))
    if not w.registry.exists(Ref("org.gnome.shell.extensions.user-theme", "name")):
        g = group(_("Shell themes & effects"))
        g.add(action_row(_("Explore installed extensions"), _("User Themes is not installed. No Shell theme override will be applied."), lambda: w.navigate("extensions")))
        content.append(g)


def build_dock(w, content):
    schema = "org.gnome.shell.extensions.dash-to-dock"
    if schema not in w.registry.schemas:
        content.append(info_box(_("Ubuntu Dock or Dash to Dock is required. No compatible dock schema was found.")))
        w.system_link(content, _("Ubuntu Desktop"), _("Manage the desktop integration provided by Ubuntu."), "ubuntu")
        return
    g = group(_("Dock visibility"), _("Your existing visibility is read from the dock. Select a behavior, then apply it explicitly."))
    refs = [Ref(schema, k) for k in ("dock-fixed", "autohide", "intellihide")]
    modes = [(True, False, False), (False, True, False), (False, True, True)]
    names = [_("Always visible"), _("Automatic hiding"), _("Hide when windows overlap")]
    states = [w.registry.state(r) for r in refs]
    actual = tuple(w.registry.value(r).unpack() for r in refs)
    initial = modes.index(actual) if actual in modes else 3
    if initial == 3:
        names.append(_("Custom configuration"))
    selection = Gtk.DropDown(model=Gtk.StringList.new(names), selected=initial, valign=Gtk.Align.CENTER)
    row = action_row(_("Visibility behavior"), _("Always visible keeps the dock on screen and reserves space for it."))
    row.add_suffix(selection)
    apply = button(label=_("Apply"), css="suggested-action")
    apply.set_sensitive(False)
    row.add_suffix(apply); g.add(row); content.append(g)
    def selected(*_a):
        apply.set_sensitive(selection.get_selected() < 3 and selection.get_selected() != initial)
    selection.connect("notify::selected", selected)
    def commit():
        index = selection.get_selected()
        if index >= len(modes):
            return
        edits = [(r, GLib.Variant("b", val).print_(True), expected) for r, val, expected in zip(refs, modes[index], states)]
        w.safe(lambda: w.store.apply(edits, _("Dock visibility"), backup=w.profiles.backup), lambda _r: (w.toast(_("Dock visibility saved")), w.render("dock")))
    apply.connect("clicked", lambda _b: commit())
    def external(_s, token):
        if token in {r.token for r in refs}:
            apply.set_sensitive(False)
            row.set_subtitle(_("Dock visibility changed. Reopen this page before applying another behavior."))
    w.subscribe(w.store, "changed", external)
    for ref in refs:
        w.store.watch(ref)
    w.add_specs(content, "dock")
    build_pinned(w, content)
    content.append(info_box(_("Ubuntu Dock groups windows by application. Its exposed click actions and window previews are available above; an ungrouped taskbar needs a different compatible extension. Alignment is limited to centering and the launcher placement options exposed by this dock.")))


def build_pinned(w, content):
    ref = Ref("org.gnome.shell", "favorite-apps")
    if not w.registry.exists(ref):
        return
    g = group(_("Pinned applications"), _("Use the arrows to reorder favorites. Removing a favorite does not uninstall it."))
    add = button(icon="list-add-symbolic", tooltip=_("Pin an application"))
    g.set_header_suffix(add)
    content.append(g)
    rows = []
    def render():
        for row in rows:
            g.remove(row)
        rows.clear()
        current = w.registry.value(ref).unpack()
        expected = w.registry.state(ref)
        def change(items):
            w.safe(lambda: w.store.set(ref, GLib.Variant("as", items).print_(True), expected, _("Pinned applications")))
        for index, app_id in enumerate(current):
            try:
                app = DesktopAppInfo.new(app_id)
            except TypeError:
                app = None
            row = action_row(app.get_display_name() if app else app_id, app_id)
            if app and app.get_icon():
                row.add_prefix(Gtk.Image(gicon=app.get_icon(), pixel_size=24))
            up = button(icon="go-up-symbolic", callback=lambda i=index: move_at(i, -1), tooltip=_("Move up"), css="flat")
            down = button(icon="go-down-symbolic", callback=lambda i=index: move_at(i, 1), tooltip=_("Move down"), css="flat")
            def move_at(i, delta):
                items = current[:]; items[i], items[i + delta] = items[i + delta], items[i]; change(items)
            up.set_sensitive(index > 0); down.set_sensitive(index < len(current) - 1)
            row.add_suffix(up); row.add_suffix(down)
            row.add_suffix(button(icon="list-remove-symbolic", callback=lambda i=index: change(current[:i] + current[i + 1:]), tooltip=_("Unpin application"), css="flat"))
            g.add(row); rows.append(row)
        if not rows:
            row = action_row(_("No pinned applications")); g.add(row); rows.append(row)
    def choose():
        current = w.registry.value(ref).unpack(); expected = w.registry.state(ref)
        apps = sorted([a for a in Gio.AppInfo.get_all() if a.get_id() and a.should_show() and a.get_id() not in current], key=lambda a: a.get_display_name().casefold())
        d, body, header = dialog(w, _("Pin an application"), 600, 450)
        chooser = Gtk.DropDown(model=Gtk.StringList.new([a.get_display_name() for a in apps]), enable_search=True)
        body.append(chooser)
        def pin():
            if chooser.get_selected() < len(apps):
                w.safe(lambda: w.store.set(ref, GLib.Variant("as", current + [apps[chooser.get_selected()].get_id()]).print_(True), expected, _("Pin application")), lambda _r: d.close())
        header.pack_end(button(label=_("Pin"), callback=pin, css="suggested-action"))
        d.present(w)
    add.connect("clicked", lambda _b: choose())
    render(); w.store.watch(ref)
    w.subscribe(w.store, "changed", lambda _s, token: render() if token == ref.token else None)


def build_extensions(w, content):
    w.add_specs(content, "extensions")
    g = group(_("Installed extensions"), _("GNOME Shell reports the actual runtime state. Disabling some extensions takes effect after logout."))
    g.set_header_suffix(button(icon="view-refresh-symbolic", callback=lambda: w.render("extensions"), tooltip=_("Refresh extensions"), css="flat"))
    content.append(g)
    try:
        extensions = w.extensions.list()
    except Exception as exc:
        g.add(action_row(_("Extension service unavailable"), str(exc)))
        return
    for uuid, data in sorted(extensions.items(), key=lambda x: x[1].get("name", x[0]).casefold()):
        state = int(data.get("state", 0))
        status = w.extensions.STATES.get(state, _("Unknown"))
        versions = data.get("shell-version", [])
        error = data.get("error", "")
        subtitle = uuid
        if versions:
            subtitle += "\n" + _("Supported Shell versions: ") + ", ".join(str(x) for x in versions)
        if error:
            subtitle += "\n" + str(error)
        row = action_row(data.get("name", uuid), subtitle)
        kind = {1: "success", 3: "error", 4: "warning"}.get(state, "neutral")
        row.add_suffix(pill(_(status), kind))
        toggle = Gtk.Switch(active=bool(data.get("enabled", state == 1)), valign=Gtk.Align.CENTER, sensitive=bool(data.get("canChange", True)) and (state in (1, 2, 6) or bool(data.get("enabled"))))
        toggle.update_property([Gtk.AccessibleProperty.LABEL], [_("Enable extension: ") + data.get("name", uuid)])
        def toggled(s, _p, uuid=uuid, state=state):
            w.safe(lambda: w.extensions.enable(uuid, s.get_active(), state), lambda _r: w.toast(_("Extension state updated")))
            # Refresh only after GNOME has delivered the state change.
            GLib.timeout_add(400, lambda: (w.render("extensions") if w.current_page == "extensions" else None, False)[1])
        toggle.connect("notify::active", toggled)
        row.add_suffix(toggle)
        if data.get("hasPrefs") or data.get("has-prefs"):
            row.add_suffix(button(icon="emblem-system-symbolic", callback=lambda uuid=uuid: w.safe(lambda: w.extensions.preferences(uuid)), tooltip=_("Extension preferences"), css="flat circular row-action"))
        schemas = w.registry.extension_schema_ids.get(uuid, set())
        if not schemas:
            # Some system extensions use globally installed schemas.
            if "ubuntu-dock" in uuid:
                schemas = {"org.gnome.shell.extensions.dash-to-dock"}
            elif "tiling-assistant" in uuid:
                schemas = {"org.gnome.shell.extensions.tiling-assistant"}
        if schemas:
            row.add_suffix(button(icon="preferences-other-symbolic", callback=lambda schemas=schemas: extension_schemas(w, schemas), tooltip=_("Browse exposed extension settings"), css="flat circular row-action"))
        if state in (3, 4) or error:
            row.add_suffix(button(icon="dialog-warning-symbolic", callback=lambda uuid=uuid: extension_errors(w, uuid), tooltip=_("Show extension errors"), css="flat circular row-action"))
        g.add(row)
    content.append(info_box(_("Extension settings are read from installed GSettings schemas and the extension preferences API. Desktop Studio never edits extension source files or bypasses version compatibility checks.")))
    g2 = group(_("More extensions"))
    g2.add(action_row(_("GNOME Extensions website"), _("Find extensions compatible with your Shell version."), lambda: w.safe(lambda: open_uri("https://extensions.gnome.org/")), "web-browser-symbolic", external=True))
    content.append(g2)
    scheduled = {"pending": False}
    def changed(_p, _sender, signal, _args):
        if signal in ("ExtensionStateChanged", "ExtensionStatusChanged") and not scheduled["pending"]:
            scheduled["pending"] = True
            def refresh():
                if content.get_root() and w.current_page == "extensions":
                    w.render("extensions")
                return False
            GLib.idle_add(refresh)
    w.subscribe(w.extensions.proxy, "g-signal", changed)


def extension_schemas(w, schemas):
    from .advanced import schema_dialog
    for sid in sorted(schemas):
        if sid in w.registry.schemas:
            schema_dialog(w, sid)
            break


def extension_errors(w, uuid):
    errors = w.safe(lambda: w.extensions.errors(uuid))
    if errors is not None:
        d = Adw.AlertDialog(heading=_("Extension diagnostics"), body="\n".join(errors) or _("No runtime errors reported. Check GNOME Shell version compatibility."))
        d.add_response("close", _("Close")); d.present(w)


def build_keyboard(w, content):
    from .keyboard import build
    build(w, content)


def build_windows(w, content):
    w.add_specs(content, "windows")
    schema = "org.gnome.shell.extensions.tiling-assistant"
    if schema in w.registry.schemas:
        g = group(_("Tiling Assistant"))
        g.add(action_row(_("Tiling & snapping preferences"), _("Browse the settings exposed by the installed Tiling Assistant extension."), lambda: extension_schemas(w, {schema})))
        content.append(g)
    g = group(_("Workspace & switching shortcuts"))
    g.add(action_row(_("Edit keyboard shortcuts"), _("Search for workspace, switch-applications, switch-windows, or tile."), lambda: w.navigate("keyboard")))
    content.append(g)


def build_input(w, content):
    detected = []
    for k, title in (("mouse", _("Mouse")), ("touchpad", _("Touchpad"))):
        if w.env.has_input(k):
            detected.append(title)
    content.append(info_box(_("Detected input capabilities: ") + (", ".join(detected) or _("No device capabilities reported by udev")) + ". " + _("Preferences may also apply to devices connected later. Individual libinput options depend on the hardware.")))
    w.add_specs(content, "input")
    content.append(info_box(_("GNOME’s built-in Wayland multi-finger gestures do not expose arbitrary gesture remapping through a supported settings API. Only installed extension settings can add configurable gestures.")))
    w.system_link(content, _("Mouse & Touchpad"), _("Inspect device-specific options exposed by GNOME Settings."), "mouse")


def build_displays(w, content):
    from .display import build
    build(w, content)


def build_sound(w, content):
    audio = Audio()
    if audio.available:
        g = group(_("Output volume"), _("Uses the session’s default WirePlumber audio output."))
        row = action_row(_("Volume"))
        slider = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        slider.set_size_request(220, -1); slider.set_draw_value(True); slider.set_valign(Gtk.Align.CENTER)
        row.add_suffix(slider)
        mute = Gtk.Switch(valign=Gtk.Align.CENTER)
        mute_row = action_row(_("Mute output")); mute_row.add_suffix(mute)
        g.add(row); g.add(mute_row); content.append(g)
        state = {"value": None, "freeze": False, "drag": False}
        def refresh():
            if not slider.get_root():
                return False
            def update(text):
                if state["drag"]:
                    return
                state["freeze"] = True; state["value"] = text
                match = re.search(r"Volume:\s*([0-9.]+)", text)
                if match:
                    slider.set_value(float(match.group(1)) * 100)
                mute.set_active("MUTED" in text)
                state["freeze"] = False
            background(audio.volume, update, lambda msg: row.set_subtitle(msg))
            return True
        def set_volume(_s):
            if not state["freeze"] and state["value"]:
                expected = state["value"]
                fraction = slider.get_value() / 100
                background(lambda: audio.set_volume(fraction, expected), lambda _r: refresh(), lambda msg: (w.error(msg), refresh()))
        # Commit on release / key release to avoid spawning a process per pixel.
        click = Gtk.GestureClick(); slider.add_controller(click)
        click.connect("pressed", lambda *_a: state.update(drag=True))
        click.connect("released", lambda *_a: (state.update(drag=False), set_volume(slider)))
        keys = Gtk.EventControllerKey(); slider.add_controller(keys)
        keys.connect("key-released", lambda *_a: set_volume(slider))
        def set_mute(s, _p):
            if not state["freeze"] and state["value"]:
                muted, expected = s.get_active(), state["value"]
                background(lambda: audio.mute(muted, expected), lambda _r: refresh(), lambda msg: (w.error(msg), refresh()))
        mute.connect("notify::active", set_mute)
        GLib.idle_add(refresh); GLib.timeout_add_seconds(3, refresh)
    w.add_specs(content, "sound")
    w.system_link(content, _("Sound"), _("Choose input/output devices, balance, audio profiles, and per-application levels in the supported GNOME sound mixer."), "sound")
    w.system_link(content, _("Notifications"), _("Per-application notification permissions and lock-screen behavior."), "notifications")


def build_power(w, content):
    w.add_specs(content, "power")
    w.system_link(content, _("Power"), _("Battery status, hardware power profiles, and device-specific options."), "power")
    w.system_link(content, _("Privacy & Security"), _("Manage application permissions and platform privacy services."), "privacy")


def build_accessibility(w, content):
    w.add_specs(content, "accessibility")
    w.system_link(content, _("Accessibility"), _("Additional magnifier, hearing, typing, and pointing options."), "universal-access")


def build_system(w, content):
    w.add_specs(content, "system")
    build_connections(w, content)
    build_defaults(w, content)
    build_startup(w, content)
    w.system_link(content, _("Region & Language"), _("Install languages and choose display language. A session logout may be required."), "region", _("Logout"))
    w.system_link(content, _("Date & Time"), _("Set system time, NTP, and time zone. GNOME Settings requests authorization only for the operation that needs it."), "datetime", _("Administrator"))
    w.system_link(content, _("Default Applications"), _("Configure additional MIME types and preferred applications."), "default-apps")


def build_connections(w, content):
    connections = Connections()
    g = group(_("Connections"), _("Changes use NetworkManager and BlueZ. Their service policies decide whether authorization is needed."))
    content.append(g)
    try:
        network = connections.network()
        for field, title in (("NetworkingEnabled", _("Networking")), ("WirelessEnabled", _("Wi-Fi"))):
            if field not in network:
                continue
            expected = network[field]
            row = action_row(title)
            toggle = Gtk.Switch(active=expected, valign=Gtk.Align.CENTER)
            row.add_suffix(toggle); g.add(row)
            def changed(s, _p, field=field, expected=expected):
                s.set_sensitive(False)
                enabled = s.get_active()
                background(lambda: connections.set_network(field, enabled, expected), lambda _r: w.render("system") if w.current_page == "system" else None, lambda msg: (w.error(msg), w.render("system") if w.current_page == "system" else None))
            toggle.connect("notify::active", changed)
    except Exception as exc:
        g.add(unavailable_row(_("Networking"), _("NetworkManager is not available in this session."), exc))
    try:
        adapters = connections.bluetooth()
        for path, props in adapters:
            row = action_row(_("Bluetooth"), props.get("Alias", path))
            toggle = Gtk.Switch(active=props.get("Powered", False), valign=Gtk.Align.CENTER)
            row.add_suffix(toggle); g.add(row)
            def changed(s, _p, path=path, expected=props.get("Powered", False)):
                s.set_sensitive(False)
                enabled = s.get_active()
                background(lambda: connections.set_bluetooth(path, enabled, expected), lambda _r: w.render("system") if w.current_page == "system" else None, lambda msg: (w.error(msg), w.render("system") if w.current_page == "system" else None))
            toggle.connect("notify::active", changed)
        if not adapters:
            g.add(action_row(_("Bluetooth"), _("No Bluetooth adapter reported by BlueZ.")))
    except Exception as exc:
        g.add(unavailable_row(_("Bluetooth"), _("The Bluetooth service (BlueZ) is not running."), exc))
    g.add(action_row(_("Network settings"), _("Connections, VPN, and network details."), lambda: w.safe(lambda: open_settings("network")), external=True))
    g.add(action_row(_("Wi-Fi settings"), _("Choose and manage wireless networks."), lambda: w.safe(lambda: open_settings("wifi")), external=True))
    g.add(action_row(_("Bluetooth settings"), _("Pair and manage Bluetooth devices."), lambda: w.safe(lambda: open_settings("bluetooth")), external=True))
    scheduled = {"pending": False}
    def refresh(*_args):
        if scheduled["pending"]:
            return
        scheduled["pending"] = True
        def rebuild():
            if content.get_root() and w.current_page == "system":
                w.render("system")
            return False
        GLib.idle_add(rebuild)
    if connections.network_proxy:
        w.subscribe(connections.network_proxy, "g-properties-changed", refresh)
    if connections.bluetooth_proxy:
        w.subscribe(connections.bluetooth_proxy, "g-signal", refresh)
        try:
            for path, props in connections.bluetooth():
                from ..platform.services import dbus_proxy
                proxy = dbus_proxy("org.bluez", path, "org.bluez.Adapter1", True)
                w.subscribe(proxy, "g-properties-changed", refresh)
        except Exception:
            pass


def unavailable_row(title, message, exc):
    row = action_row(title, message)
    row.set_tooltip_text(str(exc))
    row.add_suffix(pill(_("Unavailable"), "neutral", str(exc)))
    return row


def build_defaults(w, content):
    g = group(_("Default applications"))
    content.append(g)
    for mime, title, scheme in (("x-scheme-handler/http", _("Web browser"), True), ("x-scheme-handler/mailto", _("Email"), True), ("text/plain", _("Text files"), False), ("image/png", _("Images"), False), ("application/pdf", _("PDF documents"), False)):
        current = Gio.AppInfo.get_default_for_type(mime, False)
        apps = Gio.AppInfo.get_all_for_type(mime)
        if current and not any(a.equal(current) for a in apps):
            apps.insert(0, current)
        if not apps:
            g.add(action_row(title, _("No compatible applications installed.")))
            continue
        row = action_row(title, mime)
        selected = next((i for i, a in enumerate(apps) if current and a.equal(current)), 0)
        chooser = Gtk.DropDown(model=Gtk.StringList.new([a.get_display_name() for a in apps]), selected=selected, enable_search=True, valign=Gtk.Align.CENTER)
        row.add_suffix(chooser); g.add(row)
        def choose(c, _p, mime=mime, apps=apps, current=current):
            def work():
                now = Gio.AppInfo.get_default_for_type(mime, False)
                if (now is None) != (current is None) or (now and not now.equal(current)):
                    raise SettingsError("Default application changed elsewhere; reopen this page")
                app = apps[c.get_selected()]
                if not app.set_as_default_for_type(mime):
                    raise SettingsError("The default application could not be changed")
                if mime == "x-scheme-handler/http":
                    app.set_as_default_for_type("x-scheme-handler/https")
            w.safe(work, lambda _r: w.toast(_("Default application updated")))
            GLib.idle_add(lambda: (w.render("system") if w.current_page == "system" else None, False)[1])
        chooser.connect("notify::selected", choose)


def build_startup(w, content):
    service = StartupApps()
    backup_dir = w.get_application().data_dir / "backups/startup"
    g = group(_("Startup applications"), _("Manage the autostart entries registered for your desktop. User overrides are backed up before editing."))
    g.set_header_suffix(button(icon="list-add-symbolic", callback=lambda: add_startup(), tooltip=_("Add startup application")))
    content.append(g)
    def saved(backup):
        w.toast(_("Startup preference saved · takes effect next login"))
        toast = Adw.Toast(title=_("Startup entry backed up"), button_label=_("Undo"), timeout=0)
        toast.connect("button-clicked", lambda _t: w.safe(lambda: service.restore(backup), lambda _r: (w.toast(_("Startup change undone")), w.render("system") if w.current_page == "system" else None)))
        w.toasts.add_toast(toast)
    def add_startup():
        apps = sorted([a for a in Gio.AppInfo.get_all() if a.should_show() and isinstance(a, DesktopAppInfo)], key=lambda a: a.get_display_name().casefold())
        d, body, header = dialog(w, _("Add startup application"), 620, 340)
        chooser = Gtk.DropDown(model=Gtk.StringList.new([a.get_display_name() for a in apps]), enable_search=True)
        body.append(chooser)
        body.append(info_box(_("The selected application will launch at your next desktop login. Adding it does not launch it now.")))
        def add():
            i = chooser.get_selected()
            if i < len(apps):
                w.safe(lambda: service.add(apps[i], backup_dir), lambda backup: (saved(backup), d.close(), w.render("system")))
        header.pack_end(button(label=_("Add"), callback=add, css="suggested-action")); d.present(w)
    apps = service.list()
    for path, title, enabled, data in apps:
        row = action_row(title, str(path))
        toggle = Gtk.Switch(active=enabled, valign=Gtk.Align.CENTER)
        row.add_suffix(toggle)
        def change(s, _p, path=path, data=data):
            w.safe(lambda: service.set_enabled(path, s.get_active(), data, backup_dir), saved)
            GLib.idle_add(lambda: (w.render("system") if w.current_page == "system" else None, False)[1])
        toggle.connect("notify::active", change)
        g.add(row)
    if not apps:
        g.add(action_row(_("No registered startup applications")))


def build_advanced(w, content):
    from .advanced import build
    build(w, content)


def build_profiles(w, content):
    from .profiles import build
    build(w, content)


def build_history(w, content):
    from .profiles import build_history as build
    build(w, content)
