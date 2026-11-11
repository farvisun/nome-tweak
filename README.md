# Desktop Studio

A native Python 3, GTK4, and libadwaita application for Ubuntu and GNOME.
It discovers the installed session and schemas instead of assuming that a setting
or extension exists. Opening the app never applies a preset or resets preferences.

## Launch

From this directory:

```sh
./desktop-studio
# or
/usr/bin/python3 -m desktop_studio
```

Use the system Python because Ubuntu installs PyGObject for `/usr/bin/python3`.
No virtual environment, pip packages, web server, or elevated application process
is needed. Tested on Ubuntu 26.04.1, GNOME 50.1, GTK 4.22, libadwaita 1.9, Wayland.

Dependencies on supported Ubuntu systems:

```sh
sudo apt install python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gdkpixbuf-2.0 librsvg2-common
```

GTK 4.12+ and libadwaita 1.5+ are required. GNOME Settings provides supported
fallback panels. WirePlumber's `wpctl` enables output volume and mute controls.
Ubuntu Dock/Dash to Dock and Toshy are optional, discovered capabilities.

## Install for your user

```sh
/usr/bin/python3 scripts/install.py
~/.local/bin/desktop-studio
```

This installs an Applications-menu launcher and an SVG application icon. It
does not require administrator access. Application files go in
`~/.local/lib/desktop-studio`. Use `--prefix /some/path` for another prefix.
Re-running the installer updates the application without modifying profiles.

Uninstall:

```sh
/usr/bin/python3 scripts/install.py --uninstall
```

Uninstall leaves GNOME preferences, profiles, initial snapshots, Toshy backups,
and logs intact. It does not undo changes you intentionally made in the app.

## Ryoku cursor collection

Open **Appearance → Cursor → Ryoku cursors…** to browse the Bibata collection
shipped by Ryoku OS. It includes Modern (rounded) and Original (sharp) styles in
Ice, Classic, and Amber, plus mirrored Right variants: 12 themes in total.
**Bibata-Modern-Ice** is Ryoku’s configured default. The gallery previews the
actual pointer, text, and link cursor files. Hovering a preview affects only that
preview widget; choose **Use this cursor** to change your desktop cursor.

The gallery can install the collection for your user. Alternatively:

```sh
/usr/bin/python3 scripts/install_cursors.py
```

