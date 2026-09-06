#!/usr/bin/env bash
# Isolated behavioural contracts for the idempotent ZeroTier installer.
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
installer="$repo_dir/scripts/install-zerotier.sh"
status_script="$repo_dir/scripts/zerotier-status.sh"
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT
fake_bin="$work_dir/bin"
mkdir -p "$fake_bin"

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
write_fake_tools() {
  cat >"$fake_bin/id" <<'EOF'
#!/usr/bin/env bash
printf '0\n'
EOF
  cat >"$fake_bin/systemctl" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$ZT_LOG"
case "$1" in is-enabled|is-active) exit 0;; *) exit 0;; esac
EOF
  cat >"$fake_bin/curl" <<'EOF'
#!/usr/bin/env bash
[[ "${ZT_INSTALL_FAIL:-0}" != 1 ]] || exit 1
printf '%s\n' curl >>"$ZT_LOG"
printf '%s\n' '#!/usr/bin/env bash' 'cp "$ZT_TEMPLATE" "$ZT_BIN"' 'chmod +x "$ZT_BIN"'
EOF
  chmod +x "$fake_bin/id" "$fake_bin/systemctl" "$fake_bin/curl"
  cat >"$work_dir/zerotier-cli-template" <<'EOF'
#!/usr/bin/env bash
case "$1" in
  status) printf '200 info abcdef1234 ONLINE\n' ;;
  -v) printf '1.14.2\n' ;;
  info) printf '200 info abcdef1234 1.14.2 ONLINE\n' ;;
  listnetworks) [[ -z "${ZT_NETWORK_LINE:-}" ]] || printf '%s\n' "$ZT_NETWORK_LINE" ;;
  join) printf 'join %s\n' "$2" >>"$ZT_LOG"; [[ "${ZT_JOIN_FAIL:-0}" != 1 ]] ;;
  *) exit 1 ;;
esac
EOF
  chmod +x "$work_dir/zerotier-cli-template"
}
run_installer() {
  local config="$1"
  PATH="$fake_bin:$PATH" ZT_LOG="$work_dir/log" ZT_TEMPLATE="$work_dir/zerotier-cli-template" ZT_BIN="$fake_bin/zerotier-cli" PCDOG_ZEROTIER_CLI="$fake_bin/zerotier-cli" PCDOG_ZEROTIER_CONFIG_PATH="$config" "$installer"
}

# A: not installed; B/C: installation occurs once and missing Network ID skips join.
write_fake_tools
: >"$work_dir/log"
run_installer "$work_dir/no-config"
grep -Fxq curl "$work_dir/log" || fail 'brak oficjalnego instalatora dla nieobecnego ZeroTier'
! grep -q '^join ' "$work_dir/log" || fail 'join mimo braku Network ID'

# G: an official installer failure is propagated.
rm -f "$fake_bin/zerotier-cli"
if PATH="$fake_bin:$PATH" ZT_LOG="$work_dir/log" ZT_INSTALL_FAIL=1 PCDOG_ZEROTIER_CLI="$fake_bin/zerotier-cli" PCDOG_ZEROTIER_CONFIG_PATH="$work_dir/no-config" "$installer" >/dev/null 2>&1; then
  fail 'błąd instalatora nie zakończył instalatora błędem'
fi
cp "$work_dir/zerotier-cli-template" "$fake_bin/zerotier-cli"
chmod +x "$fake_bin/zerotier-cli"

# D: configured but not joined performs exactly one join.
: >"$work_dir/log"
PATH="$fake_bin:$PATH" ZT_LOG="$work_dir/log" ZT_NETWORK_LINE='' PCDOG_ZEROTIER_CLI="$fake_bin/zerotier-cli" PCDOG_ZEROTIER_NETWORK_ID=0123456789abcdef PCDOG_ZEROTIER_CONFIG_PATH="$work_dir/no-config" "$installer"
grep -Fxq 'join 0123456789abcdef' "$work_dir/log" || fail 'brak join dla niebędącego członkiem node'

# E/F: existing membership makes the second run a no-op for join and restart.
: >"$work_dir/log"
PATH="$fake_bin:$PATH" ZT_LOG="$work_dir/log" ZT_NETWORK_LINE='200 listnetworks 0123456789abcdef aa:bb name OK PRIVATE zt0 10.0.0.2/24' PCDOG_ZEROTIER_CLI="$fake_bin/zerotier-cli" PCDOG_ZEROTIER_NETWORK_ID=0123456789abcdef PCDOG_ZEROTIER_CONFIG_PATH="$work_dir/no-config" "$installer"
! grep -q '^join ' "$work_dir/log" || fail 'zbędny join istniejącego członkostwa'
! grep -q '^restart ' "$work_dir/log" || fail 'zbędny restart aktywnej usługi'
! grep -q '^curl$' "$work_dir/log" || fail 'zbędna reinstalacja istniejącego ZeroTier'

# G: a failing join is reported as an error.
: >"$work_dir/log"
if PATH="$fake_bin:$PATH" ZT_LOG="$work_dir/log" ZT_NETWORK_LINE='' ZT_JOIN_FAIL=1 PCDOG_ZEROTIER_CLI="$fake_bin/zerotier-cli" PCDOG_ZEROTIER_NETWORK_ID=0123456789abcdef PCDOG_ZEROTIER_CONFIG_PATH="$work_dir/no-config" "$installer" >/dev/null 2>&1; then
  fail 'błąd join nie zakończył instalatora błędem'
fi

# Read-only diagnostics expose state but hide deployment configuration.
output="$(PATH="$fake_bin:$PATH" ZT_LOG="$work_dir/log" ZT_NETWORK_LINE='200 listnetworks 0123456789abcdef aa:bb name ACCESS_DENIED PRIVATE zt0 10.0.0.2/24' PCDOG_ZEROTIER_CLI="$fake_bin/zerotier-cli" PCDOG_ZEROTIER_NETWORK_ID=0123456789abcdef PCDOG_ZEROTIER_CONFIG_PATH="$work_dir/no-config" "$status_script")"
grep -Fq 'Membership status: ACCESS_DENIED' <<<"$output" || fail 'diagnostyka nie rozpoznaje oczekiwania na autoryzację'
grep -Fq 'Network ID: configured (hidden' <<<"$output" || fail 'diagnostyka ujawnia lub pomija konfigurację deploymentu'

# H: installer has no commands that configure PcDog USB/Wi-Fi/routing.
! grep -Eq '(nmcli|ip route|route add|iptables|nft|usb0|rndis|ecm)' "$installer" || fail 'installer ingeruje w istniejącą sieć PcDog'
printf 'PASS: ZeroTier installation contracts\n'
