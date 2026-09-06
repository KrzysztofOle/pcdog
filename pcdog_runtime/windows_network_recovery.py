"""Safe, manual Windows network diagnostics and level-1 recovery for PcDog.

This module deliberately has no knowledge of GPIO, power control or routing on
PcDog.  Its only mutable operation is a guarded ``Restart-NetAdapter`` issued
to Windows through the already established USB service channel.
"""

from __future__ import annotations

import base64
import json
import subprocess
import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Callable, Mapping, Sequence


SERVICE_ADDRESS = "172.23.254.2"
SERVICE_PREFIX_LENGTH = 30
SERVICE_DESCRIPTION = "Remote NDIS Compatible Device"
DEFAULT_INTERNET_TARGET = "1.1.1.1"
DEFAULT_DNS_NAME = "one.one.one.one"


class ExitCode(IntEnum):
    HEALTHY = 0
    SSH_UNAVAILABLE = 10
    ADAPTER_DOWN = 11
    NO_IPV4 = 12
    NO_GATEWAY = 13
    GATEWAY_UNREACHABLE = 14
    INTERNET_UNREACHABLE = 15
    DNS_FAILURE = 16
    RECOVERY_TIMEOUT = 30
    RECOVERY_FAILED = 31
    SERVICE_INTERFACE_PROTECTED = 32
    INVALID_ARGUMENT = 64


STATUS_CODES: Mapping[str, ExitCode] = {
    "HEALTHY": ExitCode.HEALTHY,
    "SSH_UNAVAILABLE": ExitCode.SSH_UNAVAILABLE,
    "ADAPTER_DOWN": ExitCode.ADAPTER_DOWN,
    "NO_IPV4": ExitCode.NO_IPV4,
    "NO_GATEWAY": ExitCode.NO_GATEWAY,
    "GATEWAY_UNREACHABLE": ExitCode.GATEWAY_UNREACHABLE,
    "INTERNET_UNREACHABLE": ExitCode.INTERNET_UNREACHABLE,
    "DNS_FAILURE": ExitCode.DNS_FAILURE,
    "RECOVERED": ExitCode.HEALTHY,
    "RECOVERY_TIMEOUT": ExitCode.RECOVERY_TIMEOUT,
    "RECOVERY_FAILED": ExitCode.RECOVERY_FAILED,
    "SERVICE_INTERFACE_PROTECTED": ExitCode.SERVICE_INTERFACE_PROTECTED,
}


class RemoteError(RuntimeError):
    """The Windows command could not be run or returned invalid data."""


@dataclass(frozen=True)
class Timing:
    initial_delay: float = 10.0
    retry_interval: float = 5.0
    timeout: float = 60.0

    def validate(self) -> None:
        if self.initial_delay < 0 or self.retry_interval <= 0 or self.timeout < 0:
            raise ValueError("initial-delay i timeout muszą być >= 0, a retry-interval > 0")


def classify_diagnostic(data: Mapping[str, Any]) -> str:
    """Return the deterministic health classification for a remote snapshot."""
    adapter = data.get("adapter", {})
    if adapter.get("status") != "Up":
        return "ADAPTER_DOWN"
    if not data.get("ipv4"):
        return "NO_IPV4"
    if not data.get("gateways"):
        return "NO_GATEWAY"
    if not data.get("gateway_reachable"):
        return "GATEWAY_UNREACHABLE"
    if not data.get("internet_reachable"):
        return "INTERNET_UNREACHABLE"
    if not data.get("dns_resolves"):
        return "DNS_FAILURE"
    return "HEALTHY"


def service_interface_is_unambiguously_protected(data: Mapping[str, Any]) -> bool:
    """Require one and only one interface to match *both* service signatures.

    If either signal is absent, split across adapters, or occurs more than
    once, recovery is fail-safe blocked.  The selected adapter must be a
    different interface.
    """
    adapters = data.get("service_candidates")
    selected = data.get("adapter", {}).get("if_index")
    if not isinstance(adapters, list) or selected is None:
        return False
    by_index: dict[Any, dict[str, bool]] = {}
    for candidate in adapters:
        if not isinstance(candidate, Mapping) or "if_index" not in candidate:
            return False
        index = candidate["if_index"]
        signals = by_index.setdefault(index, {"address": False, "description": False})
        signals["address"] |= bool(candidate.get("has_service_address"))
        signals["description"] |= bool(candidate.get("has_service_description"))
    protected = [index for index, signals in by_index.items() if all(signals.values())]
    any_partial = any(not all(signals.values()) for signals in by_index.values())
    return len(protected) == 1 and not any_partial and protected[0] != selected


