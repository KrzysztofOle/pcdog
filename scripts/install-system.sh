#!/usr/bin/env bash
# Install minimal operating-system dependencies for PcDog.

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=common.sh
source "$script_dir/common.sh"

usage() {
  cat <<'EOF'
Użycie: ./scripts/install-system.sh [--check]

Instaluje minimalne pakiety systemowe wymagane przez fundament PcDog.
--check tylko sprawdza ich obecność.
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

readonly REQUIRED_PACKAGES=(ca-certificates curl git)

require_command dpkg-query

packages_missing() {
  local package_name
  local missing=0

  for package_name in "${REQUIRED_PACKAGES[@]}"; do
    if ! dpkg-query --show --showformat='${db:Status-Status}' "$package_name" 2>/dev/null | grep --quiet '^installed$'; then
      log_error "Brakuje pakietu: ${package_name}"
      missing=1
    fi
  done

  return "$missing"
}

if "$check_only"; then
  if packages_missing; then
    log_success 'Wszystkie minimalne pakiety systemowe są obecne.'
    exit 0
  fi
  die 'Brakuje minimalnych pakietów. Uruchom bootstrap bez --check.'
fi

require_root
require_command apt-get

log_info 'Odświeżanie indeksu pakietów APT.'
apt-get update

log_info "Zapewnianie pakietów: ${REQUIRED_PACKAGES[*]}"
DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends "${REQUIRED_PACKAGES[@]}"

log_success 'Minimalne pakiety systemowe są gotowe.'
