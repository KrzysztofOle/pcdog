"""Kontrakt root-only CLI pcdog-test, bez dostępu do prawdziwego GPIO."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import subprocess
import unittest
from unittest.mock import Mock, patch

from pcdog_runtime.diagnostic_controls import (
    DIAGNOSTIC_CONSUMER,
    DiagnosticControls,
    DiagnosticControlsError,
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
    def test_help_variants_return_zero_without_gpio_access(self) -> None:
        for command in ("help", "--help", "-h"):
            output = StringIO()
            with patch("pcdog_runtime.diagnostic_controls.DiagnosticControls") as controls, \
                 patch("pcdog_runtime.diagnostic_controls.subprocess.run") as run, \
                 redirect_stdout(output):
                self.assertIsNone(main([command]))
            self.assertIn("Usage:", output.getvalue())
            self.assertIn("GPIO17  POWER CONTROL", output.getvalue())
            self.assertIn("GPIO18  RESET CONTROL", output.getvalue())
            self.assertIn("GPIO19  POWER LED MONITOR", output.getvalue())
            self.assertIn("GPIO20  HDD LED MONITOR", output.getvalue())
            controls.assert_not_called()
            run.assert_not_called()

    def test_unknown_command_is_rejected_without_gpio_access(self) -> None:
        error = StringIO()
        with patch("pcdog_runtime.diagnostic_controls.DiagnosticControls") as controls, \
             redirect_stderr(error), self.assertRaises(SystemExit) as raised:
            main(["xyz"])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("Unknown command: xyz", error.getvalue())
        self.assertIn("Run: pcdog-test help", error.getvalue())
        controls.assert_not_called()

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
                main(["999"])
        with patch("pcdog_runtime.diagnostic_controls.os.geteuid", return_value=1000), \
             patch("pcdog_runtime.diagnostic_controls.DiagnosticControls") as controls:
            with self.assertRaises(SystemExit):
                main(["power-on"])
        controls.assert_not_called()

    def test_independent_controls_and_all_controls_use_only_active_high_fixed_lines(self) -> None:
        events: list[str] = []
        processes = iter([Process(101), Process(102)])
        popen = Mock(side_effect=lambda command, **_: events.append(f"active:{command[-1].split('=')[0]}") or next(processes))
        runner = Mock(side_effect=lambda command, **_: events.append(f"low:{command[2]}") or Mock())
        with TemporaryDirectory() as directory:
            controls = DiagnosticControls(
                Path(directory), popen, lambda pid, _: events.append(f"term:{pid}"), lambda _: None,
                Lock, lambda _: True, runner,
            )  # type: ignore[arg-type]
            controls.power_on()
            controls.reset_on()
            controls.power_off()
            controls.reset_off()
        self.assertEqual([call.args[0] for call in popen.call_args_list], [
            ["gpioset", "--chip", "gpiochip0", "--consumer", DIAGNOSTIC_CONSUMER, "17=active"],
            ["gpioset", "--chip", "gpiochip0", "--consumer", DIAGNOSTIC_CONSUMER, "18=active"],
        ])
        self.assertEqual(events, ["active:17", "active:18", "low:17", "term:101", "low:18", "term:102"])
        self.assertEqual(
            [call.args[0] for call in runner.call_args_list],
            [["pinctrl", "set", "17", "op", "dl"], ["pinctrl", "set", "18", "op", "dl"]],
        )
        self.assertEqual(ControlPolarity.ACTIVE_HIGH.value, "active-high")

    def test_all_off_sets_both_lines_inactive_before_releasing_either_owner(self) -> None:
        events: list[str] = []
        processes = iter([Process(101), Process(102)])
        popen = Mock(side_effect=lambda command, **_: events.append(f"active:{command[-1].split('=')[0]}") or next(processes))
        runner = Mock(side_effect=lambda command, **_: events.append(f"low:{command[2]}") or Mock())
        with TemporaryDirectory() as directory:
            controls = DiagnosticControls(
                Path(directory), popen, lambda pid, _: events.append(f"term:{pid}"), lambda _: None,
                Lock, lambda _: True, runner,
            )  # type: ignore[arg-type]
            controls.all_on()
            controls.all_off()
        self.assertEqual(events, ["active:17", "active:18", "low:17", "low:18", "term:101", "term:102"])
        self.assertEqual(len(popen.call_args_list), 2)

    def test_failed_inactive_transition_does_not_release_active_owner(self) -> None:
        process = Process(101)
        popen = Mock(return_value=process)
        killed: list[int] = []
        runner = Mock(side_effect=subprocess.CalledProcessError(1, ["pinctrl", "set", "17", "op", "dl"]))
        with TemporaryDirectory() as directory:
            state_directory = Path(directory)
            controls = DiagnosticControls(
                state_directory, popen, lambda pid, _: killed.append(pid), lambda _: None,
                Lock, lambda _: True, runner,
            )  # type: ignore[arg-type]
            controls.power_on()
            with self.assertRaises(DiagnosticControlsError):
                controls.power_off()
            self.assertTrue((state_directory / "gpio17.pid").exists())
        self.assertEqual(killed, [])

    def test_agent_refuses_output_when_diagnostic_owner_holds_lock(self) -> None:
        popen = Mock()
        with self.assertRaises(OutputBusyError):
            GpioPulseExecutor(ControlPolarity.ACTIVE_HIGH, popen, BusyLock).pulse(17, 200)
        popen.assert_not_called()

    def test_status_format_is_read_only_and_covers_only_requested_fixed_signals(self) -> None:
        output_completed = Mock(stdout="17 POWER output active\n18 RESET output inactive\n")
        input_completed = Mock(stdout="20=active 19=inactive\n")
        with patch("pcdog_runtime.diagnostic_controls.subprocess.run", side_effect=[output_completed, input_completed]) as run, \
             patch("builtins.print") as output:
            print_status("status")
        self.assertEqual(run.call_args_list[0].args[0], ["gpioinfo", "--chip", "gpiochip0", "17", "18"])
        self.assertEqual(run.call_args_list[1].args[0], ["gpioget", "--numeric", "--chip", "gpiochip0", "20", "19"])
        self.assertEqual(output.call_count, 4)
        self.assertEqual(
            [call.args[0] for call in output.call_args_list],
            [
                "POWER_CONTROL   GPIO17  HIGH",
                "RESET_CONTROL   GPIO18  LOW",
                "HDD_MONITOR     GPIO20  HIGH",
                "POWER_MONITOR   GPIO19  LOW",
            ],
        )

    def test_web_api_has_no_control_surface(self) -> None:
        source = (Path(__file__).parents[1] / "pcdog_runtime" / "web_api.py").read_text(encoding="utf-8")
        self.assertNotIn("pcdog-test", source)
        self.assertNotIn("power-on", source)
        self.assertNotIn("reset-on", source)


if __name__ == "__main__":
    unittest.main()
