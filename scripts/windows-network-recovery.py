#!/usr/bin/env python3
"""Manual Windows network diagnostics and guarded level-1 recovery via USB."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pcdog_runtime.windows_network_recovery import (
    DEFAULT_DNS_NAME,
    DEFAULT_INTERNET_TARGET,
    SERVICE_ADDRESS,
    ExitCode,
    STATUS_CODES,
    SshRunner,
    Timing,
    diagnostic,
    recover,
)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--ssh-user", required=True, help="konto administratora Windows używane przez SSH")
    result.add_argument("--ssh-host", default=SERVICE_ADDRESS, help=f"host SSH Windows (domyślnie {SERVICE_ADDRESS})")
    result.add_argument("--identity-file", type=Path, default=Path.home() / ".ssh" / "pcdog_windows_ed25519", help="dedykowany klucz SSH PcDog")
    result.add_argument("--adapter", required=True, help="jawny alias docelowego adaptera internetowego Windows")
    result.add_argument("--recover", action="store_true", help="jawnie wykonaj recovery Level 1")
    result.add_argument("--internet-target", default=DEFAULT_INTERNET_TARGET)
    result.add_argument("--dns-name", default=DEFAULT_DNS_NAME)
    result.add_argument("--initial-delay", type=float, default=10.0)
    result.add_argument("--retry-interval", type=float, default=5.0)
    result.add_argument("--timeout", type=float, default=60.0)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    timing = Timing(args.initial_delay, args.retry_interval, args.timeout)
    try:
        timing.validate()
    except ValueError as exc:
        print(json.dumps({"status": "INVALID_ARGUMENT", "error": str(exc)}))
        return int(ExitCode.INVALID_ARGUMENT)
    runner = SshRunner(args.ssh_user, args.ssh_host, args.identity_file.expanduser())
    if args.recover:
        status, snapshot = recover(runner, args.adapter, args.internet_target, args.dns_name, timing)
    else:
        status, snapshot = diagnostic(runner, args.adapter, args.internet_target, args.dns_name)
    print(json.dumps({"status": status, "snapshot": snapshot}, sort_keys=True))
    return int(STATUS_CODES[status])


if __name__ == "__main__":
    sys.exit(main())
