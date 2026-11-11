"""A native gallery of the exact Bibata family shipped by Ryoku."""
from gi.repository import Adw, Gdk, GLib, Gtk

from ..core.settings import Ref
from ..i18n import _
from ..platform.cursors import THEMES, SOURCE, UPSTREAM, cursor_image, install_collection, theme_directory
from ..platform.services import background, open_uri
from .widgets import button, dialog, info_box, label

CURSOR_THEME = Ref("org.gnome.desktop.interface", "cursor-theme")
CURSOR_SIZE = Ref("org.gnome.desktop.interface", "cursor-size")


def texture_for(image):
    return Gdk.MemoryTexture.new(image.width, image.height, Gdk.MemoryFormat.B8G8R8A8_PREMULTIPLIED, GLib.Bytes.new(image.pixels), image.width * 4)


def preview(theme, size=40):
    """Show actual installed arrow, text, and hand cursor images."""
    box = Gtk.Box(spacing=18, halign=Gtk.Align.CENTER, height_request=78, valign=Gtk.Align.CENTER)
    box.update_property([Gtk.AccessibleProperty.LABEL], [_("Cursor image preview: ") + theme])
    arrow = None
    for name, title in (("left_ptr", _("Pointer")), ("xterm", _("Text cursor")), ("hand2", _("Link pointer"))):
        image = cursor_image(theme, name, size)
        if image:
            texture = texture_for(image)
            picture = Gtk.Picture(paintable=texture, width_request=42, height_request=52, content_fit=Gtk.ContentFit.CONTAIN, can_shrink=True)
            picture.set_tooltip_text(title)
            picture.update_property([Gtk.AccessibleProperty.LABEL], [title])
            box.append(picture)
            if name == "left_ptr":
                arrow = Gdk.Cursor.new_from_texture(texture, image.xhot, image.yhot, None)
    if not box.get_first_child():
        box.append(Gtk.Image(icon_name="input-mouse-symbolic", pixel_size=40))
    if arrow:
        # Hover previews affect this widget only; no desktop preference changes.
        box.set_cursor(arrow)
    return box


def collection_dialog(window):
    d, content, header = dialog(window, _("Ryoku cursor collection"), 960, 760)
    content.append(label(_("Bibata · the Ryoku cursor family"), "title-2"))
    content.append(info_box(_("Ryoku uses Bibata Modern Ice by default. Choose Modern (rounded) or Original (sharp), in Ice (white), Classic (black), or Amber, including mirrored Right variants. Previewing or installing themes keeps your current cursor selected.")))
    status = label("", "dim-label")
    content.append(status)
    download = button(label=_("Install collection"), css="suggested-action")
    header.pack_end(download)
    progress = Gtk.ProgressBar(show_text=True, visible=False)
    content.append(progress)
    grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, min_children_per_line=1, max_children_per_line=2, column_spacing=14, row_spacing=14)
    content.append(grid)
    error = label("", "error")
    content.append(error)
    state = {"installing": False, "closed": False}

    def render():
        child = grid.get_first_child()
        while child:
            following = child.get_next_sibling()
            grid.remove(child)
            child = following
        current = window.registry.value(CURSOR_THEME).unpack()
        expected = window.registry.state(CURSOR_THEME)
        installed = sum(theme_directory(theme) is not None for theme in THEMES)
        status.set_label(_("Current cursor: {current} · {installed}/{total} collection themes installed").format(current=current, installed=installed, total=len(THEMES)))
        download.set_visible(installed < len(THEMES))
        download.set_sensitive(not state["installing"])
        for theme in THEMES:
            present = theme_directory(theme) is not None
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=2, margin_bottom=2)
            card.add_css_class("cursor-card")
            title = theme.removeprefix("Bibata-").replace("-", " · ")
            card.append(label(title, "heading"))
            card.append(preview(theme))
            chosen = current == theme
            text = _("Selected") if chosen else _("Use this cursor") if present else _("Install collection to use")
            use = button(label=text, css="suggested-action" if chosen else None)
            use.set_sensitive(present and not chosen and not state["installing"] and window.registry.settings(CURSOR_THEME).is_writable(CURSOR_THEME.key))
            def select(theme=theme, expected=expected):
                window.safe(lambda: window.store.set(CURSOR_THEME, GLib.Variant("s", theme).print_(True), expected, _("Cursor theme")), lambda _r: window.toast(_("Cursor theme saved")))
            use.connect("clicked", lambda _b, select=select: select())
            card.append(use)
            if theme == "Bibata-Modern-Ice":
                card.append(label(_("Ryoku default"), "caption"))
            grid.append(card)

    def notify_progress(phase, done, total):
        def update():
            if state["closed"]:
                return False
            progress.set_fraction(min(1.0, done / total) if total else 0)
            progress.set_text(_("Downloading cursors…") if phase == "download" else _("Installing cursor images…"))
            return False
        GLib.idle_add(update)

    def install():
        state["installing"] = True
        # Keep this dialog until its reversible file installation completes.
        d.set_can_close(False)
        progress.set_visible(True)
        progress.set_fraction(0)
        error.set_label("")
        render()
        def finished(result):
            state["installing"] = False
            d.set_can_close(True)
            progress.set_visible(False)
            render()
            if window.current_page == "appearance":
                window.render("appearance")
            window.toast(_("Cursor collection installed · your selected cursor is unchanged"))
        def failed(message):
            state["installing"] = False
            d.set_can_close(True)
            progress.set_visible(False)
            error.set_label(message)
            render()
        background(lambda: install_collection(notify_progress), finished, failed)
    download.connect("clicked", lambda _b: install())
    content.append(label(_("One-time download: 22 MB. Installed images: about 322 MiB. Installed only for your user; existing theme folders are preserved. The archive is verified against Ryoku’s pinned checksum."), "caption"))
    links = Gtk.Box(spacing=8)
    links.append(button(label=_("Ryoku package source"), callback=lambda: window.safe(lambda: open_uri(SOURCE))))
    links.append(button(label=_("Bibata project & license"), callback=lambda: window.safe(lambda: open_uri(UPSTREAM))))
    content.append(links)
    content.append(info_box(_("These are standard Xcursor themes supported by GNOME on Wayland. Hyprland-specific stretch, rotate, and cursor trail effects do not carry over. Ryoku’s optional wallpaper-driven Material recoloring is a separate integration and is not enabled here.")))

    def changed(_store, token):
        if token == CURSOR_THEME.token and not state["closed"]:
            render()
    window.store.watch(CURSOR_THEME)
    handler = window.store.connect("changed", changed)
    def closed(_dialog):
        state["closed"] = True
        window.store.disconnect(handler)
    d.connect("closed", closed)
    render()
    d.present(window)
    return d
