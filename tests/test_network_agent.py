"""Lokalne kontrakty network-agenta; nigdy nie wywołują NetworkManagera hosta."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import struct
from tempfile import TemporaryDirectory
from threading import Event, Thread
import time
import unittest

from pcdog_runtime.network_agent import (
    NetworkAgentError,
    NmcliExecutor,
    PreviousConnection,
    WifiJobManager,
    _split_nmcli,
    create_server,
    handle_request,
    peer_uid,
    validate_bssid,
    validate_password,
    validate_ssid,
)
from pcdog_runtime.network_agent_client import request_network_agent


class FakeExecutor:
    def __init__(self, *, failure: str | None = None, confirmed: bool = True, rollback_fails: bool = False, block: Event | None = None) -> None:
        self.failure, self.confirmed, self.rollback_fails, self.block = failure, confirmed, rollback_fails, block
        self.rollback_calls: list[PreviousConnection] = []
        self.commands: list[tuple[str, object]] = []

    def list_wifi(self) -> list[dict[str, object]]:
        return [{"ssid": "Domowa", "bssid": "AA:BB:CC:DD:EE:FF", "security": "WPA2", "signal": 77}]

    def active_wifi(self) -> PreviousConnection | None:
        self.commands.append(("active", None))
        return PreviousConnection("wlan0", "old-profile")

    def connect(self, ssid: str, bssid: str | None, password: str, timeout: int) -> None:
        self.commands.append(("connect", (ssid, bssid, timeout)))
        if self.block is not None:
            self.block.wait(1)
        if self.failure:
            raise NetworkAgentError(self.failure)

    def is_confirmed(self, ssid: str, bssid: str | None) -> bool:
        self.commands.append(("confirmed", (ssid, bssid)))
        return self.confirmed

    def rollback(self, previous: PreviousConnection) -> None:
        self.rollback_calls.append(previous)
        if self.rollback_fails:
            raise OSError("not reported")

    def cleanup_failed_connection(self) -> None:
        self.commands.append(("cleanup", None))


def await_done(manager: WifiJobManager) -> dict[str, object]:
    for _ in range(100):
        result = manager.status()
        if result["status"] != "IN_PROGRESS":
            return result
        time.sleep(0.01)
    raise AssertionError("job did not finish")


class NetworkAgentTests(unittest.TestCase):
    def test_nmcli_scan_parser_keeps_escaped_fields_and_filters_invalid_rows(self) -> None:
        self.assertEqual(_split_nmcli(r"Cafe\:Net:AA\:BB\\CC:WPA2:42"), ["Cafe:Net", "AA:BB\\CC", "WPA2", "42"])
        executor = NmcliExecutor()
        calls: list[tuple[list[str], str | None]] = []

        def run(arguments, *, timeout, input_text=None):
            calls.append((arguments, input_text))
            from subprocess import CompletedProcess
            return CompletedProcess(arguments, 0, "Cafe\\:Net:aa\\:bb\\:cc\\:dd\\:ee\\:ff:WPA2:42\ninvalid:line\n", "")

        executor._run = run  # type: ignore[method-assign]
        self.assertEqual(executor.list_wifi(), [{"ssid": "Cafe:Net", "bssid": "AA:BB:CC:DD:EE:FF", "security": "WPA2", "signal": 42}])
        self.assertNotIn("password", " ".join(calls[0][0]).lower())

    def test_validators_reject_control_data_and_invalid_identifiers(self) -> None:
        self.assertEqual(validate_ssid("Sieć"), "Sieć")
        self.assertEqual(validate_bssid("aa:bb:cc:dd:ee:ff"), "AA:BB:CC:DD:EE:FF")
        self.assertEqual(validate_password("abcdefgh"), "abcdefgh")
        for value in ("", "x" * 33, "bad\nssid", 1):
            with self.subTest(ssid=value):
                with self.assertRaises(NetworkAgentError): validate_ssid(value)
        for value in ("no", "aa:bb", 1):
            with self.subTest(bssid=value):
                with self.assertRaises(NetworkAgentError): validate_bssid(value)
        for value in ("short", "x" * 64, "bad\npass", 1):
            with self.subTest(password=value):
                with self.assertRaises(NetworkAgentError): validate_password(value)

    def test_nmcli_never_receives_password_in_argv(self) -> None:
        executor = NmcliExecutor(); received: list[tuple[list[str], str | None]] = []

        def run(arguments, *, timeout, input_text=None):
            received.append((arguments, input_text))
            from subprocess import CompletedProcess
            return CompletedProcess(arguments, 0, "", "")

        executor._run = run  # type: ignore[method-assign]
        executor.active_wifi = lambda: PreviousConnection("wlan0", "old")  # type: ignore[method-assign]
        executor.connect("Home", "AA:BB:CC:DD:EE:FF", "never-in-argv", 30)
        self.assertTrue(all("never-in-argv" not in arguments for arguments, _ in received))
        self.assertEqual(received[-1][1], "never-in-argv\n")
        self.assertIn("save", received[0][0]); self.assertIn("no", received[0][0])

    def test_single_job_success_requires_network_manager_and_ip_confirmation(self) -> None:
        executor = FakeExecutor(confirmed=True); manager = WifiJobManager(executor)
        started = manager.start("Domowa", "AA:BB:CC:DD:EE:FF", "secret-pass")
        self.assertEqual(started["status"], "STARTED")
        result = await_done(manager)
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertNotIn("secret-pass", json.dumps(result))
        self.assertIn(("confirmed", ("Domowa", "AA:BB:CC:DD:EE:FF")), executor.commands)

    def test_second_active_job_is_rejected_as_busy(self) -> None:
        release = Event(); manager = WifiJobManager(FakeExecutor(block=release))
        self.assertEqual(manager.start("One", None, "password1")["status"], "STARTED")
        self.assertEqual(manager.start("Two", None, "password2"), {"status": "BUSY"})
        release.set(); await_done(manager)

    def test_bad_password_timeout_or_missing_manager_roll_back(self) -> None:
        for code in ("CONNECTION_FAILED", "TIMEOUT", "NETWORK_MANAGER_UNAVAILABLE"):
            with self.subTest(code=code):
                executor = FakeExecutor(failure=code); result = await_done(self._started_manager(executor))
                self.assertEqual(result["status"], "ROLLED_BACK")
                self.assertEqual(result["reason"], code)
                self.assertEqual(executor.rollback_calls, [PreviousConnection("wlan0", "old-profile")])

    @staticmethod
    def _started_manager(executor: FakeExecutor) -> WifiJobManager:
        manager = WifiJobManager(executor); manager.start("Domowa", None, "password1"); return manager

    def test_missing_ip_confirmation_rolls_back_and_failed_rollback_is_reported(self) -> None:
        executor = FakeExecutor(confirmed=False); manager = self._started_manager(executor)
        result = await_done(manager)
        self.assertEqual(result["status"], "ROLLED_BACK")
        self.assertEqual(result["reason"], "CONNECTION_NOT_CONFIRMED")
        broken = FakeExecutor(failure="TIMEOUT", rollback_fails=True)
        self.assertEqual(await_done(self._started_manager(broken))["status"], "ROLLBACK_FAILED")

    def test_closed_protocol_and_unix_socket_do_not_expose_secret(self) -> None:
        executor = FakeExecutor(); manager = WifiJobManager(executor)
        self.assertEqual(handle_request(b'{"operation":"poweroff"}\n', manager, executor), {"status": "INVALID_WIFI_REQUEST"})
        with TemporaryDirectory() as directory:
            socket_path = Path(directory) / "agent.sock"
            server = create_server(socket_path, executor=executor, allowed_uid=os.getuid())
            thread = Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                scan = request_network_agent({"operation": "list_wifi"}, socket_path)
                self.assertEqual(scan["status"], "AVAILABLE")
                started = request_network_agent({"operation": "connect_wifi", "ssid": "Domowa", "password": "secret-pass"}, socket_path)
                self.assertEqual(started["status"], "STARTED")
                self.assertNotIn("secret-pass", json.dumps(started))
            finally:
                server.shutdown(); server.server_close(); thread.join()

    def test_peer_credentials_are_read_when_platform_supports_them(self) -> None:
        if not hasattr(socket, "SO_PEERCRED"):
            self.skipTest("SO_PEERCRED unavailable")
        class Connection:
            def getsockopt(self, *_): return struct.pack("3i", 123, 456, 789)
        self.assertEqual(peer_uid(Connection()), 456)  # type: ignore[arg-type]

    def test_linux_socket_rejects_a_peer_with_another_uid(self) -> None:
        if not hasattr(socket, "SO_PEERCRED"):
            self.skipTest("SO_PEERCRED unavailable")
        with TemporaryDirectory() as directory:
            socket_path = Path(directory) / "agent.sock"
            server = create_server(socket_path, executor=FakeExecutor(), allowed_uid=os.getuid() + 1)
            thread = Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                self.assertEqual(request_network_agent({"operation": "list_wifi"}, socket_path), {"status": "UNAUTHORIZED_CLIENT"})
            finally:
                server.shutdown(); server.server_close(); thread.join()

    def test_systemd_integration_is_isolated_from_power_agent(self) -> None:
        root = Path(__file__).parents[1]
        unit = (root / "systemd/pcdog-network-agent.service").read_text(encoding="utf-8")
        installer = (root / "scripts/install-runtime.sh").read_text(encoding="utf-8")
        system_agent = (root / "pcdog_runtime/system_agent.py").read_text(encoding="utf-8")
        self.assertIn("pcdog-network-agent", unit); self.assertIn("RuntimeDirectory=pcdog-network-agent", unit)
        self.assertIn("NETWORK_AGENT_SERVICE_NAME", installer)
        self.assertNotIn("connect_wifi", system_agent)
        self.assertNotRegex(unit.lower(), r"(gpio|power|reset|reboot|shutdown)")
