from pathlib import Path
import re

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from ..catalog import Spec
from ..core.settings import Ref, SettingsError
from ..i18n import _
from ..platform.keyboard import INPUT, CUSTOM, MEDIA, canonical_shortcut, conflicts, create_custom_shortcut, layouts, shortcut_refs, toshy_to_gnome, xkb_options, validate_xkb_options
from ..platform.services import background, launch, open_settings, open_uri
from .widgets import action_row, buffer_text, button, dialog, group, info_box, label, text_editor


def build(w, content):
    w.registry.refresh_paths()
    build_layouts(w, content)
    build_xkb(w, content)
    w.add_specs(content, "keyboard")
    build_shortcuts(w, content)
    build_toshy(w, content)
    w.system_link(content, _("Keyboard"), _("GNOME’s input-source chooser also supports installed IBus input methods."), "keyboard")
    # Rebuild native option/shortcut lists after an external edit. Defer until
    # signal delivery completes, so controls are never removed in their callback.
    pending = {"source": None}
    def external(_s, token):
        sid, path, key = token.split("|")
        if sid == INPUT and key != "sources" or "keybindings" in sid or sid in (MEDIA, CUSTOM):
            if pending["source"] is None:
                def refresh():
                    pending["source"] = None
                    if content.get_root() and w.current_page == "keyboard":
                        w.render("keyboard")
                    return False
                pending["source"] = GLib.idle_add(refresh)
    for ref in list(shortcut_refs(w.registry)) + [Ref(INPUT, "xkb-options"), Ref(MEDIA, "custom-keybindings")]:
        if w.registry.exists(ref):
            w.store.watch(ref)
    w.subscribe(w.store, "changed", external)


def build_layouts(w, content):
    ref = Ref(INPUT, "sources")
    if not w.registry.exists(ref):
        return
    available = layouts()
    titles = dict(available)
    g = group(_("Keyboard layouts"), _("Ordering affects layout cycling. Existing English, Persian, IBus sources, and layout variants are preserved until you edit them."))
    g.set_header_suffix(button(icon="list-add-symbolic", callback=lambda: add_layout(), tooltip=_("Add a layout")))
    content.append(g)
    rows = []
    def render():
        for row in rows:
            g.remove(row)
        rows.clear()
        current = w.registry.value(ref).unpack()
        expected = w.registry.state(ref)
        def change(items):
            if not items:
                w.error(_("Keep at least one input source.")); return
            w.safe(lambda: w.store.set(ref, GLib.Variant("a(ss)", items).print_(True), expected, _("Keyboard layouts")))
        for index, (kind, name) in enumerate(current):
            row = action_row(titles.get(name, name) if kind == "xkb" else name, f"{kind} · {name}")
            row.add_prefix(Gtk.Image(icon_name="input-keyboard-symbolic"))
            def move(index, delta):
                items = current[:]
                items[index], items[index + delta] = items[index + delta], items[index]
                change(items)
            up = button(icon="go-up-symbolic", callback=lambda i=index: move(i, -1), tooltip=_("Move layout up"), css="flat")
            down = button(icon="go-down-symbolic", callback=lambda i=index: move(i, 1), tooltip=_("Move layout down"), css="flat")
            remove = button(icon="list-remove-symbolic", callback=lambda i=index: change(current[:i] + current[i + 1:]), tooltip=_("Remove layout"), css="flat")
            up.set_sensitive(index > 0); down.set_sensitive(index < len(current) - 1); remove.set_sensitive(len(current) > 1)
            row.add_suffix(up); row.add_suffix(down); row.add_suffix(remove)
            g.add(row); rows.append(row)
    def add_layout():
        current = w.registry.value(ref).unpack(); expected = w.registry.state(ref)
        choices = [(name, title) for name, title in available if ("xkb", name) not in current]
        d, body, header = dialog(w, _("Add keyboard layout"), 600, 380)
        chooser = Gtk.DropDown(model=Gtk.StringList.new([f"{title} · {name}" for name, title in choices]), enable_search=True)
        body.append(chooser)
        body.append(info_box(_("Layout definitions come from your installed XKB rules. Input methods are managed in GNOME Keyboard settings.")))
        def add():
            i = chooser.get_selected()
            if i < len(choices):
                w.safe(lambda: w.store.set(ref, GLib.Variant("a(ss)", current + [("xkb", choices[i][0])]).print_(True), expected, _("Add keyboard layout")), lambda _r: d.close())
        header.pack_end(button(label=_("Add"), callback=add, css="suggested-action"))
        d.present(w)
    render(); w.store.watch(ref)
    w.subscribe(w.store, "changed", lambda _s, token: render() if token == ref.token else None)


