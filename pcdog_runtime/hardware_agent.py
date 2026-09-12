"""Wąsko ograniczony, wyłącznie odczytowy agent GPIO PcDog.

Agent zna tylko GPIO19 (HDD LED) i GPIO20 (POWER LED).  Nie importuje ani nie
wywołuje żadnego mechanizmu ustawiania linii GPIO.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import socketserver
import subprocess
from typing import Sequence

from .inputs import InputReading
from .models import HddActivity, PowerLedState


DEFAULT_SOCKET_PATH = Path("/run/pcdog-hardware-agent/agent.sock")
MAX_REQUEST_BYTES = 256
PROTOCOL_VERSION = 1
GPIO_CHIP = "gpiochip0"
HDD_LED_GPIO = 19
POWER_LED_GPIO = 20


class GpioInputReader:
    """Czyta tylko dwie ustalone linie przez narzędzie libgpiod ``gpioget``.

    ``gpioget`` żąda linii jako wejść i kończy działanie po odczycie; nie
    zmienia ich na output.  Błąd programu lub nieczytelny wynik jest jawnie
    mapowany na niewiarygodny odczyt, nigdy na stan PC OFF.
    """

    def __init__(self, runner=subprocess.run) -> None:
        self._runner = runner

    def read(self) -> InputReading:
        try:
            result = self._runner(
                ["gpioget", "--numeric", GPIO_CHIP, str(HDD_LED_GPIO), str(POWER_LED_GPIO)],
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
        # gpiod v2 emits e.g. "19=active 20=inactive" with --numeric.
        fields = dict(item.split("=", 1) for item in output.split() if "=" in item)
        if set(fields) != {str(HDD_LED_GPIO), str(POWER_LED_GPIO)}:
            raise ValueError("Nieprawidłowa odpowiedź gpioget")
        values = []
        for gpio in (HDD_LED_GPIO, POWER_LED_GPIO):
            value = fields[str(gpio)]
            if value not in {"active", "inactive", "1", "0"}:
                raise ValueError("Nieprawidłowy poziom GPIO")
            values.append(value in {"active", "1"})
        return values[0], values[1]


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


def handle_request(raw_request: bytes, reader: GpioInputReader) -> dict[str, object]:
    if len(raw_request) > MAX_REQUEST_BYTES or not raw_request.endswith(b"\n"):
        return {"status": "INVALID_REQUEST"}
    try:
        request = json.loads(raw_request.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"status": "INVALID_REQUEST"}
    if request == {"operation": "status"}:
        return {"status": "READY", "protocol_version": PROTOCOL_VERSION, "inputs": ["hdd_led", "power_led"]}
    if request == {"operation": "read_inputs"}:
        return reading_payload(reader.read())
    return {"status": "ACTION_NOT_ENABLED"}


class HardwareAgentRequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        response = handle_request(self.rfile.readline(MAX_REQUEST_BYTES + 1), self.server.reader)  # type: ignore[attr-defined]
        self.wfile.write(json.dumps(response, separators=(",", ":")).encode("utf-8") + b"\n")


class HardwareAgentServer(socketserver.UnixStreamServer):
    allow_reuse_address = True


def create_server(socket_path: Path, reader: GpioInputReader | None = None) -> HardwareAgentServer:
    if socket_path.exists():
        raise RuntimeError(f"Socket już istnieje: {socket_path}")
    server = HardwareAgentServer(str(socket_path), HardwareAgentRequestHandler)
    server.reader = reader or GpioInputReader()  # type: ignore[attr-defined]
    socket_path.chmod(0o660)
    return server


def main(arguments: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="PcDog hardware-agent (GPIO input only)")
    parser.add_argument("--socket", type=Path, default=DEFAULT_SOCKET_PATH)
    arguments = parser.parse_args(arguments)
    with create_server(arguments.socket) as server:
        server.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
