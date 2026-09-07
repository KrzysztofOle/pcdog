"""Izolowany agent zmiany Wi-Fi PcDog.

Agent przyjmuje tylko trzy operacje przez lokalny socket Unix.  Nie loguje
żądań, dzięki czemu hasło Wi-Fi nie trafia do journald ani historii jobów.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import pwd
import re
import socket
import socketserver
import struct
import subprocess
from threading import Lock, Thread
import time
from typing import Protocol, Sequence
import uuid


DEFAULT_SOCKET_PATH = Path("/run/pcdog-network-agent/agent.sock")
MAX_REQUEST_BYTES = 4096
JOB_RESULT_TTL_SECONDS = 300
CONNECT_TIMEOUT_SECONDS = 30
_BSSID = re.compile(r"^[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}$")


class NetworkAgentError(ValueError):
    """Błąd bez treści mogącej zawierać sekret albo dane systemowe."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class PreviousConnection:
    device: str
    profile: str


class NetworkManagerExecutor(Protocol):
    def list_wifi(self) -> list[dict[str, object]]: ...
    def active_wifi(self) -> PreviousConnection | None: ...
    def connect(self, ssid: str, bssid: str | None, password: str, timeout: int) -> None: ...
    def is_confirmed(self, ssid: str, bssid: str | None) -> bool: ...
    def rollback(self, previous: PreviousConnection) -> None: ...
    def cleanup_failed_connection(self) -> None: ...


def _split_nmcli(line: str) -> list[str]:
    """Rozdziela `nmcli -t --escape yes`, bez wykonywania interpretacji shell."""
    fields: list[str] = []
    value: list[str] = []
    escaped = False
    for char in line.rstrip("\n"):
        if escaped:
            value.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            fields.append("".join(value))
            value = []
        else:
            value.append(char)
    if escaped:
        value.append("\\")
    fields.append("".join(value))
    return fields


def validate_ssid(ssid: object) -> str:
    if not isinstance(ssid, str) or not ssid or len(ssid.encode("utf-8")) > 32 or any(ord(char) < 32 for char in ssid):
        raise NetworkAgentError("INVALID_WIFI_REQUEST")
    return ssid


def validate_bssid(bssid: object) -> str | None:
    if bssid is None:
        return None
    if not isinstance(bssid, str) or not _BSSID.fullmatch(bssid):
        raise NetworkAgentError("INVALID_WIFI_REQUEST")
    return bssid.upper()


def validate_password(password: object) -> str:
    # WPA-PSK accepts 8--63 printable characters.  Open networks are deliberately
    # unsupported by this privileged endpoint.
    if not isinstance(password, str) or not 8 <= len(password) <= 63 or any(ord(char) < 32 or ord(char) == 127 for char in password):
        raise NetworkAgentError("INVALID_WIFI_REQUEST")
    return password


def validate_connect_request(request: object) -> tuple[str, str | None, str]:
    if not isinstance(request, dict) or set(request) not in ({"operation", "ssid", "password"}, {"operation", "ssid", "bssid", "password"}) or request.get("operation") != "connect_wifi":
        raise NetworkAgentError("INVALID_WIFI_REQUEST")
    return validate_ssid(request.get("ssid")), validate_bssid(request.get("bssid")), validate_password(request.get("password"))