def build_xkb(w, content):
    ref = Ref(INPUT, "xkb-options")
    if not w.registry.exists(ref):
        return
    g = group(_("Native modifiers & layout switching"), _("These are GNOME/XKB options. Toshy can remap the resulting keys again; its mappings are managed separately below."))
    content.append(g)
    installed_options = xkb_options()
    families = [
        ("grp:", _("XKB layout-switching shortcut"), [("", _("No extra XKB shortcut")), ("grp:caps_toggle", _("Caps Lock")), ("grp:alt_shift_toggle", _("Alt + Shift")), ("grp:ctrl_shift_toggle", _("Ctrl + Shift")), ("grp:win_space_toggle", _("Super + Space")), ("grp:lwin_toggle", _("Left Super"))]),
        ("caps:", _("Caps Lock behavior"), [("", _("Default")), ("caps:escape", _("Escape")), ("caps:swapescape", _("Swap Caps Lock and Escape")), ("caps:ctrl_modifier", _("Control modifier")), ("caps:none", _("Disabled"))]),
        ("compose:", _("Compose key"), [("", _("No Compose key")), ("compose:ralt", _("Right Alt")), ("compose:rwin", _("Right Super")), ("compose:menu", _("Menu")), ("compose:caps", _("Caps Lock"))]),
        ("altwin:", _("Alt & Super behavior"), [("", _("Default")), ("altwin:swap_alt_win", _("Swap Alt and Super")), ("altwin:swap_lalt_lwin", _("Swap left Alt and left Super")), ("altwin:ctrl_win", _("Map Super to Control"))]),
        ("ctrl:", _("Control key position"), [("", _("Default")), ("ctrl:nocaps", _("Caps Lock as Control")), ("ctrl:swapcaps", _("Swap Control and Caps Lock")), ("ctrl:rctrl_ralt", _("Right Alt as right Control"))]),
    ]
    for prefix, title, options in families:
        options = [(key, name) for key, name in options if not key or key in installed_options]
        current = w.registry.value(ref).unpack(); expected = w.registry.state(ref)
        active = [x for x in current if x.startswith(prefix)]
        actual = active[0] if len(active) == 1 else "" if not active else "|".join(active)
        opts = options[:]
        if actual not in {x[0] for x in opts}:
            opts.append((actual, _("Current custom options: ") + ", ".join(active)))
        select = Gtk.DropDown(model=Gtk.StringList.new([x[1] for x in opts]), selected=next(i for i, x in enumerate(opts) if x[0] == actual), valign=Gtk.Align.CENTER)
        row = action_row(title, _("Preserves all other XKB option families.")); row.add_suffix(select); g.add(row)
        def changed(s, _p, prefix=prefix, opts=opts, current=current, expected=expected, title=title):
            choice = opts[s.get_selected()][0]
            if "|" in choice:
                return
            items = [x for x in current if not x.startswith(prefix)] + ([choice] if choice else [])
            def save():
                validate_xkb_options(items)
                return w.store.set(ref, GLib.Variant("as", items).print_(True), expected, title)
            w.safe(save, lambda _r: w.toast(_("Native keyboard option saved")))
            GLib.idle_add(lambda: (w.render("keyboard") if w.current_page == "keyboard" else None, False)[1])
        select.connect("notify::selected", changed)
    g.add(action_row(_("Active XKB options"), ", ".join(w.registry.value(ref).unpack()) or _("None")))


