"""Model domenowy oraz bezpieczne warstwy runtime PcDog.

Pakiet nie wykonuje GPIO, sterowania PC ani działań systemd. Warstwy wejść są
obecnie symulowane, persistence używa standardowego SQLite, a HTTP pozostaje
wyłącznie lokalnie testowanym API read-only.
"""

from .inputs import FakeInputSource, InputReading, InputSource
from .input_monitor import InputMonitor, InputMonitorConfig
from .event_store import (
    EventStore,
    EventStoreError,
    StoredEvent,
    UnsupportedSchemaVersionError,
)
from .web_api import (
    ApiRequestError,
    PcDogApiServer,
    ReadOnlyApi,
    StaticHealthProvider,
    create_server,
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
    "ApiRequestError",
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
    "PcDogApiServer",
    "PcState",
    "PowerLedState",
    "ReadOnlyApi",
    "StateEngine",
    "StateSnapshot",
    "StateUpdate",
    "StaticHealthProvider",
    "StoredEvent",
    "UnsupportedSchemaVersionError",
    "create_server",
]
