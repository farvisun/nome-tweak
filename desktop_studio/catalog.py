"""Curated labels and presentation hints; schemas remain the source of truth."""
from dataclasses import dataclass

from .core.settings import Ref
from .i18n import _


@dataclass(frozen=True)
class Category:
    id: str
    title: str
    icon: str
    description: str
    section: str = ""


SECTIONS = {
    "personalize": _("Personalization"),
    "devices": _("Input & Devices"),
    "system": _("System"),
    "manage": _("Management"),
}

CATEGORIES = [
    Category("overview", _("Overview"), "user-home-symbolic", _("A desktop that feels like yours.")),
    Category("appearance", _("Appearance"), "applications-graphics-symbolic", _("Color, character, and the finer details."), "personalize"),
    Category("dock", _("Dock"), "view-app-grid-symbolic", _("Your applications, exactly where you want them."), "personalize"),
    Category("extensions", _("Top Bar & Extensions"), "application-x-addon-symbolic", _("The small details at the top of your desktop."), "personalize"),
    Category("windows", _("Windows & Workspaces"), "focus-windows-symbolic", _("Make room for the way you work."), "personalize"),
    Category("keyboard", _("Keyboard"), "input-keyboard-symbolic", _("Layouts, shortcuts, and familiar muscle memory."), "devices"),
    Category("input", _("Mouse & Touchpad"), "input-mouse-symbolic", _("Fine-tune every movement."), "devices"),
    Category("displays", _("Displays"), "video-display-symbolic", _("A comfortable view, on every screen."), "devices"),
    Category("sound", _("Sound & Notifications"), "audio-volume-high-symbolic", _("Choose what deserves your attention."), "devices"),
    Category("power", _("Power & Privacy"), "battery-symbolic", _("Balance comfort, energy, and privacy."), "system"),
    Category("accessibility", _("Accessibility"), "preferences-desktop-accessibility-symbolic", _("A desktop that works for everyone."), "system"),
    Category("system", _("System & Apps"), "preferences-system-symbolic", _("Connections, language, and everyday essentials."), "system"),
    Category("advanced", _("Advanced Settings"), "preferences-other-symbolic", _("Explore the settings your system exposes."), "system"),
    Category("profiles", _("Profiles & Backups"), "document-save-symbolic", _("Save a setup. Review every change. Return anytime."), "manage"),
    Category("history", _("Recent Changes"), "document-open-recent-symbolic", _("A clear record, with a way back."), "manage"),
]
CATEGORY_MAP = {c.id: c for c in CATEGORIES}


@dataclass
class Spec:
    category: str
    group: str
    ref: Ref
    title: str
    description: str = ""
    kind: str = "auto"
    bounds: tuple | None = None
    options: tuple | None = None
    badge: str = ""
    keywords: str = ""


SPECS = []


def add(category, group, schema, entries, badge=""):
    for entry in entries:
        key, title, *rest = entry
        opts = rest[0] if rest and isinstance(rest[0], dict) else {}
        SPECS.append(Spec(category, _(group), Ref(schema, key), _(title), _(opts.get("description", "")), opts.get("kind", "auto"), opts.get("bounds"), opts.get("options"), _(opts.get("badge", badge)), opts.get("keywords", "")))


