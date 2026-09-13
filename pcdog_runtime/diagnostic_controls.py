"""Lokalna, root-only diagnostyka czterech stałych sygnałów PcDog."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Callable, Sequence

from .hardware_agent import (
    ControlPolarity,
    GPIO_CHIP,
    GpioInputReader,
    HDD_LED_GPIO,
    POWER_CONTROL_GPIO,
    POWER_LED_GPIO,
    RESET_CONTROL_GPIO,
)
from .gpio_ownership import OutputLock, OutputLockBusyError


DIAGNOSTIC_GPIOS = (POWER_CONTROL_GPIO, RESET_CONTROL_GPIO)
DIAGNOSTIC_CONSUMER = "pcdog-test"
DEFAULT_STATE_DIRECTORY = Path("/run/pcdog-diagnostic-controls")
HDD_MONITOR_GPIO = HDD_LED_GPIO
POWER_MONITOR_GPIO = POWER_LED_GPIO

HELP_TEXT = """Usage:
  pcdog-test <command>

Commands:
  status       Show all PcDog GPIO states
  inputs       Show GPIO19/GPIO20 monitor inputs
  outputs      Show GPIO17/GPIO18 control outputs

  power-on     Set POWER control GPIO17 ACTIVE
  power-off    Set POWER control GPIO17 INACTIVE, then release it
  reset-on     Set RESET control GPIO18 ACTIVE
  reset-off    Set RESET control GPIO18 INACTIVE, then release it
  all-on       Set GPIO17 and GPIO18 ACTIVE
  all-off      Set GPIO17 and GPIO18 INACTIVE, then release them
  help         Show this help

GPIO mapping:
  GPIO17  POWER CONTROL
  GPIO18  RESET CONTROL
  GPIO19  POWER LED MONITOR
  GPIO20  HDD LED MONITOR

WARNING:
  power-on, reset-on and all-on are diagnostic commands.
  Do not use them when PcDog POWER/RESET outputs are connected to a PC
  unless explicitly intended.