def powershell_script(mode: str, adapter: str, internet_target: str, dns_name: str) -> str:
    """Build the remote program. Only ``restart`` contains a mutable command."""
    if mode not in {"diagnostic", "restart"}:
        raise ValueError("nieprawidłowy tryb zdalny")
    # JSON quoting also makes the values safe PowerShell string literals.
    quoted = lambda value: json.dumps(value)
    restart = ""
    if mode == "restart":
        restart = """
if (-not $safe) { throw 'SERVICE_INTERFACE_PROTECTED' }
Restart-NetAdapter -Name $adapter.Name -Confirm:$false -ErrorAction Stop
[pscustomobject]@{ kind = 'restart'; safe = $safe } | ConvertTo-Json -Compress
exit 0
"""
    return f"""
$ErrorActionPreference = 'Stop'
$adapterName = {quoted(adapter)}
$internetTarget = {quoted(internet_target)}
$dnsName = {quoted(dns_name)}
$serviceAddress = '{SERVICE_ADDRESS}'
$servicePrefix = {SERVICE_PREFIX_LENGTH}
$serviceDescription = '{SERVICE_DESCRIPTION}'
$adapter = Get-NetAdapter -Name $adapterName -ErrorAction Stop
$all = Get-NetAdapter -IncludeHidden | ForEach-Object {{
  $a = $_
  $ips = @(Get-NetIPAddress -InterfaceIndex $a.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue)
  [pscustomobject]@{{
    if_index = $a.ifIndex
    has_service_address = @($ips | Where-Object {{ $_.IPAddress -eq $serviceAddress -and $_.PrefixLength -eq $servicePrefix }}).Count -gt 0
    has_service_description = $a.InterfaceDescription -eq $serviceDescription
  }}
}}
$protected = @($all | Where-Object {{ $_.has_service_address -and $_.has_service_description }})
$partial = @($all | Where-Object {{ $_.has_service_address -xor $_.has_service_description }})
$safe = $protected.Count -eq 1 -and $partial.Count -eq 0 -and $protected[0].if_index -ne $adapter.ifIndex
{restart}
$ip = @(Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
  Where-Object {{ $_.IPAddress -notlike '169.254.*' }} | ForEach-Object {{ $_.IPAddress + '/' + $_.PrefixLength }})
$gateways = @(Get-NetRoute -InterfaceIndex $adapter.ifIndex -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
  Where-Object {{ $_.NextHop -and $_.NextHop -ne '0.0.0.0' }} | ForEach-Object {{ $_.NextHop }} | Select-Object -Unique)
$gatewayReachable = $false
if ($gateways.Count -gt 0) {{ $gatewayReachable = Test-Connection -TargetName $gateways[0] -Count 1 -Quiet -ErrorAction SilentlyContinue }}
$internetReachable = Test-Connection -TargetName $internetTarget -Count 1 -Quiet -ErrorAction SilentlyContinue
$dnsResolves = $false
try {{ $dnsResolves = @(Resolve-DnsName -Name $dnsName -ErrorAction Stop).Count -gt 0 }} catch {{ $dnsResolves = $false }}
[pscustomobject]@{{
  kind = 'diagnostic'
  adapter = [pscustomobject]@{{ name = $adapter.Name; if_index = $adapter.ifIndex; status = [string]$adapter.Status; description = $adapter.InterfaceDescription }}
  ipv4 = $ip
  gateways = $gateways
  gateway_reachable = [bool]$gatewayReachable
  internet_reachable = [bool]$internetReachable
  dns_resolves = [bool]$dnsResolves
  service_candidates = $all
}} | ConvertTo-Json -Compress -Depth 4
"""


class SshRunner:
    def __init__(self, user: str, host: str, ssh_command: str = "ssh") -> None:
        self.user, self.host, self.ssh_command = user, host, ssh_command

    def run(self, script: str) -> Mapping[str, Any]:
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        command: Sequence[str] = (
            self.ssh_command, "-o", "ConnectTimeout=10",
            f"{self.user}@{self.host}", "powershell.exe", "-NoProfile", "-NonInteractive",
            "-EncodedCommand", encoded,
        )
        try:
            result = subprocess.run(command, check=False, text=True, capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RemoteError(str(exc)) from exc
        if result.returncode:
            raise RemoteError(result.stderr.strip() or f"ssh zakończył się kodem {result.returncode}")
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RemoteError("Windows nie zwrócił poprawnego JSON") from exc
        if not isinstance(value, Mapping):
            raise RemoteError("Windows zwrócił nieprawidłowy typ danych")
        return value


def diagnostic(runner: Any, adapter: str, internet_target: str, dns_name: str) -> tuple[str, Mapping[str, Any]]:
    try:
        data = runner.run(powershell_script("diagnostic", adapter, internet_target, dns_name))
    except RemoteError:
        return "SSH_UNAVAILABLE", {}
    return classify_diagnostic(data), data


def recover(
    runner: Any,
    adapter: str,
    internet_target: str,
    dns_name: str,
    timing: Timing,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[str, Mapping[str, Any]]:
    timing.validate()
    _, before = diagnostic(runner, adapter, internet_target, dns_name)
    if not before or not service_interface_is_unambiguously_protected(before):
        return "SERVICE_INTERFACE_PROTECTED", before
    try:
        restarted = runner.run(powershell_script("restart", adapter, internet_target, dns_name))
    except RemoteError as exc:
        if "SERVICE_INTERFACE_PROTECTED" in str(exc):
            return "SERVICE_INTERFACE_PROTECTED", before
        return "RECOVERY_FAILED", before
    if restarted.get("kind") != "restart" or not restarted.get("safe"):
        return "SERVICE_INTERFACE_PROTECTED", before
    sleep(timing.initial_delay)
    elapsed = 0.0
    last: Mapping[str, Any] = before
    while True:
        status, last = diagnostic(runner, adapter, internet_target, dns_name)
        if status == "HEALTHY":
            return "RECOVERED", last
        if elapsed >= timing.timeout:
            return "RECOVERY_TIMEOUT", last
        sleep(timing.retry_interval)
        elapsed += timing.retry_interval
