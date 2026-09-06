#!/usr/bin/env bash
# Local health check for the systemd-managed PcDog runtime.

set -euo pipefail

readonly SERVICE_NAME='pcdog.service'
readonly RUNTIME_MODULE='pcdog_runtime.read_only_runtime'

unhealthy() {
  printf 'UNHEALTHY: %s\n' "$*" >&2
  exit 1
}

if ! systemctl is-active --quiet "$SERVICE_NAME"; then
  unhealthy "${SERVICE_NAME} is not active"
fi

main_pid="$(systemctl show --property=MainPID --value "$SERVICE_NAME")"
if [[ ! "$main_pid" =~ ^[1-9][0-9]*$ ]]; then
  unhealthy "${SERVICE_NAME} has no main process"
fi

command_line_path="/proc/${main_pid}/cmdline"
if [[ ! -r "$command_line_path" ]]; then
  unhealthy "main process ${main_pid} is not readable"
fi

command_line="$(tr '\000' ' ' <"$command_line_path")"
if [[ "$command_line" != *"$RUNTIME_MODULE"* ]]; then
  unhealthy "main process ${main_pid} is not the PcDog runtime"
fi

printf 'HEALTHY\n'
