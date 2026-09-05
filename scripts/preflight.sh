#!/usr/bin/env bash
# Validate that this host is a supported PcDog target without changing it.

set -euo pipefail

usage() {
  cat <<'EOF'
Użycie: ./scripts/preflight.sh [--check]

Sprawdza, bez dokonywania zmian, czy host jest obsługiwanym celem PcDog.
EOF
}

if [[ $# -gt 1 ]]; then
  usage >&2
  exit 2
fi

if [[ $# -eq 1 && "$1" != "--check" ]]; then
  usage >&2
  exit 2
fi

readonly EXPECTED_ARCHITECTURE_REGEX='^(aarch64|arm64)$'
readonly EXPECTED_MODEL='Raspberry Pi Zero 2 W'

failures=0

check() {
  local description="$1"
  shift

  if "$@"; then
    printf '[ OK ] %s\n' "$description"
  else
    printf '[ERR ] %s\n' "$description" >&2
    failures=$((failures + 1))
  fi
}

has_raspberry_pi_repository() {
  grep --recursive --quiet --include='*.list' --include='*.sources' \
    'archive\.raspberrypi\.com/debian' /etc/apt/sources.list /etc/apt/sources.list.d 2>/dev/null
}

read_pi_model() {
  if [[ -r /proc/device-tree/model ]]; then
    tr -d '\000' </proc/device-tree/model
  elif [[ -r /proc/cpuinfo ]]; then
    awk -F ': ' '/^Model/ { print $2; exit }' /proc/cpuinfo
  fi
}

printf 'PcDog preflight (tryb tylko do odczytu)\n'

check 'dostępne jest /etc/os-release' test -r /etc/os-release

if [[ -r /etc/os-release ]]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  check 'bazowy system to Debian' test "${ID:-}" = 'debian'
else
  printf '[ERR ] Nie można określić systemu operacyjnego.\n' >&2
  failures=$((failures + 1))
fi

check 'skonfigurowano oficjalne repozytorium Raspberry Pi OS' has_raspberry_pi_repository

architecture="$(uname -m)"
check "architektura ${architecture} jest 64-bit ARM" grep --quiet --extended-regexp "$EXPECTED_ARCHITECTURE_REGEX" <<<"$architecture"

model="$(read_pi_model)"
if [[ -n "$model" ]]; then
  check "model to ${EXPECTED_MODEL} (wykryto: ${model})" grep --fixed-strings --quiet "$EXPECTED_MODEL" <<<"$model"
else
  printf '[ERR ] Nie można odczytać modelu Raspberry Pi.\n' >&2
  failures=$((failures + 1))
fi

if (( failures > 0 )); then
  printf 'Preflight niezaliczony: %d problem(y). Instalacja nie zostanie uruchomiona.\n' "$failures" >&2
  exit 1
fi

printf 'Preflight zaliczony: host jest obsługiwanym celem PcDog.\n'
