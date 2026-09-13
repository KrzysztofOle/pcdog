"""Granica hardware-agent: wejścia i ograniczone, semantyczne impulsy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import socket
import subprocess
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import Mock

from pcdog_runtime import EventStore, HddActivity, InputMonitor, InputMonitorConfig, InputReading, PcState, PowerLedState, StateEngine
from pcdog_runtime.hardware_agent import (
    ControlPolarity,
    DEFAULT_PULSE_DURATION_MS,
    GpioInputReader,
    GpioPulseExecutor,
    HDD_LED_GPIO,
    OutputBusyError,
    POWER_CONTROL_GPIO,
    POWER_LED_GPIO,
    PulseController,
    PulseError,
    RESET_CONTROL_GPIO,
    create_server,
    handle_request,
)
from pcdog_runtime.diagnostic_controls import (
    DIAGNOSTIC_CONSUMER,
    DiagnosticControls,
    DiagnosticControlsError,
)
from pcdog_runtime.hardware_agent_client import HardwareAgentInputSource
from pcdog_runtime.hardware_loopback import observe_one_pulse
from pcdog_runtime.read_only_runtime import RuntimeInputMonitor


class Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    def pulse(self, gpio: int, duration_ms: int) -> None:
        self.calls.append((gpio, duration_ms))


class BlockingExecutor(RecordingExecutor):
    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.completed = threading.Event()

    def pulse(self, gpio: int, duration_ms: int) -> None:
        super().pulse(gpio, duration_ms)
        self.entered.set()
        self.release.wait(1.0)
        self.completed.set()


class DiagnosticProcess:
    def __init__(self, pid: int, returncode: int | None = None, stderr: str = "") -> None:
        self.pid = pid
        self.returncode = returncode
        self.stderr = Mock()
        self.stderr.read.return_value = stderr

    def poll(self) -> int | None:
        return self.returncode


class FakeOutputLock:
    def acquire(self) -> int:
        return 42

    def release(self) -> None:
        pass

    def __enter__(self) -> "FakeOutputLock":
        return self

    def __exit__(self, *_: object) -> None:
        pass


class HardwareAgentTests(unittest.TestCase):
    def test_systemd_unit_limits_gpio_device_and_no_arbitrary_command(self) -> None:
        unit = (Path(__file__).parents[1] / "systemd" / "pcdog-hardware-agent.service").read_text()
        source = (Path(__file__).parents[1] / "pcdog_runtime" / "hardware_agent.py").read_text()
        self.assertIn("DevicePolicy=closed", unit)
        self.assertIn("DeviceAllow=/dev/gpiochip0 rw", unit)
        self.assertNotIn("set_gpio", source)
        self.assertNotIn("read_gpio", source)
        self.assertNotIn("gpio=", source)

    def test_confirmed_gpio_mapping_covers_all_four_signals(self) -> None:
        self.assertEqual(POWER_CONTROL_GPIO, 17)
        self.assertEqual(RESET_CONTROL_GPIO, 18)
        self.assertEqual(POWER_LED_GPIO, 19)
        self.assertEqual(HDD_LED_GPIO, 20)

    def test_gpio_reader_maps_power19_and_hdd20(self) -> None:
        completed = Mock(stdout="20=active 19=inactive\n")
        runner = Mock(return_value=completed)
        reading = GpioInputReader(runner).read()
        self.assertEqual(reading.hdd_activity, HddActivity.ACTIVE)
        self.assertEqual(reading.power_led, PowerLedState.OFF)
        self.assertTrue(reading.hdd_activity_reliable)
        self.assertEqual(
            runner.call_args.args[0],
            ["gpioget", "--numeric", "--active-low", "--bias", "pull-up", "--chip", "gpiochip0", "20", "19"],
        )

    def test_open_collector_input_configuration_is_active_low_with_pull_up(self) -> None:
        unit = (Path(__file__).parents[1] / "systemd" / "pcdog-hardware-agent.service").read_text()
        self.assertIn("ExecStartPre=/usr/bin/pinctrl set 19 ip pu", unit)
        self.assertIn("ExecStartPre=/usr/bin/pinctrl set 20 ip pu", unit)
        completed = Mock(stdout="20=active 19=inactive\n")
        reading = GpioInputReader(Mock(return_value=completed)).read()
        self.assertEqual(reading.hdd_activity, HddActivity.ACTIVE)
        self.assertEqual(reading.power_led, PowerLedState.OFF)

    def test_gpio_reader_accepts_libgpiod_v2_numeric_output(self) -> None:
        self.assertEqual(GpioInputReader._parse_values("0 1\n"), (False, True))

    def test_gpio_failure_is_unknown_not_off(self) -> None:
        reading = GpioInputReader(Mock(side_effect=OSError())).read()
        self.assertEqual(reading.power_led, PowerLedState.UNKNOWN)
        self.assertFalse(reading.power_led_reliable)

    def test_default_startup_has_no_enabled_output_and_read_inputs_is_unchanged(self) -> None:
        reader = Mock()
        reader.read.return_value = InputReading(PowerLedState.OFF, True, HddActivity.IDLE, True)
        status = handle_request(b'{"operation":"status"}\n', reader)
        self.assertEqual(status["controls"], [])
        response = handle_request(b'{"operation":"read_inputs"}\n', reader)
        self.assertEqual(response["status"], "READY")
        self.assertEqual(response["power_led"], "OFF")
        self.assertEqual(response["hdd_activity"], "IDLE")

    def test_closed_protocol_has_no_arbitrary_gpio_operation(self) -> None:
        reader = Mock()
        for request in (
            b'{"operation":"set_gpio","gpio":999,"value":1}\n',
            b'{"operation":"read_gpio","gpio":19}\n',
            b'{"operation":"pulse_power","gpio":999}\n',
        ):
            self.assertIn(handle_request(request, reader)["status"], {"ACTION_NOT_ENABLED", "INVALID_REQUEST"})
        reader.read.assert_not_called()

    def test_diagnostic_controls_are_local_only_and_fixed_to_active_high_gpio17_gpio18(self) -> None:
        processes = [DiagnosticProcess(101), DiagnosticProcess(102)]
        popen = Mock(side_effect=processes)
        killed: list[tuple[int, int]] = []
        runner = Mock(return_value=Mock())
        with TemporaryDirectory() as directory:
            controls = DiagnosticControls(Path(directory) / "state", popen, lambda pid, sig: killed.append((pid, sig)), lambda _: None, FakeOutputLock, lambda _: True, runner)  # type: ignore[arg-type]
            controls.on()
            self.assertEqual(
                [call.args[0] for call in popen.call_args_list],
                [
                    ["gpioset", "--chip", "gpiochip0", "--consumer", DIAGNOSTIC_CONSUMER, "17=active"],
                    ["gpioset", "--chip", "gpiochip0", "--consumer", DIAGNOSTIC_CONSUMER, "18=active"],
                ],
            )
            controls.off()
        self.assertEqual([pid for pid, _ in killed], [101, 102])

    def test_diagnostic_start_failure_releases_already_started_channel(self) -> None:
        popen = Mock(side_effect=[DiagnosticProcess(101), DiagnosticProcess(102, returncode=1, stderr="busy")])
        killed: list[int] = []
        runner = Mock(return_value=Mock())
        with TemporaryDirectory() as directory:
            controls = DiagnosticControls(Path(directory) / "state", popen, lambda pid, _: killed.append(pid), lambda _: None, FakeOutputLock, lambda _: True, runner)  # type: ignore[arg-type]
            with self.assertRaises(DiagnosticControlsError):
                controls.on()
        self.assertEqual(killed, [101])

    def test_power_and_reset_pulses_use_only_fixed_lines_and_default_duration(self) -> None:
        executor = RecordingExecutor()
        controller = PulseController(executor)  # type: ignore[arg-type]
        self.assertEqual(controller.pulse_power(), DEFAULT_PULSE_DURATION_MS)
        self.assertEqual(controller.pulse_reset(75), 75)
        self.assertEqual(executor.calls, [(POWER_CONTROL_GPIO, DEFAULT_PULSE_DURATION_MS), (RESET_CONTROL_GPIO, 75)])

    def test_gpioset_command_transitions_active_to_inactive_then_releases(self) -> None:
        process = Mock(returncode=0)
        process.communicate.return_value = ("", "")
        popen = Mock(return_value=process)
        GpioPulseExecutor(ControlPolarity.ACTIVE_HIGH, popen, FakeOutputLock).pulse(POWER_CONTROL_GPIO, 200)
        self.assertEqual(
            popen.call_args.args[0],
            ["gpioset", "--chip", "gpiochip0", "--consumer", "pcdog-hardware-agent", "--toggle", "200ms,0", "17=active"],
        )
        self.assertEqual(popen.call_args.kwargs["stdout"], subprocess.PIPE)

    def test_active_low_polarity_is_explicit_in_gpioset_command(self) -> None:
        process = Mock(returncode=0)
        process.communicate.return_value = ("", "")
        popen = Mock(return_value=process)
        GpioPulseExecutor(ControlPolarity.ACTIVE_LOW, popen, FakeOutputLock).pulse(RESET_CONTROL_GPIO, 200)
        self.assertIn("--active-low", popen.call_args.args[0])
        self.assertIn("18=active", popen.call_args.args[0])

    def test_timeout_or_exception_terminates_gpio_owner_and_reports_failure(self) -> None:
        process = Mock()
        process.communicate.side_effect = [subprocess.TimeoutExpired("gpioset", 1), ("", "")]
        popen = Mock(return_value=process)
        with self.assertRaises(PulseError):
            GpioPulseExecutor(ControlPolarity.ACTIVE_HIGH, popen, FakeOutputLock).pulse(POWER_CONTROL_GPIO, 50)
        process.terminate.assert_called_once()

    def test_invalid_duration_fails_closed_without_gpio_action(self) -> None:
        executor = RecordingExecutor()
        controller = PulseController(executor)  # type: ignore[arg-type]
        reader = Mock()
        for duration in (0, 49, 501, -1, True, "200"):
            response = handle_request((json.dumps({"operation": "pulse_power", "duration_ms": duration}) + "\n").encode(), reader, controller)
            self.assertEqual(response, {"status": "PULSE_DURATION_NOT_ALLOWED"})
        self.assertEqual(executor.calls, [])

    def test_simultaneous_power_and_reset_is_rejected(self) -> None:
        executor = BlockingExecutor()
        controller = PulseController(executor)  # type: ignore[arg-type]
        worker = threading.Thread(target=controller.pulse_power)
        worker.start()
        self.assertTrue(executor.entered.wait(1.0))
        with self.assertRaises(OutputBusyError):
            controller.pulse_reset()
        executor.release.set()
        worker.join(1.0)
        self.assertEqual(executor.calls, [(POWER_CONTROL_GPIO, DEFAULT_PULSE_DURATION_MS)])

    def test_client_ipc_disconnect_does_not_cancel_or_extend_pulse(self) -> None:
        executor = BlockingExecutor()
        reader = Mock()
        with TemporaryDirectory() as directory:
            socket_path = Path(directory) / "agent.sock"
            server = create_server(socket_path, reader, PulseController(executor))  # type: ignore[arg-type]
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                    connection.connect(str(socket_path))
                    connection.sendall(b'{"operation":"pulse_power"}\n')
                self.assertTrue(executor.entered.wait(1.0))
                executor.release.set()
                self.assertTrue(executor.completed.wait(1.0))
                self.assertEqual(executor.calls, [(POWER_CONTROL_GPIO, DEFAULT_PULSE_DURATION_MS)])
            finally:
                server.shutdown()
                server.server_close()
                server_thread.join(1.0)

    def test_loopback_observer_uses_one_semantic_pulse_and_captures_during_reading(self) -> None:
        class Source:
            def __init__(self) -> None:
                self.count = 0

            def read(self) -> InputReading:
                self.count += 1
                activity = HddActivity.ACTIVE if self.count == 2 else HddActivity.IDLE
                return InputReading(PowerLedState.OFF, True, activity, True)

        calls: list[str] = []

        def pulse() -> int:
            calls.append("power")
            time.sleep(.02)
            return DEFAULT_PULSE_DURATION_MS

        observation = observe_one_pulse(pulse, Source(), sample_interval=.001)  # type: ignore[arg-type]
        self.assertEqual(calls, ["power"])
        self.assertEqual(observation.before.hdd_activity, HddActivity.IDLE)
        self.assertIn(HddActivity.ACTIVE, [reading.hdd_activity for reading in observation.during])
        self.assertEqual(observation.after.hdd_activity, HddActivity.IDLE)

    def test_missing_agent_and_reappearance_are_safe(self) -> None:
        with TemporaryDirectory() as directory:
            source = HardwareAgentInputSource(Path(directory) / "missing.sock")
            self.assertFalse(source.read().power_led_reliable)
            valid = {"status": "READY", "protocol_version": 1, "power_led": "ON", "power_led_reliable": True, "hdd_activity": "ACTIVE", "hdd_activity_reliable": True}
            recovered = source._parse_response(valid)
            self.assertEqual(recovered.power_led, PowerLedState.ON)
            self.assertEqual(recovered.hdd_activity, HddActivity.ACTIVE)

    def test_runtime_monitor_persists_events_and_restart_keeps_history(self) -> None:
        class Source:
            def __init__(self) -> None:
                self.reading = 0

            def read(self) -> InputReading:
                self.reading += 1
                return InputReading(PowerLedState.ON, True, HddActivity.ACTIVE if self.reading > 1 else HddActivity.IDLE, True)

        with TemporaryDirectory() as directory:
            database = Path(directory) / "pcdog.sqlite3"
            clock = Clock()
            monitor = InputMonitor(Source(), StateEngine(clock=lambda: datetime(2026, 1, 1, tzinfo=UTC)), InputMonitorConfig(timedelta(milliseconds=1), timedelta(0), timedelta(milliseconds=1)), clock)
            with EventStore(database) as store:
                runtime_monitor = RuntimeInputMonitor(database, Mock())
                runtime_monitor.poll_once(monitor, store)
                clock.value = .01
                runtime_monitor.poll_once(monitor, store)
                self.assertEqual(store.read_current_state().pc_state, PcState.ON)
                self.assertEqual([event.event.event_type.value for event in store.read_recent_events()], ["POWER_LED_CHANGED", "HDD_ACTIVITY_CHANGED", "PC_STATE_CHANGED"])
            with EventStore(database, read_only=True) as reopened:
                self.assertEqual(len(reopened.read_recent_events()), 3)


if __name__ == "__main__":
    unittest.main()
