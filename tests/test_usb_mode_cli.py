"""USB mode CLI safety tests use mocked routes and an inert switcher."""

from __future__ import annotations

from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import stat
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pcdog_runtime import cli, usb_mode


class UsbModeCliTests(unittest.TestCase):
    def routes(self, session_dev="wlan0", usb_dev="usb0", *, session_src="192.0.2.10", usb_src="172.23.254.1"):
        return [
            subprocess.CompletedProcess([], 0, json.dumps([{"dev": session_dev, "from": session_src}]), ""),
            subprocess.CompletedProcess([], 0, json.dumps([{"dev": usb_dev, "prefsrc": usb_src}]), ""),
        ]

    def invoke_switch(self, mode="mac", *, route_results=None, connection="198.51.100.8 50000 192.0.2.10 22",
                      euid=1000, exists=True, returncode=0):
        output = StringIO()
        route_results = route_results or self.routes()
        with patch.dict(os.environ, {"SSH_CONNECTION": connection} if connection is not None else {}, clear=False), \
             patch.object(usb_mode.subprocess, "run", side_effect=route_results + [subprocess.CompletedProcess([], returncode)] if exists else route_results) as run, \
             patch.object(Path, "lstat", return_value=SimpleNamespace(st_mode=stat.S_IFREG | 0o755, st_uid=0) if exists else None) as lstat, \
             patch.object(usb_mode.os, "access", return_value=exists), \
             patch.object(usb_mode.os, "geteuid", return_value=euid):
            code = usb_mode.change_usb_mode(mode, output=output)
        return code, output.getvalue(), run

    def test_invalid_mode_is_rejected_before_route_or_privileged_call(self):
        output = StringIO()
        with patch.object(usb_mode, "_route") as route:
            self.assertEqual(usb_mode.change_usb_mode("bad;id", output=output), 2)
        route.assert_not_called()
        self.assertIn("obsługiwane tryby", output.getvalue())

    def test_parser_accepts_exact_modes_and_rejects_others(self):
        for mode in ("windows", "mac"):
            with self.subTest(mode=mode):
                parsed = cli.build_parser().parse_args(["usb", "mode", mode])
                self.assertEqual((parsed.usb_command, parsed.mode), ("mode", mode))
        for argv in (("usb", "mode"), ("usb", "mode", "auto"), ("usb", "mode", "mac", "extra")):
            with self.subTest(argv=argv), self.assertRaises(SystemExit) as raised:
                cli.build_parser().parse_args(argv)
            self.assertEqual(raised.exception.code, 2)

    def test_wifi_and_zerotier_routes_delegate_without_shell(self):
        for mode in ("windows", "mac"):
            with self.subTest(mode=mode):
                code, output, run = self.invoke_switch(mode, route_results=self.routes("wlan0", "usb0"))
                self.assertEqual(code, 0)
                self.assertIn("SSH zosta\u0142 rozpoznany poza USB", output)
                self.assertEqual(run.call_count, 3)
                delegate = run.call_args_list[-1]
                self.assertEqual(delegate.args[0], [usb_mode.SUDO, "--", usb_mode.USB_MODE, mode])
                self.assertNotIn("shell", delegate.kwargs)

    def test_ssh_through_usb_is_refused_without_delegate(self):
        code, output, run = self.invoke_switch(route_results=self.routes("usb0", "usb0"))
        self.assertEqual(code, 1)
        self.assertIn("przebiega przez USB", output)
        self.assertEqual(run.call_count, 2)

    def test_missing_ssh_or_ambiguous_route_is_refused_without_side_effects(self):
        for connection, routes in ((None, self.routes()), ("bad", self.routes()),
                                   ("198.51.100.8 50000 192.0.2.10 22", [OSError("ip missing")]),
                                   ("198.51.100.8 50000 192.0.2.10 22", self.routes(session_src="198.51.100.2")),
                                   ("198.51.100.8 50000 192.0.2.10 22", self.routes(usb_src="192.0.2.10")),
                                   ("198.51.100.8 50000 192.0.2.10 22", [
                                       subprocess.CompletedProcess([], 0, '[{"dev":"wlan0","prefsrc":"192.0.2.10"}]', ""),
                                       subprocess.CompletedProcess([], 0, '[{"dev":"usb0","prefsrc":"172.23.254.1","gateway":"172.23.254.254"}]', ""),
                                   ])):
            with self.subTest(connection=connection, routes=routes):
                code, output, run = self.invoke_switch(connection=connection, route_results=routes)
                self.assertEqual(code, 1)
                self.assertIn("zablokowana", output)
                self.assertNotIn(usb_mode.USB_MODE, str(run.call_args_list))

    def test_missing_switcher_and_operation_failures_are_reported(self):
        code, output, run = self.invoke_switch(exists=False)
        self.assertEqual(code, 1)
        self.assertIn("NIEDOSTĘPNE", output)
        self.assertEqual(run.call_count, 2)
        code, output, _ = self.invoke_switch(returncode=1)
        self.assertEqual(code, 1)
        self.assertIn("kod 1", output)

    def test_cli_status_remains_read_only_and_mode_calls_guard(self):
        with patch.object(cli, "read_usb_status", return_value={"status": "OK", "values": {}}):
            self.assertEqual(cli.run_cli(("usb", "status"), output=StringIO(), usb=lambda: {"status": "OK", "values": {}}), 0)
        with patch("pcdog_runtime.cli.change_usb_mode", return_value=1) as change:
            self.assertEqual(cli.run_cli(("usb", "mode", "windows"), output=StringIO()), 1)
        change.assert_called_once_with("windows", output=unittest.mock.ANY)


if __name__ == "__main__":
    unittest.main()
