#!/usr/bin/env bash
# Select and inspect the persistent PcDog USB Service Channel host mode.

set -euo pipefail

readonly mode_file=/etc/pcdog/usb-mode.conf
readonly default_mode=windows
readonly gadget_dir=/sys/kernel/config/usb_gadget/pcdog
readonly gadget_service=pcdog-usb-gadget.service
readonly dhcp_service=pcdog-usb-dhcp.service

die() {
  printf 'pcdog-usb-mode: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Użycie: pcdog-usb-mode {windows|mac|status}

windows  Ustawia RNDIS dla Windows.
mac      Ustawia ECM dla macOS.
status   Pokazuje trwałą konfigurację i bieżący stan gadgetu.
EOF
}

configured_mode() {
  if [[ ! -e "$mode_file" ]]; then
    printf '%s\n' "$default_mode"
    return
  fi

  case "$(<"$mode_file")" in
    mode=windows) printf '%s\n' windows ;;
    mode=mac) printf '%s\n' mac ;;
    *) die "nieprawidłowa konfiguracja trybu USB: $mode_file" ;;
  esac
}

active_function() {
  if [[ -d "$gadget_dir/functions/rndis.usb0" ]]; then
    printf '%s\n' rndis.usb0
  elif [[ -d "$gadget_dir/functions/ecm.usb0" ]]; then
    printf '%s\n' ecm.usb0
  else
    printf '%s\n' none
  fi
}

udc_bound() {
  [[ -r "$gadget_dir/UDC" ]] && [[ -n "$(<"$gadget_dir/UDC")" ]]
}

status() {
  printf 'configured mode: %s\n' "$(configured_mode)"
  printf 'active USB function: %s\n' "$(active_function)"
  if udc_bound; then
    printf 'UDC bound: %s\n' "$(<"$gadget_dir/UDC")"
  else
    printf 'UDC bound: no\n'
  fi
  printf 'usb0 state: '
  ip -brief link show usb0 2>/dev/null || printf 'absent\n'
  printf 'PcDog1 USB IPv4: '
  ip -4 -brief addr show usb0 2>/dev/null || printf 'absent\n'
}

write_mode() {
  local requested_mode="$1"
  local temporary

  install --directory --owner=root --group=root --mode=755 /etc/pcdog
  temporary="$(mktemp "${mode_file}.XXXXXX")"
  printf 'mode=%s\n' "$requested_mode" >"$temporary"
  chown root:root "$temporary"
  chmod 644 "$temporary"
  mv -f "$temporary" "$mode_file"
}

set_mode() {
  local requested_mode="$1"
  local previous_mode expected_function
  previous_mode="$(configured_mode)"
  case "$requested_mode" in
    windows) expected_function=rndis.usb0 ;;
    mac) expected_function=ecm.usb0 ;;
    *) die "nieobsługiwany tryb USB: $requested_mode" ;;
  esac

  if [[ "$previous_mode" = "$requested_mode" ]] && \
     [[ "$(active_function)" = "$expected_function" ]] && udc_bound; then
    printf 'Tryb USB %s jest już aktywny.\n' "$requested_mode"
    status
    return
  fi

  write_mode "$requested_mode"
  if ! systemctl restart "$gadget_service"; then
    write_mode "$previous_mode"
    systemctl restart "$gadget_service" || true
    die "nie udało się przełączyć USB na $requested_mode; przywrócono $previous_mode"
  fi
  systemctl is-active --quiet "$gadget_service" || die 'usługa gadgetu nie jest aktywna'
  systemctl is-active --quiet "$dhcp_service" || die 'usługa DHCP nie jest aktywna'
  status
}

[[ $# -eq 1 ]] || { usage >&2; exit 2; }
case "$1" in
  status) status ;;
  windows|mac)
    [[ $EUID -eq 0 ]] || die 'zmiana trybu wymaga root; użyj sudo pcdog-usb-mode <tryb>'
    set_mode "$1"
    ;;
  *) usage >&2; exit 2 ;;
esac
