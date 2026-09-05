"""Typy domenowe niezależne od infrastruktury PcDog."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Mapping, TypeAlias


class PcState(str, Enum):
    """Stan komputera wyznaczany przez wiarygodny sygnał POWER LED."""

    OFF = "OFF"
    ON = "ON"
    UNKNOWN = "UNKNOWN"


class PcDogState(str, Enum):
    """Stan zdrowia samego runtime PcDog."""

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    ERROR = "ERROR"


class PowerLedState(str, Enum):
    """Odczyt POWER LED, zanim State Engine oceni jego wiarygodność."""

    OFF = "OFF"
    ON = "ON"
    UNKNOWN = "UNKNOWN"


class HddActivity(str, Enum):
    """Pomocnicza aktywność HDD LED; nie wyznacza stanu PC."""

    IDLE = "IDLE"
    ACTIVE = "ACTIVE"
    UNKNOWN = "UNKNOWN"


class EventType(str, Enum):
    PC_STATE_CHANGED = "PC_STATE_CHANGED"
    POWER_LED_CHANGED = "POWER_LED_CHANGED"
    HDD_ACTIVITY_CHANGED = "HDD_ACTIVITY_CHANGED"


class EventSource(str, Enum):
    STATE_ENGINE = "STATE_ENGINE"


EventValue: TypeAlias = PcState | PowerLedState | HddActivity


@dataclass(frozen=True, slots=True)
class StateSnapshot:
    """Bieżący, nietrwały snapshot stanu domenowego."""

    pc_state: PcState
    power_led: PowerLedState
    power_led_reliable: bool
    hdd_activity: HddActivity
    hdd_activity_reliable: bool
    pcdog_state: PcDogState
    timestamp_utc: datetime


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """Zdarzenie gotowe do zapisania przez przyszły Event Store."""

    timestamp_utc: datetime
    event_type: EventType
    source: EventSource
    old_value: EventValue
    new_value: EventValue
    details: Mapping[str, object] | None = None
