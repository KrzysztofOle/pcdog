"""Read-only command line diagnostics for PcDog."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from typing import Callable, Sequence, TextIO, TypeVar

from .network_status import read_network_status
from .usb_mode import change_usb_mode


HEALTH_CHECK = "/opt/pcdog/bin/pcdog-healthcheck"
USB_MODE = "/usr/local/sbin/pcdog-usb-mode"
T = TypeVar("T")


def _safe_call(provider: Callable[[], T], fallback: T) -> T:
    try:
        return provider()
    except Exception:
        return fallback


def _run_readonly(arguments: list[str], *, timeout: float = 3) -> subprocess.CompletedProcess[str]:
    return subprocess.run(arguments, capture_output=True, text=True, timeout=timeout,
                          env={**os.environ, "LC_ALL": "C"}, check=False)


def read_health() -> dict[str, str]:
    try:
        result = _run_readonly([HEALTH_CHECK])
    except (OSError, subprocess.SubprocessError):
        return {"status": "UNAVAILABLE", "detail": "health check niedostępny"}
    if result.returncode == 0 and result.stdout.strip() == "HEALTHY":
        return {"status": "OK", "detail": "runtime działa"}
    if result.returncode == 1 and "UNHEALTHY:" in result.stderr:
        return {"status": "ERROR", "detail": "runtime nie przeszedł health check"}
    return {"status": "UNAVAILABLE", "detail": "health check niedostępny lub zwrócił nieznany wynik"}


def read_wifi_profiles() -> dict[str, object]:
    try:
        result = _run_readonly(["nmcli", "--terse", "--escape", "yes", "--fields",
                                "NAME,TYPE,DEVICE", "connection", "show"])
    except (OSError, subprocess.SubprocessError):
        return {"status": "UNAVAILABLE", "profiles": []}
    if result.returncode != 0:
        return {"status": "UNAVAILABLE", "profiles": []}
    # These fields exclude secrets, UUIDs and other authentication material.
    profiles: list[dict[str, str]] = []
    for line in result.stdout.splitlines():
        fields = _split_nmcli(line)
        if len(fields) == 3 and fields[1] in {"802-11-wireless", "wifi"}:
            profiles.append({"name": fields[0], "device": fields[2] or "—"})
    return {"status": "OK", "profiles": profiles}


def _split_nmcli(line: str) -> list[str]:
    fields: list[str] = []
    value: list[str] = []
    escaped = False
    for char in line:
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


def read_usb_status() -> dict[str, object]:
    try:
        result = _run_readonly([USB_MODE, "status"])
    except (OSError, subprocess.SubprocessError):
        return {"status": "UNAVAILABLE", "detail": "pcdog-usb-mode niedostępny"}
    if result.returncode != 0:
        return {"status": "ERROR", "detail": "odczyt statusu USB nie powiódł się"}
    # Filter to the documented status fields; never relay arbitrary command output.
    values: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, separator, value = line.partition(":")
        if separator and key in {"configured mode", "active USB function", "UDC bound", "usb0 state", "PcDog1 USB IPv4"}:
            values[key] = value.strip()
    required = {"configured mode", "active USB function", "UDC bound"}
    if not required.issubset(values):
        return {"status": "UNAVAILABLE", "detail": "status USB nie zawiera kompletnych danych"}
    return {"status": "OK", "values": values}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pcdog", description="Diagnostyka i kontrolowane operacje PcDog.")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("help", help="pokaż tę pomoc")
    commands.add_parser("status", help="podsumowanie stanu PcDog")
    network = commands.add_parser("network", help="diagnostyka sieci")
    network.add_subparsers(dest="network_command").add_parser("status", help="stan interfejsów")
    wifi = commands.add_parser("wifi", help="diagnostyka Wi-Fi")
    wifi.add_subparsers(dest="wifi_command").add_parser("profiles", help="zapisane profile Wi-Fi")
    usb = commands.add_parser("usb", help="diagnostyka USB Service Channel")
    usb_commands = usb.add_subparsers(dest="usb_command")
    usb_commands.add_parser("status", help="stan trybu i gadgetu USB")
    mode = usb_commands.add_parser("mode", help="zmień tryb hosta USB po kontroli kanału SSH")
    mode.add_argument("mode", choices=("windows", "mac"), help="windows (RNDIS) albo mac (ECM)")
    return parser


def _status_line(label: str, status: str, detail: str) -> str:
    names = {"OK": "OK", "ERROR": "BŁĄD", "UNAVAILABLE": "NIEDOSTĘPNE", "NO_DATA": "BRAK DANYCH"}
    return f"{label}: {names.get(status, status)} — {detail}"


def _format_network(result: dict[str, object]) -> tuple[list[str], bool]:
    if result.get("status") != "AVAILABLE":
        return [_status_line("Sieć", "UNAVAILABLE", "brak danych z NetworkManagera")], False
    interfaces = result.get("interfaces")
    if not isinstance(interfaces, list) or not interfaces:
        return [_status_line("Sieć", "NO_DATA", "brak interfejsów")], False
    lines = [_status_line("Sieć", "OK", f"{len(interfaces)} interfejs(y)")]
    for interface in interfaces:
        if not isinstance(interface, dict):
            continue
        name = str(interface.get("name") or "?")
        state = interface.get("state") or "brak danych"
        connection = interface.get("connection") or "brak profilu"
        addresses = interface.get("addresses")
        address_text = ", ".join(str(item) for item in addresses) if isinstance(addresses, list) and addresses else "brak adresu"
        lines.append(f"  {name}: {state}; {connection}; {address_text}")
    return lines, True


def _print_profiles(result: dict[str, object], output: TextIO) -> bool:
    if result.get("status") != "OK":
        print(_status_line("Profile Wi-Fi", "UNAVAILABLE", "nie można odczytać profili"), file=output)
        return False
    profiles = result.get("profiles")
    if not isinstance(profiles, list):
        print(_status_line("Profile Wi-Fi", "ERROR", "nieprawidłowa odpowiedź"), file=output)
        return False
    print(_status_line("Profile Wi-Fi", "OK", f"{len(profiles)} zapisanych"), file=output)
    for profile in profiles:
        if isinstance(profile, dict):
            print(f"  {profile.get('name', '?')} ({profile.get('device') or 'nieaktywne'})", file=output)
    return True


def run_cli(argv: Sequence[str] | None = None, *, output: TextIO | None = None,
            health: Callable[[], dict[str, str]] = read_health,
            network: Callable[[], dict[str, object]] = read_network_status,
            wifi: Callable[[], dict[str, object]] = read_wifi_profiles,
            usb: Callable[[], dict[str, object]] = read_usb_status) -> int:
    output = output or sys.stdout
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command in (None, "help"):
        parser.print_help(output)
        return 0
    if args.command == "network" and args.network_command == "status":
        lines, ok = _format_network(_safe_call(network, {"status": "UNAVAILABLE", "interfaces": []}))
        print("\n".join(lines), file=output)
        return 0 if ok else 1
    if args.command == "wifi" and args.wifi_command == "profiles":
        result = _safe_call(wifi, {"status": "UNAVAILABLE", "profiles": []})
        return 0 if _print_profiles(result, output) else 1
    if args.command == "usb" and args.usb_command == "status":
        result = _safe_call(usb, {"status": "UNAVAILABLE", "detail": "status USB niedostępny"})
        if result.get("status") != "OK":
            print(_status_line("USB", str(result.get("status", "ERROR")), str(result.get("detail", "brak danych"))), file=output)
            return 1
        print(_status_line("USB", "OK", "status dostępny"), file=output)
        values = result.get("values")
        if isinstance(values, dict):
            for key, value in values.items():
                print(f"  {key}: {value}", file=output)
        return 0
    if args.command == "usb" and args.usb_command == "mode":
        return change_usb_mode(args.mode, output=output)
    if args.command == "status":
        results = [
            _safe_call(health, {"status": "UNAVAILABLE", "detail": "health check niedostępny"}),
            _safe_call(network, {"status": "UNAVAILABLE", "interfaces": []}),
            _safe_call(wifi, {"status": "UNAVAILABLE", "profiles": []}),
            _safe_call(usb, {"status": "UNAVAILABLE", "detail": "status USB niedostępny"}),
        ]
        ok = results[0].get("status") == "OK"
        print(_status_line("Runtime", str(results[0].get("status", "ERROR")), results[0].get("detail", "brak danych")), file=output)
        network_lines, network_ok = _format_network(results[1])
        print("\n".join(network_lines), file=output)
        ok = ok and network_ok
        ok = _print_profiles(results[2], output) and ok
        usb_result = results[3]
        if usb_result.get("status") == "OK":
            print(_status_line("USB", "OK", "status dostępny"), file=output)
        else:
            print(_status_line("USB", str(usb_result.get("status", "ERROR")), str(usb_result.get("detail", "brak danych"))), file=output)
            ok = False
        return 0 if ok else 1
    parser.error("nieznane lub niepełne polecenie; użyj `pcdog help`")
    return 2


def main() -> None:
    raise SystemExit(run_cli())


if __name__ == "__main__":
    main()
