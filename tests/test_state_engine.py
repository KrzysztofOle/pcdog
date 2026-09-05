"""Testy czystego State Engine; nie wymagają systemu ani sprzętu."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import unittest

from pcdog_runtime import (
    EventType,
    FakeInputSource,
    HddActivity,
    InputReading,
    PcState,
    PowerLedState,
    StateEngine,
    StateUpdate,
)


class IncrementingClock:
    def __init__(self) -> None:
        self._value = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        value = self._value
        self._value += timedelta(seconds=1)
        return value


def reading(
    power_led: PowerLedState,
    hdd_activity: HddActivity = HddActivity.IDLE,
    *,
    power_reliable: bool = True,
    hdd_reliable: bool = True,
) -> InputReading:
    return InputReading(
        power_led=power_led,
        power_led_reliable=power_reliable,
        hdd_activity=hdd_activity,
        hdd_activity_reliable=hdd_reliable,
    )


class StateEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = StateEngine(clock=IncrementingClock())

    def establish(self, input_reading: InputReading) -> None:
        self.assertEqual(self.engine.process(input_reading).events, ())

    def test_power_on_means_pc_on(self) -> None:
        update = self.engine.process(reading(PowerLedState.ON))
        self.assertEqual(update.snapshot.pc_state, PcState.ON)

    def test_power_off_means_pc_off(self) -> None:
        update = self.engine.process(reading(PowerLedState.OFF))
        self.assertEqual(update.snapshot.pc_state, PcState.OFF)

    def test_unreliable_power_means_pc_unknown(self) -> None:
        update = self.engine.process(
            reading(PowerLedState.ON, power_reliable=False)
        )
        self.assertEqual(update.snapshot.pc_state, PcState.UNKNOWN)

    def test_unknown_power_led_means_pc_unknown(self) -> None:
        update = self.engine.process(reading(PowerLedState.UNKNOWN))
        self.assertEqual(update.snapshot.pc_state, PcState.UNKNOWN)

    def test_hdd_activity_does_not_change_pc_state(self) -> None:
        self.establish(reading(PowerLedState.ON, HddActivity.IDLE))
        update = self.engine.process(reading(PowerLedState.ON, HddActivity.ACTIVE))
        self.assertEqual(update.snapshot.pc_state, PcState.ON)
        self.assertEqual(
            [event.event_type for event in update.events],
            [EventType.HDD_ACTIVITY_CHANGED],
        )

    def test_unknown_to_on(self) -> None:
        self.establish(reading(PowerLedState.UNKNOWN, power_reliable=False))
        update = self.engine.process(reading(PowerLedState.ON))
        self.assert_transition(update, PcState.UNKNOWN, PcState.ON)

    def test_unknown_to_off(self) -> None:
        self.establish(reading(PowerLedState.UNKNOWN, power_reliable=False))
        update = self.engine.process(reading(PowerLedState.OFF))
        self.assert_transition(update, PcState.UNKNOWN, PcState.OFF)

    def test_off_to_on(self) -> None:
        self.establish(reading(PowerLedState.OFF))
        update = self.engine.process(reading(PowerLedState.ON))
        self.assert_transition(update, PcState.OFF, PcState.ON)

    def test_on_to_off(self) -> None:
        self.establish(reading(PowerLedState.ON))
        update = self.engine.process(reading(PowerLedState.OFF))
        self.assert_transition(update, PcState.ON, PcState.OFF)

    def test_on_to_unknown(self) -> None:
        self.establish(reading(PowerLedState.ON))
        update = self.engine.process(
            reading(PowerLedState.UNKNOWN, power_reliable=False)
        )
        self.assert_transition(update, PcState.ON, PcState.UNKNOWN)

    def test_off_to_unknown(self) -> None:
        self.establish(reading(PowerLedState.OFF))
        update = self.engine.process(
            reading(PowerLedState.UNKNOWN, power_reliable=False)
        )
        self.assert_transition(update, PcState.OFF, PcState.UNKNOWN)

    def test_identical_snapshot_does_not_emit_events(self) -> None:
        input_reading = reading(PowerLedState.ON, HddActivity.ACTIVE)
        self.establish(input_reading)
        self.assertEqual(self.engine.process(input_reading).events, ())

    def test_hdd_change_emits_hdd_event(self) -> None:
        self.establish(reading(PowerLedState.OFF, HddActivity.IDLE))
        update = self.engine.process(reading(PowerLedState.OFF, HddActivity.ACTIVE))
        self.assertEqual(len(update.events), 1)
        event = update.events[0]
        self.assertEqual(event.event_type, EventType.HDD_ACTIVITY_CHANGED)
        self.assertEqual(event.old_value, HddActivity.IDLE)
        self.assertEqual(event.new_value, HddActivity.ACTIVE)

    def test_timestamps_are_utc(self) -> None:
        update = self.engine.process(reading(PowerLedState.ON))
        self.assertEqual(update.snapshot.timestamp_utc.tzinfo, UTC)
        self.assertEqual(update.snapshot.timestamp_utc.utcoffset(), timedelta(0))

    def test_fake_input_source_is_deterministic(self) -> None:
        source = FakeInputSource(
            [reading(PowerLedState.OFF), reading(PowerLedState.ON)]
        )
        self.assertEqual(
            self.engine.process_next(source).snapshot.pc_state, PcState.OFF
        )
        self.assertEqual(
            self.engine.process_next(source).snapshot.pc_state, PcState.ON
        )
        with self.assertRaises(StopIteration):
            source.read()

    def assert_transition(
        self, update: StateUpdate, old_state: PcState, new_state: PcState
    ) -> None:
        events = [
            event
            for event in update.events
            if event.event_type is EventType.PC_STATE_CHANGED
        ]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].old_value, old_state)
        self.assertEqual(events[0].new_value, new_state)


if __name__ == "__main__":
    unittest.main()