def build_shortcuts(w, content):
    g = group(_("GNOME shortcuts"), _("Search all discovered native and extension shortcuts. Recording captures the key events delivered after any remapping service."))
    add = button(icon="list-add-symbolic", callback=lambda: custom_dialog(w), tooltip=_("Add custom shortcut"))
    g.set_header_suffix(add); content.append(g)
    search = Gtk.SearchEntry(placeholder_text=_("Find shortcuts — workspace, screenshot, switch-input-source…"))
    search.update_property([Gtk.AccessibleProperty.LABEL], [_("Search keyboard shortcuts")])
    content.append(search)
    results = group(_("Shortcut bindings"))
    content.append(results)
    entries = []
    for ref in shortcut_refs(w.registry):
        key = w.registry.schema_key(ref)
        title = key.get_summary() or ref.key
        if ref.schema == CUSTOM:
            title = w.registry.value(Ref(CUSTOM, "name", ref.path)).unpack() or _("Custom shortcut")
        current = w.registry.value(ref).unpack()
        current = current if isinstance(current, list) else [current]
        entries.append((ref, title, current, (ref.key + " " + title + " " + ref.schema + " " + " ".join(current)).casefold()))
    rows = []
    def render(*_a):
        for row in rows:
            results.remove(row)
        rows.clear()
        words = search.get_text().casefold().split()
        matches = [x for x in entries if all(word in x[3] for word in words)]
        results.set_description(_("{shown} of {total} bindings. Narrow your search to find more.").format(shown=min(len(matches), 60), total=len(matches)))
        for ref, title, current, _hay in matches[:60]:
            binding = ", ".join(filter(None, current)) or _("Disabled")
            row = action_row(title, ref.key + " · " + binding)
            if ref.key.endswith("-static"):
                row.add_suffix(label(_("Reserved hardware binding"), "badge", False))
            else:
                edit = button(icon="document-edit-symbolic", callback=lambda ref=ref, title=title: shortcut_dialog(w, ref, title), tooltip=_("Edit shortcut"))
                row.add_suffix(edit); row.set_activatable_widget(edit)
            if ref.schema == CUSTOM:
                row.add_suffix(button(icon="emblem-system-symbolic", callback=lambda ref=ref: custom_dialog(w, ref.path), tooltip=_("Edit custom shortcut command")))
                row.add_suffix(button(icon="list-remove-symbolic", callback=lambda ref=ref: remove_custom(w, ref.path), tooltip=_("Remove custom shortcut")))
            results.add(row); rows.append(row)
    search.connect("search-changed", render)
    render()


def record_button(w, entry, append=False):
    def start():
        d, body, header = dialog(w, _("Record a shortcut"), 520, 280)
        body.append(Gtk.Image(icon_name="input-keyboard-symbolic", pixel_size=48))
        body.append(label(_("Press a key combination"), "title-2", xalign=0.5))
        body.append(label(_("Escape cancels. Press Backspace alone to clear. Global compositor shortcuts may be intercepted by GNOME."), "dim-label", xalign=0.5))
        receiver = Gtk.Box(focusable=True, height_request=40)
        body.append(receiver)
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        def pressed(_keys, keyval, keycode, state):
            if keyval == Gdk.KEY_Escape:
                d.close(); return True
            if keyval in (Gdk.KEY_Control_L, Gdk.KEY_Control_R, Gdk.KEY_Shift_L, Gdk.KEY_Shift_R, Gdk.KEY_Alt_L, Gdk.KEY_Alt_R, Gdk.KEY_Super_L, Gdk.KEY_Super_R, Gdk.KEY_ISO_Level3_Shift):
                return True
            mods = state & Gtk.accelerator_get_default_mod_mask()
            if keyval == Gdk.KEY_BackSpace and not mods:
                entry.set_text(""); d.close(); return True
            if keyval == Gdk.KEY_ISO_Left_Tab:
                keyval = Gdk.KEY_Tab; mods |= Gdk.ModifierType.SHIFT_MASK
            keyval = Gdk.keyval_to_lower(keyval)
            accelerator = Gtk.accelerator_name(keyval, mods)
            if not Gtk.accelerator_valid(keyval, mods):
                return True
            existing = entry.get_text().strip()
            entry.set_text(existing + ", " + accelerator if append and existing else accelerator)
            d.close(); return True
        keys.connect("key-pressed", pressed)
        receiver.add_controller(keys)
        d.present(w); receiver.grab_focus()
    return button(label=_("Record…"), callback=start)