I = "org.gnome.desktop.interface"
D = "org.gnome.shell.extensions.dash-to-dock"
WM = "org.gnome.desktop.wm.preferences"
M = "org.gnome.mutter"
add("appearance", "Personal style", I, [
    ("color-scheme", "Appearance", {"description": "Choose the desktop light or dark preference. Applications decide how to honor it.", "keywords": "light dark system"}),
    ("accent-color", "Accent color", {"kind": "accent"}),
    ("icon-theme", "Icon theme", {"kind": "icons", "description": "Installed themes, including themes in your home directory."}),
    ("gtk-theme", "GTK theme", {"kind": "themes", "description": "Primarily affects GTK3 applications. GTK4 support depends on the theme; libadwaita uses its own stylesheet. Some applications need to restart.", "badge": "App restart"}),
    ("enable-animations", "Interface animations"),
])
add("appearance", "Background", "org.gnome.desktop.background", [
    ("picture-uri", "Light background", {"kind": "file", "keywords": "wallpaper picture photo"}),
    ("picture-uri-dark", "Dark background", {"kind": "file"}),
    ("picture-options", "Picture placement"),
    ("primary-color", "Background color", {"kind": "color"}),
    ("color-shading-type", "Color shading"),
])
add("appearance", "Cursor", I, [
    ("cursor-theme", "Cursor theme", {"kind": "cursors", "description": "Choose an installed theme, or browse the Ryoku collection for Bibata Modern and Original cursors.", "keywords": "Ryoku Bibata Modern Original Ice Classic Amber cursor pointer"}),
    ("cursor-size", "Cursor size", {"bounds": (16, 128, 1), "description": "Size in pixels; actual sizes depend on the cursor theme."}),
    ("locate-pointer", "Locate pointer", {"description": "Highlight the pointer when its configured modifier is pressed."}),
])
add("appearance", "Typography", I, [
    ("font-name", "Interface font", {"kind": "font"}),
    ("document-font-name", "Document font", {"kind": "font"}),
    ("monospace-font-name", "Monospace font", {"kind": "font"}),
    ("text-scaling-factor", "Text scale", {"bounds": (0.5, 3.0, 0.05)}),
    ("font-rendering", "Font rendering mode", {"description": "Manual mode allows the rendering preferences below to take effect where supported."}),
    ("font-antialiasing", "Font antialiasing"),
    ("font-hinting", "Font hinting"),
    ("font-rgba-order", "Subpixel order"),
])
add("appearance", "Shell theme", "org.gnome.shell.extensions.user-theme", [
    ("name", "GNOME Shell theme", {"description": "Requires the User Themes extension to be installed, enabled, and compatible.", "kind": "shell-themes"}),
], badge="Extension")

add("dock", "Placement & size", D, [
    ("dock-position", "Position"),
    ("extend-height", "Fill available length", {"description": "Turn off for a floating, compact dock."}),
    ("height-fraction", "Maximum length", {"bounds": (0.1, 1, 0.05), "description": "Fraction of the screen edge."}),
    ("always-center-icons", "Center application icons"),
    ("dash-max-icon-size", "Icon size", {"bounds": (16, 128, 1)}),
    ("icon-size-fixed", "Keep icon size fixed"),
    ("multi-monitor", "Show on all monitors"),
    ("preferred-monitor-by-connector", "Preferred monitor", {"kind": "monitor", "description": "Uses the physical connector name, so it stays consistent when monitor order changes."}),
    ("preferred-monitor", "Preferred monitor index", {"bounds": (-2, 16, 1), "description": "Fallback index used by older dock versions: −2 follows the primary display."}),
], badge="Extension")
add("dock", "Visibility", D, [
    ("autohide-in-fullscreen", "Hide for fullscreen windows"),
    ("require-pressure-to-show", "Require pointer pressure"),
    ("show-delay", "Show delay (seconds)", {"bounds": (0, 5, 0.05)}),
    ("hide-delay", "Hide delay (seconds)", {"bounds": (0, 5, 0.05)}),
    ("intellihide-mode", "Overlap detection"),
], badge="Extension")
add("dock", "Style & indicators", D, [
    ("transparency-mode", "Transparency mode"),
    ("background-opacity", "Background opacity", {"bounds": (0, 1, 0.05)}),
    ("custom-background-color", "Use a custom background"),
    ("background-color", "Background color", {"kind": "color"}),
    ("apply-custom-theme", "Dock theme styling"),
    ("custom-theme-shrink", "Compact spacing"),
    ("running-indicator-style", "Running indicators"),
    ("running-indicator-dominant-color", "Match indicator to application color"),
    ("show-icons-emblems", "Application badges"),
    ("show-icons-notifications-counter", "Notification counters"),
], badge="Extension")
add("dock", "Application behavior", D, [
    ("click-action", "Click action"),
    ("middle-click-action", "Middle-click action"),
    ("shift-click-action", "Shift-click action"),
    ("scroll-action", "Scroll action"),
    ("show-windows-preview", "Window previews"),
    ("activate-single-window", "Activate a single window directly"),
    ("show-favorites", "Show pinned applications"),
    ("show-running", "Show running applications"),
    ("isolate-workspaces", "Only show this workspace"),
    ("isolate-monitors", "Only show this monitor"),
    ("show-trash", "Show Trash"),
    ("show-mounts", "Show mounted drives"),
    ("show-mounts-network", "Show network drives"),
    ("show-show-apps-button", "Show application launcher"),
    ("show-apps-at-top", "Put launcher at the beginning"),
], badge="Extension")
add("extensions", "Clock & status", I, [
    ("clock-format", "Clock format"),
    ("clock-show-date", "Show date"),
    ("clock-show-weekday", "Show weekday"),
    ("clock-show-seconds", "Show seconds"),
    ("show-battery-percentage", "Show battery percentage"),
])
add("extensions", "Calendar", "org.gnome.desktop.calendar", [("show-weekdate", "Show week numbers")])

