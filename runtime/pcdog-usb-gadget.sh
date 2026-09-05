#!/usr/bin/env bash
# Create exactly one isolated CDC ECM gadget through ConfigFS.

set -euo pipefail

readonly gadget_dir=/sys/kernel/config/usb_gadget/pcdog
readonly config_dir="$gadget_dir/configs/c.1"
readonly function_dir="$gadget_dir/functions/ecm.usb0"
readonly function_link="$config_dir/ecm.usb0"

die() {
  printf 'pcdog-usb-gadget: %s\n' "$*" >&2
  exit 1
}

cleanup() {
  [[ -d "$gadget_dir" ]] || exit 0

  if [[ -e "$gadget_dir/UDC" ]]; then
    printf '' >"$gadget_dir/UDC"
  fi
  rm -f "$function_link"
  rmdir "$config_dir/strings/0x409" 2>/dev/null || true
  rmdir "$config_dir" 2>/dev/null || true
  rmdir "$function_dir" 2>/dev/null || true
  rmdir "$gadget_dir/strings/0x409" 2>/dev/null || true
  rmdir "$gadget_dir" 2>/dev/null || true
}

if [[ "${1:-}" = '--cleanup' ]]; then
  cleanup
  exit 0
fi
[[ $# -eq 0 ]] || die 'nieznana opcja'
modprobe libcomposite
[[ -d /sys/kernel/config/usb_gadget ]] || die 'ConfigFS USB gadget nie jest dostępny'

if [[ -e "$gadget_dir/UDC" ]] && [[ -n "$(<"$gadget_dir/UDC")" ]]; then
  exit 0
fi

# Do not alter a partially created or foreign gadget; cleanup is explicit.
[[ ! -e "$gadget_dir" ]] || die "istnieje nieaktywny lub niekompletny gadget: $gadget_dir"

# Resolve UDC before writing ConfigFS so a pre-reboot validation cannot leave
# behind a partial gadget on a host where dwc2 is not yet available.
udc="$(find /sys/class/udc -mindepth 1 -maxdepth 1 -printf '%f\n' | head -n 1)"
[[ -n "$udc" ]] || die 'brak dostępnego UDC'

mkdir "$gadget_dir"
printf '0x1d6b' >"$gadget_dir/idVendor"       # Linux Foundation
printf '0x0104' >"$gadget_dir/idProduct"      # Multifunction Composite Gadget
printf '0x0100' >"$gadget_dir/bcdDevice"
printf '0x0200' >"$gadget_dir/bcdUSB"
mkdir -p "$gadget_dir/strings/0x409"
printf 'PcDog1 USB service' >"$gadget_dir/strings/0x409/serialnumber"
printf 'PcDog' >"$gadget_dir/strings/0x409/manufacturer"
printf 'PcDog USB ECM service' >"$gadget_dir/strings/0x409/product"

mkdir -p "$config_dir/strings/0x409"
printf 'Isolated SSH service link' >"$config_dir/strings/0x409/configuration"
printf '250' >"$config_dir/MaxPower"

mkdir "$function_dir"
printf '%s' 'usb%d' >"$function_dir/ifname"
# Locally administered, stable addresses. The host uses host_addr.
printf '02:50:43:44:4f:47' >"$function_dir/dev_addr"
printf '02:50:43:44:4f:48' >"$function_dir/host_addr"
ln -s "$function_dir" "$function_link"
printf '%s' "$udc" >"$gadget_dir/UDC"
