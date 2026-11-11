from gi.repository import Adw, Gtk

from ..catalog import Spec, category_for
from ..i18n import _
from .widgets import SettingRow, action_row, button, dialog, group, info_box


def build(w, content):
    content.append(info_box(_("Schemas are discovered from GNOME, applications, and installed extensions. Relocatable schemas are opened only for registered instance paths. Advanced changes can affect desktop behavior; inspect the description, range, and default before editing.")))
    w.registry.refresh_paths()
    names = sorted(w.registry.schemas)
    selector = Gtk.DropDown(model=Gtk.StringList.new([_("All schemas")] + names), enable_search=True)
    selector.update_property([Gtk.AccessibleProperty.LABEL], [_("Filter by GSettings schema")])
    content.append(selector)
    search = Gtk.SearchEntry(placeholder_text=_("Filter keys, descriptions, types, and schema names…"))
    search.update_property([Gtk.AccessibleProperty.LABEL], [_("Search advanced settings")])
    content.append(search)
    status = group(_("Installed settings"))
    content.append(status)
    more = button(label=_("Show more settings"))
    content.append(more)
    rows = []
    state = {"limit": 60}
    all_refs = list(w.registry.refs())
    metadata = []
    for ref in all_refs:
        key = w.registry.schema_key(ref)
        spec = Spec(category_for(ref), _("Advanced"), ref, key.get_summary() or ref.key, key.get_description() or "")
        hay = " ".join((ref.schema, ref.key, ref.path, key.get_summary() or "", key.get_description() or "", key.get_value_type().dup_string())).casefold()
        metadata.append((spec, hay))
    def render(reset=True):
        if reset:
            state["limit"] = 60
        for row in rows:
            status.remove(row)
        rows.clear()
        selected = selector.get_selected()
        sid = names[selected - 1] if selected else None
        words = search.get_text().casefold().split()
        matches = [spec for spec, hay in metadata if (not sid or spec.ref.schema == sid) and all(word in hay for word in words)]
        status.set_description(_("{shown} of {total} settings · {schemas} installed schemas").format(shown=min(state["limit"], len(matches)), total=len(matches), schemas=len(names)))
        if sid and not w.registry.schemas[sid].get_path() and not w.registry.known_paths.get(sid):
            row = action_row(_("No known instance paths"), _("This is a relocatable schema. No actual instance is registered by a supported GNOME source. Desktop Studio will not invent a path."))
            status.add(row); rows.append(row)
        for spec in matches[:state["limit"]]:
            row = SettingRow(w, spec, advanced=True)
            row.set_title(spec.ref.key)
            status.add(row); rows.append(row)
        more.set_visible(len(matches) > state["limit"])
    selector.connect("notify::selected", lambda *_a: render())
    search.connect("search-changed", lambda *_a: render())
    more.connect("clicked", lambda *_a: (state.update(limit=state["limit"] + 60), render(False)))
    render()


def schema_dialog(w, schema):
    d, content, header = dialog(w, schema, 850, 720)
    content.append(info_box(_("Source: ") + w.registry.schema_origins.get(schema, _("System"))))
    refs = list(w.registry.refs(schema))
    if not refs:
        content.append(info_box(_("This relocatable schema has no known registered instance paths. No editor is opened at a guessed path.")))
    groups = {}
    for ref in refs:
        path = ref.path or w.registry.schemas[schema].get_path()
        if path not in groups:
            groups[path] = group(path)
            content.append(groups[path])
        key = w.registry.schema_key(ref)
        spec = Spec(category_for(ref), _("Extension settings"), ref, key.get_summary() or ref.key, key.get_description() or "")
        groups[path].add(SettingRow(w, spec, advanced=True))
    d.present(w)
    return d
