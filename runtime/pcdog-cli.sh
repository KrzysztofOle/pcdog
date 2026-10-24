#!/usr/bin/env bash
# Read-only PcDog administration CLI.
set -eu
export PYTHONPATH='/opt/pcdog-cli/current'
exec /usr/bin/python3 -m pcdog_runtime.cli "$@"
