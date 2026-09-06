import unittest
from pathlib import Path
from unittest.mock import patch

from pcdog_runtime.windows_network_recovery import (
    ExitCode,
    RemoteError,
    Timing,
    classify_diagnostic,
    diagnostic,
    powershell_script,
    recover,
    service_interface_is_unambiguously_protected,
    SshRunner,
)


def healthy_snapshot(**overrides):
    value = {
        "adapter": {"name": "Wi-Fi", "if_index": 7, "status": "Up"},
        "ipv4": ["192.168.7.100/22"],
        "gateways": ["192.168.7.1"],
        "gateway_reachable": True,
        "internet_reachable": True,
        "dns_resolves": True,
        "service_candidates": [
            {"if_index": 3, "has_service_address": True, "has_service_description": True}
        ],
    }
    value.update(overrides)
    return value


class FakeRunner:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.scripts = []

    def run(self, script):
        self.scripts.append(script)
        item = next(self.responses)
        if isinstance(item, Exception):
            raise item
        return item


class WindowsNetworkRecoveryTests(unittest.TestCase):
    def test_healthy(self):
        self.assertEqual(classify_diagnostic(healthy_snapshot()), "HEALTHY")

    def test_ssh_unavailable(self):
        status, snapshot = diagnostic(FakeRunner([RemoteError("offline")]), "Wi-Fi", "1.1.1.1", "example.com")
        self.assertEqual((status, snapshot), ("SSH_UNAVAILABLE", {}))
        self.assertEqual(ExitCode.SSH_UNAVAILABLE, 10)

    def test_adapter_down(self):
        self.assertEqual(classify_diagnostic(healthy_snapshot(adapter={"status": "Down"})), "ADAPTER_DOWN")

    def test_no_ipv4(self):
        self.assertEqual(classify_diagnostic(healthy_snapshot(ipv4=[])), "NO_IPV4")

    def test_no_gateway(self):
        self.assertEqual(classify_diagnostic(healthy_snapshot(gateways=[])), "NO_GATEWAY")

    def test_gateway_unreachable(self):
        self.assertEqual(classify_diagnostic(healthy_snapshot(gateway_reachable=False)), "GATEWAY_UNREACHABLE")

    def test_internet_unreachable(self):
        self.assertEqual(classify_diagnostic(healthy_snapshot(internet_reachable=False)), "INTERNET_UNREACHABLE")

    def test_dns_failure(self):
        self.assertEqual(classify_diagnostic(healthy_snapshot(dns_resolves=False)), "DNS_FAILURE")

    def test_recovery_succeeds_after_stabilization(self):
        unhealthy = healthy_snapshot(internet_reachable=False)
        runner = FakeRunner([unhealthy, {"kind": "restart", "safe": True}, unhealthy, healthy_snapshot()])
        sleeps = []
        status, _ = recover(runner, "Wi-Fi", "1.1.1.1", "example.com", Timing(2, 1, 5), sleeps.append)
        self.assertEqual(status, "RECOVERED")
        self.assertEqual(sleeps, [2, 1])
        self.assertIn("Restart-NetAdapter", runner.scripts[1])

    def test_recovery_timeout(self):
        unhealthy = healthy_snapshot(internet_reachable=False)
        runner = FakeRunner([unhealthy, {"kind": "restart", "safe": True}, unhealthy, unhealthy, unhealthy])
        status, _ = recover(runner, "Wi-Fi", "1.1.1.1", "example.com", Timing(0, 1, 2), lambda _: None)
        self.assertEqual(status, "RECOVERY_TIMEOUT")

    def test_recovery_blocks_usb_service_adapter(self):
        usb = healthy_snapshot(adapter={"name": "Ethernet 2", "if_index": 3, "status": "Up"})
        runner = FakeRunner([usb])
        status, _ = recover(runner, "Ethernet 2", "1.1.1.1", "example.com", Timing(0, 1, 1), lambda _: None)
        self.assertEqual(status, "SERVICE_INTERFACE_PROTECTED")
        self.assertEqual(len(runner.scripts), 1)
        self.assertNotIn("Restart-NetAdapter", runner.scripts[0])

    def test_partial_service_identification_is_fail_safe(self):
        ambiguous = healthy_snapshot(service_candidates=[
            {"if_index": 3, "has_service_address": True, "has_service_description": False},
            {"if_index": 4, "has_service_address": False, "has_service_description": True},
        ])
        self.assertFalse(service_interface_is_unambiguously_protected(ambiguous))
        runner = FakeRunner([ambiguous])
        self.assertEqual(recover(runner, "Wi-Fi", "1.1.1.1", "example.com", Timing(0, 1, 1), lambda _: None)[0], "SERVICE_INTERFACE_PROTECTED")

    def test_diagnostic_never_contains_restart_command(self):
        self.assertNotIn("Restart-NetAdapter", powershell_script("diagnostic", "Wi-Fi", "1.1.1.1", "example.com"))
        self.assertIn("Restart-NetAdapter", powershell_script("restart", "Wi-Fi", "1.1.1.1", "example.com"))

    def test_invalid_timing_is_rejected(self):
        with self.assertRaises(ValueError):
            Timing(-1, 1, 1).validate()
        with self.assertRaises(ValueError):
            Timing(0, 0, 1).validate()

    def test_remote_restart_must_confirm_guard(self):
        runner = FakeRunner([healthy_snapshot(), {"kind": "restart", "safe": False}])
        self.assertEqual(recover(runner, "Wi-Fi", "1.1.1.1", "example.com", Timing(0, 1, 1), lambda _: None)[0], "SERVICE_INTERFACE_PROTECTED")

    def test_remote_fail_safe_is_reported_as_protected(self):
        runner = FakeRunner([healthy_snapshot(), RemoteError("SERVICE_INTERFACE_PROTECTED")])
        self.assertEqual(recover(runner, "Wi-Fi", "1.1.1.1", "example.com", Timing(0, 1, 1), lambda _: None)[0], "SERVICE_INTERFACE_PROTECTED")

    def test_ssh_runner_uses_dedicated_identity_in_batch_mode(self):
        runner = SshRunner("admin", "172.23.254.2", Path("/tmp/pcdog-key"))
        with patch("pcdog_runtime.windows_network_recovery.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = '{"kind":"diagnostic"}'
            self.assertEqual(runner.run("Write-Output ok"), {"kind": "diagnostic"})
        command = run.call_args.args[0]
        self.assertIn("BatchMode=yes", command)
        self.assertIn("PasswordAuthentication=no", command)
        self.assertEqual(command[command.index("-i") + 1], "/tmp/pcdog-key")


if __name__ == "__main__":
    unittest.main()
