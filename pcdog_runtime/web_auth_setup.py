"""Jawne, lokalne ustawienie hasła administratora panelu PcDog."""

from __future__ import annotations

import argparse
import getpass
import grp
import json
import os
from pathlib import Path
import tempfile
from typing import Sequence

from .web_auth import CONFIG_VERSION, WebAuthError, hash_password


DEFAULT_CONFIG = Path("/etc/pcdog/web-auth.json")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ustawia hasło administratora Web Panelu PcDog")
    parser.add_argument("command", choices=("set-password",))
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    return parser


def set_password(config: Path, password: str) -> None:
    if os.geteuid() != 0:
        raise WebAuthError("To polecenie wymaga uruchomienia przez sudo")
    config.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    payload = json.dumps({"version": CONFIG_VERSION, "password": hash_password(password)}, separators=(",", ":"))
    group_id = grp.getgrnam("pcdog").gr_gid
    descriptor, temporary = tempfile.mkstemp(prefix=".web-auth.", dir=config.parent, text=True)
    try:
        os.fchmod(descriptor, 0o640)
        os.fchown(descriptor, 0, group_id)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, config)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def main(arguments: Sequence[str] | None = None) -> None:
    options = build_parser().parse_args(arguments)
    first = getpass.getpass("Nowe hasło panelu PcDog: ")
    second = getpass.getpass("Powtórz hasło: ")
    if first != second:
        raise SystemExit("Hasła nie są identyczne")
    try:
        set_password(options.config, first)
    except WebAuthError as error:
        raise SystemExit(str(error)) from error
    print("Hasło panelu PcDog zostało zapisane. Zrestartuj usługę pcdog.")


if __name__ == "__main__":
    main()
