"""All write tests use an isolated memory backend and temporary schema source."""
import os
os.environ["GSETTINGS_BACKEND"] = "memory"

import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from gi.repository import Gio, GLib

from desktop_studio.core.settings import Registry, Ref, SettingsStore, SettingsError, ConflictError, exportable
from desktop_studio.core.profiles import History, Profiles, atomic_json
from desktop_studio.platform.keyboard import canonical_shortcut, conflicts, create_custom_shortcut, Toshy, validate_xkb_options
from desktop_studio.platform.displays import Displays
from desktop_studio.platform.services import DesktopAppInfo, StartupApps, settings_argv


SCHEMA = '''<schemalist>
<enum id="org.desktopstudio.Mode"><value nick="light" value="0"/><value nick="dark" value="1"/></enum>
<schema id="org.desktopstudio.tests" path="/org/desktopstudio/tests/">
  <key name="enabled" type="b"><default>true</default><summary>Enabled</summary></key>
  <key name="size" type="i"><range min="8" max="128"/><default>24</default></key>
  <key name="scale" type="d"><range min="0.5" max="3.0"/><default>1.0</default></key>
  <key name="theme" enum="org.desktopstudio.Mode"><default>'light'</default></key>
  <key name="names" type="as"><default>['a', 'b']</default></key>
  <key name="sources" type="a(ss)"><default>[('xkb','us'),('xkb','ir+winkeys')]</default></key>
  <key name="password" type="s"><default>'private'</default></key>
  <key name="command" type="s"><default>'echo token=private'</default></key>
</schema>
<schema id="org.gnome.desktop.wm.keybindings" path="/org/desktopstudio/keybindings/">
  <key name="close" type="as"><default>['&lt;Primary&gt;q']</default></key>
  <key name="switch" type="as"><default>['&lt;Alt&gt;Tab']</default></key>
  <key name="unused" type="as"><default>[]</default></key>
</schema>
<schema id="org.gnome.settings-daemon.plugins.media-keys" path="/org/desktopstudio/media-keys/">
  <key name="custom-keybindings" type="as"><default>[]</default></key>
</schema>
<schema id="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding">
  <key name="name" type="s"><default>''</default></key>
  <key name="command" type="s"><default>''</default></key>
  <key name="binding" type="s"><default>''</default></key>
</schema>
<schema id="org.desktopstudio.relocatable"><key name="value" type="b"><default>false</default></key></schema>
</schemalist>'''


class CoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema_dir = tempfile.TemporaryDirectory()
        path = Path(cls.schema_dir.name)
        (path / "test.gschema.xml").write_text(SCHEMA)
        subprocess.run(["glib-compile-schemas", "--strict", str(path)], check=True)
        cls.source = Gio.SettingsSchemaSource.new_from_directory(str(path), None, False)

    @classmethod
    def tearDownClass(cls):
        cls.schema_dir.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.registry = Registry(self.source, extension_roots=[])
        # Only the temporary source is reachable; no desktop writes are possible.
        for ref in self.registry.refs():
            self.registry.settings(ref).reset(ref.key)
        self.history = History(self.root)
        self.store = SettingsStore(self.registry, self.history)
        self.profiles = Profiles(self.root / "profiles", self.registry, lambda r: "appearance" if r.schema == "org.desktopstudio.tests" else "keyboard")

    def tearDown(self):
        self.temp.cleanup()

    def ref(self, key):
        return Ref("org.desktopstudio.tests", key)

    def set(self, key, value):
        ref = self.ref(key)
        return self.store.set(ref, value, self.registry.state(ref), key)

    def test_open_and_snapshot_do_not_write(self):
        before = {r: self.registry.state(r) for r in self.registry.refs()}
        path = self.profiles.initial(list(self.registry.refs()))
        self.assertTrue(path.is_file())
        self.assertEqual(before, {r: self.registry.state(r) for r in self.registry.refs()})
        self.set("size", "48")
        self.profiles.initial(list(self.registry.refs()))
        original = self.profiles.load(path)
        self.assertEqual(next(x["value"] for x in original["settings"] if x["key"] == "size"), "24")

    def test_validate_types_ranges_enums_arrays(self):
        for key, text in (("enabled", "true"), ("size", "64"), ("scale", "1.25"), ("theme", "'dark'"), ("names", "['x','y']"), ("sources", "[('xkb','ir+winkeys')]")):
            self.assertIsNotNone(self.registry.validate(self.ref(key), text))
        for key, text in (("enabled", "'yes'"), ("size", "129"), ("size", "8.5"), ("scale", "0.2"), ("theme", "'uninstalled'"), ("names", "[1,2]"), ("sources", "['x']")):
            with self.assertRaises(SettingsError, msg=(key, text)):
                self.registry.validate(self.ref(key), text)

    def test_stale_edit_refuses_to_overwrite(self):
        ref = self.ref("size"); old = self.registry.state(ref)
        self.registry.settings(ref).set_int("size", 32)
        with self.assertRaises(ConflictError):
            self.store.set(ref, "64", old)
        self.assertEqual(self.registry.value(ref).unpack(), 32)

    def test_nan_cannot_bypass_glib_range_comparison(self):
        ref = self.ref("scale"); before = self.registry.state(ref)
        with self.assertRaises(SettingsError): self.store.set(ref, "nan", before)
        self.assertEqual(self.registry.state(ref), before)

    def test_entire_group_validated_before_writing(self):
        first, second = self.ref("enabled"), self.ref("size")
        before = self.registry.state(first)
        with self.assertRaises(SettingsError):
            self.store.apply([(first, "false", before), (second, "999", self.registry.state(second))])
        self.assertEqual(self.registry.state(first), before)
        self.assertEqual(len(self.history.entries), 0)

    def test_administrator_policy_blocks_writes_and_marks_profile_skip(self):
        original = self.registry.settings
        class Locked:
            def __init__(self, st): self.st = st
            def __getattr__(self, name): return getattr(self.st, name)
            def is_writable(self, key): return key != "size"
        self.registry.settings = lambda ref: Locked(original(ref))
        ref = self.ref("size")
        profile = self.profiles.snapshot("Locked", [ref])
        before = self.registry.state(ref)
        with self.assertRaises(SettingsError): self.store.set(ref, "64", before)
        self.assertEqual(self.registry.state(ref), before)
        changes, skipped = self.profiles.compare(profile)
        self.assertFalse(changes); self.assertIn("Locked", skipped[0][1])

    def test_failed_backend_rolls_back_completed_values(self):
        first, second = self.ref("enabled"), self.ref("size")
        original = self.registry.settings
        class Wrapper:
            def __init__(self, st): self.st = st
            def __getattr__(self, key): return getattr(self.st, key)
            def set_value(self, key, value):
                return False if key == "size" else self.st.set_value(key, value)
        self.registry.settings = lambda ref: Wrapper(original(ref))
        before = self.registry.state(first)
        with self.assertRaises(SettingsError):
            self.store.apply([(first, "false", before), (second, "64", self.registry.state(second))])
        self.assertEqual(self.registry.state(first), before)
        self.assertEqual(self.history.entries[-1]["status"], "failed")

    def test_undo_restores_default_override_state(self):
        ref = self.ref("size")
        before = self.registry.state(ref)
        self.set("size", "32")
        self.history.undo(self.history.entries[-1], self.store)
        self.assertEqual(self.registry.state(ref), before)
        self.assertIsNone(self.registry.settings(ref).get_user_value(ref.key))

    def test_undo_preserves_original_explicit_override(self):
        ref = self.ref("size")
        self.registry.settings(ref).set_int(ref.key, 40)
        self.set("size", "64")
        self.history.undo(self.history.entries[-1], self.store)
        self.assertEqual(self.registry.settings(ref).get_user_value(ref.key).unpack(), 40)

    def test_undo_external_edit_is_blocked(self):
        self.set("size", "32"); entry = self.history.entries[-1]
        self.registry.settings(self.ref("size")).set_int("size", 40)
        with self.assertRaises(ConflictError): self.history.undo(entry, self.store)
        self.assertEqual(self.registry.value(self.ref("size")).unpack(), 40)

    def test_profile_roundtrip_selective_restore_and_backup(self):
        refs = list(self.registry.refs())
        profile = self.profiles.snapshot("Original", refs)
        path = self.profiles.save(profile)
        loaded = self.profiles.load(path)
        self.set("size", "64")
        shortcut = Ref("org.gnome.desktop.wm.keybindings", "close")
        self.store.set(shortcut, "['<Alt>F4']", self.registry.state(shortcut))
        review, skipped = self.profiles.compare(loaded, {"appearance"})
        self.assertEqual([x["ref"].key for x in review], ["size"])
        self.profiles.apply_review(review, self.store, "Original")
        self.assertEqual(self.registry.value(self.ref("size")).unpack(), 24)
        self.assertEqual(self.registry.value(shortcut).unpack(), ["<Alt>F4"])
        backup = next(p for path, p in self.profiles.list() if p["name"].startswith("Automatic backup"))
        review, _ = self.profiles.compare(backup)
        self.profiles.apply_review(review, self.store, "Restore backup")
        self.assertEqual(self.registry.value(self.ref("size")).unpack(), 64)

    def test_profile_review_stays_stale_when_external_edit_arrives(self):
        profile = self.profiles.snapshot("Before", [self.ref("size")])
        self.set("size", "40")
        review, _ = self.profiles.compare(profile)
        self.set("size", "48")
        with self.assertRaises(ConflictError): self.profiles.apply_review(review, self.store, "Before")
        self.assertEqual(self.registry.value(self.ref("size")).unpack(), 48)

    def test_unavailable_type_mismatch_and_locked_profile_are_reported(self):
        profile = self.profiles.snapshot("Before", [self.ref("size")])
        profile["settings"][0]["type"] = "u"
        review, skipped = self.profiles.compare(profile)
        self.assertFalse(review); self.assertEqual(len(skipped), 1)
        profile["settings"][0]["schema"] = "org.not.installed"
        review, skipped = self.profiles.compare(profile)
        self.assertFalse(review); self.assertIn("Unavailable", skipped[0][1])

    def test_profile_rejects_bad_versions_duplicates_and_inconsistent_state(self):
        profile = self.profiles.snapshot("Test", [self.ref("size")])
        wrong = copy.deepcopy(profile); wrong["version"] = 2
        with self.assertRaises(SettingsError): self.profiles.validate_document(wrong)
        wrong = copy.deepcopy(profile); wrong["settings"] *= 2
        with self.assertRaises(SettingsError): self.profiles.validate_document(wrong)
        wrong = copy.deepcopy(profile); wrong["settings"][0]["user"] = "64"
        review, skipped = self.profiles.compare(wrong)
        self.assertEqual(len(skipped), 1)

    def test_secret_and_command_values_are_excluded(self):
        profile = self.profiles.snapshot("Safe", list(self.registry.refs()))
        dumped = json.dumps(profile)
        self.assertNotIn('"password"', dumped); self.assertNotIn('"command"', dumped)
        self.assertNotIn("private", dumped)
        self.assertFalse(exportable(self.ref("names"), "'https://person:password@example.org'"))
        self.set("password", "'new-private'")
        self.assertNotIn("new-private", self.history.path.read_text())
        with self.assertRaises(SettingsError): self.history.undo(self.history.entries[-1], self.store)

    def test_relocatable_unknown_path_rejected(self):
        ref = Ref("org.desktopstudio.relocatable", "value", "/invented/path/")
        self.assertFalse(self.registry.exists(ref))
        with self.assertRaises(SettingsError): self.registry.settings(ref)
        self.assertEqual(list(self.registry.refs("org.desktopstudio.relocatable")), [])

    def test_active_extension_schema_wins_over_stale_duplicate(self):
        root = self.root / "extensions"
        for uuid, default in (("active@a", "true"), ("stale@z", "false")):
            directory = root / uuid / "schemas"
            directory.mkdir(parents=True)
            (directory / "extension.gschema.xml").write_text('<schemalist><schema id="org.desktopstudio.extension" path="/org/desktopstudio/extension/"><key name="flag" type="b"><default>' + default + '</default></key></schema></schemalist>')
            subprocess.run(["glib-compile-schemas", "--strict", str(directory)], check=True)
        registry = Registry(self.source, [root], active_extensions={"active@a"})
        self.assertEqual(registry.schema_origins["org.desktopstudio.extension"], "active@a")
        self.assertTrue(registry.schema_key(Ref("org.desktopstudio.extension", "flag")).get_default_value().unpack())

    def test_shortcut_conflicts_normalize_aliases_and_order(self):
        self.assertEqual(canonical_shortcut("<Primary><Shift>Q"), canonical_shortcut("<shift><CTRL>q"))
        self.assertEqual(canonical_shortcut("<Alt>ISO_Left_Tab"), canonical_shortcut("<Shift><Alt>Tab"))
        ref = Ref("org.gnome.desktop.wm.keybindings", "close")
        self.assertEqual(conflicts(self.registry, ["<Control>q"])[0][0], ref)
        self.assertFalse(conflicts(self.registry, ["<Control>q"], ref))
        self.assertFalse(conflicts(self.registry, [""]))

    def test_caps_layout_switching_conflicts_with_modifier_and_compose_roles(self):
        validate_xkb_options(["grp:caps_toggle", "grp_led:scroll", "compose:ralt"])
        for other in ("caps:escape", "ctrl:nocaps", "compose:caps"):
            with self.assertRaises(SettingsError): validate_xkb_options(["grp:caps_toggle", other])

    def test_custom_shortcut_creation_and_registered_discovery(self):
        create_custom_shortcut(self.registry, self.store, "Editor", "gedit", "<Control><Alt>e")
        refs = list(self.registry.refs("org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"))
        self.assertEqual(len(refs), 3)
        self.registry.refresh_paths()
        binding = next(r for r in refs if r.key == "binding")
        self.assertEqual(conflicts(self.registry, ["<Alt><Ctrl>e"])[0][0], binding)
        with self.assertRaises(SettingsError): create_custom_shortcut(self.registry, self.store, "Again", "gedit", "<Ctrl>q")

    def test_change_subscription_fires_for_external_writes(self):
        ref = self.ref("size"); received = []
        self.store.watch(ref); self.store.connect("changed", lambda _s, token: received.append(token))
        self.registry.settings(ref).set_int("size", 42)
        while GLib.MainContext.default().pending(): GLib.MainContext.default().iteration(False)
        self.assertIn(ref.token, received)

    def test_private_atomic_profile_permissions(self):
        path = self.root / "private.json"
        atomic_json(path, {"value": 1})
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)


class ToshyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.path = self.root / "toshy_config.py"
        self.original = '# Existing Mac-style mappings\n' + Toshy.START + '  ### preserved\n\nkeymap("User", {})\n\n' + Toshy.END + '  ### preserved\n# Other mappings\n'
        self.path.write_text(self.original)
        self.toshy = Toshy(self.root / "backups", self.path)

    def tearDown(self): self.temp.cleanup()

    def test_backup_slice_preservation_and_restore(self):
        text, digest = self.toshy.slice()
        backup, new_digest = self.toshy.save_slice(text + '\nkeymap("New", {})', digest)
        self.assertEqual(backup.read_text(), self.original)
        self.assertTrue(self.path.read_text().startswith('# Existing Mac-style mappings\n'))
        self.assertTrue(self.path.read_text().endswith('# Other mappings\n'))
        self.toshy.restore(backup, new_digest)
        self.assertEqual(self.path.read_text(), self.original)

    def test_syntax_error_and_external_edit_leave_file_intact(self):
        _, digest = self.toshy.slice()
        with self.assertRaises(SettingsError): self.toshy.save_slice('keymap(', digest)
        self.assertEqual(self.path.read_text(), self.original)
        self.path.write_text(self.original + '# external\n')
        with self.assertRaises(SettingsError): self.toshy.save_slice('pass', digest)
        self.assertTrue(self.path.read_text().endswith('# external\n'))

    def test_mapping_generation_rejects_code_and_validates_regex(self):
        import ast
        text = Toshy.mapping('RC-c', 'C-Shift-v', r'^org\.gnome\.TextEditor$')
        ast.parse(text)
        with self.assertRaises(SettingsError): Toshy.mapping('C-a");evil()', 'C-c', 'foo')
        with self.assertRaises(SettingsError): Toshy.mapping('C-a', 'C-c', '[')


