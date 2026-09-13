"""Wąsko ograniczony agent GPIO PcDog.

Agent zawsze udostępnia tylko odczyty GPIO19/GPIO20. Sterowanie jest domyślnie
wyłączone (fail-closed) i może zostać włączone wyłącznie przez lokalną
konfigurację procesu z uprzednio potwierdzoną polaryzacją. Protokół IPC nie
zawiera numerów GPIO ani ogólnej operacji ustawiania linii.
"""

from __future__ import annotations

import argparse
from enum import Enum
import json
from pathlib import Path
import socketserver
import subprocess
import threading
from typing import Sequence

from .inputs import InputReading
from .models import HddActivity, PowerLedState
from .gpio_ownership import OutputLock, OutputLockBusyError


DEFAULT_SOCKET_PATH = Path("/run/pcdog-hardware-agent/agent.sock")
MAX_REQUEST_BYTES = 256
PROTOCOL_VERSION = 1
GPIO_CHIP = "gpiochip0"
POWER_CONTROL_GPIO = 17
RESET_CONTROL_GPIO = 18
POWER_LED_GPIO = 19
HDD_LED_GPIO = 20
DEFAULT_PULSE_DURATION_MS = 200
MIN_PULSE_DURATION_MS = 50
MAX_PULSE_DURATION_MS = 500
GPIOSET_CONSUMER = "pcdog-hardware-agent"


class ControlPolarity(str, Enum):
    """Fizyczny poziom, który załącza transoptor sterujący."""

    ACTIVE_HIGH = "active-high"
    ACTIVE_LOW = "active-low"


class PulseError(RuntimeError):
    """Błąd impulsu; linia została już zwolniona lub jest zwalniana."""


class PulseDurationError(ValueError):
    """Czas impulsu nie spełnia kontraktu bezpieczeństwa."""


class OutputBusyError(RuntimeError):
    """Inny kanał jest właśnie aktywowany."""


class GpioInputReader:
    """Czyta aktywne-nisko GPIO19/GPIO20 z pull-up przez ``gpioget``."""

    def __init__(self, runner=subprocess.run) -> None:
        self._runner = runner

    def read(self) -> InputReading:
        try:
            result = self._runner(
                [
                    "gpioget", "--numeric", "--active-low", "--bias", "pull-up",
                    "--chip", GPIO_CHIP, str(HDD_LED_GPIO), str(POWER_LED_GPIO),
                ],
                check=True, capture_output=True, text=True, timeout=1.0,
            )
            hdd_value, power_value = self._parse_values(result.stdout)
        except (OSError, subprocess.SubprocessError, ValueError):
            return unavailable_reading()
        return InputReading(
            power_led=PowerLedState.ON if power_value else PowerLedState.OFF,
            power_led_reliable=True,
            hdd_activity=HddActivity.ACTIVE if hdd_value else HddActivity.IDLE,
            hdd_activity_reliable=True,
        )

    @staticmethod
    def _parse_values(output: str) -> tuple[bool, bool]:
        tokens = output.split()
        fields = dict(item.split("=", 1) for item in tokens if "=" in item)
        if fields:
            if set(fields) != {str(HDD_LED_GPIO), str(POWER_LED_GPIO)}:
                raise ValueError("Nieprawidłowa odpowiedź gpioget")
            ordered_values = [fields[str(HDD_LED_GPIO)], fields[str(POWER_LED_GPIO)]]
        elif len(tokens) == 2:
            ordered_values = tokens
        else:
            raise ValueError("Nieprawidłowa odpowiedź gpioget")
        values = []
        for value in ordered_values:
            if value not in {"active", "inactive", "1", "0"}:
                raise ValueError("Nieprawidłowy poziom GPIO")
            values.append(value in {"active", "1"})
        return values[0], values[1]


class GpioPulseExecutor:
    """Wykonuje jeden ograniczony czasowo impuls stałej linii.

    ``gpioset --toggle <czas>,0`` aktywuje linię, po czasie przełącza ją na
    nieaktywną i kończy proces. Zwolnienie żądania GPIO przy zakończeniu procesu
    przywraca linię do wejścia. Timeout lub wyjątek kończy dziecko, więc nie
    może ono dalej utrzymywać aktywnego wyjścia.
    """

    def __init__(self, polarity: ControlPolarity, popen=subprocess.Popen, lock_factory=OutputLock) -> None:
        self._polarity = polarity
        self._popen = popen
        self._lock_factory = lock_factory

    def pulse(self, gpio: int, duration_ms: int) -> None:
        command = ["gpioset", "--chip", GPIO_CHIP, "--consumer", GPIOSET_CONSUMER]
        if self._polarity is ControlPolarity.ACTIVE_LOW:
            command.append("--active-low")
        command.extend(["--toggle", f"{duration_ms}ms,0", f"{gpio}=active"])

        process = None
        try:
            with self._lock_factory():
                process = self._popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                _, stderr = process.communicate(timeout=(duration_ms / 1000) + 1.0)
                if process.returncode != 0:
                    raise PulseError(f"gpioset zakończył się kodem {process.returncode}: {stderr.strip()}")
        except OutputLockBusyError as error:
            raise OutputBusyError("Wyjścia zajęte przez diagnostykę lokalną") from error
        except subprocess.TimeoutExpired as error:
            if process is not None:
                self._stop_process(process)
            raise PulseError("Przekroczono ograniczony czas impulsu") from error
        except OSError as error:
            raise PulseError("Nie udało się uruchomić gpioset") from error
        except BaseException:
            if process is not None and process.poll() is None:
                self._stop_process(process)
            raise

    @staticmethod
    def _stop_process(process: object) -> None:
        process.terminate()  # type: ignore[attr-defined]
        try:
            process.communicate(timeout=1.0)  # type: ignore[attr-defined]
        except subprocess.TimeoutExpired:
            process.kill()  # type: ignore[attr-defined]
            process.communicate(timeout=1.0)  # type: ignore[attr-defined]


