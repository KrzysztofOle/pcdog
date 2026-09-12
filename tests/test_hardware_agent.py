"""Granica hardware-agent: tylko wejścia GPIO19/GPIO20, bez output."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from pcdog_runtime import EventStore, HddActivity, InputMonitor, InputMonitorConfig, InputReading, PcState, PowerLedState, StateEngine
from pcdog_runtime.hardware_agent import GpioInputReader, handle_request
from pcdog_runtime.hardware_agent_client import HardwareAgentInputSource
from pcdog_runtime.read_only_runtime import RuntimeInputMonitor


class Clock:
    def __init__(self) -> None:
        self.value = 0.0
    def __call__(self) -> float:
        return self.value


class HardwareAgentTests(unittest.TestCase):
    def test_gpio_reader_maps_hdd19_and_power20(self) -> None:
        completed = Mock(stdout="19=active 20=inactive\n")
        runner = Mock(return_value=completed)
        reading = GpioInputReader(runner).read()
        self.assertEqual(reading.hdd_activity, HddActivity.ACTIVE)
        self.assertEqual(reading.power_led, PowerLedState.OFF)
        self.assertTrue(reading.hdd_activity_reliable)
        runner.assert_called_once()
        self.assertEqual(runner.call_args.args[0], ["gpioget", "--numeric", "gpiochip0", "19", "20"])

    def test_gpio_failure_is_unknown_not_off(self) -> None:
        reading = GpioInputReader(Mock(side_effect=OSError())).read()
        self.assertEqual(reading.power_led, PowerLedState.UNKNOWN)
        self.assertFalse(reading.power_led_reliable)

    def test_closed_protocol_has_no_output_or_arbitrary_gpio_operation(self) -> None:
        reader = Mock()
        self.assertEqual(handle_request(b'{"operation":"set_gpio","gpio":16,"value":1}\n', reader), {"status": "ACTION_NOT_ENABLED"})
        self.assertEqual(handle_request(b'{"operation":"read_gpio","gpio":19}\n', reader), {"status": "ACTION_NOT_ENABLED"})
        self.assertEqual(handle_request(b'{"operation":"status"}\n', reader)["inputs"], ["hdd_led", "power_led"])
        reader.read.assert_not_called()

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
            def __init__(self) -> None: self.reading = 0
            def read(self) -> InputReading:
                self.reading += 1
                return InputReading(
                    PowerLedState.ON, True, HddActivity.ACTIVE if self.reading > 1 else HddActivity.IDLE, True)
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
