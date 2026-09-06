"""Fail-safe bootstrap of a dedicated PcDog SSH key for Windows."""

from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

DEFAULT_HOST = "172.23.254.2"
KEY_COMMENT = "PcDog Windows service access"


class BootstrapError(RuntimeError):
    """A fail-safe condition which must not be worked around automatically."""


@dataclass(frozen=True)
class KeyPair:
    private: Path
    public: Path
    state: str


def public_key_material(value: str) -> tuple[str, str]:
    fields = value.strip().split()
    if len(fields) < 2 or not fields[0].startswith("ssh-"):
        raise BootstrapError("klucz publiczny ma nieprawidłowy format")
    return fields[0], fields[1]


def ensure_key_pair(private: Path, run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> KeyPair:
    """Create exactly one absent pair, or verify and reuse an existing pair."""
    public = Path(f"{private}.pub")
    private_exists, public_exists = private.exists(), public.exists()
    if private_exists != public_exists:
        raise BootstrapError("niespójna para kluczy: istnieje tylko jeden z plików; nic nie zostało nadpisane")
    if not private_exists:
        private.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            os.chmod(private.parent, 0o700)
        except OSError:
            pass
        result = run(["ssh-keygen", "-q", "-t", "ed25519", "-f", str(private), "-N", "", "-C", KEY_COMMENT], check=False, text=True, capture_output=True)
        if result.returncode:
            raise BootstrapError(result.stderr.strip() or "ssh-keygen zakończył się błędem")
        state = "generated"
    else:
        state = "reused"
    try:
        os.chmod(private, 0o600)
    except OSError as exc:
        raise BootstrapError(f"nie można ustawić 0600 na kluczu prywatnym: {exc}") from exc
    result = run(["ssh-keygen", "-y", "-f", str(private)], check=False, text=True, capture_output=True)
    if result.returncode:
        raise BootstrapError("istniejący klucz prywatny nie może zostać odczytany")
    if public_key_material(result.stdout) != public_key_material(public.read_text(encoding="utf-8")):
        raise BootstrapError("klucz publiczny nie odpowiada istniejącemu kluczowi prywatnemu; nic nie zostało nadpisane")
    return KeyPair(private, public, state)


def check_tcp(host: str, port: int = 22, timeout: float = 5.0) -> None:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return
    except OSError as exc:
        raise BootstrapError(f"Windows SSH jest nieosiągalny pod {host}:{port}: {exc}") from exc


def key_auth_command(user: str, host: str, private: Path) -> list[str]:
    return ["ssh", "-o", "BatchMode=yes", "-o", "PasswordAuthentication=no", "-o", "KbdInteractiveAuthentication=no", "-o", "ConnectTimeout=10", "-o", "IdentitiesOnly=yes", "-i", str(private), f"{user}@{host}", "exit"]


def key_auth_works(user: str, host: str, private: Path, run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> bool:
    return run(key_auth_command(user, host, private), check=False, text=True, capture_output=True).returncode == 0


def installation_script(public_key: str) -> str:
    """Resolve effective sshd config then safely add one key and narrow its ACL."""
    encoded_key = json.dumps(public_key.strip())
    return f"""
$ErrorActionPreference = 'Stop'
$publicKey = {encoded_key}
$sshd = (Get-Command sshd.exe -ErrorAction Stop).Source
$effective = @(& $sshd -T -C "user=$env:USERNAME,host=localhost,addr=127.0.0.1" 2>&1)
if ($LASTEXITCODE -ne 0) {{ throw 'SSHD_CONFIG_UNRESOLVED:sshd -T failed' }}
$configured = @($effective | Where-Object {{ $_ -match '^authorizedkeysfile\\s+(.+)$' }} | ForEach-Object {{ $Matches[1].Trim() }})
if ($configured.Count -ne 1) {{ throw 'SSHD_CONFIG_AMBIGUOUS:expected exactly one effective AuthorizedKeysFile' }}
$raw = $configured[0]
$expanded = [Environment]::ExpandEnvironmentVariables($raw.Replace('__PROGRAMDATA__', $env:ProgramData))
if (-not [IO.Path]::IsPathRooted($expanded)) {{ $expanded = Join-Path $env:USERPROFILE $expanded }}
$target = [IO.Path]::GetFullPath($expanded)
$adminTarget = [IO.Path]::GetFullPath((Join-Path $env:ProgramData 'ssh\\administrators_authorized_keys'))
$userTarget = [IO.Path]::GetFullPath((Join-Path $env:USERPROFILE '.ssh\\authorized_keys'))
if ($target -ieq $adminTarget) {{ $aclKind = 'administrators' }}
elseif ($target -ieq $userTarget) {{ $aclKind = 'user' }}
else {{ throw "SSHD_CONFIG_UNRESOLVED:unsupported effective AuthorizedKeysFile: $target" }}
$parent = Split-Path -Parent $target
if (-not (Test-Path -LiteralPath $parent)) {{ New-Item -ItemType Directory -Path $parent -Force | Out-Null }}
$existing = if (Test-Path -LiteralPath $target) {{ @(Get-Content -LiteralPath $target -ErrorAction Stop) }} else {{ @() }}
$wanted = ($publicKey -split '\\s+')[0..1] -join ' '
$present = @($existing | Where-Object {{ $_.Trim() -match '^(ssh-[^ ]+)\\s+([^ ]+)' -and (($Matches[1] + ' ' + $Matches[2]) -eq $wanted) }}).Count -gt 0
if (-not $present) {{ Add-Content -LiteralPath $target -Value $publicKey -Encoding ascii }}
$acl = New-Object System.Security.AccessControl.FileSecurity
$acl.SetAccessRuleProtection($true, $false)
if ($aclKind -eq 'administrators') {{
  $acl.SetOwner([System.Security.Principal.NTAccount]'BUILTIN\\Administrators')
  foreach ($identity in @('BUILTIN\\Administrators', 'NT AUTHORITY\\SYSTEM')) {{ $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule($identity, 'FullControl', 'Allow'))) }}
}} else {{
  $acl.SetOwner([System.Security.Principal.NTAccount]$env:USERNAME)
  foreach ($identity in @($env:USERNAME, 'NT AUTHORITY\\SYSTEM')) {{ $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule($identity, 'FullControl', 'Allow'))) }}
}}
Set-Acl -LiteralPath $target -AclObject $acl
[pscustomobject]@{{ authorized_keys = $target; acl_kind = $aclKind; key_added = (-not $present) }} | ConvertTo-Json -Compress
"""


def interactive_install(user: str, host: str, public_key: str, run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> str:
    """One interactive SSH call; Python never receives or retains its password."""
    encoded = base64.b64encode(installation_script(public_key).encode("utf-16le")).decode("ascii")
    command: Sequence[str] = ("ssh", "-o", "ConnectTimeout=10", f"{user}@{host}", "powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded)
    result = run(command, check=False, text=True)
    if result.returncode:
        raise BootstrapError(f"interaktywna instalacja klucza nie powiodła się (ssh exit {result.returncode})")
    return "installed"


def bootstrap(
    user: str,
    host: str,
    private: Path,
    *,
    tcp_check: Callable[[str], None] = check_tcp,
    key_pair: Callable[[Path], KeyPair] = ensure_key_pair,
    auth_check: Callable[[str, str, Path], bool] = key_auth_works,
    install: Callable[[str, str, str], str] = interactive_install,
) -> tuple[str, KeyPair]:
    """Run the ordered bootstrap protocol, with a testable interactive boundary."""
    tcp_check(host)
    pair = key_pair(private)
    if auth_check(user, host, pair.private):
        return "already_configured", pair
    install(user, host, pair.public.read_text(encoding="utf-8"))
    if not auth_check(user, host, pair.private):
        raise BootstrapError("końcowy test SSH BatchMode z kluczem nie powiódł się")
    return "configured", pair
