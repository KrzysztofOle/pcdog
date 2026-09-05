#!/usr/bin/env bash
# Stage the PcDog USB service channel without starting it in the current boot.

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=common.sh
source "$script_dir/common.sh"

readonly boot_config=/boot/firmware/config.txt
readonly backup_dir=/var/lib/pcdog/usb-service-channel-backup
readonly gadget_script=/usr/local/lib/pcdog/pcdog-usb-gadget
readonly gadget_unit=/etc/systemd/system/pcdog-usb-gadget.service
readonly dhcp_unit=/etc/systemd/system/pcdog-usb-dhcp.service
readonly dhcp_config=/etc/pcdog/usb-dhcp.conf
readonly nm_profile=/etc/NetworkManager/system-connections/pcdog-usb0.nmconnection
readonly mode_config=/etc/pcdog/usb-mode.conf
readonly mode_command=/usr/local/sbin/pcdog-usb-mode

usage() {
  cat <<'EOF'
Użycie: sudo ./scripts/install-usb-service-channel.sh [--check]

Bez argumentów zapisuje konfigurację USB Service Channel do użycia po następnym,
zatwierdzonym reboocie. Nie uruchamia gadgetu, DHCP ani NetworkManager.
--check tylko weryfikuje przygotowane pliki.
EOF
}

check_only=false
if [[ $# -gt 1 ]]; then
  usage >&2; exit 2
elif [[ $# -eq 1 ]]; then
  [[ "$1" = '--check' ]] || { usage >&2; exit 2; }
  check_only=true
fi

check() {
  [[ -x "$gadget_script" ]] || die "Brakuje $gadget_script"
  [[ -x "$mode_command" ]] || die "Brakuje $mode_command"
  [[ -f "$gadget_unit" && -f "$dhcp_unit" ]] || die 'Brakuje unitów USB.'
  [[ -f "$dhcp_config" && -f "$nm_profile" && -f "$mode_config" ]] || die 'Brakuje konfiguracji USB.'
  grep -Fxq 'mode=windows' "$mode_config" || grep -Fxq 'mode=mac' "$mode_config" || die 'Nieprawidłowy tryb USB.'
  /usr/sbin/dnsmasq --test --conf-file="$dhcp_config"
  systemd-analyze verify "$gadget_unit" "$dhcp_unit"
  grep -Fxq 'dtoverlay=dwc2,dr_mode=peripheral' "$boot_config" || die 'Brakuje overlay dwc2.'
  [[ "$(nmcli -g connection.interface-name connection show pcdog-usb0)" = 'usb0' ]] || die 'Profil NetworkManager usb0 nie jest załadowany.'
  systemctl is-enabled pcdog-usb-gadget.service >/dev/null
  systemctl is-enabled pcdog-usb-dhcp.service >/dev/null
  log_success 'Konfiguracja USB service channel jest poprawnie przygotowana i oczekuje na reboot.'
}

if "$check_only"; then
  check
  exit 0
fi

require_root
require_command install
require_command systemctl
require_command nmcli
require_command dnsmasq
[[ -r "$boot_config" ]] || die "Brakuje aktywnego pliku boot: $boot_config"

install --directory --owner=root --group=root --mode=750 "$backup_dir"
if [[ ! -e "$backup_dir/config.txt.pre-usb-service" ]]; then
  install --owner=root --group=root --mode=600 "$boot_config" "$backup_dir/config.txt.pre-usb-service"
fi

if ! grep -Fxq 'dtoverlay=dwc2,dr_mode=peripheral' "$boot_config"; then
  printf '\n# PcDog USB service gadget (applies to this Pi Zero 2 W host).\ndtoverlay=dwc2,dr_mode=peripheral\n' >>"$boot_config"
fi

install --directory --owner=root --group=root --mode=755 /usr/local/lib/pcdog
install --owner=root --group=root --mode=755 "$script_dir/../runtime/pcdog-usb-gadget.sh" "$gadget_script"
install --directory --owner=root --group=root --mode=755 /usr/local/sbin
install --owner=root --group=root --mode=755 "$script_dir/../runtime/pcdog-usb-mode.sh" "$mode_command"
install --owner=root --group=root --mode=644 "$script_dir/../systemd/pcdog-usb-gadget.service" "$gadget_unit"
install --owner=root --group=root --mode=644 "$script_dir/../systemd/pcdog-usb-dhcp.service" "$dhcp_unit"
install --owner=root --group=root --mode=644 "$script_dir/../config/usb-dhcp.conf" "$dhcp_config"
if [[ ! -e "$mode_config" ]]; then
  install --owner=root --group=root --mode=644 "$script_dir/../config/usb-mode.conf" "$mode_config"
fi
install --directory --owner=root --group=root --mode=700 /etc/NetworkManager/system-connections
install --owner=root --group=root --mode=600 "$script_dir/../config/pcdog-usb0.nmconnection" "$nm_profile"
install --owner=root --group=root --mode=640 /dev/null /var/lib/pcdog/usb-dhcp.leases

nmcli connection load "$nm_profile"
systemctl daemon-reload
systemctl enable pcdog-usb-gadget.service pcdog-usb-dhcp.service

check
log_success 'USB service channel zapisany. Nie został uruchomiony w bieżącym boocie.'
