#!/usr/bin/env bash
# Verify the completed Phase 1 PcDog system foundation.

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=common.sh
source "$script_dir/common.sh"

usage() {
  cat <<'EOF'
Użycie: ./scripts/verify-installation.sh [--check]

Weryfikuje bez modyfikacji preflight, pakiety i układ katalogów PcDog.
EOF
}

if [[ $# -gt 1 ]]; then
  usage >&2
  exit 2
elif [[ $# -eq 1 && "$1" != '--check' ]]; then
  usage >&2
  exit 2
fi

log_info 'Weryfikacja obsługiwanego środowiska.'
"$script_dir/preflight.sh" --check

log_info 'Weryfikacja minimalnych pakietów systemowych.'
"$script_dir/install-system.sh" --check

log_info 'Weryfikacja układu katalogów systemowych.'
"$script_dir/configure-system.sh" --check

log_success 'Instalacja fundamentu PcDog została zweryfikowana.'