add("keyboard", "Typing", "org.gnome.desktop.peripherals.keyboard", [
    ("repeat", "Repeat held keys"),
    ("delay", "Repeat delay (milliseconds)", {"bounds": (100, 2000, 25)}),
    ("repeat-interval", "Repeat interval (milliseconds)", {"bounds": (10, 500, 5), "description": "A smaller interval repeats more quickly."}),
    ("remember-numlock-state", "Remember Num Lock"),
])
add("keyboard", "Input sources", "org.gnome.desktop.input-sources", [
    ("per-window", "Separate layout for each window"),
])
add("keyboard", "Cursor & text input", I, [
    ("cursor-blink", "Blink text cursor"),
    ("cursor-blink-time", "Cursor blink interval (milliseconds)"),
    ("gtk-enable-primary-paste", "Middle-click paste"),
])

add("windows", "Title bar", WM, [
    ("button-layout", "Title-bar buttons", {"options": (("close,minimize,maximize:", "Left · close, minimize, maximize"), (":minimize,maximize,close", "Right · minimize, maximize, close"), (":close", "Right · close only")), "description": "Client-side decorations may follow an application's own preferences."}),
    ("action-double-click-titlebar", "Double-click action"),
    ("action-middle-click-titlebar", "Middle-click action"),
    ("action-right-click-titlebar", "Right-click action"),
    ("titlebar-uses-system-font", "Use interface font for titles"),
    ("titlebar-font", "Title font", {"kind": "font"}),
])
add("windows", "Focus & placement", WM, [
    ("focus-mode", "Window focus"),
    ("focus-new-windows", "Focus for new windows"),
    ("raise-on-click", "Raise on click"),
    ("auto-raise", "Raise automatically when focused"),
    ("auto-raise-delay", "Automatic raise delay (milliseconds)"),
    ("resize-with-right-button", "Resize with modifier + right button"),
    ("mouse-button-modifier", "Window move modifier", {"options": (("<Super>", "Super"), ("<Alt>", "Alt"))}),
])
add("windows", "Focus & placement", M, [
    ("center-new-windows", "Center new windows"),
    ("attach-modal-dialogs", "Attach dialogs to parent windows"),
    ("auto-maximize", "Maximize large new windows"),
    ("edge-tiling", "Tile at screen edges"),
])
add("windows", "Workspaces", M, [
    ("dynamic-workspaces", "Create workspaces dynamically", {"description": "Turn off to use the fixed workspace count below."}),
    ("workspaces-only-on-primary", "Workspaces only on primary display"),
])
add("windows", "Workspaces", WM, [
    ("num-workspaces", "Fixed workspace count", {"description": "Used when dynamic workspaces are disabled."}),
    ("workspace-names", "Workspace names", {"kind": "variant"}),
])
add("windows", "Application & window switching", "org.gnome.shell.app-switcher", [("current-workspace-only", "Application switcher: current workspace only")])
add("windows", "Application & window switching", "org.gnome.shell.window-switcher", [("current-workspace-only", "Window switcher: current workspace only"), ("app-icon-mode", "Window switcher labels")])
add("windows", "Overview", I, [("enable-hot-corners", "Activities hot corner")])

