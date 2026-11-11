import shutil
from .core.settings import Ref


def report(registry, env):
    dock = {}
    for key in ("dock-position", "dock-fixed", "autohide", "intellihide"):
        ref = Ref("org.gnome.shell.extensions.dash-to-dock", key)
        if registry.exists(ref):
            dock[key] = registry.value(ref).unpack()
    return {
        "application": "Desktop Studio 1.0.0", "os": env.os,
        "shell": env.shell_version, "session": env.session,
        "schemas": len(registry.schemas),
        "extension_schemas": {k: sorted(v) for k, v in registry.extension_schema_ids.items()},
        "relocatable_schemas_without_known_instances": sorted(k for k, v in registry.schemas.items() if v.get_path() is None and not registry.known_paths.get(k)),
        "schema_discovery_errors": registry.discovery_errors,
        "dock": dock,
        "input_capabilities": {x: env.has_input(x) for x in ("mouse", "touchpad", "keyboard")},
        "tools": {x: bool(shutil.which(x)) for x in ("gnome-control-center", "gnome-extensions", "wpctl", "toshy-gui", "toshy-services-restart")},
    }
