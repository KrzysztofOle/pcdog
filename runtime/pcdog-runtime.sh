#!/usr/bin/env bash
# Read-only PcDog runtime. It deliberately has no GPIO or PC control access.

set -eu

readonly RUNTIME_LIBRARY='/opt/pcdog/lib'
readonly RUNTIME_DATABASE='/var/lib/pcdog-runtime/pcdog.sqlite3'

export PYTHONPATH="$RUNTIME_LIBRARY"
exec /usr/bin/python3 -m pcdog_runtime.read_only_runtime \
  --database "$RUNTIME_DATABASE" \
  --host 0.0.0.0 \
  --port 8080