add("input", "Mouse", "org.gnome.desktop.peripherals.mouse", [
    ("speed", "Pointer speed", {"bounds": (-1, 1, 0.05)}),
    ("accel-profile", "Acceleration profile"),
    ("natural-scroll", "Natural scrolling"),
    ("left-handed", "Left-handed primary button"),
    ("middle-click-emulation", "Emulate middle click"),
    ("double-click", "Double-click interval (milliseconds)"),
])
add("input", "Touchpad", "org.gnome.desktop.peripherals.touchpad", [
    ("send-events", "Touchpad availability"),
    ("speed", "Touchpad pointer speed", {"bounds": (-1, 1, 0.05)}),
    ("accel-profile", "Touchpad acceleration"),
    ("natural-scroll", "Natural touchpad scrolling"),
    ("tap-to-click", "Tap to click"),
    ("tap-and-drag", "Tap and drag"),
    ("tap-and-drag-lock", "Drag lock"),
    ("two-finger-scrolling-enabled", "Two-finger scrolling"),
    ("edge-scrolling-enabled", "Edge scrolling"),
    ("disable-while-typing", "Disable while typing"),
    ("disable-while-typing-timeout", "Typing timeout (milliseconds)"),
    ("click-method", "Click method"),
    ("left-handed", "Touchpad primary button"),
])
add("input", "Trackball", "org.gnome.desktop.peripherals.trackball", [("scroll-wheel-emulation-button", "Scroll emulation button"), ("accel-profile", "Trackball acceleration")])

add("displays", "Night Light", "org.gnome.settings-daemon.plugins.color", [
    ("night-light-enabled", "Night Light"),
    ("night-light-temperature", "Color temperature (kelvin)", {"bounds": (1000, 10000, 100)}),
    ("night-light-schedule-automatic", "Sunset to sunrise"),
    ("night-light-schedule-from", "Custom start hour", {"bounds": (0, 24, 0.25), "description": "Used when the automatic schedule is off. 20.5 means 20:30."}),
    ("night-light-schedule-to", "Custom end hour", {"bounds": (0, 24, 0.25)}),
])
add("sound", "Alert sounds", "org.gnome.desktop.sound", [
    ("event-sounds", "Play alert sounds"),
    ("input-feedback-sounds", "Input feedback sounds"),
    ("theme-name", "Sound theme"),
    ("allow-volume-above-100-percent", "Allow amplified volume"),
])
add("sound", "Notifications", "org.gnome.desktop.notifications", [
    ("show-banners", "Notification banners", {"description": "Turn off for Do Not Disturb."}),
    ("show-in-lock-screen", "Notifications on lock screen"),
])
add("power", "Idle & screen lock", "org.gnome.desktop.session", [("idle-delay", "Blank screen after (seconds)", {"bounds": (0, 7200, 60), "description": "Zero means never."})])
add("power", "Idle & screen lock", "org.gnome.desktop.screensaver", [
    ("lock-enabled", "Lock automatically"),
    ("lock-delay", "Lock delay after blanking (seconds)", {"bounds": (0, 7200, 30)}),
    ("ubuntu-lock-on-suspend", "Lock on suspend"),
])
add("power", "Power management", "org.gnome.settings-daemon.plugins.power", [
    ("idle-dim", "Dim when idle"),
    ("power-button-action", "Power button action"),
    ("sleep-inactive-ac-type", "When inactive on AC power"),
    ("sleep-inactive-ac-timeout", "AC inactivity timeout (seconds)", {"bounds": (0, 14400, 60)}),
    ("sleep-inactive-battery-type", "When inactive on battery"),
    ("sleep-inactive-battery-timeout", "Battery inactivity timeout (seconds)", {"bounds": (0, 14400, 60)}),
    ("power-saver-profile-on-low-battery", "Power saver when battery is low"),
])
add("power", "Privacy", "org.gnome.desktop.privacy", [
    ("remember-recent-files", "Remember recent files"),
    ("recent-files-max-age", "Recent file retention (days)", {"bounds": (-1, 3650, 1), "description": "−1 keeps history indefinitely; 0 disables history."}),
    ("remove-old-trash-files", "Automatically empty old Trash"),
    ("remove-old-temp-files", "Automatically remove temporary files"),
    ("old-files-age", "Cleanup age (days)"),
    ("report-technical-problems", "Report technical problems"),
    ("send-software-usage-stats", "Send software usage statistics"),
])
add("power", "Location", "org.gnome.system.location", [("enabled", "Location services")])

