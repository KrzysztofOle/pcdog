#!/usr/bin/env bash
# Main entry point for setting up a supported Raspberry Pi as a PcDog host.

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=common.sh
source "$script_dir/common.sh"

usage() {
  cat <<'EOF'
Użycie: sudo ./scripts/bootstrap.sh [--check]

Uruchamia instalację fundamentu PcDog na Raspberry Pi Zero 2 W z Raspberry Pi OS.
--check wykonuje wyłącznie weryfikację i nie wprowadza zmian.
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

if "$check_only"; then
  log_info 'Uruchamianie preflightu bez zmian.'
  "$script_dir/preflight.sh" --check
  if [[ -e /etc/systemd/system/pcdog.service || -e /opt/pcdog ]] || getent passwd pcdog >/dev/null 2>&1; then
    log_info 'Weryfikacja istniejącego runtime PcDog bez zmian.'
    "$script_dir/install-runtime.sh" --check
  else
    log_info 'Runtime PcDog nie jest jeszcze zainstalowany; zwykły bootstrap go przygotuje.'
  fi
  if command -v zerotier-cli >/dev/null 2>&1 || [[ -e /etc/systemd/system/zerotier-one.service ]]; then
    log_info 'Weryfikacja istniejącej instalacji ZeroTier bez zmian.'
    "$script_dir/install-zerotier.sh" --check
  fi
  log_success 'Środowisko spełnia warunki rozpoczęcia bootstrapu.'
  exit 0
fi

require_root

log_info 'Etap 1/6: preflight środowiska.'
"$script_dir/preflight.sh"

log_info 'Etap 2/6: minimalne pakiety systemowe.'
"$script_dir/install-system.sh"

log_info 'Etap 3/6: konfiguracja fundamentu systemowego.'
"$script_dir/configure-system.sh"

log_info 'Etap 4/6: ZeroTier jako dodatkowy kanał łączności.'
"$script_dir/install-zerotier.sh"

log_info 'Etap 5/6: runtime PcDog i usługa systemd.'
"$script_dir/install-runtime.sh"

log_info 'Etap 6/6: weryfikacja instalacji.'
"$script_dir/verify-installation.sh"

log_success 'Bootstrap PcDog zakończony powodzeniem.'
