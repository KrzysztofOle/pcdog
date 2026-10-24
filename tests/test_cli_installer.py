"""Installer lifecycle tests run entirely inside temporary directories."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pcdog_cli_installer", REPO / "scripts/install-cli.py")
assert SPEC is not None and SPEC.loader is not None
installer_module = importlib.util.module_from_spec(SPEC)
import sys
sys.modules[SPEC.name] = installer_module
SPEC.loader.exec_module(installer_module)


class CliInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="pcdog-cli-install-test-")
        self.base = Path(self.temporary.name)
        self.source = self.base / "source"
        self.source.mkdir()
        for filename in installer_module.MODULES:
            shutil.copyfile(REPO / "pcdog_runtime" / filename, self.source / filename)
        self.launcher_source = self.base / "pcdog-cli.sh"
        shutil.copyfile(REPO / "runtime/pcdog-cli.sh", self.launcher_source)
        self.root = self.base / "opt/pcdog-cli"
        self.launcher = self.base / "usr/local/bin/pcdog"
        self.root.parent.mkdir()
        self.launcher.parent.mkdir(parents=True)
        self.layout = installer_module.Layout(self.root, self.launcher, self.source,
                                               self.launcher_source, os.getuid(), os.getgid())
        self.installer = installer_module.CliInstaller(self.layout, require_root=False)

    def tearDown(self):
        self.temporary.cleanup()

    def test_install_and_repeat_are_idempotent(self):
        self.assertTrue(self.installer.install())
        first_target = os.readlink(self.root / "current")
        self.assertFalse(self.installer.install())
        self.assertEqual(os.readlink(self.root / "current"), first_target)
        self.installer.check()
        self.assertEqual(self.launcher.read_bytes(), self.launcher_source.read_bytes())
        self.assertEqual(os.stat(self.launcher).st_mode & 0o777, 0o755)

    def test_installed_package_is_minimal_and_help_runs_from_release(self):
        self.installer.install()
        release = self.root / "current"
        package_init = release / "pcdog_runtime/__init__.py"
        self.assertEqual(package_init.read_bytes(), installer_module.CLI_PACKAGE_INIT)
        environment = {**os.environ, "PYTHONPATH": str(release)}
        result = subprocess.run(
            [sys.executable, "-m", "pcdog_runtime.cli", "help"],
            cwd=self.base, env=environment, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage: pcdog", result.stdout)

    def test_installed_release_contains_mode_guard_and_cli_can_parse_mode(self):
        self.installer.install()
        release = self.root / "current"
        self.assertTrue((release / "pcdog_runtime/usb_mode.py").is_file())
        result = subprocess.run(
            [sys.executable, "-m", "pcdog_runtime.cli", "usb", "mode", "mac", "--help"],
            cwd=self.base, env={**os.environ, "PYTHONPATH": str(release)}, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("windows", result.stdout)
        self.assertIn("mac", result.stdout)

    def test_update_keeps_previous_release_and_rollback_swaps_back(self):
        self.installer.install()
        first = os.readlink(self.root / "current")
        with (self.source / "cli.py").open("ab") as stream:
            stream.write(b"\n# next release\n")
        self.assertTrue(self.installer.install())
        second = os.readlink(self.root / "current")
        self.assertNotEqual(first, second)
        self.assertEqual(os.readlink(self.root / "previous"), first)
        self.installer.rollback()
        self.assertEqual(os.readlink(self.root / "current"), first)
        self.assertEqual(os.readlink(self.root / "previous"), second)
        self.installer.rollback()
        self.assertEqual(os.readlink(self.root / "current"), second)

    def test_rollback_refuses_to_switch_release_when_launcher_was_replaced(self):
        self.installer.install()
        with (self.source / "cli.py").open("ab") as stream:
            stream.write(b"\n# updated\n")
        self.installer.install()
        current = os.readlink(self.root / "current")
        self.launcher.write_text("operator replacement", encoding="utf-8")
        self.launcher.chmod(0o755)
        with self.assertRaisesRegex(installer_module.InstallError, "odmowa nadpisania nieznanego pliku"):
            self.installer.rollback()
        self.assertEqual(os.readlink(self.root / "current"), current)
        self.assertEqual(self.launcher.read_text(encoding="utf-8"), "operator replacement")

    def test_first_install_rollback_removes_owned_files(self):
        self.installer.install()
        self.installer.rollback()
        self.assertFalse(self.launcher.exists())
        self.assertFalse((self.root / "current").is_symlink())
        with self.assertRaises(installer_module.InstallError):
            self.installer.rollback()

    def test_first_install_rollback_restores_known_legacy_launcher(self):
        self.launcher.write_bytes(installer_module.LEGACY_LAUNCHER)
        self.launcher.chmod(0o755)
        self.installer.install()
        self.assertEqual(self.launcher.read_bytes(), self.launcher_source.read_bytes())
        self.installer.rollback()
        self.assertEqual(self.launcher.read_bytes(), installer_module.LEGACY_LAUNCHER)

    def test_unknown_launcher_or_store_content_is_never_overwritten(self):
        unknown = b"user-owned command\n"
        self.launcher.write_bytes(unknown)
        self.launcher.chmod(0o755)
        with self.assertRaisesRegex(installer_module.InstallError, "nieznanego pliku"):
            self.installer.install()
        self.assertEqual(self.launcher.read_bytes(), unknown)
        self.launcher.unlink()
        self.installer.install()
        extra = self.root / "user-data"
        extra.write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(installer_module.InstallError, "nieznane elementy"):
            self.installer.install()
        self.assertEqual(extra.read_text(encoding="utf-8"), "keep")

    def test_missing_source_dependency_fails_before_target_changes(self):
        (self.source / "network_status.py").unlink()
        with self.assertRaisesRegex(installer_module.InstallError, "wymaganego pliku"):
            self.installer.install()
        self.assertFalse(self.root.exists())
        self.assertFalse(self.launcher.exists())

    def test_unsupported_python_fails_before_target_changes(self):
        with patch.object(installer_module.sys, "version_info", (3, 8, 0)):
            with self.assertRaisesRegex(installer_module.InstallError, "Python 3.9"):
                self.installer.install()
        self.assertFalse(self.root.exists())
        self.assertFalse(self.launcher.exists())

    def test_non_root_install_and_rollback_are_refused_before_changes(self):
        root_required = installer_module.CliInstaller(self.layout, require_root=True)
        with patch.object(installer_module.os, "geteuid", return_value=1001):
            with self.assertRaisesRegex(installer_module.InstallError, "wymagają uprawnień root"):
                root_required.install()
            with self.assertRaisesRegex(installer_module.InstallError, "wymagają uprawnień root"):
                root_required.rollback()
        self.assertFalse(self.root.exists())
        self.assertFalse(self.launcher.exists())

    def test_check_is_read_only_and_detects_source_drift(self):
        self.installer.install()
        target_before = os.readlink(self.root / "current")
        with (self.source / "cli.py").open("ab") as stream:
            stream.write(b"# drift\n")
        with self.assertRaisesRegex(installer_module.InstallError, "nie odpowiada bieżącym źródłom"):
            self.installer.check()
        self.assertEqual(os.readlink(self.root / "current"), target_before)

    def test_installer_has_no_service_or_system_configuration_calls(self):
        source = (REPO / "scripts/install-cli.py").read_text(encoding="utf-8")
        forbidden = ("systemctl", "subprocess.run", "NetworkManager", "usb-mode.conf", "zerotier.conf", "gpio")
        for token in forbidden:
            self.assertNotIn(token, source)
        runtime_installer = (REPO / "scripts/install-runtime.sh").read_text(encoding="utf-8")
        self.assertIn('"$script_dir/install-cli.sh"', runtime_installer)


if __name__ == "__main__":
    unittest.main()
