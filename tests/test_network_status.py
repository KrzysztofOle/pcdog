import subprocess
import unittest
from unittest.mock import patch

from pcdog_runtime.network_status import read_network_status
from pcdog_runtime.web_api import ReadOnlyApi, ApiRequestError


class NetworkStatusTests(unittest.TestCase):
    @patch("pcdog_runtime.network_status.subprocess.run")
    def test_read_only_command_and_escaped_values(self, run):
        run.return_value.stdout = (
            "GENERAL.DEVICE:wlan0\nGENERAL.TYPE:wifi\nGENERAL.STATE:100 (connected)\n"
            "GENERAL.CONNECTION:Office\\: WiFi\nIP4.ADDRESS[1]:192.168.1.2/24\n"
            "IP6.ADDRESS[1]:fe80\\:\\:1/64\n"
            "GENERAL.DEVICE:usb0\nGENERAL.TYPE:ethernet\nGENERAL.CONNECTION:--\n"
        )
        result = read_network_status()
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertEqual(result["interfaces"][0]["connection"], "Office: WiFi")
        self.assertEqual(result["interfaces"][0]["addresses"], ["192.168.1.2/24", "fe80::1/64"])
        self.assertIsNone(result["interfaces"][1]["connection"])
        args, kwargs = run.call_args
        self.assertEqual(args[0][-2:], ["device", "show"])
        self.assertEqual(kwargs["timeout"], 2)
        self.assertNotIn("shell", kwargs)
        self.assertNotIn("--show-secrets", args[0])

    @patch("pcdog_runtime.network_status.subprocess.run")
    def test_failures_never_claim_disconnected(self, run):
        for error in (FileNotFoundError(), subprocess.TimeoutExpired("nmcli", 2),
                      subprocess.CalledProcessError(1, "nmcli")):
            run.side_effect = error
            self.assertEqual(read_network_status(), {"status": "UNAVAILABLE", "interfaces": []})

    @patch("pcdog_runtime.web_api.read_network_status")
    def test_api_validates_query_without_database_access(self, read):
        read.return_value = {"status": "UNAVAILABLE", "interfaces": []}
        api = ReadOnlyApi(lambda: self.fail("Network must not open Event Store"))
        self.assertEqual(api.handle_get("/api/v1/network", {}), read.return_value)
        with self.assertRaises(ApiRequestError):
            api.handle_get("/api/v1/network", {"password": ["secret"]})
        self.assertEqual(read.call_count, 1)


if __name__ == "__main__":
    unittest.main()
