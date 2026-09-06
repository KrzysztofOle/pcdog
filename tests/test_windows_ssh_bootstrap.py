import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from pcdog_runtime.windows_ssh_bootstrap import (
    BootstrapError,
    KeyPair,
    bootstrap,
    ensure_key_pair,
    installation_script,
    key_auth_command,
)


PUBLIC = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITest PcDog Windows service access\n"


class WindowsSshBootstrapTests(unittest.TestCase):
    def test_absent_key_generates_pair_with_expected_parameters(self):
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "pcdog_windows_ed25519"
            calls = []

            def fake_run(command, **kwargs):
                calls.append(command)
                if command[1] == "-y":
                    return subprocess.CompletedProcess(command, 0, stdout=PUBLIC, stderr="")
                private.write_text("private", encoding="utf-8")
                Path(f"{private}.pub").write_text(PUBLIC, encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            pair = ensure_key_pair(private, fake_run)
            self.assertEqual(pair.state, "generated")
            self.assertEqual(calls[0][:4], ["ssh-keygen", "-q", "-t", "ed25519"])
            self.assertEqual(stat.S_IMODE(private.stat().st_mode), 0o600)

    def test_complete_pair_is_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "key"
            private.write_text("private", encoding="utf-8")
            Path(f"{private}.pub").write_text(PUBLIC, encoding="utf-8")
            calls = []
            def fake_run(command, **kwargs):
                calls.append(command)
                return subprocess.CompletedProcess(command, 0, stdout=PUBLIC, stderr="")
            self.assertEqual(ensure_key_pair(private, fake_run).state, "reused")
            self.assertEqual(calls, [["ssh-keygen", "-y", "-f", str(private)]])

    def test_incomplete_pair_is_fail_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "key"
            private.write_text("private", encoding="utf-8")
            with self.assertRaisesRegex(BootstrapError, "niespójna"):
                ensure_key_pair(private)

    def test_existing_key_auth_skips_password_bootstrap(self):
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "key"
            public = Path(f"{private}.pub")
            public.write_text(PUBLIC, encoding="utf-8")
            pair = KeyPair(private, public, "reused")
            calls = []
            result, _ = bootstrap("admin", "host", private, tcp_check=lambda _: calls.append("tcp"), key_pair=lambda _: pair, auth_check=lambda *_: True, install=lambda *_: calls.append("install"))
            self.assertEqual(result, "already_configured")
            self.assertEqual(calls, ["tcp"])

    def test_password_bootstrap_installs_then_rechecks(self):
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "key"
            public = Path(f"{private}.pub")
            public.write_text(PUBLIC, encoding="utf-8")
            pair, calls = KeyPair(private, public, "generated"), []
            answers = iter([False, True])
            result, _ = bootstrap("admin", "host", private, tcp_check=lambda _: None, key_pair=lambda _: pair, auth_check=lambda *_: next(answers), install=lambda user, host, key: calls.append((user, host, key)))
            self.assertEqual(result, "configured")
            self.assertEqual(calls, [("admin", "host", PUBLIC)])

    def test_final_batchmode_failure_fails_whole_bootstrap(self):
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "key"
            public = Path(f"{private}.pub")
            public.write_text(PUBLIC, encoding="utf-8")
            pair = KeyPair(private, public, "generated")
            with self.assertRaisesRegex(BootstrapError, "końcowy test"):
                bootstrap("admin", "host", private, tcp_check=lambda _: None, key_pair=lambda _: pair, auth_check=lambda *_: False, install=lambda *_: "installed")

    def test_key_is_not_duplicated_and_admin_path_is_resolved_from_sshd(self):
        script = installation_script(PUBLIC)
        self.assertIn("sshd -T -C", script)
        self.assertIn("$present", script)
        self.assertIn("if (-not $present) { Add-Content", script)
        self.assertIn("administrators_authorized_keys", script)

    def test_acl_uses_well_known_sids_not_localized_account_names(self):
        """Regression for Polish Windows where 'Administrators' cannot resolve."""
        script = installation_script(PUBLIC)
        self.assertIn("BuiltinAdministratorsSid", script)
        self.assertIn("LocalSystemSid", script)
        self.assertIn("WindowsIdentity]::GetCurrent().User", script)
        self.assertIn("$acl.SetOwner($administratorsSid)", script)
        self.assertNotIn("BUILTIN\\\\Administrators", script)
        self.assertNotIn("NT AUTHORITY\\\\SYSTEM", script)
        self.assertNotIn("$acl.SetOwner([System.Security.Principal.NTAccount]", script)

    def test_ambiguous_or_unsupported_sshd_config_stops_before_write(self):
        script = installation_script(PUBLIC)
        self.assertIn("SSHD_CONFIG_AMBIGUOUS", script)
        self.assertIn("SSHD_CONFIG_UNRESOLVED", script)
        self.assertLess(script.index("SSHD_CONFIG_AMBIGUOUS"), script.index("Add-Content"))

    def test_no_password_storage_or_sshd_config_mutation(self):
        script = installation_script(PUBLIC)
        self.assertNotIn("PasswordAuthentication", script)
        self.assertNotIn("sshd_config", script)
        self.assertNotIn("Set-Content", script)

    def test_recovery_compatible_key_command_is_batch_only(self):
        command = key_auth_command("admin", "host", Path("/tmp/key"))
        self.assertIn("BatchMode=yes", command)
        self.assertIn("PasswordAuthentication=no", command)
        self.assertIn("-i", command)


if __name__ == "__main__":
    unittest.main()
