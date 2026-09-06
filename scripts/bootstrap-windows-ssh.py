#!/usr/bin/env python3
"""Ręczny, idempotentny bootstrap klucza SSH PcDog -> Windows przez USB."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pcdog_runtime.windows_ssh_bootstrap import DEFAULT_HOST, BootstrapError, bootstrap


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--ssh-user", required=True, help="konto Windows używane przez SSH")
    result.add_argument("--ssh-host", default=DEFAULT_HOST, help=f"host SSH Windows (domyślnie {DEFAULT_HOST})")
    result.add_argument("--key-path", type=Path, default=Path.home() / ".ssh" / "pcdog_windows_ed25519")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        outcome, pair = bootstrap(args.ssh_user, args.ssh_host, args.key_path.expanduser())
        if outcome == "already_configured":
            print(f"PASS: key auth already works; key={pair.private}; state={pair.state}")
            return 0
        print(f"PASS: key auth configured; key={pair.private}; state={pair.state}")
        return 0
    except BootstrapError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
