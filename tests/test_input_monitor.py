"""Testy deterministycznego Input Monitora bez GPIO i realnego czasu."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import unittest

from pcdog_runtime import (
    EventType,
    FakeInputSource,
    HddActivity,
    InputMonitor,
    InputMonitorConfig,
    InputReading,
    PcState,
    PowerLedState,
    StateEngine,
    StateUpdate,
)


class ManualClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, duration: timedelta) -> None:
        self.value += duration.total_seconds()


class UtcClock:
    def __init__(self, monotonic_clock: ManualClock) -> None:
        self._monotonic_clock = monotonic_clock

    def __call__(self) -> datetime:
        return datetime(2026, 9, 5, tzinfo=UTC) + timedelta(
            seconds=self._monotonic_clock()
        )


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


class InputMonitorTests(unittest.TestCase):
    debounce = timedelta(seconds=1)
    unreliable_timeout = timedelta(seconds=2)
    hdd_hold = timedelta(milliseconds=500)

    def monitor_for(self, readings: list[InputReading]) -> tuple[InputMonitor, ManualClock]:
        clock = ManualClock()
        engine = StateEngine(clock=UtcClock(clock))
        monitor = InputMonitor(
            source=FakeInputSource(readings),
            state_engine=engine,
            config=InputMonitorConfig(
                power_debounce=self.debounce,
                unreliable_power_timeout=self.unreliable_timeout,
                hdd_active_hold=self.hdd_hold,
            ),
            clock=clock,
        )
        return monitor, clock

    @staticmethod
    def poll_after(
        monitor: InputMonitor, clock: ManualClock, duration: timedelta
    ):
        clock.advance(duration)
        return monitor.poll_once()

    def test_stable_power_on(self) -> None:
        monitor, clock = self.monitor_for([reading(PowerLedState.ON)] * 2)
        self.assertEqual(monitor.poll_once().snapshot.pc_state, PcState.UNKNOWN)
        self.assertEqual(
            self.poll_after(monitor, clock, self.debounce).snapshot.pc_state,
            PcState.ON,
        )

    def test_stable_power_off(self) -> None:
        monitor, clock = self.monitor_for([reading(PowerLedState.OFF)] * 2)
        monitor.poll_once()
        self.assertEqual(
            self.poll_after(monitor, clock, self.debounce).snapshot.pc_state,
            PcState.OFF,
        )

    def test_short_power_glitch_is_ignored(self) -> None:
        monitor, clock = self.monitor_for(
            [
                reading(PowerLedState.ON),
                reading(PowerLedState.ON),
                reading(PowerLedState.OFF),
                reading(PowerLedState.ON),
                reading(PowerLedState.ON),
            ]
        )
        monitor.poll_once()
        self.poll_after(monitor, clock, self.debounce)
        clock.advance(timedelta(milliseconds=100))
        self.assertEqual(monitor.poll_once().events, ())
        clock.advance(timedelta(milliseconds=100))
        self.assertEqual(monitor.poll_once().events, ())
        update = self.poll_after(monitor, clock, self.debounce)
        self.assertEqual(update.snapshot.pc_state, PcState.ON)
        self.assertEqual(update.events, ())

    def test_stable_on_to_off_emits_only_stable_events(self) -> None:
        monitor, clock = self.monitor_for(
            [
                reading(PowerLedState.ON),
                reading(PowerLedState.ON),
                reading(PowerLedState.OFF),
                reading(PowerLedState.OFF),
            ]
        )
        monitor.poll_once()
        self.poll_after(monitor, clock, self.debounce)
        monitor.poll_once()
        update = self.poll_after(monitor, clock, self.debounce)
        self.assertEqual(update.snapshot.pc_state, PcState.OFF)
        self.assertEqual(
            [event.event_type for event in update.events],
            [EventType.POWER_LED_CHANGED, EventType.PC_STATE_CHANGED],
        )

    def test_stable_off_to_on_emits_only_stable_events(self) -> None:
        monitor, clock = self.monitor_for(
            [
                reading(PowerLedState.OFF),
                reading(PowerLedState.OFF),
                reading(PowerLedState.ON),
                reading(PowerLedState.ON),
            ]
        )
        monitor.poll_once()
        self.poll_after(monitor, clock, self.debounce)
        monitor.poll_once()
        update = self.poll_after(monitor, clock, self.debounce)
        self.assertEqual(update.snapshot.pc_state, PcState.ON)
        self.assertEqual(
            [event.event_type for event in update.events],
            [EventType.POWER_LED_CHANGED, EventType.PC_STATE_CHANGED],
        )

    def test_unreliable_power_is_not_off(self) -> None:
        monitor, clock = self.monitor_for(
            [
                reading(PowerLedState.ON),
                reading(PowerLedState.ON),
                reading(PowerLedState.OFF, power_reliable=False),
                reading(PowerLedState.OFF, power_reliable=False),
            ]
        )
        monitor.poll_once()
        self.poll_after(monitor, clock, self.debounce)
        monitor.poll_once()
        update = self.poll_after(monitor, clock, self.unreliable_timeout)
        self.assertEqual(update.snapshot.pc_state, PcState.UNKNOWN)
        self.assertNotEqual(update.snapshot.pc_state, PcState.OFF)

    def test_reliable_recovery_unknown_to_on(self) -> None:
        monitor, clock = self._monitor_from_unknown([reading(PowerLedState.ON)] * 2)
        monitor.poll_once()
        update = self.poll_after(monitor, clock, self.debounce)
        self.assertEqual(update.snapshot.pc_state, PcState.ON)
        self.assert_pc_state_event(update, PcState.UNKNOWN, PcState.ON)

    def test_reliable_recovery_unknown_to_off(self) -> None:
        monitor, clock = self._monitor_from_unknown([reading(PowerLedState.OFF)] * 2)
        monitor.poll_once()
        update = self.poll_after(monitor, clock, self.debounce)
        self.assertEqual(update.snapshot.pc_state, PcState.OFF)
        self.assert_pc_state_event(update, PcState.UNKNOWN, PcState.OFF)

    def test_hdd_activity_does_not_change_pc_state(self) -> None:
        monitor, clock = self.monitor_for(
            [
                reading(PowerLedState.ON, HddActivity.IDLE),
                reading(PowerLedState.ON, HddActivity.IDLE),
                reading(PowerLedState.ON, HddActivity.ACTIVE),
            ]
        )
        monitor.poll_once()
        self.poll_after(monitor, clock, self.debounce)
        update = monitor.poll_once()
        self.assertEqual(update.snapshot.pc_state, PcState.ON)
        self.assertEqual(
            [event.event_type for event in update.events],
            [EventType.HDD_ACTIVITY_CHANGED],
        )

    def test_short_hdd_impulse_is_held_then_returns_to_idle(self) -> None:
        monitor, clock = self.monitor_for(
            [
                reading(PowerLedState.ON, HddActivity.ACTIVE),
                reading(PowerLedState.ON, HddActivity.IDLE),
                reading(PowerLedState.ON, HddActivity.IDLE),
            ]
        )
        first = monitor.poll_once()
        self.assertEqual(first.snapshot.hdd_activity, HddActivity.ACTIVE)
        held = self.poll_after(monitor, clock, timedelta(milliseconds=100))
        self.assertEqual(held.snapshot.hdd_activity, HddActivity.ACTIVE)
        released = self.poll_after(monitor, clock, self.hdd_hold)
        self.assertEqual(released.snapshot.hdd_activity, HddActivity.IDLE)
        self.assertEqual(
            [event.event_type for event in released.events],
            [EventType.HDD_ACTIVITY_CHANGED],
        )

    def test_no_stable_change_means_no_domain_event(self) -> None:
        monitor, clock = self.monitor_for(
            [
                reading(PowerLedState.OFF),
                reading(PowerLedState.OFF),
                reading(PowerLedState.ON),
                reading(PowerLedState.OFF),
            ]
        )
        monitor.poll_once()
        self.poll_after(monitor, clock, self.debounce)
        monitor.poll_once()
        update = self.poll_after(monitor, clock, timedelta(milliseconds=100))
        self.assertEqual(update.events, ())

    def test_clock_is_deterministic(self) -> None:
        monitor, clock = self.monitor_for([reading(PowerLedState.ON)] * 3)
        monitor.poll_once()
        before_debounce = self.poll_after(
            monitor, clock, self.debounce - timedelta(milliseconds=1)
        )
        self.assertEqual(before_debounce.snapshot.pc_state, PcState.UNKNOWN)
        at_debounce = self.poll_after(monitor, clock, timedelta(milliseconds=1))
        self.assertEqual(at_debounce.snapshot.pc_state, PcState.ON)

    def _monitor_from_unknown(
        self, recovery_readings: list[InputReading]
    ) -> tuple[InputMonitor, ManualClock]:
        monitor, clock = self.monitor_for(
            [
                reading(PowerLedState.UNKNOWN, power_reliable=False),
                reading(PowerLedState.UNKNOWN, power_reliable=False),
                *recovery_readings,
            ]
        )
        monitor.poll_once()
        self.poll_after(monitor, clock, self.unreliable_timeout)
        return monitor, clock

    def assert_pc_state_event(
        self, update: StateUpdate, old: PcState, new: PcState
    ) -> None:
        events = [
            event
            for event in update.events
            if event.event_type is EventType.PC_STATE_CHANGED
        ]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].old_value, old)
        self.assertEqual(events[0].new_value, new)


if __name__ == "__main__":
    unittest.main()
