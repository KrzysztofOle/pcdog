"""Czysty model domenowy i State Engine dla PcDog.

Pakiet nie wykonuje operacji wejścia/wyjścia: nie zna GPIO, SQLite, sieci ani
systemd. Adaptery tych warstw będą dodawane w osobnych etapach.
"""

from .inputs import FakeInputSource, InputReading, InputSource
from .input_monitor import InputMonitor, InputMonitorConfig
from .event_store import (
    EventStore,
    EventStoreError,
    StoredEvent,
    UnsupportedSchemaVersionError,
)
from .models import (
    DomainEvent,
    EventSource,
    EventType,
    HddActivity,
    PcDogState,
    PcState,
    PowerLedState,
    StateSnapshot,
)
from .state_engine import StateEngine, StateUpdate

__all__ = [
    "DomainEvent",
    "EventSource",
    "EventStore",
    "EventStoreError",
    "EventType",
    "FakeInputSource",
    "HddActivity",
    "InputMonitor",
    "InputMonitorConfig",
    "InputReading",
    "InputSource",
    "PcDogState",
    "PcState",
    "PowerLedState",
    "StateEngine",
    "StateSnapshot",
    "StateUpdate",
    "StoredEvent",
    "UnsupportedSchemaVersionError",
]