def validate_accelerators(items):
    canonical = []
    for item in items:
        if not item:
            continue
        # Mutter also accepts the physical key Above_Tab, which GTK's parser
        # does not know. Validate its syntax through the equivalent named key.
        ok, keyval, mods = Gtk.accelerator_parse(item.replace("Above_Tab", "grave"))
        if not ok or not Gtk.accelerator_valid(keyval, mods):
            raise SettingsError(_("Invalid shortcut: ") + item)
        normalized = canonical_shortcut(item)
        if normalized in canonical:
            raise SettingsError(_("The same shortcut appears more than once."))
        canonical.append(normalized)


def shortcut_dialog(w, ref, title):
    expected = w.registry.state(ref)
    current = w.registry.value(ref).unpack()
    typ = w.registry.value(ref).get_type_string()
    bindings = current if isinstance(current, list) else [current]
    d, body, header = dialog(w, title, 720, 560)
    key = w.registry.schema_key(ref)
    body.append(label(key.get_description() or ref.key, "dim-label"))
    g = group(_("Shortcut combinations"), _("Separate alternate combinations with commas. Empty disables this shortcut."))
    entry = Adw.EntryRow(title=_("Bindings"), text=", ".join(filter(None, bindings)))
    g.add(entry); body.append(g)
    controls = Gtk.Box(spacing=8)
    controls.append(record_button(w, entry, append=typ == "as"))
    body.append(controls)
    error = label("", "error"); body.append(error)
    feedback = label("", "dim-label"); body.append(feedback)
    body.append(info_box(_("Conflicts are compared with all discovered GNOME and extension shortcuts. Toshy can transform physical keys before GNOME sees them; its runtime contexts and generated mappings cannot be fully inferred.")))
    def examine(*_a):
        items = [x.strip() for x in entry.get_text().split(",") if x.strip()]
        matches = conflicts(w.registry, items, ref)
        feedback.set_label(_("Conflicts: ") + "\n".join(f"{r.schema} / {r.key}: {', '.join(v)}" for r, v in matches) if matches else _("No exact GNOME shortcut conflicts found."))
    entry.connect("changed", examine); examine()
    def save(reset=False):
        try:
            if reset:
                default = key.get_default_value().unpack()
                items = default if isinstance(default, list) else [default]
            else:
                items = [x.strip() for x in entry.get_text().split(",") if x.strip()]
            if typ == "s" and len(items) > 1:
                raise SettingsError(_("This shortcut supports a single combination."))
            validate_accelerators(items)
            matches = conflicts(w.registry, items, ref)
            if matches:
                raise SettingsError(_("This combination is already assigned. Resolve the listed conflicts before saving."))
            text = None if reset else GLib.Variant(typ, items if typ == "as" else items[0] if items else "").print_(True)
            w.store.set(ref, text, expected, title)
            d.close(); w.toast(_("Shortcut saved"))
            if w.current_page == "keyboard":
                w.render("keyboard")
        except Exception as exc:
            error.set_label(str(exc))
    header.pack_end(button(label=_("Apply"), callback=save, css="suggested-action"))
    controls.append(button(label=_("Reset to default"), callback=lambda: save(True)))
    d.present(w)


def custom_dialog(w, path=None):
    d, body, header = dialog(w, _("Custom shortcut"), 700, 540)
    refs = {k: Ref(CUSTOM, k, path) for k in ("name", "command", "binding")} if path else {}
    expected = {k: w.registry.state(r) for k, r in refs.items()}
    g = group(_("Launch a command"), _("Commands run as your user when GNOME receives the binding. Desktop Studio does not execute the command while editing."))
    entries = {}
    for key, title in (("name", _("Name")), ("command", _("Command")), ("binding", _("Shortcut"))):
        entry = Adw.EntryRow(title=title, text=w.registry.value(refs[key]).unpack() if path else "")
        entries[key] = entry; g.add(entry)
    body.append(g); body.append(record_button(w, entries["binding"]))
    error = label("", "error"); body.append(error)
    body.append(info_box(_("Command values are excluded from profile exports and change-history values because they may contain credentials.")))
    def save():
        try:
            name, command, binding = (entries[k].get_text().strip() for k in ("name", "command", "binding"))
            validate_accelerators([binding])
            if not name or not command or not binding:
                raise SettingsError(_("Name, command, and shortcut are required."))
            if conflicts(w.registry, [binding], refs.get("binding")):
                raise SettingsError(_("This shortcut conflicts with an existing binding."))
            if path:
                edits = [(refs[k], GLib.Variant("s", entries[k].get_text().strip()).print_(True), expected[k]) for k in entries]
                w.store.apply(edits, _("Edit custom shortcut"), backup=w.profiles.backup)
            else:
                create_custom_shortcut(w.registry, w.store, name, command, binding)
            d.close(); w.search_index = None; w.render("keyboard")
        except Exception as exc:
            error.set_label(str(exc))
    header.pack_end(button(label=_("Save"), callback=save, css="suggested-action")); d.present(w)


