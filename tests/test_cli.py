"""Read-only CLI contracts; never contact host services or PcDog1."""

from __future__ import annotations

from io import StringIO
import subprocess
import unittest
from unittest.mock import patch

from pcdog_runtime import cli


GOOD_NETWORK = {"status": "AVAILABLE", "interfaces": [{"name": "wlan0", "state": "connected",
                  "connection": "Home", "addresses": ["192.0.2.5/24"]}]}
GOOD_WIFI = {"status": "OK", "profiles": [{"name": "Home", "device": "wlan0"}]}
GOOD_USB = {"status": "OK", "values": {"configured mode": "windows", "active USB function": "rndis.usb0",
             "UDC bound": "dummy_udc"}}


class CliTests(unittest.TestCase):
    def invoke(self, argv=(), **providers):
        output = StringIO()
        code = cli.run_cli(argv, output=output, **providers)
        return code, output.getvalue()

    def test_empty_arguments_and_help_print_usage_without_providers(self):
        for argv in ((), ("help",)):
            code, output = self.invoke(argv)
            self.assertEqual(code, 0)
            self.assertIn("usage: pcdog", output)
            self.assertNotIn("POWER", output)

    def test_unknown_and_incomplete_commands_return_usage_error(self):
        for argv in (("wat",), ("network",), ("wifi",), ("usb",), ("status", "extra")):
            with self.subTest(argv=argv), self.assertRaises(SystemExit) as raised:
                cli.run_cli(argv, output=StringIO())
            self.assertEqual(raised.exception.code, 2)

    def test_network_status_uses_provider(self):
        provider = lambda: GOOD_NETWORK
        code, output = self.invoke(("network", "status"), network=provider)
        self.assertEqual(code, 0)
        self.assertIn("wlan0: connected", output)

    def test_wifi_profiles_only_shows_profile_name_and_device(self):
        code, output = self.invoke(("wifi", "profiles"), wifi=lambda: GOOD_WIFI)
        self.assertEqual(code, 0)
        self.assertIn("Home (wlan0)", output)

    def test_usb_status_uses_read_only_status_provider(self):
        code, output = self.invoke(("usb", "status"), usb=lambda: GOOD_USB)
        self.assertEqual(code, 0)
        self.assertIn("configured mode: windows", output)

    def test_summary_continues_when_one_provider_raises(self):
        code, output = self.invoke(("status",), health=lambda: {"status": "OK", "detail": "runtime działa"},
                                   network=lambda: (_ for _ in ()).throw(OSError("offline")),
                                   wifi=lambda: GOOD_WIFI, usb=lambda: GOOD_USB)
        self.assertEqual(code, 1)
        self.assertIn("Runtime: OK", output)
        self.assertIn("Profile Wi-Fi: OK", output)
        self.assertIn("Sieć: NIEDOSTĘPNE", output)
        self.assertIn("USB: OK", output)

    def test_readers_only_call_read_commands_and_never_show_secrets(self):
        secret = "SHOULD_NOT_APPEAR"
        def fake_run(arguments, **kwargs):
            self.assertNotIn(secret, " ".join(arguments))
            self.assertNotIn("password", " ".join(arguments).lower())
            self.assertTrue(arguments[-2:] == ["connection", "show"] or arguments[-1:] == ["status"] or arguments == [cli.HEALTH_CHECK])
            return subprocess.CompletedProcess(arguments, 0,
                "Home:802-11-wireless:wlan0\n" if "nmcli" in arguments else "HEALTHY\n" if arguments == [cli.HEALTH_CHECK] else
                "configured mode: windows\nactive USB function: rndis.usb0\nUDC bound: dummy\n", "")
        with patch.object(cli, "_run_readonly", side_effect=fake_run):
            self.assertEqual(cli.read_wifi_profiles()["profiles"], [{"name": "Home", "device": "wlan0"}])
            self.assertEqual(cli.read_health()["status"], "OK")
            self.assertEqual(cli.read_usb_status()["status"], "OK")

    def test_wifi_reader_does_not_request_secret_fields_or_relay_command_output(self):
        secret = "not-for-output"
        def fake_run(arguments, **kwargs):
            self.assertEqual(arguments[arguments.index("--fields") + 1], "NAME,TYPE,DEVICE")
            return subprocess.CompletedProcess(arguments, 0, f"Home:802-11-wireless:wlan0\n{secret}:802-11-wireless\n", "")
        output = StringIO()
        with patch.object(cli, "_run_readonly", side_effect=fake_run):
            code = cli.run_cli(("wifi", "profiles"), output=output)
        self.assertEqual(code, 0)
        self.assertNotIn(secret, output.getvalue())

    def test_all_status_readers_run_without_sudo(self):
        calls = []
        def fake_run(arguments, **kwargs):
            calls.append(arguments)
            if arguments == [cli.HEALTH_CHECK]:
                return subprocess.CompletedProcess(arguments, 0, "HEALTHY\n", "")
            if arguments[-2:] == ["connection", "show"]:
                return subprocess.CompletedProcess(arguments, 0, "Home:802-11-wireless:wlan0\n", "")
            return subprocess.CompletedProcess(arguments, 0,
                "configured mode: windows\nactive USB function: rndis.usb0\nUDC bound: dummy\n", "")
        with patch.object(cli, "_run_readonly", side_effect=fake_run):
            self.assertEqual(cli.read_health()["status"], "OK")
            self.assertEqual(cli.read_wifi_profiles()["status"], "OK")
            self.assertEqual(cli.read_usb_status()["status"], "OK")
        self.assertEqual(calls[0], [cli.HEALTH_CHECK])
        self.assertEqual(calls[1][-2:], ["connection", "show"])
        self.assertEqual(calls[2], [cli.USB_MODE, "status"])
        self.assertTrue(all(arguments[0] != "sudo" for arguments in calls))
        from pcdog_runtime.network_status import read_network_status
        with patch("pcdog_runtime.network_status.subprocess.run", return_value=subprocess.CompletedProcess(
                ["nmcli"], 0, "GENERAL.DEVICE:wlan0\n", "")) as network_run:
            read_network_status()
        self.assertEqual(network_run.call_args.args[0][0], "nmcli")


if __name__ == "__main__":
    unittest.main()
