from pathlib import Path
import uuid

from gi.repository import Adw, Gdk, GdkPixbuf, GLib, Gtk

from ..core.profiles import atomic_json, timestamp
from ..i18n import _
from ..platform.displays import Displays
from .widgets import action_row, button, group, info_box, label


def build(w, content):
    try:
        current = w.displays.read()
        draft = Displays.draft(current)
    except Exception as exc:
        content.append(info_box(_("The Mutter display interface is unavailable: ") + str(exc)))
        w.system_link(content, _("Displays"), _("Configure monitors in GNOME Settings."), "display")
        w.add_specs(content, "displays")
        return
    content.append(info_box(_("Display changes are grouped. Apply opens GNOME Shell’s Keep Changes / Revert dialog with an automatic timeout. The compositor restores the previous layout if you do not confirm, including if this application closes. Night Light below applies immediately.")))
    state = {"dirty": False, "applying": False, "stale": False}
    warning = label("", "warning")
    content.append(warning)
    buttons = Gtk.Box(spacing=10)
    apply = button(label=_("Apply display changes"), css="suggested-action")
    apply.set_sensitive(False)
    reset = button(label=_("Reload / Revert edits"), callback=lambda: w.render("displays"))
    buttons.append(apply); buttons.append(reset); content.append(buttons)
    def dirty():
        state["dirty"] = True
        apply.set_sensitive(not state["stale"])
    physical = {m[0][0]: m for m in current[1]}
    used = {member[0] for g in draft for member in g[5]}
    groups = [(g, True) for g in draft]
    # Inactive, connected monitors are editable and can be enabled explicitly.
    for connector, monitor in physical.items():
        if connector in used or monitor[2].get("is-for-lease") or not monitor[1]:
            continue
        mode = next((m for m in monitor[1] if m[6].get("is-preferred")), monitor[1][0])
        groups.append(([0, 0, mode[4], 0, False, [(connector, mode[0], {})]], False))
    active = []
    primary_buttons = []
    preview = Gtk.Picture(height_request=190, content_fit=Gtk.ContentFit.CONTAIN, can_shrink=True)
    preview.add_css_class("card")
    preview.update_property([Gtk.AccessibleProperty.LABEL], [_("Monitor arrangement preview")])
    content.append(preview)
    def render_preview():
        width, height = 800, 190
        shown = [(g, active[i].get_active()) for i, (g, _enabled) in enumerate(groups) if i < len(active)]
        shown = [g for g, enabled in shown if enabled]
        dimensions = []
        for g in shown:
            connector, mode_id, _props = g[5][0]
            mode = next((m for m in physical[connector][1] if m[0] == mode_id), physical[connector][1][0])
            mw, mh = mode[1], mode[2]
            if g[3] % 2:
                mw, mh = mh, mw
            if current[3].get("layout-mode", 1) == 1:
                mw /= g[2]; mh /= g[2]
            dimensions.append((g, mw, mh))
        if not dimensions:
            return
        maxx = max(g[0] + mw for g, mw, mh in dimensions)
        maxy = max(g[1] + mh for g, mw, mh in dimensions)
        factor = min((width - 40) / max(maxx, 1), (height - 36) / max(maxy, 1))
        shapes = []
        for g, mw, mh in dimensions:
            x, y = 20 + g[0] * factor, 18 + g[1] * factor
            shapes.append(f'<rect x="{x+1}" y="{y+1}" width="{max(1,mw*factor-2)}" height="{max(1,mh*factor-2)}" rx="6" fill="{"#7cbbb2" if g[4] else "#b7d8d3"}" stroke="#287970" stroke-width="2"/>')
            name = GLib.markup_escape_text(g[5][0][0] + (" ★" if g[4] else ""))
            shapes.append(f'<text x="{x+12}" y="{y+25}" font-family="sans-serif" font-size="14" font-weight="bold" fill="#164d47">{name}</text>')
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">' + ''.join(shapes) + '</svg>'
        loader = GdkPixbuf.PixbufLoader.new_with_type("svg")
        loader.write(svg.encode()); loader.close()
        preview.set_paintable(Gdk.Texture.new_for_pixbuf(loader.get_pixbuf()))
    def update():
        dirty(); render_preview()
    first_primary = None
    for index, (g, enabled) in enumerate(groups):
        connector = g[5][0][0]
        monitor = physical[connector]
        title = monitor[2].get("display-name", connector) + " · " + connector
        card = group(title)
        content.append(card)
        toggle = Gtk.Switch(active=enabled, valign=Gtk.Align.CENTER)
        active.append(toggle)
        row = action_row(_("Enable display")); row.add_suffix(toggle); card.add(row)
        toggle.connect("notify::active", lambda *_a: update())
        if len(g[5]) > 1:
            card.add(action_row(_("Mirrored display group"), _("This group contains multiple monitors. Use GNOME Displays to change mirroring; the existing group will be preserved."), lambda: w.safe(lambda: __import__("desktop_studio.platform.services", fromlist=["open_settings"]).open_settings("display"))))
            continue
        mode_list = monitor[1]
        ids = [m[0] for m in mode_list]
        mode = next(m for m in mode_list if m[0] == g[5][0][1])
        mode_select = Gtk.DropDown(model=Gtk.StringList.new([f"{m[1]} × {m[2]} · {m[3]:.2f} Hz" + (" · VRR" if m[6].get("refresh-rate-mode") == "variable" else "") for m in mode_list]), selected=ids.index(mode[0]), enable_search=True, valign=Gtk.Align.CENTER)
        mode_row = action_row(_("Resolution & refresh rate")); mode_row.add_suffix(mode_select); card.add(mode_row)
        scale_select = Gtk.DropDown(valign=Gtk.Align.CENTER)
        scales = {"values": mode[5]}
        scale_select.set_model(Gtk.StringList.new([f"{s * 100:.0f}%" for s in mode[5]]))
        scale_select.set_selected(next((i for i, s in enumerate(mode[5]) if abs(s - g[2]) < 0.00001), 0))
        scale_row = action_row(_("Scale"), _("Only scales advertised by this monitor mode are offered.")); scale_row.add_suffix(scale_select); card.add(scale_row)
        def mode_changed(s, _p, g=g, mode_list=mode_list, scale_select=scale_select, scales=scales):
            m = mode_list[s.get_selected()]
            old_props = g[5][0][2]
            g[5][0] = (g[5][0][0], m[0], old_props)
            scales["values"] = m[5]
            old = g[2]
            # Ignore the transient invalid selection during model replacement.
            scale_select.set_model(Gtk.StringList.new([f"{x * 100:.0f}%" for x in m[5]]))
            pick = next((i for i, x in enumerate(m[5]) if abs(x - old) < 0.00001), 0)
            scale_select.set_selected(pick)
            g[2] = m[5][pick]
            update()
        mode_select.connect("notify::selected", mode_changed)
        def scale_changed(s, _p, g=g, scales=scales):
            i = s.get_selected()
            if i < len(scales["values"]):
                g[2] = scales["values"][i]; update()
        scale_select.connect("notify::selected", scale_changed)
        orientation_names = [_("Landscape"), _("Portrait · 90°"), _("Landscape · 180°"), _("Portrait · 270°"), _("Flipped"), _("Flipped · 90°"), _("Flipped · 180°"), _("Flipped · 270°")]
        orientation = Gtk.DropDown(model=Gtk.StringList.new(orientation_names), selected=g[3], valign=Gtk.Align.CENTER)
        orientation.connect("notify::selected", lambda s, _p, g=g: (g.__setitem__(3, s.get_selected()), update()))
        row = action_row(_("Orientation")); row.add_suffix(orientation); card.add(row)
        primary = Gtk.CheckButton(active=g[4], valign=Gtk.Align.CENTER)
        if first_primary:
            primary.set_group(first_primary)
        else:
            first_primary = primary
        primary_buttons.append(primary)
        row = action_row(_("Primary display")); row.add_suffix(primary); card.add(row)
        primary.connect("toggled", lambda s, g=g: (g.__setitem__(4, s.get_active()), update()))
        for coord, title in ((0, _("Horizontal position")), (1, _("Vertical position"))):
            spin = Gtk.SpinButton.new_with_range(0, 65535, 1)
            spin.set_value(g[coord]); spin.set_valign(Gtk.Align.CENTER)
            row = action_row(title, _("Logical coordinates in the desktop arrangement.")); row.add_suffix(spin); card.add(row)
            spin.connect("value-changed", lambda s, g=g, coord=coord: (g.__setitem__(coord, s.get_value_as_int()), update()))
    # Initial construction must not count as an edit.
    state["dirty"] = False; apply.set_sensitive(False)
    render_preview()
    def commit():
        if state["stale"]:
            return
        selected = [g for i, (g, enabled) in enumerate(groups) if active[i].get_active()]
        def work():
            Displays.validate_draft(current, selected)
            backup = w.get_application().data_dir / "backups/displays" / (uuid.uuid4().hex + ".json")
            atomic_json(backup, {"created": timestamp(), "state": current})
            state["applying"] = True
            w.displays.apply_with_confirmation(current, selected)
            apply.set_sensitive(False)
            warning.set_label(_("Confirm in GNOME’s Keep Changes / Revert dialog. Without confirmation GNOME automatically restores the previous layout. Reload this page after the dialog closes."))
        w.safe(work)
        state["applying"] = False
    apply.connect("clicked", lambda _b: commit())
    def monitor_signal(_p, _sender, signal, _args):
        if signal == "MonitorsChanged":
            state["stale"] = True; apply.set_sensitive(False)
            if not state["applying"]:
                warning.set_label(_("The display state changed. Finish GNOME’s confirmation if visible, then reload this page before making more changes."))
    w.subscribe(w.displays.proxy, "g-signal", monitor_signal)
    w.add_specs(content, "displays")
    w.system_link(content, _("Displays"), _("Manage mirroring, HDR, color profiles, and additional hardware-specific options in GNOME Settings."), "display")
