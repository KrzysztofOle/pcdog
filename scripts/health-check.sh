#!/usr/bin/env bash
# Run the installed local PcDog health check without modifying the system.

set -euo pipefail

readonly HEALTH_CHECK_PATH='/opt/pcdog/bin/pcdog-healthcheck'

if [[ ! -x "$HEALTH_CHECK_PATH" ]]; then
  printf 'UNHEALTHY: nie zainstalowano %s\n' "$HEALTH_CHECK_PATH" >&2
  exit 1
fi

exec "$HEALTH_CHECK_PATH"
