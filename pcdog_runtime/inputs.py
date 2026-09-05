"""Abstrakcje danych wejściowych bez zależności od GPIO."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

from .models import HddActivity, PowerLedState


@dataclass(frozen=True, slots=True)
class InputReading:
    """Odczyt wejść oraz niezależna ocena jego wiarygodności.

    Niewiarygodny albo niedostępny POWER LED nie może wyznaczać ``PcState``.
    """

    power_led: PowerLedState
    power_led_reliable: bool
    hdd_activity: HddActivity
    hdd_activity_reliable: bool


class InputSource(Protocol):
    """Źródło kolejnych odczytów wejść, niezależne od ich transportu."""

    def read(self) -> InputReading:
        """Zwraca kolejny odczyt wejść."""


class FakeInputSource:
    """Deterministyczne źródło testowe zwracające zadaną sekwencję odczytów."""

    def __init__(self, readings: Iterable[InputReading]) -> None:
        self._readings = iter(readings)

    def read(self) -> InputReading:
        return next(self._readings)
