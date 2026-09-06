#!/usr/bin/env bash
# Read-only ZeroTier diagnostics for PcDog.
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source "$script_dir/common.sh"
readonly zerotier_service="${PCDOG_ZEROTIER_SERVICE:-zerotier-one.service}"
readonly zerotier_config="${PCDOG_ZEROTIER_CONFIG_PATH:-/etc/pcdog/zerotier.conf}"
readonly zerotier_cli="${PCDOG_ZEROTIER_CLI:-zerotier-cli}"
network_id="${PCDOG_ZEROTIER_NETWORK_ID:-}"
if [[ -z "$network_id" && -r "$zerotier_config" ]]; then network_id="$(sed -n 's/^PCDOG_ZEROTIER_NETWORK_ID=//p' "$zerotier_config" | tail -n 1)"; fi
printf 'ZeroTier installed: '
if command -v "$zerotier_cli" >/dev/null 2>&1; then printf 'yes\n'; printf 'ZeroTier version: '; "$zerotier_cli" -v || true; printf 'Node ID: '; "$zerotier_cli" info 2>/dev/null | awk '$1 == "200" && $2 == "info" { print $3; exit }'
else printf 'no\n'; exit 1; fi
printf 'Systemd enabled: '; systemctl is-enabled "$zerotier_service" 2>/dev/null || true
printf 'Systemd active: '; systemctl is-active "$zerotier_service" 2>/dev/null || true
printf 'CLI status: '; "$zerotier_cli" status || true
if [[ -n "$network_id" ]]; then
  printf 'Network ID: configured (hidden; supplied as deployment configuration)\n'
  line="$("$zerotier_cli" listnetworks | awk -v id="$network_id" '$1 == "200" && $2 == "listnetworks" && tolower($3) == tolower(id) { print; exit }')"
  if [[ -n "$line" ]]; then printf 'Membership status: %s\n' "$(awk '{print $6}' <<<"$line")"; printf 'ZeroTier address(es): %s\n' "$(awk '{for (i = 9; i <= NF; i++) printf "%s%s", (i == 9 ? "" : " "), $i; print ""}' <<<"$line")"
  else printf 'Membership status: not joined\n'; fi
else printf 'Network ID: not configured\nMembership status: not applicable\n'; fi