Installation downloads the upstream Bibata 2.0.7 release (about 22 MB, 322 MiB
installed) and verifies the SHA-256 pinned by
[Ryoku’s cursor package](https://github.com/Ryoku-dev/ryoku/blob/main/release/packages/ryoku-cursors/PKGBUILD).
It only adds data under `~/.local/share/icons/`, preserves existing theme folders,
includes the upstream GPL license and source/version metadata, and never selects
a theme or changes its size. No upstream installer scripts are executed. The
regular Cursor theme chooser also discovers all these themes.

GNOME uses their standard Xcursor assets on Wayland. Ryoku’s Hyprland-specific
stretch/rotate/trail effects and its optional wallpaper-driven Material recoloring
are separate integrations and are not enabled by this collection. Application
uninstall preserves the cursor themes you installed, just as it preserves profiles.

## Software updates

Open **Main menu → Software Updates** for **Check now**, release notes, downloads,
and the optional automatic check. When enabled, checks run at most once per day
while the application is open. They inspect stable published **GitHub Releases**;
drafts, prereleases, and bare Git tags are excluded. No background service is
installed. Updates are never downloaded or installed automatically.

The official release source is stored in `data/update-source.json`. The dialog
also accepts a GitHub `owner/repository` or repository URL, so builds from forks
can check their own releases. Per-user overrides and the daily-check preference
are stored in `~/.config/desktop-studio/updates.json`; check results and times are
stored in `~/.local/state/desktop-studio/updates.json`. These files never contain
GitHub tokens or exported desktop settings. Public releases need no sign-in.
For a private repository, the checker can reuse `gh auth login` through GitHub
CLI’s supported API command, without extracting or copying credentials.

For a terminal check without opening GTK:

```sh
./desktop-studio --check-updates
# Check a specific repository without saving an override:
./desktop-studio --check-updates --repository OWNER/REPOSITORY
```

The checker compares semantic versions, handles network/rate-limit/authentication
errors visibly, and never suggests a downgrade. Download links must match the
configured GitHub repository, release tag, and exact versioned package name.
After installing an update, restart Desktop Studio. Your desktop preferences,
profiles, backups, cursor themes, and remapping configuration stay in place.

## Local Debian package

```sh
make package
sudo apt install ./dist/desktop-studio_1.0.0_all.deb
desktop-studio
# uninstall the packaged application:
sudo apt remove desktop-studio
```

Building requires `dpkg-deb` (normally installed on Ubuntu). Package creation
does not install anything or change desktop preferences. Choose either the user
installation or the Debian package to avoid duplicate menu launchers.

## GitHub repository and release workflow

The project uses `main` and separate Conventional Commits for the application,
update checker, and release automation. Generated artifacts, Python caches,
`.env` files, and logs are ignored. GitHub Releases are the updater's source of
truth; pushing source or a tag alone does not count as a published update.

One-time setup for a new repository (GitHub CLI must be signed in):

```sh
gh auth login --hostname github.com --git-protocol https --web --scopes workflow
gh repo create OWNER/desktop-studio --public --source=. --remote=origin
/usr/bin/python3 scripts/configure_github.py OWNER/desktop-studio
git add data/update-source.json
git commit -m "chore: configure GitHub release source"
git push -u origin main
```

Use your actual GitHub account/organization in place of `OWNER`. Configuration
does not create a token or embed credentials. Once the source is configured,
`make release-package` builds these artifacts from the single version in
`desktop_studio/__init__.py`:

- `desktop-studio_VERSION_all.deb` for Debian package installations.
- `desktop-studio-VERSION-linux.tar.gz` containing the per-user installer and
  selected source files. Extract it and run `/usr/bin/python3 scripts/install.py`.
- `SHA256SUMS`, which can be checked with `sha256sum --check SHA256SUMS`.

The package builders copy Git-tracked files from checkouts, excluding ignored or
untracked local credentials and artifacts. Release builds bind both packages to
the publishing repository without modifying source configuration or desktop
settings. This also makes the workflow work correctly in forks.

To publish the initial release:

```sh
git tag v1.0.0
git push origin v1.0.0
```

For later releases, bump `__version__` to the next stable semantic version, commit
the change, push `main`, then create and push the matching `vVERSION` tag.
`.github/workflows/ci.yml` tests and packages pushes/pull requests.
`.github/workflows/release.yml` tests the tagged source, requires a clean checkout
and an exact version/tag match, builds packages and checksums, uploads them to a
draft GitHub Release, then publishes it as the latest stable release. Published
assets are never silently replaced. A failed draft upload can be retried safely.
The workflow can also be dispatched manually for an existing matching tag.

After a new release is published, older app versions can see it through
**Software Updates**. Public release checks work without GitHub authentication.

## What is implemented

- Global search through installed schema keys, descriptions, curated labels,
  and keywords; responsive sidebar; keyboard navigation; Ctrl+F/Ctrl+K search;
  Ctrl+Q quit; light, dark, and system appearance for the app.
- Appearance: desktop color preference/accent, installed icons/cursors/GTK themes,
  Shell themes when User Themes exists, background files, pointer size and live
  pointer target, font pickers, text scaling, rendering, animations, and a desktop
  preview. Arbitrary GTK themes do not restyle libadwaita applications.
- Dock: explicit grouped visibility Apply; position, centering, length, size,
  connector selection, transparency/color, indicators/badges, favorites ordering,
  actions, previews, launcher/Trash/drives, and workspace/monitor isolation.
- Keyboard: XKB layouts and ordering (including Persian variants), native
  modifier/Compose/layout-switch options, key repeat, a searchable shortcut
  browser, recording, alternatives, reset, normalized exact conflict detection,
  custom command shortcuts, and conservative static Toshy overlap analysis.
- Toshy: supported preferences launcher and service commands, syntax-checked User
  Apps slice editing, constrained application-mapping generation, automatic
  full-file private backups, stale-file checks, and immediate restoration of the
  previous slice. Existing code outside that slice is retained. Edits may activate
  Toshy's own config watcher; it is never imported or executed by Desktop Studio.
- Windows/workspaces: title buttons and fonts, focus/raise behavior, window
  actions, edge tiling, positioning, dynamic/fixed workspaces, monitor behavior,
  switchers, and the installed Tiling Assistant's exposed settings.
- Mouse/touchpad: udev capability detection, acceleration, speed, button
  preference, natural scroll, tapping, dragging, scroll methods, and typing
  suppression. Stored preferences can also apply to devices connected later.
- Extensions: actual runtime state, enable/disable, compatibility/errors,
  preferences, and installed extension schema browsing. No extension source edits.
- Displays: live Mutter state, monitor arrangement preview, coordinates, primary
  display, enable/disable, combined resolution/refresh options, supported scale
  choices, transforms, Night Light, stale-serial validation, and compositor-owned
  timed Keep Changes/Revert confirmation. Display drafts use explicit Apply.
- Sound/notifications, power/idle/locking/privacy, accessibility, default apps,
  existing startup entries, locale formats, clock, and automatic time zone.
  Networking and Wi-Fi use NetworkManager; Bluetooth uses BlueZ. Service policy
  controls authorization. The main process always runs as the regular user.
- Advanced browser: dynamic system/application/extension schema discovery,
  registered relocatable instances, descriptions, type/range/current/default,
  policy lock state, typed editors, reset, and copy.
- Named profiles, category-selective import/export, initial snapshot, optional
  Mac-style and installed GNOME-default presets, exact pre-apply comparison,
  automatic pre-bulk snapshots, recent GSettings changes, and checked undo.

## Platform boundaries

The app labels or links the exact GNOME Settings panel for integrations whose
supported UI offers capabilities beyond this application: audio device/profile
selection, per-app sound and notification permissions, network/VPN configuration,
Bluetooth pairing, battery/hardware power profiles, system time/NTP, display
language installation, additional defaults/MIME types, mirroring, HDR, and color
profiles. Changing system time or installing language support may require the
system's operation-specific authorization; Desktop Studio does not use `sudo`.

GNOME Wayland does not expose arbitrary multi-finger gesture remapping through
GSettings. Extra effects and ungrouped taskbars need compatible extensions. Shell
themes require User Themes; GTK3 themes do not universally theme GTK4, and
libadwaita follows its own stylesheet and supported appearance preferences.

Toshy conflict analysis is intentionally conservative. Dynamic Python mappings,
per-app context, keymapper runtime state, and physical versus logical modifiers
cannot be completely inferred statically. Native shortcut recording sees the
events after remapping, and GNOME may intercept global shortcuts before GTK.

Relocatable schemas are opened only at registered custom-shortcut, notification,
or application-folder instances. Other relocatable schemas stay visible with an
explanation until a supported source supplies actual paths. Missing or uncompiled
extension schemas are not fabricated or compiled inside installed extensions.

## Data, backups, and dependable editing

- Profiles: `${XDG_DATA_HOME:-~/.local/share}/desktop-studio/profiles/`.
  `initial-snapshot.json` is created once and never overwritten on launch.
- Private service/file backups: `…/desktop-studio/backups/`, including Toshy,
  startup overrides, and the display state before an Apply operation.
- Change history and rotating logs:
  `${XDG_STATE_HOME:-~/.local/state}/desktop-studio/`.
- Profiles are JSON with `format: desktop-studio-profile` and `version: 1`.
  They store effective values **and** explicit override state so restoration can
  remove an override as well as put back a value. Missing/locked/type-incompatible
  keys are shown as skipped. Imported categories are reclassified locally.
- Exports exclude credential/secret/token/password keys, credential connection
  stores, command strings, remapper source, and common embedded-credential
  patterns. They contain settings, not a copy of your home directory. Review
  custom extension text values before sharing a profile; arbitrary strings do
  not carry reliable semantic secret annotations.
- Settings are read through Gio.Settings and monitored for external changes.
  Editors/profile reviews hold expected states and refuse stale writes. Groups
  are prevalidated; partial failures are compensated only where the values still
  belong to the operation. A durable journal is written before settings changes.
  Gio.Settings/dconf has no cross-process compare-and-swap transaction: a tiny
  race between the final read and a write remains a platform limitation.
- History omits private values and cannot replay external service actions. Undo
  refuses mixed private operations, policy locks, or subsequent external edits.
  Toshy restoration similarly refuses later file edits. Display confirmation and
  automatic timeout belong to GNOME Shell, so they survive this app exiting.

Restore a category from the starting configuration by opening Profiles & Backups,
choosing **Initial configuration → Compare**, selecting that category, inspecting
the differences, then choosing **Apply**. Selecting the profile alone does nothing.

## Verification and diagnostics

```sh
make test
make verify
./desktop-studio --diagnose
```

Tests use a memory GSettings backend, temporary compiled schemas, and temporary
files. No write test targets your real desktop or Toshy source. Tests cover range
and type checks, stale edits, partial-failure rollback, profile versions and
category restoration, automatic backups, undo, secret exclusion, real-instance
path handling, custom shortcuts/conflicts, remapper backups/restoration, and display
serial/scale/confirmation validation.
Cursor tests also cover checksums, archive path and symlink validation, partial
failure cleanup, preservation of existing themes, and bounded Xcursor decoding.

The live `verify_session.py` opens every page, searches, opens and closes editors
and profile reviews, inspects installed extensions and Toshy, and asks Mutter only
to **verify** the existing display configuration (method 0). It compares all
tracked settings before/after and saves reports and UI captures in `artifacts/`.
It never applies display changes, restarts Toshy, or toggles an extension. The
interactive Keep/Revert path is covered through an isolated D-Bus test double;
it is deliberately not exercised against your real monitors during verification.

## Source layout and translation

`desktop_studio/core/` owns validation, concurrency, snapshots, profiles, and
history. `platform/` owns D-Bus and supported service/file integration.
`catalog.py` contains curated metadata and display hints. `ui/` contains GTK
widgets and category views. `app.py` owns navigation and the application lifecycle.

User-facing strings use gettext. Persian navigation/common strings are included;
untranslated strings fall back to English, and schema descriptions use the
installed GLib translations. GTK mirrors layouts in RTL locales. Rebuild the
included catalog with `make translations`. For a Persian UI without changing any
GNOME preferences, launch a separate app process with `LANGUAGE=fa ./desktop-studio`.
Quit any already running instance first. No profile changes keyboard layouts or
application language merely because it is selected.

Implementation references: [libadwaita appearance](https://gnome.pages.gitlab.gnome.org/libadwaita/doc/1-latest/styles-and-appearance.html),
[Mutter display interface](https://gitlab.gnome.org/GNOME/mutter/-/blob/main/data/dbus-interfaces/org.gnome.Mutter.DisplayConfig.xml),
[Toshy configuration](https://github.com/RedBearAK/toshy#readme).
