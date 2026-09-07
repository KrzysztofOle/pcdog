"""Testy kontraktu system-agenta bez żadnych działań na systemie."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pcdog_runtime.system_agent import handle_request
from pcdog_runtime.system_agent_client import read_system_agent_status


class SystemAgentTests(unittest.TestCase):

    def test_status_contract_is_ready_and_actions_are_disabled(self) -> None:
        self.assertEqual(handle_request(b'{"operation":"status"}\n'), {
            "status": "READY", "protocol_version": 1, "actions_enabled": False,
        })

    def test_actions_are_explicitly_not_enabled(self) -> None:
        self.assertEqual(handle_request(b'{"operation":"reboot"}\n'), {"status": "ACTION_NOT_ENABLED"})
        self.assertEqual(handle_request(b'{"operation":"poweroff"}\n'), {"status": "ACTION_NOT_ENABLED"})

    def test_invalid_request_is_rejected(self) -> None:
        self.assertEqual(handle_request(b'not json\n'), {"status": "INVALID_REQUEST"})
        self.assertEqual(handle_request(b'{"operation":"status","extra":true}\n'), {"status": "ACTION_NOT_ENABLED"})
        self.assertEqual(handle_request(b"x" * 257), {"status": "INVALID_REQUEST"})

    def test_missing_agent_is_unavailable(self) -> None:
        with TemporaryDirectory() as directory:
            self.assertEqual(read_system_agent_status(Path(directory) / "missing.sock"), {"status": "UNAVAILABLE"})
