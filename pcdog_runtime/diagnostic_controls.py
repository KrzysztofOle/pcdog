"""Lokalne, root-only podtrzymanie dwóch wyjść diagnostycznych PcDog.

To narzędzie nie jest częścią socketu hardware-agenta ani Web API. Udostępnia
wyłącznie dwa polecenia: ``diagnostic_controls_on`` i
``diagnostic_controls_off`` (w CLI: ``on`` i ``off``). Nie przyjmuje numerów
GPIO, czasu ani polaryzacji od wywołującego.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import subprocess
import time
from typing import Callable, Sequence

from .hardware_agent import ControlPolarity, GPIO_CHIP, POWER_CONTROL_GPIO, RESET_CONTROL_GPIO


DIAGNOSTIC_GPIOS = (POWER_CONTROL_GPIO, RESET_CONTROL_GPIO)
DIAGNOSTIC_CONSUMER = "pcdog-diagnostic-controls"
DEFAULT_STATE_DIRECTORY = Path("/run/pcdog-diagnostic-controls")


class DiagnosticControlsError(RuntimeError):
    """Nie udało się jednoznacznie ustawić albo zwolnić obu wyjść."""


class DiagnosticControls:
    """Utrzymuje wyłącznie GPIO16 i GPIO17 w potwierdzonej polaryzacji.

    Każdy kanał ma własny proces ``gpioset``. Proces pozostaje aktywny bez
    timeoutu, więc jest właścicielem żądania GPIO aż do jawnego ``off``.
    """

    def __init__(
        self,
        state_directory: Path = DEFAULT_STATE_DIRECTORY,
        popen: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
        kill: Callable[[int, int], None] = os.kill,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._state_directory = state_directory
        self._popen = popen
        self._kill = kill
        self._sleep = sleep

    def on(self) -> None:
        """Uruchamia oba kanały ACTIVE-HIGH i pozostawia je załączone."""
        self.off()
        started: list[int] = []
        try:
            self._state_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            self._state_directory.chmod(0o700)
            for gpio in DIAGNOSTIC_GPIOS:
                process = self._popen(
                    self._command(gpio),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                self._sleep(0.05)
                if process.poll() is not None:
                    stderr = process.stderr.read().strip() if process.stderr is not None else ""
                    raise DiagnosticControlsError(f"gpioset dla GPIO{gpio} zakończył się przedwcześnie: {stderr}")
                self._pid_path(gpio).write_text(f"{process.pid}\n", encoding="ascii")
                self._pid_path(gpio).chmod(0o600)
                started.append(gpio)
        except BaseException:
            self._stop_gpios(started)
            raise

    def off(self) -> None:
        """Bezwarunkowo kończy znane procesy właścicieli obu wyjść."""
        self._stop_gpios(DIAGNOSTIC_GPIOS)
        if self._state_directory.exists():
            try:
                self._state_directory.rmdir()
            except OSError:
                pass

    @staticmethod
    def _command(gpio: int) -> list[str]:
        # Polaryzacja diagnostyki jest stała i nie pochodzi od klienta.
        assert ControlPolarity.ACTIVE_HIGH.value == "active-high"
        return [
            "gpioset", "--chip", GPIO_CHIP, "--consumer", DIAGNOSTIC_CONSUMER,
            f"{gpio}=active",
        ]

    def _pid_path(self, gpio: int) -> Path:
        return self._state_directory / f"gpio{gpio}.pid"

    def _stop_gpios(self, gpios: Sequence[int]) -> None:
        for gpio in gpios:
            path = self._pid_path(gpio)
            try:
                pid = int(path.read_text(encoding="ascii").strip())
            except (OSError, ValueError):
                continue
            try:
                self._kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            finally:
                path.unlink(missing_ok=True)


def main(arguments: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="PcDog: root-only GPIO16/GPIO17 diagnostic controls")
    parser.add_argument("operation", choices=("on", "off"), help="on = diagnostic_controls_on; off = diagnostic_controls_off")
    args = parser.parse_args(arguments)
    if os.geteuid() != 0:
        parser.error("to narzędzie diagnostyczne wymaga root")
    controls = DiagnosticControls()
    try:
        if args.operation == "on":
            controls.on()
            print("diagnostic_controls_on: GPIO16=ACTIVE/HIGH GPIO17=ACTIVE/HIGH")
        else:
            controls.off()
            print("diagnostic_controls_off: GPIO16=inactive GPIO17=inactive")
    except DiagnosticControlsError as error:
        controls.off()
        parser.error(str(error))


if __name__ == "__main__":
    main()
