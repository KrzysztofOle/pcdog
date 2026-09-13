"""Jednorazowy, obserwowany test loopback przez semantyczne API hardware-agenta.

Ten moduł nie ma dostępu do GPIO. Wysyła dokładnie jedno ``pulse_power`` albo
``pulse_reset`` przez socket agenta i odczytuje tylko istniejące API wejściowe
w trakcie oczekiwania na odpowiedź.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import threading
import time
from typing import Callable, Sequence

from .hardware_agent import DEFAULT_SOCKET_PATH
from .hardware_agent_client import HardwareAgentControlClient, HardwareAgentInputSource
from .inputs import InputReading


@dataclass(frozen=True)
class LoopbackObservation:
    before: InputReading
    during: tuple[InputReading, ...]
    after: InputReading
    duration_ms: int


def _is_reliable(reading: InputReading) -> bool:
    return reading.hdd_activity_reliable and reading.power_led_reliable


def observe_one_pulse(
    pulse: Callable[[], int], input_source: HardwareAgentInputSource, *, sample_interval: float = 0.01,
) -> LoopbackObservation:
    """Wykonuje raz ``pulse`` i próbuje uchwycić surowe wejścia podczas niego."""

    before = input_source.read()
    if not _is_reliable(before):
        raise RuntimeError("Baseline wejść jest niewiarygodny; impuls nie został wykonany")

    result: dict[str, object] = {}

    def run_pulse() -> None:
        try:
            result["duration_ms"] = pulse()
        except BaseException as error:
            result["error"] = error

    worker = threading.Thread(target=run_pulse, daemon=True)
    worker.start()
    during: list[InputReading] = []
    while worker.is_alive():
        during.append(input_source.read())
        time.sleep(sample_interval)
    worker.join()
    if "error" in result:
        raise result["error"]  # type: ignore[misc]
    after = input_source.read()
    if not _is_reliable(after):
        raise RuntimeError("Odczyt końcowy wejść jest niewiarygodny")
    return LoopbackObservation(before, tuple(during), after, result["duration_ms"])  # type: ignore[arg-type]


def _reading_payload(reading: InputReading) -> dict[str, object]:
    return {
        "gpio19_power_monitor": reading.power_led.value,
        "gpio19_reliable": reading.power_led_reliable,
        "gpio20_hdd_monitor": reading.hdd_activity.value,
        "gpio20_reliable": reading.hdd_activity_reliable,
    }


def main(arguments: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="PcDog one-shot GPIO loopback observation")
    parser.add_argument("--channel", choices=("power", "reset"), required=True)
    parser.add_argument("--socket", type=Path, default=DEFAULT_SOCKET_PATH)
    arguments = parser.parse_args(arguments)

    source = HardwareAgentInputSource(arguments.socket, timeout=0.5)
    control = HardwareAgentControlClient(arguments.socket, timeout=2.0)
    pulse = control.pulse_power if arguments.channel == "power" else control.pulse_reset
    observation = observe_one_pulse(pulse, source)
    print(json.dumps({
        "channel": arguments.channel,
        "duration_ms": observation.duration_ms,
        "before": _reading_payload(observation.before),
        "during": [_reading_payload(reading) for reading in observation.during],
        "after": _reading_payload(observation.after),
    }, separators=(",", ":")))


if __name__ == "__main__":
    main()
