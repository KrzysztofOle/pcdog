#!/usr/bin/env bash
# Minimal PcDog runtime. It deliberately has no hardware or network access.

set -u

readonly RUNTIME_VERSION='pcdog-runtime-1'

stop_runtime() {
  printf 'PcDog runtime stopping (version=%s pid=%s)\n' "$RUNTIME_VERSION" "$$"
  exit 0
}

trap stop_runtime INT TERM

printf 'PcDog runtime started (version=%s pid=%s)\n' "$RUNTIME_VERSION" "$$"

while :; do
  sleep 3600 &
  wait "$!" || true
done
