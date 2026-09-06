#!/usr/bin/env bash
# Install and reconcile ZeroTier without changing PcDog network interfaces.
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source "$script_dir/common.sh"
readonly zerotier_service="${PCDOG_ZEROTIER_SERVICE:-zerotier-one.service}"
readonly zerotier_config="${PCDOG_ZEROTIER_CONFIG_PATH:-/etc/pcdog/zerotier.conf}"
readonly zerotier_installer_url="${PCDOG_ZEROTIER_INSTALLER_URL:-https://install.zerotier.com}"
readonly zerotier_cli="${PCDOG_ZEROTIER_CLI:-zerotier-cli}"
usage() { cat <<'EOF'
Użycie: ./scripts/install-zerotier.sh [--check]

Instaluje i konfiguruje ZeroTier jako dodatkowy kanał łączności PcDog.
Network ID podaj przez PCDOG_ZEROTIER_NETWORK_ID albo /etc/pcdog/zerotier.conf.
--check nie wprowadza zmian ani nie wykonuje join.
EOF
}
check_only=false
if [[ $# -gt 1 ]]; then usage >&2; exit 2
elif [[ $# -eq 1 ]]; then [[ "$1" = '--check' ]] || { usage >&2; exit 2; }; check_only=true; fi
load_network_id() {
  local line
  if [[ -n "${PCDOG_ZEROTIER_NETWORK_ID:-}" ]]; then printf '%s\n' "$PCDOG_ZEROTIER_NETWORK_ID"; return; fi
  [[ -r "$zerotier_config" ]] || return 0
  line="$(sed -n 's/^PCDOG_ZEROTIER_NETWORK_ID=//p' "$zerotier_config" | tail -n 1)"
  printf '%s\n' "$line"
}
network_config_is_safe() {
  [[ ! -e "$zerotier_config" ]] && return 0
  [[ -f "$zerotier_config" ]] || return 1
  [[ "$(stat --format='%u:%g:%a' "$zerotier_config")" = '0:0:600' ]]
}
validate_network_id() { [[ "$1" =~ ^[[:xdigit:]]{16}$ ]]; }
zt() { "$zerotier_cli" "$@"; }
service_is_healthy() { systemctl is-enabled --quiet "$zerotier_service" && systemctl is-active --quiet "$zerotier_service" && zt status >/dev/null; }
network_line() { local network_id="$1"; zt listnetworks | awk -v id="$network_id" '$1 == "200" && $2 == "listnetworks" && tolower($3) == tolower(id) { print; exit }'; }
if "$check_only"; then
  require_command systemctl; require_command "$zerotier_cli"
  service_is_healthy || die 'ZeroTier nie jest włączony, aktywny lub zerotier-cli status kończy się błędem.'
  network_config_is_safe || die "Plik ${zerotier_config} musi być zwykłym plikiem root:root o trybie 600."
  network_id="$(load_network_id)"
  if [[ -n "$network_id" ]]; then
    validate_network_id "$network_id" || die 'Skonfigurowany ZeroTier Network ID ma nieprawidłowy format.'
    [[ -n "$(network_line "$network_id")" ]] || die 'ZeroTier działa, ale urządzenie nie należy do skonfigurowanej sieci.'
  fi
  log_success 'ZeroTier jest zainstalowany, włączony i aktywny.'; exit 0
fi
require_root; require_command curl; require_command systemctl
network_config_is_safe || die "Plik ${zerotier_config} musi być zwykłym plikiem root:root o trybie 600."
if ! command -v "$zerotier_cli" >/dev/null 2>&1; then
  log_info 'Instalowanie ZeroTier oficjalnym instalatorem dla Debian/Raspberry Pi OS.'
  curl --fail --silent --show-error --location "$zerotier_installer_url" | bash
else log_info 'ZeroTier jest już zainstalowany; reinstalacja nie jest potrzebna.'; fi
require_command "$zerotier_cli"
if ! systemctl is-enabled --quiet "$zerotier_service"; then log_info "Włączanie ${zerotier_service} do autostartu."; systemctl enable "$zerotier_service"; fi
if ! systemctl is-active --quiet "$zerotier_service"; then log_info "Uruchamianie ${zerotier_service}."; systemctl start "$zerotier_service"
else log_info "${zerotier_service} jest już aktywna; restart nie jest potrzebny."; fi
service_is_healthy || die 'ZeroTier nie przeszedł weryfikacji systemd lub zerotier-cli status.'
network_id="$(load_network_id)"
if [[ -z "$network_id" ]]; then log_info 'ZeroTier jest zainstalowany, ale Network ID nie został skonfigurowany; join pominięto.'; exit 0; fi
validate_network_id "$network_id" || die 'Skonfigurowany ZeroTier Network ID ma nieprawidłowy format.'
line="$(network_line "$network_id")"
if [[ -z "$line" ]]; then log_info 'Dołączanie urządzenia do skonfigurowanej sieci ZeroTier.'; zt join "$network_id" || die 'Join do sieci ZeroTier nie powiódł się.'; line="$(network_line "$network_id")"; fi
if [[ -z "$line" ]]; then log_info 'Żądanie join zostało wysłane; członkostwo nie jest jeszcze widoczne. Sprawdź później zerotier-status.sh.'
elif [[ "$(awk '{print $6}' <<<"$line")" = 'ACCESS_DENIED' ]]; then log_info 'Urządzenie oczekuje na ręczną autoryzację w panelu ZeroTier; nie będą wykonywane retry.'
elif [[ "$(awk '{print $6}' <<<"$line")" = 'OK' ]]; then log_success 'Urządzenie należy do skonfigurowanej sieci ZeroTier i jest aktywne.'
else log_info "Urządzenie należy do sieci, ale jej stan to $(awk '{print $6}' <<<"$line"); sprawdź zerotier-status.sh."; fi