class PulseController:
    """Semantyczne, wzajemnie wykluczające sterowanie POWER/RESET."""

    def __init__(self, executor: GpioPulseExecutor | None = None) -> None:
        self._executor = executor
        self._lock = threading.Lock()

    @property
    def enabled_operations(self) -> list[str]:
        return ["pulse_power", "pulse_reset"] if self._executor is not None else []

    @staticmethod
    def validate_duration(duration_ms: object | None) -> int:
        if duration_ms is None:
            return DEFAULT_PULSE_DURATION_MS
        if isinstance(duration_ms, bool) or not isinstance(duration_ms, int):
            raise PulseDurationError("Czas impulsu musi być liczbą całkowitą")
        if not MIN_PULSE_DURATION_MS <= duration_ms <= MAX_PULSE_DURATION_MS:
            raise PulseDurationError("Czas impulsu jest poza bezpiecznym zakresem")
        return duration_ms

    def pulse_power(self, duration_ms: object | None = None) -> int:
        return self._pulse(POWER_CONTROL_GPIO, duration_ms)

    def pulse_reset(self, duration_ms: object | None = None) -> int:
        return self._pulse(RESET_CONTROL_GPIO, duration_ms)

    def _pulse(self, gpio: int, duration_ms: object | None) -> int:
        if self._executor is None:
            raise PermissionError("Sterowanie wyjściami jest wyłączone")
        duration = self.validate_duration(duration_ms)
        if not self._lock.acquire(blocking=False):
            raise OutputBusyError("Inny impuls jest już wykonywany")
        try:
            self._executor.pulse(gpio, duration)
        finally:
            self._lock.release()
        return duration


def unavailable_reading() -> InputReading:
    return InputReading(PowerLedState.UNKNOWN, False, HddActivity.UNKNOWN, False)


def reading_payload(reading: InputReading) -> dict[str, object]:
    return {
        "status": "READY",
        "protocol_version": PROTOCOL_VERSION,
        "power_led": reading.power_led.value,
        "power_led_reliable": reading.power_led_reliable,
        "hdd_activity": reading.hdd_activity.value,
        "hdd_activity_reliable": reading.hdd_activity_reliable,
    }


def handle_request(
    raw_request: bytes, reader: GpioInputReader, controller: PulseController | None = None,
) -> dict[str, object]:
    controller = controller or PulseController()
    if len(raw_request) > MAX_REQUEST_BYTES or not raw_request.endswith(b"\n"):
        return {"status": "INVALID_REQUEST"}
    try:
        request = json.loads(raw_request.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"status": "INVALID_REQUEST"}
    if request == {"operation": "status"}:
        return {"status": "READY", "protocol_version": PROTOCOL_VERSION, "inputs": ["hdd_led", "power_led"], "controls": controller.enabled_operations}
    if request == {"operation": "read_inputs"}:
        return reading_payload(reader.read())
    if not isinstance(request, dict) or request.get("operation") not in {"pulse_power", "pulse_reset"}:
        return {"status": "ACTION_NOT_ENABLED"}
    if set(request) - {"operation", "duration_ms"}:
        return {"status": "INVALID_REQUEST"}
    try:
        duration_ms = request.get("duration_ms")
        duration = controller.pulse_power(duration_ms) if request["operation"] == "pulse_power" else controller.pulse_reset(duration_ms)
    except PermissionError:
        return {"status": "ACTION_NOT_ENABLED"}
    except PulseDurationError:
        return {"status": "PULSE_DURATION_NOT_ALLOWED"}
    except OutputBusyError:
        return {"status": "OUTPUT_BUSY"}
    except PulseError:
        return {"status": "PULSE_FAILED"}
    return {"status": "PULSE_COMPLETED", "duration_ms": duration}


class HardwareAgentRequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        response = handle_request(
            self.rfile.readline(MAX_REQUEST_BYTES + 1),
            self.server.reader,  # type: ignore[attr-defined]
            self.server.controller,  # type: ignore[attr-defined]
        )
        try:
            self.wfile.write(json.dumps(response, separators=(",", ":")).encode("utf-8") + b"\n")
        except BrokenPipeError:
            # Klient może zamknąć IPC po wysłaniu kompletnego żądania. Impuls
            # pozostaje ograniczony przez agenta i nie zależy od odbioru reply.
            pass


class HardwareAgentServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    allow_reuse_address = True
    daemon_threads = True


def create_server(
    socket_path: Path,
    reader: GpioInputReader | None = None,
    controller: PulseController | None = None,
) -> HardwareAgentServer:
    if socket_path.exists():
        raise RuntimeError(f"Socket już istnieje: {socket_path}")
    server = HardwareAgentServer(str(socket_path), HardwareAgentRequestHandler)
    server.reader = reader or GpioInputReader()  # type: ignore[attr-defined]
    server.controller = controller or PulseController()  # type: ignore[attr-defined]
    socket_path.chmod(0o660)
    return server


def main(arguments: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="PcDog hardware-agent")
    parser.add_argument("--socket", type=Path, default=DEFAULT_SOCKET_PATH)
    parser.add_argument("--control-polarity", choices=[polarity.value for polarity in ControlPolarity])
    arguments = parser.parse_args(arguments)
    executor = GpioPulseExecutor(ControlPolarity(arguments.control_polarity)) if arguments.control_polarity else None
    with create_server(arguments.socket, controller=PulseController(executor)) as server:
        server.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