"""


class DiagnosticControlsError(RuntimeError):
    """Nie udało się jednoznacznie ustawić albo zwolnić obu wyjść."""


class DiagnosticControls:
    """Utrzymuje wyłącznie GPIO17 i GPIO18 w potwierdzonej polaryzacji.

    Każdy kanał ma własny proces ``gpioset``. Proces pozostaje aktywny bez
    timeoutu, więc jest właścicielem żądania GPIO aż do jawnego ``off``.
    """

    def __init__(
        self,
        state_directory: Path = DEFAULT_STATE_DIRECTORY,
        popen: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
        kill: Callable[[int, int], None] = os.kill,
        sleep: Callable[[float], None] = time.sleep,
        lock_factory=OutputLock,
        is_owner: Callable[[int], bool] | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self._state_directory = state_directory
        self._popen = popen
        self._kill = kill
        self._sleep = sleep
        self._lock_factory = lock_factory
        self._is_owner = is_owner or self._is_diagnostic_owner
        self._runner = runner

    def on(self) -> None:
        self.all_on()

    def all_on(self) -> None:
        self._set_active(DIAGNOSTIC_GPIOS)

    def power_on(self) -> None:
        self._set_active((POWER_CONTROL_GPIO,))

    def reset_on(self) -> None:
        self._set_active((RESET_CONTROL_GPIO,))

    def power_off(self) -> None:
        self._stop_gpios((POWER_CONTROL_GPIO,))

    def reset_off(self) -> None:
        self._stop_gpios((RESET_CONTROL_GPIO,))

    def _set_active(self, gpios: Sequence[int]) -> None:
        """Aktywuje wskazane stałe linie bez naruszania drugiego kanału."""
        started: list[int] = []
        lock: OutputLock | None = None
        try:
            self._state_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            self._state_directory.chmod(0o700)
            active = self._active_gpios()
            if not active:
                lock = self._lock_factory()
                lock.acquire()
            for gpio in gpios:
                if gpio in active:
                    continue
                kwargs: dict[str, object] = {
                    "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                    "stderr": subprocess.PIPE, "text": True,
                }
                if lock is not None:
                    kwargs["pass_fds"] = (lock.acquire(),)
                process = self._popen(
                    self._command(gpio),
                    **kwargs,
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
        finally:
            if lock is not None:
                lock.release()

    def off(self) -> None:
        """Ustawia LOW, a następnie kończy znane procesy właścicieli wyjść."""
        self._stop_gpios(DIAGNOSTIC_GPIOS)
        if self._state_directory.exists():
            try:
                self._state_directory.rmdir()
            except OSError:
                pass

    all_off = off

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
        owners: list[tuple[int, int, Path]] = []
        for gpio in gpios:
            path = self._pid_path(gpio)
            try:
                pid = int(path.read_text(encoding="ascii").strip())
            except (OSError, ValueError):
                continue
            if not self._is_owner(pid):
                path.unlink(missing_ok=True)
                continue
            owners.append((gpio, pid, path))

        # Do not release any line until every requested line is physically
        # inactive. A released line can retain its previous electrical level.
        for gpio, _, _ in owners:
            self._set_inactive(gpio)

        for _, pid, path in owners:
            try:
                self._kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            finally:
                path.unlink(missing_ok=True)

    def _set_inactive(self, gpio: int) -> None:
        """Wymusza fizyczne LOW przed zwolnieniem właściciela linii."""
        try:
            self._runner(
                ["pinctrl", "set", str(gpio), "op", "dl"],
                check=True,
                capture_output=True,
                text=True,
                timeout=1.0,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise DiagnosticControlsError(
                f"nie udało się ustawić GPIO{gpio} w stanie INACTIVE/LOW; wyjście pozostaje zajęte"
            ) from error

    def _active_gpios(self) -> set[int]:
        active: set[int] = set()
        for gpio in DIAGNOSTIC_GPIOS:
            try:
                pid = int(self._pid_path(gpio).read_text(encoding="ascii").strip())
                if not self._is_owner(pid):
                    raise ProcessLookupError
            except (OSError, ValueError):
                self._pid_path(gpio).unlink(missing_ok=True)
            else:
                active.add(gpio)
        return active

    @staticmethod
    def _is_diagnostic_owner(pid: int) -> bool:
        """Nigdy nie wysyłaj SIGTERM do PID odziedziczonego przez inny proces."""
        try:
            command = Path(f"/proc/{pid}/cmdline").read_bytes()
        except OSError:
            return False
        return b"gpioset" in command and b"--consumer" in command and (
            DIAGNOSTIC_CONSUMER.encode() in command or b"pcdog-diagnostic-controls" in command
        )


def main(arguments: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="PcDog: root-only GPIO diagnostics")
    operations = ("status", "inputs", "outputs", "power-on", "power-off", "reset-on", "reset-off", "all-on", "all-off", "on", "off")
    parser.add_argument("operation")
    raw_arguments = list(sys.argv[1:] if arguments is None else arguments)
    if len(raw_arguments) == 1 and raw_arguments[0] in {"help", "--help", "-h"}:
        print(HELP_TEXT, end="")
        return
    if len(raw_arguments) != 1 or raw_arguments[0] not in operations:
        unknown = raw_arguments[0] if raw_arguments else ""
        print(f"Unknown command: {unknown}\nRun: pcdog-test help", file=sys.stderr)
        raise SystemExit(2)
    args = parser.parse_args(raw_arguments)
    if os.geteuid() != 0:
        parser.error("to narzędzie diagnostyczne wymaga root")
    controls = DiagnosticControls()
    operation = {"on": "all-on", "off": "all-off"}.get(args.operation, args.operation)
    try:
        if operation == "power-on": controls.power_on()
        elif operation == "power-off": controls.power_off()
        elif operation == "reset-on": controls.reset_on()
        elif operation == "reset-off": controls.reset_off()
        elif operation == "all-on": controls.all_on()
        elif operation == "all-off": controls.all_off()
    except (DiagnosticControlsError, OutputLockBusyError) as error:
        parser.error(str(error))
    try:
        print_status("outputs" if operation.endswith(("-on", "-off")) else operation)
    except DiagnosticControlsError as error:
        parser.error(str(error))


def print_status(operation: str) -> None:
    """Tylko odczyty: ``gpioget`` dla wejść i ``gpioinfo`` dla wyjść."""
    output_signals = (("POWER_CONTROL", POWER_CONTROL_GPIO), ("RESET_CONTROL", RESET_CONTROL_GPIO))
    input_signals = (("HDD_MONITOR", HDD_MONITOR_GPIO), ("POWER_MONITOR", POWER_MONITOR_GPIO))
    if operation in {"status", "outputs"}:
        for name, gpio, state in _read_output_levels(output_signals):
            print(f"{name:<15} GPIO{gpio:<2}  {state}")
    if operation in {"status", "inputs"}:
        for name, gpio, state in _read_input_levels(input_signals):
            print(f"{name:<15} GPIO{gpio:<2}  {state}")


def _read_input_levels(signals: Sequence[tuple[str, int]]) -> list[tuple[str, int, str]]:
    try:
        result = subprocess.run(["gpioget", "--numeric", "--chip", GPIO_CHIP, *[str(gpio) for _, gpio in signals]], check=True, capture_output=True, text=True, timeout=1.0)
        hdd, power = GpioInputReader._parse_values(result.stdout)
        values = (hdd, power)
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        raise DiagnosticControlsError("nie udało się odczytać wejść GPIO19/GPIO20") from error
    return [(name, gpio, "HIGH" if value else "LOW") for (name, gpio), value in zip(signals, values, strict=True)]


def _read_output_levels(signals: Sequence[tuple[str, int]]) -> list[tuple[str, int, str]]:
    try:
        result = subprocess.run(["gpioinfo", "--chip", GPIO_CHIP, *[str(gpio) for _, gpio in signals]], check=True, capture_output=True, text=True, timeout=1.0)
    except (OSError, subprocess.SubprocessError) as error:
        raise DiagnosticControlsError("nie udało się odczytać wyjść GPIO17/GPIO18") from error
    lines = result.stdout.splitlines()
    states = []
    for name, gpio in signals:
        line = next((candidate for candidate in lines if str(gpio) in candidate), "")
        # libgpiod exposes the requested logical output value as active/inactive;
        # active-high is polarity metadata and must not itself be treated as HIGH.
        fields = line.split()
        state = "HIGH" if "output active" in line else "LOW" if "output inactive" in line else "INACTIVE" if fields and fields[-1] == "input" else "UNKNOWN"
        states.append((name, gpio, state))
    return states


if __name__ == "__main__":
    main()