def remove_custom(w, path):
    master = Ref(MEDIA, "custom-keybindings")
    current = w.registry.value(master).unpack(); expected = w.registry.state(master)
    w.safe(lambda: w.store.set(master, GLib.Variant("as", [p for p in current if p != path]).print_(True), expected, _("Remove custom shortcut")), lambda _r: (w.registry.refresh_paths(), w.render("keyboard")))


def build_toshy(w, content):
    g = group(_("Toshy · Mac-style keyboard mappings"), _("A remapping service, separate from native GNOME keyboard options."))
    content.append(g)
    if not w.toshy.available:
        g.add(action_row(_("Toshy was not found"), _("No configuration at ~/.config/toshy/toshy_config.py. Native GNOME controls remain available.")))
        return
    status_row = action_row(_("Remapping service"), _("Checking service status…"))
    g.add(status_row)
    background(w.toshy.status, lambda text: status_row.set_subtitle(text), lambda msg: status_row.set_subtitle(msg))
    def refresh_status():
        if not status_row.get_root():
            return False
        background(w.toshy.status, lambda text: status_row.set_subtitle(text), lambda msg: status_row.set_subtitle(msg))
        return True
    GLib.timeout_add_seconds(4, refresh_status)
    for action, title in (("start", _("Start")), ("stop", _("Stop")), ("restart", _("Restart"))):
        def operate(action=action):
            background(lambda: w.toshy.service(action), lambda _r: (w.toast(_("Toshy service action completed")), background(w.toshy.status, lambda text: status_row.set_subtitle(text), w.error)), w.error)
        status_row.add_suffix(button(label=title, callback=operate))
    if shutil_which("toshy-gui"):
        g.add(action_row(_("Toshy preferences"), _("Use Toshy’s supported preferences for keyboard type, Mac-style behavior, and layout correction."), lambda: w.safe(lambda: launch(["toshy-gui"]))))
    g.add(action_row(_("Edit User Apps mappings"), _("Edit only Toshy’s upgrade-preserved User Apps section. Automatic private backup and syntax validation are included."), lambda: toshy_editor(w)))
    g.add(action_row(_("Add an application mapping"), _("Create a context-aware mapping using Toshy’s existing keymap backend."), lambda: mapping_dialog(w)))
    g.add(action_row(_("Check possible shortcut overlaps"), _("Compare literal Toshy combinations with GNOME bindings. Context-dependent mappings require manual review."), lambda: toshy_conflicts(w)))
    g.add(action_row(_("Open configuration backups"), _("Private full-file backups are created before every edit; they are never included in exported profiles."), lambda: w.safe(lambda: (w.toshy.backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True), open_uri(w.toshy.backup_dir.as_uri())))))
    content.append(info_box(_("Your existing Toshy configuration and English/Persian switching stay in place. Saving a User Apps edit may trigger Toshy’s configuration watcher; use Restart if needed. Physical modifier keys and GNOME logical shortcuts can differ under Mac-style remapping.")))


def shutil_which(name):
    import shutil
    return shutil.which(name)