add("accessibility", "Seeing", "org.gnome.desktop.a11y.interface", [("high-contrast", "High contrast"), ("show-status-shapes", "Use shapes in status indicators")])
add("accessibility", "Assistive tools", "org.gnome.desktop.a11y.applications", [("screen-reader-enabled", "Screen reader"), ("screen-keyboard-enabled", "On-screen keyboard"), ("screen-magnifier-enabled", "Screen magnifier")])
add("accessibility", "Typing assistance", "org.gnome.desktop.a11y.keyboard", [
    ("stickykeys-enable", "Sticky keys"), ("stickykeys-two-key-off", "Disable Sticky Keys when two keys are pressed"),
    ("slowkeys-enable", "Slow keys"), ("slowkeys-delay", "Slow key delay (milliseconds)"),
    ("bouncekeys-enable", "Bounce keys"), ("bouncekeys-delay", "Bounce key interval (milliseconds)"),
    ("togglekeys-enable", "Sound for lock keys"), ("mousekeys-enable", "Control pointer with keyboard"),
])
add("accessibility", "Pointer assistance", "org.gnome.desktop.a11y.mouse", [("secondary-click-enabled", "Simulated secondary click"), ("dwell-click-enabled", "Hover click")])
add("accessibility", "Visual alerts", WM, [("visual-bell", "Visual bell"), ("visual-bell-type", "Visual bell style"), ("audible-bell", "Audible bell")])
add("system", "Language & region", "org.gnome.system.locale", [("region", "Formats locale", {"description": "Affects date, number, and currency formats. Log out after changing.", "badge": "Logout"})])
add("system", "Date & time", "org.gnome.desktop.datetime", [("automatic-timezone", "Automatic time zone", {"description": "Requires location services."})])
add("system", "Removable media", "org.gnome.desktop.media-handling", [("automount", "Mount removable media automatically"), ("automount-open", "Open mounted media"), ("autorun-never", "Never autorun media")])

SPEC_MAP = {s.ref: s for s in SPECS}


def category_for(ref):
    if ref in SPEC_MAP:
        return SPEC_MAP[ref].category
    name = ref.schema
    if any(s in name for s in ("keybindings", "media-keys", "input-sources", "keyboard")):
        return "keyboard"
    if "dash-to-dock" in name or (name == "org.gnome.shell" and ref.key == "favorite-apps"):
        return "dock"
    if "extensions" in name:
        return "extensions"
    if any(x in name for x in ("mutter", "wm.", "switcher")):
        return "windows"
    if any(x in name for x in ("a11y",)):
        return "accessibility"
    if any(x in name for x in ("peripherals.mouse", "touchpad", "trackball", "pointingstick")):
        return "input"
    if "plugins.color" in name:
        return "displays"
    if any(x in name for x in ("interface", "background", "xsettings")):
        return "appearance"
    if any(x in name for x in ("sound", "notifications")):
        return "sound"
    if any(x in name for x in ("privacy", "screensaver", "session", "power", "location")):
        return "power"
    return "system"


def profile_refs(registry):
    return [r for r in registry.refs() if r.schema.startswith(("org.gnome.desktop.", "org.gnome.shell", "org.gnome.mutter", "org.gnome.settings-daemon.plugins.", "org.gnome.system.locale", "org.gnome.system.location"))]
