"""Czysta logika przejść stanu PcDog."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from .inputs import InputReading, InputSource
from .models import (
    DomainEvent,
    EventSource,
    EventType,
    EventValue,
    PcDogState,
    PcState,
    PowerLedState,
    StateSnapshot,
)


Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class StateUpdate:
    """Wynik pojedynczego przetworzenia wejść."""

    snapshot: StateSnapshot
    events: tuple[DomainEvent, ...]


class StateEngine:
    """Wyznacza PC state wyłącznie z wiarygodnego POWER LED.

    Pierwszy odczyt ustanawia bazowy snapshot i nie tworzy zdarzeń, ponieważ
    nie istnieje jeszcze poprzedni zaobserwowany stan. Wszystkie kolejne
    zdarzenia opisują rzeczywistą zmianę pól domenowych.
    """

    def __init__(self, clock: Clock | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._current_snapshot: StateSnapshot | None = None

    @property
    def current_snapshot(self) -> StateSnapshot | None:
        return self._current_snapshot

    def process_next(
        self, source: InputSource, pcdog_state: PcDogState = PcDogState.HEALTHY
    ) -> StateUpdate:
        """Odczytuje dane z abstrakcyjnego źródła i przetwarza je."""

        return self.process(source.read(), pcdog_state=pcdog_state)

    def process(
        self, reading: InputReading, pcdog_state: PcDogState = PcDogState.HEALTHY
    ) -> StateUpdate:
        """Tworzy snapshot i zdarzenia różniące go od poprzedniego."""

        timestamp_utc = self._utc_timestamp(self._clock())
        snapshot = StateSnapshot(
            pc_state=self._pc_state_for(reading),
            power_led=reading.power_led,
            power_led_reliable=reading.power_led_reliable,
            hdd_activity=reading.hdd_activity,
            hdd_activity_reliable=reading.hdd_activity_reliable,
            pcdog_state=pcdog_state,
            timestamp_utc=timestamp_utc,
        )
        events = self._events_for_transition(self._current_snapshot, snapshot)
        self._current_snapshot = snapshot
        return StateUpdate(snapshot=snapshot, events=events)

    @staticmethod
    def _utc_timestamp(timestamp: datetime) -> datetime:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("StateEngine clock must return a timezone-aware datetime")
        return timestamp.astimezone(UTC)

    @staticmethod
    def _pc_state_for(reading: InputReading) -> PcState:
        if not reading.power_led_reliable:
            return PcState.UNKNOWN
        if reading.power_led is PowerLedState.ON:
            return PcState.ON
        if reading.power_led is PowerLedState.OFF:
            return PcState.OFF
        return PcState.UNKNOWN

    @staticmethod
    def _event(
        timestamp_utc: datetime,
        event_type: EventType,
        old_value: EventValue,
        new_value: EventValue,
    ) -> DomainEvent:
        return DomainEvent(
            timestamp_utc=timestamp_utc,
            event_type=event_type,
            source=EventSource.STATE_ENGINE,
            old_value=old_value,
            new_value=new_value,
        )

    def _events_for_transition(
        self, previous: StateSnapshot | None, current: StateSnapshot
    ) -> tuple[DomainEvent, ...]:
        if previous is None:
            return ()

        events: list[DomainEvent] = []
        if previous.power_led is not current.power_led:
            events.append(
                self._event(
                    current.timestamp_utc,
                    EventType.POWER_LED_CHANGED,
                    previous.power_led,
                    current.power_led,
                )
            )
        if previous.hdd_activity is not current.hdd_activity:
            events.append(
                self._event(
                    current.timestamp_utc,
                    EventType.HDD_ACTIVITY_CHANGED,
                    previous.hdd_activity,
                    current.hdd_activity,
                )
            )
        if previous.pc_state is not current.pc_state:
            events.append(
                self._event(
                    current.timestamp_utc,
                    EventType.PC_STATE_CHANGED,
                    previous.pc_state,
                    current.pc_state,
                )
            )
        return tuple(events)
