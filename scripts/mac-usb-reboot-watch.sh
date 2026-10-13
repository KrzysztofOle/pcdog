#!/bin/bash

# Read-only Mac observer for one separately authorized PcDog1 reboot test.
set -uo pipefail

readonly pi_address=172.23.254.1
readonly ssh_target="krzysztof@${pi_address}"
readonly watch_seconds="${1:-300}"
readonly sample_interval=10

if [[ "$(uname -s)" != Darwin ]]; then
  printf '%s\n' 'ERROR: this observer must run on macOS.' >&2
  exit 2
fi
if [[ ! "$watch_seconds" =~ ^[0-9]+$ ]] || (( watch_seconds < 30 )); then
  printf '%s\n' 'Usage: mac-usb-reboot-watch.sh [post-disconnect-seconds >= 30]' >&2
  exit 2
fi

ecm_interface() {
  networksetup -listallhardwareports 2>/dev/null |
    awk '
      /^Hardware Port: PcDog USB ECM service$/ && !found {
        getline
        sub(/^Device: /, "")
        print
        found=1
      }
    '
}

usb_device_present() {
  ioreg -p IOUSB -l -w0 2>/dev/null |
    awk 'index($0, "PcDog USB ECM service") { found=1 } END { exit !found }'
}

ssh_hostname() {
  ssh -T -o BatchMode=yes -o ConnectTimeout=3 \
    -o StrictHostKeyChecking=yes -o ControlMaster=no \
    "$ssh_target" hostname 2>/dev/null
}

if ! ssh-keygen -F "$pi_address" >/dev/null 2>&1; then
  printf '%s\n' 'ERROR: no known_hosts entry for the USB address; verify host identity before testing.' >&2
  exit 2
fi

baseline_host="$(ssh_hostname || true)"
if [[ "$baseline_host" != PcDog1 ]]; then
  printf '%s\n' 'ERROR: baseline SSH over USB did not identify PcDog1.' >&2
  exit 2
fi

interface="$(ecm_interface)"
if [[ -z "$interface" ]] || ! usb_device_present; then
  printf '%s\n' 'ERROR: the expected PcDog ECM device/interface is not present before the test.' >&2
  exit 2
fi
baseline_address="$(ipconfig getifaddr "$interface" 2>/dev/null || true)"
if [[ "$baseline_address" != 172.23.254.2 ]]; then
  printf '%s\n' 'ERROR: baseline DHCP address is not 172.23.254.2.' >&2
  exit 2
fi

printf 'ARMED %s interface=%s address=%s; start the separately approved reboot from another terminal.\n' \
  "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$interface" "$baseline_address"
printf 'Observer window: %s seconds after USB/SSH loss; Ctrl-C stops observation without changing the system.\n' "$watch_seconds"

restart_seen=false
ssh_failure_streak=0
recovery_started=0
ssh_success_streak=0

while :; do
  timestamp="$(date '+%Y-%m-%dT%H:%M:%S%z')"
  usb_state=absent
  if usb_device_present; then usb_state=present; fi

  interface="$(ecm_interface)"
  if [[ -z "$interface" ]]; then
    interface_state=absent
    link_state=unknown
    address=none
    dhcp_fields=none
    arp_entry=unavailable
    ping_state=not-run
    tcp_state=not-run
    ssh_state=not-run
    ssh_success_streak=0
    ssh_failure_streak=$((ssh_failure_streak + 1))
  else
    interface_state="$interface"
    link_state="$(ifconfig "$interface" 2>/dev/null | awk -F': ' '/status:/ && !found {state=$2; found=1} END {if (found) print state}')"
    [[ -n "$link_state" ]] || link_state=unknown
    address="$(ipconfig getifaddr "$interface" 2>/dev/null || true)"
    [[ -n "$address" ]] || address=none
    dhcp_fields="$(ipconfig getpacket "$interface" 2>/dev/null | awk -F' = ' '/^(yiaddr|server_identifier|subnet_mask|lease_time)/ {printf "%s%s=%s", (n++ ? "," : ""), $1, $2}')"
    [[ -n "$dhcp_fields" ]] || dhcp_fields=none

    if ping -n -c 1 -W 1000 "$pi_address" >/dev/null 2>&1; then ping_state=ok; else ping_state=fail; fi
    arp_entry="$(arp -n "$pi_address" 2>/dev/null | tail -n 1 | tr '\n' ' ' | sed 's/[[:space:]]*$//')"
    [[ -n "$arp_entry" ]] || arp_entry=unavailable
    if nc -G 2 -z "$pi_address" 22 >/dev/null 2>&1; then tcp_state=open; else tcp_state=closed; fi

    remote_hostname="$(ssh_hostname || true)"
    if [[ "$remote_hostname" == PcDog1 ]]; then
      ssh_state=ok
      ssh_success_streak=$((ssh_success_streak + 1))
      ssh_failure_streak=0
    else
      ssh_state=fail
      ssh_success_streak=0
      ssh_failure_streak=$((ssh_failure_streak + 1))
    fi
  fi

  if [[ "$restart_seen" == false ]]; then
    if [[ "$usb_state" == absent ]] || (( ssh_failure_streak >= 2 )); then
      restart_seen=true
      recovery_started=$SECONDS
      phase=USB_OR_SSH_LOST
    else
      phase=WAITING_FOR_REBOOT
    fi
  else
    phase=RECOVERING
  fi

  printf '%s phase=%s usb=%s ecm=%s link=%s ipv4=%s dhcp={%s} arp={%s} ping=%s tcp22=%s ssh=%s\n' \
    "$timestamp" "$phase" "$usb_state" "$interface_state" "$link_state" "$address" \
    "$dhcp_fields" "$arp_entry" "$ping_state" "$tcp_state" "$ssh_state"

  if [[ "$restart_seen" == true ]] && (( ssh_success_streak >= 3 )); then
    printf '%s\n' 'PASS: SSH identified PcDog1 in three consecutive samples.'
    exit 0
  fi
  if [[ "$restart_seen" == true ]] && (( SECONDS - recovery_started >= watch_seconds )); then
    printf '%s\n' 'TIMEOUT: SSH did not recover within the observer window; follow the STOP/RECOVERY procedure.'
    exit 1
  fi
  sleep "$sample_interval"
done
