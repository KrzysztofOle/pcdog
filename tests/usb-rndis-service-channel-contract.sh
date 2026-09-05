#!/usr/bin/env bash
# Static contracts for the Windows-only PcDog USB RNDIS service channel.

set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
gadget="$repo_dir/runtime/pcdog-usb-gadget.sh"
dhcp="$repo_dir/config/usb-dhcp.conf"
profile="$repo_dir/config/pcdog-usb0.nmconnection"
installer="$repo_dir/scripts/install-usb-service-channel.sh"
gadget_unit="$repo_dir/systemd/pcdog-usb-gadget.service"
dhcp_unit="$repo_dir/systemd/pcdog-usb-dhcp.service"

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

require_fixed_line() {
  local file="$1"
  local expected="$2"
  grep -Fqx -- "$expected" "$file" || fail "brakuje: $expected ($file)"
}

forbid() {
  local file="$1"
  local pattern="$2"
  ! grep -Eq -- "$pattern" "$file" || fail "niedozwolony wzorzec: $pattern ($file)"
}

# One RNDIS function, its configuration link, and the kernel-required ifname.
require_fixed_line "$gadget" 'readonly function_dir="$gadget_dir/functions/rndis.usb0"'
require_fixed_line "$gadget" 'readonly function_link="$config_dir/rndis.usb0"'
require_fixed_line "$gadget" "printf '%s' 'usb%d' >\"\$function_dir/ifname\""
require_fixed_line "$gadget" 'printf '\''02:50:43:44:4f:47'\'' >"$function_dir/dev_addr"'
require_fixed_line "$gadget" 'printf '\''02:50:43:44:4f:48'\'' >"$function_dir/host_addr"'
forbid "$gadget" 'functions/ecm\.|ecm\.usb0'

# IAD fields must use bare hexadecimal digits: ConfigFS misinterprets 0x forms.
require_fixed_line "$gadget" "printf 'ef' >\"\$function_dir/class\""
require_fixed_line "$gadget" "printf '04' >\"\$function_dir/subclass\""
require_fixed_line "$gadget" "printf '01' >\"\$function_dir/protocol\""
forbid "$gadget" "printf '0x(ef|04|01)' >\"\\\$function_dir/(class|subclass|protocol)\""

# Microsoft OS descriptors must advertise RNDIS and be tied to configuration c.1.
require_fixed_line "$gadget" "printf '1' >\"\$os_desc_dir/use\""
require_fixed_line "$gadget" "printf 'MSFT100' >\"\$os_desc_dir/qw_sign\""
require_fixed_line "$gadget" "printf '0xcd' >\"\$os_desc_dir/b_vendor_code\""
require_fixed_line "$gadget" "printf 'RNDIS' >\"\$function_dir/os_desc/interface.rndis/compatible_id\""
require_fixed_line "$gadget" "printf '5162001' >\"\$function_dir/os_desc/interface.rndis/sub_compatible_id\""
require_fixed_line "$gadget" 'ln -s "$function_dir" "$function_link"'
require_fixed_line "$gadget" 'ln -s "$config_dir" "$os_desc_config_link"'

# Network and DHCP remain an isolated /30 link with no USB DNS or gateway.
require_fixed_line "$profile" 'address1=172.23.254.1/30'
require_fixed_line "$profile" 'never-default=true'
forbid "$profile" '^dns='
require_fixed_line "$dhcp" 'interface=usb0'
require_fixed_line "$dhcp" 'bind-dynamic'
require_fixed_line "$dhcp" 'port=0'
require_fixed_line "$dhcp" 'no-resolv'
require_fixed_line "$dhcp" 'dhcp-range=172.23.254.2,172.23.254.2,255.255.255.252,1h'
require_fixed_line "$dhcp" 'dhcp-option=option:router'
forbid "$dhcp" '^dhcp-option=.*(router|3),.+'
forbid "$dhcp" '^dhcp-option=.*(dns-server|6),.+'

# Existing service boundaries remain intact: DHCP follows the gadget and both
# services stay independent from Wi-Fi and the application runtime.
require_fixed_line "$gadget_unit" 'Before=pcdog-usb-dhcp.service'
require_fixed_line "$dhcp_unit" 'Requires=pcdog-usb-gadget.service'
require_fixed_line "$dhcp_unit" 'ExecStartPre=/usr/bin/test -d /sys/class/net/usb0'

# The installer remains repeatable: preserve its original boot backup and add
# the DWC2 overlay only when it is absent.
require_fixed_line "$installer" 'if [[ ! -e "$backup_dir/config.txt.pre-usb-service" ]]; then'
require_fixed_line "$installer" "if ! grep -Fxq 'dtoverlay=dwc2,dr_mode=peripheral' \"\$boot_config\"; then"

printf 'PASS: Windows RNDIS service channel contracts\n'
