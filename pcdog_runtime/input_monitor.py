"""Deterministyczna stabilizacja abstrakcyjnych wejść PcDog."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from time import monotonic

from .inputs import InputReading, InputSource
from .models import HddActivity, PcDogState, PowerLedState
from .state_engine import StateEngine, StateUpdate


MonotonicClock = Callable[[], float]
_PowerReading = tuple[PowerLedState, bool]


@dataclass(frozen=True, slots=True)
class InputMonitorConfig:
    """Jawne, niezależne od sprzętu parametry stabilizacji wejść."""

    power_debounce: timedelta
    unreliable_power_timeout: timedelta
    hdd_active_hold: timedelta

    def __post_init__(self) -> None:
        if self.power_debounce <= timedelta(0):
            raise ValueError("power_debounce must be greater than zero")
        if self.unreliable_power_timeout < timedelta(0):
            raise ValueError("unreliable_power_timeout must not be negative")
        if self.hdd_active_hold <= timedelta(0):
            raise ValueError("hdd_active_hold must be greater than zero")


class InputMonitor:
    """Pobiera wejścia, stabilizuje je i przekazuje do State Engine.

    POWER LED jest debouncowany czasowo. Utrata jego wiarygodności zachowuje
    ostatni stabilny stan tylko do ``unreliable_power_timeout``, po czym
    przekazywany jest ``UNKNOWN``. HDD używa polityki hold: wiarygodny impuls
    ``ACTIVE`` jest widoczny od razu i pozostaje aktywny przez skonfigurowany
    minimalny czas, aby pojedyncze impulsy były obserwowalne.
    """

    def __init__(
        self,
        source: InputSource,
        state_engine: StateEngine,
        config: InputMonitorConfig,
        clock: MonotonicClock | None = None,
    ) -> None:
        self._source = source
        self._state_engine = state_engine
        self._config = config
        self._clock = clock or monotonic

        self._stable_power: _PowerReading = (PowerLedState.UNKNOWN, False)
        self._power_candidate: _PowerReading | None = None
        self._power_candidate_since: float | None = None

        self._stable_hdd = HddActivity.UNKNOWN
        self._stable_hdd_reliable = False
        self._last_hdd_active_at: float | None = None

    def poll_once(
        self, pcdog_state: PcDogState = PcDogState.HEALTHY
    ) -> StateUpdate:
        """Przetwarza pojedynczy odczyt bez blokowania ani używania sleep."""

        now = self._clock()
        reading = self._source.read()
        power_led, power_led_reliable = self._stabilize_power(reading, now)
        hdd_activity, hdd_activity_reliable = self._stabilize_hdd(reading, now)
        return self._state_engine.process(
            InputReading(
                power_led=power_led,
                power_led_reliable=power_led_reliable,
                hdd_activity=hdd_activity,
                hdd_activity_reliable=hdd_activity_reliable,
            ),
            pcdog_state=pcdog_state,
        )

    def _stabilize_power(self, reading: InputReading, now: float) -> _PowerReading:
        desired = self._desired_power(reading)
        if desired == self._stable_power:
            self._power_candidate = None
            self._power_candidate_since = None
            return self._stable_power

        if desired != self._power_candidate:
            self._power_candidate = desired
            self._power_candidate_since = now

        assert self._power_candidate_since is not None
        if now - self._power_candidate_since >= self._power_wait_seconds(desired):
            self._stable_power = desired
            self._power_candidate = None
            self._power_candidate_since = None
        return self._stable_power

    @staticmethod
    def _desired_power(reading: InputReading) -> _PowerReading:
        if not reading.power_led_reliable:
            return (PowerLedState.UNKNOWN, False)
        return (reading.power_led, True)

    def _power_wait_seconds(self, desired: _PowerReading) -> float:
        duration = (
            self._config.unreliable_power_timeout
            if not desired[1]
            else self._config.power_debounce
        )
        return duration.total_seconds()

    def _stabilize_hdd(
        self, reading: InputReading, now: float
    ) -> tuple[HddActivity, bool]:
        if not reading.hdd_activity_reliable:
            self._stable_hdd = HddActivity.UNKNOWN
            self._stable_hdd_reliable = False
            self._last_hdd_active_at = None
            return self._stable_hdd, self._stable_hdd_reliable

        if reading.hdd_activity is HddActivity.ACTIVE:
            self._stable_hdd = HddActivity.ACTIVE
            self._stable_hdd_reliable = True
            self._last_hdd_active_at = now
            return self._stable_hdd, self._stable_hdd_reliable

        if reading.hdd_activity is HddActivity.UNKNOWN:
            self._stable_hdd = HddActivity.UNKNOWN
            self._stable_hdd_reliable = True
            self._last_hdd_active_at = None
            return self._stable_hdd, self._stable_hdd_reliable

        if (
            self._stable_hdd is HddActivity.ACTIVE
            and self._last_hdd_active_at is not None
            and now - self._last_hdd_active_at
            < self._config.hdd_active_hold.total_seconds()
        ):
            return self._stable_hdd, self._stable_hdd_reliable

        self._stable_hdd = HddActivity.IDLE
        self._stable_hdd_reliable = True
        self._last_hdd_active_at = None
        return self._stable_hdd, self._stable_hdd_reliable
