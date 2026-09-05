#!/usr/bin/env bash
# Create exactly one selected USB Ethernet gadget through ConfigFS.

set -euo pipefail

readonly gadget_dir=/sys/kernel/config/usb_gadget/pcdog
readonly config_dir="$gadget_dir/configs/c.1"
readonly mode_file=/etc/pcdog/usb-mode.conf
readonly default_mode=windows
readonly rndis_function_dir="$gadget_dir/functions/rndis.usb0"
readonly ecm_function_dir="$gadget_dir/functions/ecm.usb0"
readonly rndis_function_link="$config_dir/rndis.usb0"
readonly ecm_function_link="$config_dir/ecm.usb0"
readonly os_desc_dir="$gadget_dir/os_desc"
readonly os_desc_config_link="$os_desc_dir/c.1"

die() {
  printf 'pcdog-usb-gadget: %s\n' "$*" >&2
  exit 1
}

configured_mode() {
  if [[ ! -e "$mode_file" ]]; then
    printf '%s\n' "$default_mode"
    return
  fi

  local mode
  mode="$(<"$mode_file")"
  case "$mode" in
    mode=windows) printf '%s\n' windows ;;
    mode=mac) printf '%s\n' mac ;;
    *) die "nieprawidłowa konfiguracja trybu USB: $mode_file" ;;
  esac
}

cleanup() {
  [[ -d "$gadget_dir" ]] || exit 0

  if [[ -e "$gadget_dir/UDC" ]]; then
    printf '' >"$gadget_dir/UDC"
  fi
  rm -f "$os_desc_config_link" "$rndis_function_link" "$ecm_function_link"
  rmdir "$config_dir/strings/0x409" 2>/dev/null || true
  rmdir "$config_dir" 2>/dev/null || true
  rmdir "$rndis_function_dir" 2>/dev/null || true
  rmdir "$ecm_function_dir" 2>/dev/null || true
  rmdir "$gadget_dir/strings/0x409" 2>/dev/null || true
  rmdir "$gadget_dir" 2>/dev/null || true
}

if [[ "${1:-}" = '--cleanup' ]]; then
  cleanup
  exit 0
fi
[[ $# -eq 0 ]] || die 'nieznana opcja'
mode="$(configured_mode)"

modprobe libcomposite
[[ -d /sys/kernel/config/usb_gadget ]] || die 'ConfigFS USB gadget nie jest dostępny'

if [[ -e "$gadget_dir/UDC" ]] && [[ -n "$(<"$gadget_dir/UDC")" ]]; then
  exit 0
fi

# Do not alter a partially created or foreign gadget; cleanup is explicit.
[[ ! -e "$gadget_dir" ]] || die "istnieje nieaktywny lub niekompletny gadget: $gadget_dir"

# Resolve UDC before writing ConfigFS so an unavailable controller cannot leave
# a partial gadget behind.
udc="$(find /sys/class/udc -mindepth 1 -maxdepth 1 -printf '%f\n' | head -n 1)"
[[ -n "$udc" ]] || die 'brak dostępnego UDC'

mkdir "$gadget_dir"
printf '0x1d6b' >"$gadget_dir/idVendor"       # Linux Foundation
printf '0x0104' >"$gadget_dir/idProduct"      # Existing verified VID/PID
printf '0x0100' >"$gadget_dir/bcdDevice"
printf '0x0200' >"$gadget_dir/bcdUSB"
mkdir -p "$gadget_dir/strings/0x409"
printf 'PcDog1 USB service' >"$gadget_dir/strings/0x409/serialnumber"
printf 'PcDog' >"$gadget_dir/strings/0x409/manufacturer"

mkdir -p "$config_dir/strings/0x409"
printf 'Isolated SSH service link' >"$config_dir/strings/0x409/configuration"
printf '250' >"$config_dir/MaxPower"

case "$mode" in
  windows)
    function_dir="$rndis_function_dir"
    function_link="$rndis_function_link"
    printf 'PcDog USB RNDIS service' >"$gadget_dir/strings/0x409/product"
    mkdir "$function_dir"
    printf '%s' 'usb%d' >"$function_dir/ifname"
    printf '02:50:43:44:4f:47' >"$function_dir/dev_addr"
    printf '02:50:43:44:4f:48' >"$function_dir/host_addr"
    # ConfigFS needs bare hexadecimal digits; 0x-prefixed values produced 00.
    printf 'ef' >"$function_dir/class"
    printf '04' >"$function_dir/subclass"
    printf '01' >"$function_dir/protocol"
    printf '1' >"$os_desc_dir/use"
    printf 'MSFT100' >"$os_desc_dir/qw_sign"
    printf '0xcd' >"$os_desc_dir/b_vendor_code"
    printf 'RNDIS' >"$function_dir/os_desc/interface.rndis/compatible_id"
    printf '5162001' >"$function_dir/os_desc/interface.rndis/sub_compatible_id"
    ln -s "$function_dir" "$function_link"
    ln -s "$config_dir" "$os_desc_config_link"
    ;;
  mac)
    function_dir="$ecm_function_dir"
    function_link="$ecm_function_link"
    printf 'PcDog USB ECM service' >"$gadget_dir/strings/0x409/product"
    mkdir "$function_dir"
    printf '%s' 'usb%d' >"$function_dir/ifname"
    printf '02:50:43:44:4f:47' >"$function_dir/dev_addr"
    printf '02:50:43:44:4f:48' >"$function_dir/host_addr"
    # ECM intentionally has no Microsoft OS descriptor configuration.
    ln -s "$function_dir" "$function_link"
    ;;
  *) die "nieobsługiwany tryb USB: $mode" ;;
esac

printf '%s' "$udc" >"$gadget_dir/UDC"
