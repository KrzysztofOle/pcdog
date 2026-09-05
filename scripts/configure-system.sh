#!/usr/bin/env bash
# Create the minimal local state layout reserved for PcDog.

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=common.sh
source "$script_dir/common.sh"

usage() {
  cat <<'EOF'
Użycie: ./scripts/configure-system.sh [--check]

Tworzy katalogi systemowe zarezerwowane dla przyszłych komponentów PcDog.
--check tylko sprawdza ich stan.
EOF
}

check_only=false
if [[ $# -gt 1 ]]; then
  usage >&2
  exit 2
elif [[ $# -eq 1 ]]; then
  [[ "$1" = '--check' ]] || { usage >&2; exit 2; }
  check_only=true
fi

check_layout() {
  local path="$1"
  local expected_mode="$2"
  local actual_metadata

  [[ -d "$path" ]] || return 1
  actual_metadata="$(stat --format='%u:%g:%a' "$path")"
  [[ "$actual_metadata" = "0:0:${expected_mode}" ]]
}

if "$check_only"; then
  check_layout /etc/pcdog 755 || die 'Brakuje /etc/pcdog o trybie 755.'
  check_layout /var/lib/pcdog 750 || die 'Brakuje /var/lib/pcdog o trybie 750.'
  log_success 'Układ katalogów systemowych PcDog jest poprawny.'
  exit 0
fi

require_root

log_info 'Tworzenie /etc/pcdog (konfiguracja przyszłych komponentów).'
install --directory --owner=root --group=root --mode=755 /etc/pcdog

log_info 'Tworzenie /var/lib/pcdog (lokalny stan przyszłych komponentów).'
install --directory --owner=root --group=root --mode=750 /var/lib/pcdog

log_success 'Podstawowy układ katalogów PcDog jest gotowy.'
