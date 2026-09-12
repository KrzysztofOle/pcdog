"""Kontrakt root-only CLI pcdog-test, bez dostępu do prawdziwego GPIO."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from pcdog_runtime.diagnostic_controls import (
    DIAGNOSTIC_CONSUMER,
    DiagnosticControls,
    main,
    print_status,
)
from pcdog_runtime.hardware_agent import ControlPolarity, GpioPulseExecutor, OutputBusyError


class Process:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.stderr = Mock()
        self.stderr.read.return_value = ""

    def poll(self) -> None:
        return None


class Lock:
    def acquire(self) -> int:
        return 42

    def release(self) -> None:
        pass

    def __enter__(self) -> "Lock":
        return self

    def __exit__(self, *_: object) -> None:
        pass


class BusyLock:
    def __enter__(self) -> "BusyLock":
        raise OutputBusyError("busy")

    def __exit__(self, *_: object) -> None:
        pass


class PcDogTestTests(unittest.TestCase):
    def test_all_supported_commands_parse_and_read_only_commands_do_not_change_gpio(self) -> None:
        read_only = ("status", "inputs", "outputs")
        actions = ("power-on", "power-off", "reset-on", "reset-off", "all-on", "all-off")
        for command in read_only + actions:
            controls = Mock()
            with patch("pcdog_runtime.diagnostic_controls.os.geteuid", return_value=0), \
                 patch("pcdog_runtime.diagnostic_controls.DiagnosticControls", return_value=controls), \
                 patch("pcdog_runtime.diagnostic_controls.print_status") as status:
                main([command])
            if command in read_only:
                self.assertEqual(controls.method_calls, [])
                status.assert_called_once_with(command)
            else:
                getattr(controls, command.replace("-", "_"), Mock()).assert_called_once_with()
                status.assert_called_once_with("outputs")

    def test_invalid_arguments_and_non_root_fail_closed_before_gpio_action(self) -> None:
        with patch("pcdog_runtime.diagnostic_controls.os.geteuid", return_value=0):
            with self.assertRaises(SystemExit):
                main(["16"])
        with patch("pcdog_runtime.diagnostic_controls.os.geteuid", return_value=1000), \
             patch("pcdog_runtime.diagnostic_controls.DiagnosticControls") as controls:
            with self.assertRaises(SystemExit):
                main(["power-on"])
        controls.assert_not_called()

    def test_independent_controls_and_all_controls_use_only_active_high_fixed_lines(self) -> None:
        processes = [Process(101), Process(102)]
        popen = Mock(side_effect=processes)
        killed: list[int] = []
        with TemporaryDirectory() as directory:
            controls = DiagnosticControls(Path(directory), popen, lambda pid, _: killed.append(pid), lambda _: None, Lock, lambda _: True)  # type: ignore[arg-type]
            controls.power_on()
            controls.reset_on()
            controls.power_off()
            controls.reset_off()
        self.assertEqual([call.args[0] for call in popen.call_args_list], [
            ["gpioset", "--chip", "gpiochip0", "--consumer", DIAGNOSTIC_CONSUMER, "16=active"],
            ["gpioset", "--chip", "gpiochip0", "--consumer", DIAGNOSTIC_CONSUMER, "17=active"],
        ])
        self.assertEqual(killed, [101, 102])
        self.assertEqual(ControlPolarity.ACTIVE_HIGH.value, "active-high")

    def test_all_on_and_all_off_cover_both_fixed_lines(self) -> None:
        popen = Mock(side_effect=[Process(101), Process(102)])
        killed: list[int] = []
        with TemporaryDirectory() as directory:
            controls = DiagnosticControls(Path(directory), popen, lambda pid, _: killed.append(pid), lambda _: None, Lock, lambda _: True)  # type: ignore[arg-type]
            controls.all_on()
            controls.all_off()
        self.assertEqual(killed, [101, 102])
        self.assertEqual(len(popen.call_args_list), 2)

    def test_agent_refuses_output_when_diagnostic_owner_holds_lock(self) -> None:
        popen = Mock()
        with self.assertRaises(OutputBusyError):
            GpioPulseExecutor(ControlPolarity.ACTIVE_HIGH, popen, BusyLock).pulse(16, 200)
        popen.assert_not_called()

    def test_status_format_is_read_only_and_covers_only_requested_fixed_signals(self) -> None:
        output_completed = Mock(stdout="16 POWER output active\n17 RESET output inactive\n")
        input_completed = Mock(stdout="0 1\n")
        with patch("pcdog_runtime.diagnostic_controls.subprocess.run", side_effect=[output_completed, input_completed]) as run, \
             patch("builtins.print") as output:
            print_status("status")
        self.assertEqual(run.call_args_list[0].args[0], ["gpioinfo", "--chip", "gpiochip0", "16", "17"])
        self.assertEqual(run.call_args_list[1].args[0], ["gpioget", "--numeric", "--chip", "gpiochip0", "19", "20"])
        self.assertEqual(output.call_count, 4)

    def test_web_api_has_no_control_surface(self) -> None:
        source = (Path(__file__).parents[1] / "pcdog_runtime" / "web_api.py").read_text(encoding="utf-8")
        self.assertNotIn("pcdog-test", source)
        self.assertNotIn("power-on", source)
        self.assertNotIn("reset-on", source)


if __name__ == "__main__":
    unittest.main()