class DisplayTests(unittest.TestCase):
    def setUp(self):
        self.state = (7, [(('DP-1','vendor','model','serial'), [('1920x1080@60',1920,1080,60.0,1.0,[1.0,2.0],{'is-current':True})],{'color-mode':0})],[(0,0,1.0,0,True,[('DP-1','vendor','model','serial')],{})],{'layout-mode':1})

    def test_supported_scale_primary_and_unique_monitor_validation(self):
        draft = Displays.draft(self.state)
        Displays.validate_draft(self.state, draft)
        wrong = Displays.draft(self.state); wrong[0][2] = 1.75
        with self.assertRaises(SettingsError): Displays.validate_draft(self.state, wrong)
        wrong = Displays.draft(self.state); wrong[0][4] = False
        with self.assertRaises(SettingsError): Displays.validate_draft(self.state, wrong)
        wrong = Displays.draft(self.state); wrong[0][0] = -1
        with self.assertRaises(SettingsError): Displays.validate_draft(self.state, wrong)

    def test_display_serial_and_confirmation_method(self):
        class Proxy:
            def __init__(self, state): self.state = state; self.methods = []
            def get_name_owner(self): return ':test'
            def get_interface_name(self): return 'org.gnome.Mutter.DisplayConfig'
            def get_cached_property(self, key): return GLib.Variant('b', True)
            def call_sync(self, method, params, flags, timeout, cancellable):
                if method == 'GetCurrentState':
                    return GLib.Variant('(ua((ssss)a(siiddada{sv})a{sv})a(iiduba(ssss)a{sv})a{sv})', self.state)
                self.methods.append(params.unpack()[1]); return GLib.Variant('()', ())
        # Variant dictionaries need typed values for D-Bus packing.
        state = copy.deepcopy(self.state)
        state[1][0][1][0][6]['is-current'] = GLib.Variant('b', True)
        state[1][0][2]['color-mode'] = GLib.Variant('u', 0)
        state[3]['layout-mode'] = GLib.Variant('u', 1)
        proxy = Proxy(state); service = Displays(proxy)
        original = service.read(); draft = service.draft(original)
        service.apply_with_confirmation(original, draft)
        self.assertEqual(proxy.methods, [0, 2])
        newer = list(state); newer[0] = 8; proxy.state = tuple(newer)
        with self.assertRaises(ConflictError): service.verify(original, draft)


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.service = StartupApps(); self.service.user = self.root / "user-autostart"
        self.source = self.root / "system/example.desktop"
        self.source.parent.mkdir()
        self.source.write_text('[Desktop Entry]\nType=Application\nName=Example\nExec=true\n')

    def tearDown(self): self.temp.cleanup()

    def test_system_startup_override_backup_and_checked_restoration(self):
        original = self.source.read_bytes()
        backup = self.service.set_enabled(self.source, False, original, self.root / 'backups')
        destination = self.service.user / self.source.name
        self.assertIn('Hidden=true', destination.read_text())
        self.assertEqual(self.source.read_bytes(), original)
        self.service.restore(backup)
        self.assertFalse(destination.exists())
    def test_startup_undo_refuses_external_edits(self):
        backup = self.service.set_enabled(self.source, False, self.source.read_bytes(), self.root / 'backups')
        destination = self.service.user / self.source.name
        destination.write_text(destination.read_text() + '# external\n')
        with self.assertRaises(SettingsError): self.service.restore(backup)
        self.assertTrue(destination.read_text().endswith('# external\n'))

    def test_add_application_never_launches_it_and_can_undo(self):
        app = DesktopAppInfo.new_from_filename(str(self.source))
        backup = self.service.add(app, self.root / 'backups')
        destination = self.service.user / 'desktop-studio-example.desktop'
        self.assertTrue(destination.exists())
        self.service.restore(backup)
        self.assertFalse(destination.exists())


class TranslationTests(unittest.TestCase):
    def test_persian_navigation_rtl_and_empty_optional_labels(self):
        env = dict(os.environ, LANGUAGE="fa")
        subprocess.run(['/usr/bin/python3', '-c', 'from desktop_studio.i18n import _,is_rtl; assert _("Appearance") == "ظاهر"; assert _ ("") == ""; assert is_rtl()'], env=env, check=True)

    def test_settings_links_resolve_gnome_50_and_older_panels(self):
        installed = {"system", "applications", "display"}
        self.assertEqual(settings_argv("datetime", installed), ["gnome-control-center", "system", "datetime"])
        self.assertEqual(settings_argv("region", installed), ["gnome-control-center", "system", "region"])
        self.assertEqual(settings_argv("default-apps", installed), ["gnome-control-center", "applications"])
        self.assertEqual(settings_argv("datetime", {"datetime"}), ["gnome-control-center", "datetime"])
        with self.assertRaises(SettingsError): settings_argv("missing", installed)


if __name__ == '__main__': unittest.main()