class NmcliExecutor:
    """Minimalny adapter NetworkManager; hasło trafia wyłącznie na stdin nmcli."""

    def __init__(self) -> None:
        self._temporary_connection: str | None = None

    def _run(self, arguments: list[str], *, timeout: int, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(arguments, check=True, capture_output=True, text=True, input=input_text, timeout=timeout, env={**os.environ, "LC_ALL": "C"})
        except FileNotFoundError as error:
            raise NetworkAgentError("NETWORK_MANAGER_UNAVAILABLE") from error
        except subprocess.TimeoutExpired as error:
            raise NetworkAgentError("TIMEOUT") from error
        except subprocess.SubprocessError as error:
            raise NetworkAgentError("CONNECTION_FAILED") from error

    def list_wifi(self) -> list[dict[str, object]]:
        result = self._run(["nmcli", "--terse", "--escape", "yes", "--fields", "SSID,BSSID,SECURITY,SIGNAL", "device", "wifi", "list", "--rescan", "yes"], timeout=10)
        networks: list[dict[str, object]] = []
        for line in result.stdout.splitlines():
            fields = _split_nmcli(line)
            if len(fields) != 4 or not fields[0] or not fields[2] or fields[2] == "--" or not _BSSID.fullmatch(fields[1]):
                continue
            try:
                signal = int(fields[3])
            except ValueError:
                continue
            if not 0 <= signal <= 100:
                continue
            networks.append({"ssid": fields[0], "bssid": fields[1].upper(), "security": fields[2], "signal": signal})
        return networks

    def active_wifi(self) -> PreviousConnection | None:
        result = self._run(["nmcli", "--terse", "--escape", "yes", "--fields", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"], timeout=5)
        for line in result.stdout.splitlines():
            fields = _split_nmcli(line)
            if len(fields) == 4 and fields[1] == "wifi" and fields[2] == "connected" and fields[3] and fields[3] != "--":
                return PreviousConnection(device=fields[0], profile=fields[3])
        return None

    def connect(self, ssid: str, bssid: str | None, password: str, timeout: int) -> None:
        # `save no` creates only an in-memory NetworkManager profile.  `--ask`
        # consumes the secret on stdin: it is never argv, a durable profile,
        # temporary file, log line, response or job result.
        current = self.active_wifi()
        if current is None:
            raise NetworkAgentError("CONNECTION_FAILED")
        temporary = "pcdog-wifi-" + uuid.uuid4().hex
        arguments = ["nmcli", "connection", "add", "save", "no", "type", "wifi", "ifname", current.device, "con-name", temporary, "ssid", ssid, "--", "wifi-sec.key-mgmt", "wpa-psk"]
        if bssid is not None:
            arguments.extend(["802-11-wireless.bssid", bssid])
        self._run(arguments, timeout=5)
        self._temporary_connection = temporary
        self._run(["nmcli", "--ask", "--wait", str(timeout), "connection", "up", "id", temporary, "ifname", current.device], timeout=timeout + 5, input_text=password + "\n")

    def is_confirmed(self, ssid: str, bssid: str | None) -> bool:
        wifi = self._run(["nmcli", "--terse", "--escape", "yes", "--fields", "ACTIVE,SSID,BSSID", "device", "wifi"], timeout=5)
        selected = any(len(fields := _split_nmcli(line)) == 3 and fields[0] == "yes" and fields[1] == ssid and (bssid is None or fields[2].upper() == bssid) for line in wifi.stdout.splitlines())
        if not selected:
            return False
        active = self.active_wifi()
        if active is None:
            return False
        addresses = self._run(["nmcli", "--get-values", "IP4.ADDRESS", "device", "show", active.device], timeout=5)
        return any(line.strip() for line in addresses.stdout.splitlines())

    def rollback(self, previous: PreviousConnection) -> None:
        self._run(["nmcli", "--wait", str(CONNECT_TIMEOUT_SECONDS), "connection", "up", "id", previous.profile, "ifname", previous.device], timeout=CONNECT_TIMEOUT_SECONDS + 5)

    def cleanup_failed_connection(self) -> None:
        if self._temporary_connection is None:
            return
        temporary, self._temporary_connection = self._temporary_connection, None
        try:
            self._run(["nmcli", "connection", "delete", "id", temporary], timeout=5)
        except NetworkAgentError:
            # Cleanup cannot replace the already reported connection/rollback
            # result, and no exception detail may reach the client.
            pass


class WifiJobManager:
    def __init__(self, executor: NetworkManagerExecutor, *, ttl: int = JOB_RESULT_TTL_SECONDS) -> None:
        self._executor = executor
        self._ttl = ttl
        self._lock = Lock()
        self._active = False
        self._last: dict[str, object] | None = None

    def start(self, ssid: str, bssid: str | None, password: str) -> dict[str, object]:
        with self._lock:
            if self._active:
                return {"status": "BUSY"}
            self._active = True
            job_id = uuid.uuid4().hex
            self._last = {"status": "IN_PROGRESS", "job_id": job_id, "ssid": ssid, "updated_at": time.monotonic()}
        Thread(target=self._run, args=(job_id, ssid, bssid, password), daemon=True).start()
        return {"status": "STARTED", "job_id": job_id}

    def _run(self, job_id: str, ssid: str, bssid: str | None, password: str) -> None:
        previous: PreviousConnection | None = None
        code = "CONNECTION_FAILED"
        try:
            previous = self._executor.active_wifi()
            self._executor.connect(ssid, bssid, password, CONNECT_TIMEOUT_SECONDS)
            password = ""  # remove the only agent-held reference as soon as possible
            if not self._executor.is_confirmed(ssid, bssid):
                raise NetworkAgentError("CONNECTION_NOT_CONFIRMED")
            result = {"status": "SUCCEEDED", "job_id": job_id, "ssid": ssid}
        except NetworkAgentError as error:
            code = error.code
            result = self._rollback_result(job_id, ssid, previous, code)
            self._executor.cleanup_failed_connection()
        except Exception:
            result = self._rollback_result(job_id, ssid, previous, code)
            self._executor.cleanup_failed_connection()
        finally:
            password = ""
            with self._lock:
                result["updated_at"] = time.monotonic()
                self._last = result
                self._active = False

    def _rollback_result(self, job_id: str, ssid: str, previous: PreviousConnection | None, code: str) -> dict[str, object]:
        if previous is None:
            return {"status": "FAILED", "job_id": job_id, "ssid": ssid, "reason": code}
        try:
            self._executor.rollback(previous)
        except Exception:
            return {"status": "ROLLBACK_FAILED", "job_id": job_id, "ssid": ssid, "reason": code}
        return {"status": "ROLLED_BACK", "job_id": job_id, "ssid": ssid, "reason": code}

    def status(self) -> dict[str, object]:
        with self._lock:
            if self._last is None:
                return {"status": "IDLE"}
            if not self._active and time.monotonic() - float(self._last["updated_at"]) > self._ttl:
                self._last = None
                return {"status": "IDLE"}
            return {key: value for key, value in self._last.items() if key != "updated_at"}


def peer_uid(connection: socket.socket) -> int | None:
    """Zwraca UID klienta na Linuksie albo None, gdy SO_PEERCRED nie istnieje."""
    if not hasattr(socket, "SO_PEERCRED"):
        return None
    credentials = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    return struct.unpack("3i", credentials)[1]


def handle_request(raw_request: bytes, manager: WifiJobManager, executor: NetworkManagerExecutor) -> dict[str, object]:
    if len(raw_request) > MAX_REQUEST_BYTES or not raw_request.endswith(b"\n"):
        return {"status": "INVALID_REQUEST"}
    try:
        request = json.loads(raw_request.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"status": "INVALID_REQUEST"}
    try:
        if request == {"operation": "list_wifi"}:
            return {"status": "AVAILABLE", "networks": executor.list_wifi()}
        if request == {"operation": "connection_status"}:
            return manager.status()
        ssid, bssid, password = validate_connect_request(request)
        return manager.start(ssid, bssid, password)
    except NetworkAgentError as error:
        return {"status": error.code}
    except Exception:
        return {"status": "NETWORK_MANAGER_UNAVAILABLE"}


class NetworkAgentRequestHandler(socketserver.StreamRequestHandler):
    manager: WifiJobManager
    executor: NetworkManagerExecutor
    allowed_uid: int

    def handle(self) -> None:
        try:
            uid = peer_uid(self.request)
            if uid is not None and uid != self.allowed_uid:
                self._write({"status": "UNAUTHORIZED_CLIENT"})
                return
            self._write(handle_request(self.rfile.readline(MAX_REQUEST_BYTES + 1), self.manager, self.executor))
        except OSError:
            return

    def _write(self, response: dict[str, object]) -> None:
        self.wfile.write(json.dumps(response, separators=(",", ":")).encode("utf-8") + b"\n")


class NetworkAgentServer(socketserver.UnixStreamServer):
    allow_reuse_address = True


def create_server(socket_path: Path, *, executor: NetworkManagerExecutor | None = None, allowed_uid: int | None = None) -> NetworkAgentServer:
    if socket_path.exists():
        raise RuntimeError(f"Socket już istnieje: {socket_path}")
    agent_executor = executor or NmcliExecutor()
    handler = type("PcDogNetworkAgentHandler", (NetworkAgentRequestHandler,), {
        "executor": agent_executor,
        "manager": WifiJobManager(agent_executor),
        "allowed_uid": allowed_uid if allowed_uid is not None else pwd.getpwnam("pcdog").pw_uid,
    })
    server = NetworkAgentServer(str(socket_path), handler)
    socket_path.chmod(0o660)
    return server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PcDog restricted network agent")
    parser.add_argument("--socket", type=Path, default=DEFAULT_SOCKET_PATH)
    return parser


def main(arguments: Sequence[str] | None = None) -> None:
    arguments = build_parser().parse_args(arguments)
    with create_server(arguments.socket) as server:
        server.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
