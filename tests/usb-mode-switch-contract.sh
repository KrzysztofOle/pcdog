#!/usr/bin/env bash
# Static contracts for the explicit PcDog USB Service Channel mode switch.

set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
gadget="$repo_dir/runtime/pcdog-usb-gadget.sh"
switcher="$repo_dir/runtime/pcdog-usb-mode.sh"
mode_config="$repo_dir/config/usb-mode.conf"
dhcp="$repo_dir/config/usb-dhcp.conf"
profile="$repo_dir/config/pcdog-usb0.nmconnection"
installer="$repo_dir/scripts/install-usb-service-channel.sh"

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

require_fixed_line() {
  local file="$1"
  local expected="$2"
  grep -Fq -- "$expected" "$file" || fail "brakuje: $expected ($file)"
}

require_text() {
  local file="$1"
  local expected="$2"
  grep -Fq -- "$expected" "$file" || fail "brakuje tekstu: $expected ($file)"
}

forbid() {
  local file="$1"
  local pattern="$2"
  ! grep -Eq -- "$pattern" "$file" || fail "niedozwolony wzorzec: $pattern ($file)"
}

# Persistent configuration supports only the two explicit host modes. Existing
# installations default to Windows when the file is not yet present.
require_fixed_line "$mode_config" 'mode=windows'
require_fixed_line "$gadget" 'readonly default_mode=windows'
require_text "$gadget" 'mode=windows)'
require_text "$gadget" 'mode=mac)'
forbid "$gadget" 'mode=(auto|universal)'

# Windows: one RNDIS function, bare IAD hexadecimal digits and OS descriptors.
require_fixed_line "$gadget" 'readonly rndis_function_dir="$gadget_dir/functions/rndis.usb0"'
require_fixed_line "$gadget" "printf 'ef' >\"\$function_dir/class\""
require_fixed_line "$gadget" "printf '04' >\"\$function_dir/subclass\""
require_fixed_line "$gadget" "printf '01' >\"\$function_dir/protocol\""
forbid "$gadget" "printf '0x(ef|04|01)' >\"\\\$function_dir/(class|subclass|protocol)\""
require_fixed_line "$gadget" "printf '1' >\"\$os_desc_dir/use\""
require_fixed_line "$gadget" "printf 'MSFT100' >\"\$os_desc_dir/qw_sign\""
require_fixed_line "$gadget" "printf '0xcd' >\"\$os_desc_dir/b_vendor_code\""
require_fixed_line "$gadget" "printf 'RNDIS' >\"\$function_dir/os_desc/interface.rndis/compatible_id\""
require_fixed_line "$gadget" 'ln -s "$config_dir" "$os_desc_config_link"'

# macOS: ECM is the only function selected by the mac branch; it does not link
# Microsoft OS descriptors.
require_fixed_line "$gadget" 'readonly ecm_function_dir="$gadget_dir/functions/ecm.usb0"'
require_text "$gadget" '  mac)'
require_text "$gadget" 'function_dir="$ecm_function_dir"'
require_text "$gadget" 'ECM intentionally has no Microsoft OS descriptor configuration.'

# Cleanup removes both possible links/functions before the next selected mode,
# preventing a dual-function gadget after repeated switching.
require_fixed_line "$gadget" 'rm -f "$os_desc_config_link" "$rndis_function_link" "$ecm_function_link"'
require_fixed_line "$gadget" 'rmdir "$rndis_function_dir" 2>/dev/null || true'
require_fixed_line "$gadget" 'rmdir "$ecm_function_dir" 2>/dev/null || true'

# The switch command validates the two modes, persists them, rebuilds only the
# gadget service, and exposes the required technical status fields.
require_text "$switcher" 'Użycie: pcdog-usb-mode {windows|mac|status}'
require_text "$switcher" 'windows|mac)'
require_text "$switcher" 'systemctl restart "$gadget_service"'
forbid "$switcher" '(reboot|poweroff|shutdown)'
require_text "$switcher" 'configured mode:'
require_text "$switcher" 'active USB function:'
require_text "$switcher" 'UDC bound:'
require_text "$switcher" 'usb0 state:'
require_text "$switcher" 'PcDog1 USB IPv4:'

# Shared isolated-network contract remains unchanged for either function.
require_fixed_line "$profile" 'address1=172.23.254.1/30'
require_fixed_line "$profile" 'never-default=true'
forbid "$profile" '^dns='
require_fixed_line "$dhcp" 'interface=usb0'
require_fixed_line "$dhcp" 'port=0'
require_fixed_line "$dhcp" 'no-resolv'
require_fixed_line "$dhcp" 'dhcp-range=172.23.254.2,172.23.254.2,255.255.255.252,1h'
require_fixed_line "$dhcp" 'dhcp-option=option:router'
forbid "$dhcp" '^dhcp-option=.*(router|3),.+'
forbid "$dhcp" '^dhcp-option=.*(dns-server|6),.+'

# The installer preserves an existing mode selection; only a fresh install gets
# the Windows default and the supported command is installed idempotently.
require_fixed_line "$installer" 'readonly mode_config=/etc/pcdog/usb-mode.conf'
require_fixed_line "$installer" 'readonly mode_command=/usr/local/sbin/pcdog-usb-mode'
require_fixed_line "$installer" 'if [[ ! -e "$mode_config" ]]; then'
require_text "$installer" 'runtime/pcdog-usb-mode.sh'

printf 'PASS: USB mode switch contracts\n'
