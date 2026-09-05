#!/usr/bin/env bash
# Shared helpers for PcDog installation scripts. This file is sourced.

set -euo pipefail

log_info() {
  printf '[INFO] %s\n' "$*"
}

log_success() {
  printf '[ OK ] %s\n' "$*"
}

log_error() {
  printf '[ERR ] %s\n' "$*" >&2
}

die() {
  log_error "$*"
  exit 1
}

require_root() {
  if [[ "$(id -u)" -ne 0 ]]; then
    die 'Ten etap wymaga uprawnień root. Uruchom go przez sudo.'
  fi
}

require_command() {
  local command_name="$1"

  command -v "$command_name" >/dev/null 2>&1 || die "Brakuje wymaganego polecenia: ${command_name}"
}
