#!/usr/bin/env bash
# Root-only, local service diagnostic. It is deliberately not an IPC or Web API.
set -eu
export PYTHONPATH='/opt/pcdog/lib'
exec /usr/bin/python3 -m pcdog_runtime.diagnostic_controls "$@"
