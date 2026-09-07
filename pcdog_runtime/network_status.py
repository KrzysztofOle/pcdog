"""Odczyt NetworkManager bez skanowania, sekretów i zmian konfiguracji."""
import os
import subprocess


def read_network_status():
    try:
        result = subprocess.run(
            ["nmcli", "--terse", "--escape", "yes", "--fields",
             "GENERAL.DEVICE,GENERAL.TYPE,GENERAL.STATE,GENERAL.CONNECTION,IP4.ADDRESS,IP6.ADDRESS",
             "device", "show"],
            capture_output=True, text=True, check=True, timeout=2,
            env={**os.environ, "LC_ALL": "C"},
        )
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return {"status": "UNAVAILABLE", "interfaces": []}
    interfaces = []
    current = None
    for line in result.stdout.splitlines():
        key, separator, value = line.partition(":")
        if not separator:
            continue
        value = value.replace(r"\:", ":").replace(r"\\", "\\")
        if key == "GENERAL.DEVICE":
            current = {"name": value, "type": None, "state": None,
                       "connection": None, "addresses": []}
            interfaces.append(current)
        elif current is not None:
            field = {"GENERAL.TYPE": "type", "GENERAL.STATE": "state",
                     "GENERAL.CONNECTION": "connection"}.get(key)
            if field:
                current[field] = value if value and value != "--" else None
            elif key.startswith(("IP4.ADDRESS", "IP6.ADDRESS")) and value:
                current["addresses"].append(value)
    return {"status": "AVAILABLE" if interfaces else "UNAVAILABLE", "interfaces": interfaces}