def toshy_editor(w):
    try:
        text, digest = w.toshy.slice()
    except Exception as exc:
        w.error(str(exc)); return
    d, body, header = dialog(w, _("Toshy · User Apps"), 900, 720)
    body.append(info_box(_("This is executable Python configuration for Toshy. Only the User Apps slice is replaced. Existing code outside it is preserved, and a private backup is written first. Syntax checking cannot guarantee that a mapping works at runtime.")))
    sc, editor = text_editor(text, height=400); body.append(sc)
    error = label("", "error"); body.append(error)
    def save():
        try:
            backup, new_digest = w.toshy.save_slice(buffer_text(editor), digest)
            d.close(); w.toast(_("Toshy configuration saved and backed up"))
            show_toshy_saved(w, backup, new_digest)
        except Exception as exc:
            error.set_label(str(exc))
    header.pack_end(button(label=_("Save with backup"), callback=save, css="suggested-action"))
    d.present(w)


def show_toshy_saved(w, backup, digest):
    d, body, header = dialog(w, _("Toshy configuration saved"), 650, 350)
    body.append(label(_("Backup: ") + str(backup), "dim-label"))
    body.append(info_box(_("Toshy may reload its configuration automatically. You can restart its services or restore the previous User Apps section below. Restoration refuses to overwrite a later edit.")))
    body.append(button(label=_("Restart Toshy services"), callback=lambda: background(lambda: w.toshy.service("restart"), lambda _r: w.toast(_("Toshy restarted")), w.error)))
    body.append(button(label=_("Restore previous User Apps"), callback=lambda: w.safe(lambda: w.toshy.restore(backup, digest), lambda _r: (w.toast(_("Previous User Apps restored")), d.close()))))
    d.present(w)


def mapping_dialog(w):
    try:
        text, digest = w.toshy.slice()
        whole = w.toshy.read()[0]
        if "def matchProps(" not in whole or "cnfg.screen_has_focus" not in whole:
            raise SettingsError(_("This Toshy configuration does not expose the expected mapping context API. Use the User Apps editor or Toshy preferences."))
    except Exception as exc:
        w.error(str(exc)); return
    d, body, header = dialog(w, _("Application-specific mapping"), 700, 570)
    g = group(_("Toshy mapping"), _("Use Toshy combination notation, for example RC-c → C-Shift-c. The application pattern matches its window class or Wayland app ID as reported to Toshy."))
    entries = []
    for title, sample in ((_("Application class pattern"), "^org\\.gnome\\.TextEditor$"), (_("Source combination"), "RC-j"), (_("Target combination"), "C-Down")):
        e = Adw.EntryRow(title=title, text=sample); g.add(e); entries.append(e)
    body.append(g)
    body.append(info_box(_("The mapping is appended inside your User Apps slice. Existing Mac-style mappings are retained. Use Toshy’s detector tools to find the application class and confirm the resulting context.")))
    error = label("", "error"); body.append(error)
    def save():
        try:
            app, source, target = [e.get_text().strip() for e in entries]
            mapping = w.toshy.mapping(source, target, app)
            backup, new_digest = w.toshy.save_slice(text + mapping, digest)
            d.close(); show_toshy_saved(w, backup, new_digest)
        except Exception as exc:
            error.set_label(str(exc))
    header.pack_end(button(label=_("Add with backup"), callback=save, css="suggested-action")); d.present(w)


def toshy_conflicts(w):
    d, body, header = dialog(w, _("Possible remapping overlaps"), 850, 650)
    body.append(info_box(_("This is a static, conservative check. A matching combination may be intentional or restricted to an application. Conditional, generated, physical-key, and service-specific behavior cannot be completely analyzed without running Toshy.")))
    try:
        mappings = w.toshy.literal_mappings()
        results = []
        seen = set()
        for name, combo, line in mappings:
            accel = toshy_to_gnome(combo)
            if not accel or accel in seen:
                continue
            seen.add(accel)
            for ref, matches in conflicts(w.registry, [accel]):
                results.append((name, combo, line, ref))
        g = group(_("{count} possible overlaps").format(count=len(results)))
        for name, combo, line, ref in results[:150]:
            g.add(action_row(combo + " · " + ref.key, f"{name} · Toshy line {line}\n{ref.schema}"))
        body.append(g)
        if len(results) > 150:
            body.append(label(_("Showing the first 150 possible overlaps."), "dim-label"))
    except Exception as exc:
        body.append(label(str(exc), "error"))
    d.present(w)
