#!/usr/bin/env bash
# Read-only PcDog administration CLI.
set -eu
export PYTHONPATH='/opt/pcdog/lib'
exec /usr/bin/python3 -m pcdog_runtime.cli "$@"
