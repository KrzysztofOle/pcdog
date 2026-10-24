"""Guarded delegation to the installed privileged USB mode switch."""

from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from typing import TextIO


USB_MODE = "/usr/local/sbin/pcdog-usb-mode"
SUDO = "/usr/bin/sudo"
USB_HOST = "172.23.254.2"
USB_DEVICE = "172.23.254.1"


def _route(destination: str, source: str | None = None) -> dict[str, object] | None:
    command = ["/usr/sbin/ip", "-j", "route", "get", destination]
    if source:
        command.extend(("from", source))
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=3, check=False)
        routes = json.loads(result.stdout) if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(routes, list) or len(routes) != 1 or not isinstance(routes[0], dict):
        return None
    return routes[0]


def _ssh_addresses(value: str | None) -> tuple[str, str] | None:
    if not value:
        return None
    fields = value.split()
    if len(fields) != 4:
        return None
    try:
        client, server = ipaddress.ip_address(fields[0]), ipaddress.ip_address(fields[2])
        if client.version != 4 or server.version != 4:
            return None
        if not (fields[1].isdigit() and fields[3].isdigit() and 1 <= int(fields[1]) <= 65535 and 1 <= int(fields[3]) <= 65535):
            return None
        return str(client), str(server)
    except ValueError:
        return None


def _session_uses_usb() -> tuple[bool | None, str]:
    addresses = _ssh_addresses(os.environ.get("SSH_CONNECTION"))
    if addresses is None:
        return None, "brak wiarygodnego SSH_CONNECTION; zmiana USB zablokowana"
    client, server = addresses
    session = _route(client, server)
    usb = _route(USB_HOST)
    if session is None or usb is None:
        return None, "nie można wiarygodnie ustalić tras SSH i USB; zmiana zablokowana"
    session_dev = session.get("dev")
    # iproute2 can report the explicitly requested source as `from` rather
    # than `src`/`prefsrc` when route get was constrained with `from ADDRESS`.
    session_src = session.get("src") or session.get("prefsrc") or session.get("from")
    usb_dev = usb.get("dev")
    usb_src = usb.get("src") or usb.get("prefsrc") or usb.get("from")
    if not isinstance(session_dev, str) or not isinstance(session_src, str) or not isinstance(usb_dev, str):
        return None, "trasa SSH lub USB nie zawiera wymaganych danych; zmiana zablokowana"
    try:
        if ipaddress.ip_address(session_src) != ipaddress.ip_address(server):
            return None, "adres źródłowy trasy nie odpowiada aktywnej sesji SSH; zmiana zablokowana"
        if ipaddress.ip_address(usb_src) != ipaddress.ip_address(USB_DEVICE):
            return None, "trasa USB nie wskazuje skonfigurowanego adresu PcDog; zmiana zablokowana"
    except (ValueError, TypeError):
        return None, "niejednoznaczne adresy tras SSH lub USB; zmiana zablokowana"
    if usb.get("gateway") or usb.get("via"):
        return None, "trasa do hosta USB przechodzi przez bramę; zmiana zablokowana"
    if usb.get("dst") not in (None, USB_HOST):
        return None, "trasa zwróciła inny cel USB; zmiana zablokowana"
    if session_dev == usb_dev:
        return True, f"sesja SSH przebiega przez USB ({session_dev}); zmiana zablokowana"
    return False, f"sesja SSH używa {session_dev}, a USB jest na {usb_dev}"


def change_usb_mode(mode: str, *, output: TextIO = sys.stdout) -> int:
    """Check the live SSH route, then invoke the existing root-owned switcher."""
    if mode not in {"windows", "mac"}:
        print("USB: ODMOWA — obsługiwane tryby to windows i mac", file=output)
        return 2
    uses_usb, detail = _session_uses_usb()
    if uses_usb is not False:
        print(f"USB: ODMOWA — {detail}", file=output)
        return 1
    switcher = Path(USB_MODE)
    try:
        info = switcher.lstat()
    except OSError:
        info = None
    if (info is None or not stat.S_ISREG(info.st_mode) or info.st_uid != 0
            or not os.access(switcher, os.X_OK)):
        print(f"USB: NIEDOSTĘPNE — brak wykonywalnego {USB_MODE}", file=output)
        return 1
    command = [USB_MODE, mode] if os.geteuid() == 0 else [SUDO, "--", USB_MODE, mode]
    try:
        result = subprocess.run(command, check=False)
    except (OSError, subprocess.SubprocessError):
        print("USB: BŁĄD — nie można uruchomić przełącznika trybu", file=output)
        return 1
    if result.returncode:
        if result.returncode == 126 or result.returncode == 127:
            detail = "brak uprawnień lub wymaganej zależności; tryb nie został potwierdzony"
        else:
            detail = (f"odmowa uprawnień albo błąd pcdog-usb-mode "
                      f"(kod {result.returncode}); tryb nie został potwierdzony")
        print(f"USB: BŁĄD — {detail}", file=output)
        return 1
    print(f"USB: OK — zlecono tryb {mode}; kanał SSH został rozpoznany poza USB", file=output)
    return 0
