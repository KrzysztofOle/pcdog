#!/usr/bin/python3
"""Safely install, verify, or roll back only the read-only PcDog CLI."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
from typing import Sequence
import uuid


MARKER_NAME = ".pcdog-cli-managed"
MARKER_CONTENT = b"PcDog read-only CLI release store v1\n"
LEGACY_LAUNCHER = (
    b"#!/usr/bin/env bash\n"
    b"# Read-only PcDog administration CLI.\n"
    b"set -eu\n"
    b"export PYTHONPATH='/opt/pcdog/lib'\n"
    b"exec /usr/bin/python3 -m pcdog_runtime.cli \"$@\"\n"
)
MODULES = ("__init__.py", "cli.py", "network_status.py", "usb_mode.py")
CLI_PACKAGE_INIT = b'"""Minimal package initializer for the standalone PcDog CLI."""\n'


class InstallError(RuntimeError):
    """A safe precondition failed; no unknown path is overwritten."""


@dataclass(frozen=True)
class Layout:
    root: Path
    launcher: Path
    source: Path
    launcher_source: Path
    owner_uid: int = 0
    owner_gid: int = 0


def repository_layout() -> Layout:
    project = Path(__file__).resolve().parent.parent
    return Layout(
        root=Path("/opt/pcdog-cli"),
        launcher=Path("/usr/local/bin/pcdog"),
        source=project / "pcdog_runtime",
        launcher_source=project / "runtime/pcdog-cli.sh",
    )


class CliInstaller:
    def __init__(self, layout: Layout, *, require_root: bool = True) -> None:
        self.layout = layout
        self.require_root = require_root
        self.root = layout.root
        self.releases = self.root / "releases"
        self.current = self.root / "current"
        self.previous = self.root / "previous"
        self.legacy_launcher = self.root / "legacy-launcher"

    def _require_root(self) -> None:
        if self.require_root and os.geteuid() != 0:
            raise InstallError("instalacja i rollback wymagają uprawnień root; użyj sudo")

    def _report_optional_dependencies(self) -> None:
        checks = (
            (Path("/opt/pcdog/bin/pcdog-healthcheck"), "health check runtime"),
            (Path("/usr/local/sbin/pcdog-usb-mode"), "status USB"),
        )
        for path, label in checks:
            if not path.is_file() or not os.access(path, os.X_OK):
                print(f"OSTRZEŻENIE: {label} niedostępny ({path}); odpowiadająca sekcja CLI pokaże NIEDOSTĘPNE.")
        if shutil.which("nmcli") is None:
            print("OSTRZEŻENIE: nmcli niedostępne; diagnostyka sieci i profili Wi-Fi pokaże NIEDOSTĘPNE.")

    def _source_files(self) -> dict[str, bytes]:
        if sys.version_info < (3, 9):
            raise InstallError("wymagany jest Python 3.9 lub nowszy")
        files: dict[str, bytes] = {}
        for name in MODULES:
            if name == "__init__.py":
                # The full runtime package initializer imports unrelated modules.
                files[name] = CLI_PACKAGE_INIT
                continue
            path = self.layout.source / name
            try:
                files[name] = path.read_bytes()
            except OSError as error:
                raise InstallError(f"brak wymaganego pliku źródłowego: {path}") from error
        try:
            launcher = self.layout.launcher_source.read_bytes()
        except OSError as error:
            raise InstallError(f"brak launchera źródłowego: {self.layout.launcher_source}") from error
        if not launcher.startswith(b"#!/usr/bin/env bash\n") or b"/opt/pcdog-cli/current" not in launcher:
            raise InstallError("launcher źródłowy nie wskazuje wydzielonego pakietu CLI")
        files[".launcher"] = launcher
        return files

    @staticmethod
    def _digest(files: dict[str, bytes]) -> str:
        digest = hashlib.sha256()
        for name in sorted(files):
            digest.update(name.encode("ascii") + b"\0")
            digest.update(hashlib.sha256(files[name]).digest())
        return digest.hexdigest()

    def _check_directory(self, path: Path, *, expected_mode: int | None = None) -> None:
        try:
            info = path.lstat()
        except OSError as error:
            raise InstallError(f"brak wymaganego katalogu: {path}") from error
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != self.layout.owner_uid:
            raise InstallError(f"katalog ma nieoczekiwany typ lub właściciela: {path}")
        if expected_mode is not None and stat.S_IMODE(info.st_mode) != expected_mode:
            raise InstallError(f"nieprawidłowe uprawnienia katalogu {path}; oczekiwano {expected_mode:o}")
        if stat.S_IMODE(info.st_mode) & 0o022:
            raise InstallError(f"katalog jest zapisywalny dla grupy lub innych użytkowników: {path}")

    def _check_regular_file(self, path: Path, *, expected: bytes | None = None, mode: int | None = None) -> bytes:
        try:
            info = path.lstat()
            content = path.read_bytes()
        except OSError as error:
            raise InstallError(f"nie można odczytać pliku: {path}") from error
        if not stat.S_ISREG(info.st_mode) or info.st_uid != self.layout.owner_uid:
            raise InstallError(f"plik ma nieoczekiwany typ lub właściciela: {path}")
        if mode is not None and stat.S_IMODE(info.st_mode) != mode:
            raise InstallError(f"nieprawidłowe uprawnienia pliku {path}; oczekiwano {mode:o}")
        if expected is not None and content != expected:
            raise InstallError(f"plik nie jest wersją zarządzaną przez instalator: {path}")
        return content

    def _launcher_state(self, new_launcher: bytes) -> str:
        path = self.layout.launcher
        try:
            info = path.lstat()
        except FileNotFoundError:
            return "absent"
        except OSError as error:
            raise InstallError(f"nie można sprawdzić {path}") from error
        if not stat.S_ISREG(info.st_mode) or info.st_uid != self.layout.owner_uid:
            raise InstallError(f"istniejący launcher nie jest zwykłym plikiem należącym do root: {path}")
        if stat.S_IMODE(info.st_mode) != 0o755:
            raise InstallError(f"istniejący launcher ma nieoczekiwane uprawnienia: {path}")
        content = path.read_bytes()
        if content == new_launcher:
            return "managed"
        if content == LEGACY_LAUNCHER:
            return "legacy"
        raise InstallError(f"odmowa nadpisania nieznanego pliku: {path}")

    def _validate_release(self, path: Path) -> None:
        if path.is_symlink() or not path.is_dir():
            raise InstallError(f"wydanie CLI ma nieoczekiwany typ: {path}")
        self._check_directory(path, expected_mode=0o755)
        package = path / "pcdog_runtime"
        self._check_directory(package, expected_mode=0o755)
        expected_names = {"pcdog_runtime"}
        if {item.name for item in path.iterdir()} != expected_names:
            raise InstallError(f"wydanie zawiera niezarządzane pliki: {path}")
        if {item.name for item in package.iterdir()} != set(MODULES):
            raise InstallError(f"pakiet wydania zawiera niezarządzane pliki: {package}")
        content: dict[str, bytes] = {}
        for name in MODULES:
            content[name] = self._check_regular_file(package / name, mode=0o644)
        if path.name != self._digest(content):
            raise InstallError(f"suma kontrolna wydania nie zgadza się z nazwą katalogu: {path}")

    def _link_target(self, path: Path) -> str | None:
        if not path.exists() and not path.is_symlink():
            return None
        if not path.is_symlink():
            raise InstallError(f"odmowa nadpisania nieznanej ścieżki: {path}")
        target = os.readlink(path)
        if not target.startswith("releases/") or len(target) != len("releases/") + 64:
            raise InstallError(f"nieprawidłowy link wydania: {path}")
        digest = target.removeprefix("releases/")
        if any(character not in "0123456789abcdef" for character in digest):
            raise InstallError(f"nieprawidłowy link wydania: {path}")
        self._validate_release(self.releases / digest)
        return target

    def _prepare_store(self, *, create: bool = False) -> None:
        if not self.root.exists():
            if not create:
                raise InstallError(f"CLI nie jest zainstalowane: {self.root}")
            self.root.mkdir(mode=0o755)
            os.chown(self.root, self.layout.owner_uid, self.layout.owner_gid)
            os.chmod(self.root, 0o755)
            self._atomic_write(self.root / MARKER_NAME, MARKER_CONTENT, 0o644)
        else:
            if self.root.is_symlink():
                raise InstallError(f"katalog instalacji jest linkiem symbolicznym: {self.root}")
            self._check_directory(self.root, expected_mode=0o755)
            marker = self.root / MARKER_NAME
            self._check_regular_file(marker, expected=MARKER_CONTENT, mode=0o644)
        self._check_directory(self.root, expected_mode=0o755)
        allowed = {MARKER_NAME, "releases", "current", "previous", "legacy-launcher"}
        unknown = {item.name for item in self.root.iterdir()} - allowed
        if unknown:
            raise InstallError(f"katalog CLI zawiera nieznane elementy: {', '.join(sorted(unknown))}")
        if not self.releases.exists():
            if not create:
                raise InstallError(f"brak katalogu wydań CLI: {self.releases}")
            self.releases.mkdir(mode=0o755)
            os.chown(self.releases, self.layout.owner_uid, self.layout.owner_gid)
            os.chmod(self.releases, 0o755)
        self._check_directory(self.releases, expected_mode=0o755)
        for item in self.releases.iterdir():
            if item.name.startswith(".stage-"):
                raise InstallError(f"znaleziono niedokończone staging area; sprawdź ręcznie: {item}")
            if len(item.name) != 64 or any(char not in "0123456789abcdef" for char in item.name):
                raise InstallError(f"nieznany element w katalogu wydań: {item}")
            self._validate_release(item)
        self._link_target(self.current)
        self._link_target(self.previous)
        if self.legacy_launcher.exists() or self.legacy_launcher.is_symlink():
            self._check_regular_file(self.legacy_launcher, expected=LEGACY_LAUNCHER, mode=0o755)

    def _atomic_write(self, path: Path, content: bytes, mode: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.stage-", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.chown(temporary, self.layout.owner_uid, self.layout.owner_gid)
            os.chmod(temporary, mode)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _atomic_link(self, path: Path, target: str | None) -> None:
        if target is None:
            path.unlink(missing_ok=True)
            return
        temporary = path.parent / f".{path.name}.stage-{uuid.uuid4().hex}"
        os.symlink(target, temporary)
        os.chown(temporary, self.layout.owner_uid, self.layout.owner_gid, follow_symlinks=False)
        os.replace(temporary, path)

    def _install_release(self, files: dict[str, bytes], digest: str) -> None:
        release = self.releases / digest
        if release.exists():
            self._validate_release(release)
            return
        stage = Path(tempfile.mkdtemp(prefix=".stage-", dir=self.releases))
        try:
            os.chown(stage, self.layout.owner_uid, self.layout.owner_gid)
            os.chmod(stage, 0o755)
            package = stage / "pcdog_runtime"
            package.mkdir(mode=0o755)
            os.chown(package, self.layout.owner_uid, self.layout.owner_gid)
            for name in MODULES:
                target = package / name
                target.write_bytes(files[name])
                os.chown(target, self.layout.owner_uid, self.layout.owner_gid)
                os.chmod(target, 0o644)
            os.replace(stage, release)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
        self._validate_release(release)

    def install(self) -> bool:
        self._require_root()
        self._check_directory(self.root.parent)
        self._check_directory(self.layout.launcher.parent)
        files = self._source_files()
        launcher = files.pop(".launcher")
        launcher_state = self._launcher_state(launcher)
        self._prepare_store(create=True)
        digest = self._digest(files)
        self._install_release(files, digest)
        current_target = self._link_target(self.current)
        new_target = f"releases/{digest}"

        if launcher_state == "legacy" and not (self.legacy_launcher.exists() or self.legacy_launcher.is_symlink()):
            self._atomic_write(self.legacy_launcher, LEGACY_LAUNCHER, 0o755)
        changed = current_target != new_target or launcher_state != "managed"
        if current_target != new_target:
            if current_target is not None:
                self._atomic_link(self.previous, current_target)
            self._atomic_link(self.current, new_target)
        if launcher_state != "managed":
            self._atomic_write(self.layout.launcher, launcher, 0o755)
        self._check_all_files(launcher)
        return changed

    def _check_all_files(self, launcher: bytes) -> None:
        self._prepare_store()
        target = self._link_target(self.current)
        if target is None:
            raise InstallError("brak aktywnego wydania CLI")
        expected_files = self._source_files()
        expected_files.pop(".launcher")
        expected = self._digest(expected_files)
        if target != f"releases/{expected}":
            raise InstallError("aktywne wydanie CLI nie odpowiada bieżącym źródłom")
        self._check_regular_file(self.layout.launcher, expected=launcher, mode=0o755)

    def check(self) -> None:
        self._check_directory(self.root.parent)
        self._check_directory(self.layout.launcher.parent)
        files = self._source_files()
        launcher = files.pop(".launcher")
        self._check_all_files(launcher)

    def rollback(self) -> None:
        self._require_root()
        self._check_directory(self.root.parent)
        self._check_directory(self.layout.launcher.parent)
        files = self._source_files()
        launcher = files.pop(".launcher")
        state = self._launcher_state(launcher)
        self._prepare_store()
        current_target = self._link_target(self.current)
        if current_target is None:
            raise InstallError("nie ma aktywnego wydania CLI do wycofania")
        previous_target = self._link_target(self.previous)
        if previous_target is not None:
            if state != "managed":
                raise InstallError("launcher nie jest zarządzaną wersją CLI; odmowa zmiany aktywnego wydania")
            self._atomic_link(self.current, previous_target)
            self._atomic_link(self.previous, current_target)
            print(f"Przywrócono poprzednie wydanie: {previous_target.removeprefix('releases/')}")
            return

        if self.legacy_launcher.exists() or self.legacy_launcher.is_symlink():
            legacy = self._check_regular_file(self.legacy_launcher, expected=LEGACY_LAUNCHER, mode=0o755)
            self._atomic_write(self.layout.launcher, legacy, 0o755)
        elif state == "managed":
            self.layout.launcher.unlink()
        else:
            raise InstallError("launcher uległ zmianie; odmowa usunięcia nieznanego pliku")
        self._atomic_link(self.current, None)
        print("Wycofano pierwszą instalację CLI.")


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Instalacja wyłącznie odczytowego CLI PcDog.")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--check", action="store_true", help="sprawdź instalację bez zmian")
    action.add_argument("--rollback", action="store_true", help="przywróć poprzednie wydanie CLI")
    parser.add_argument("--version", action="version", version="pcdog-cli-installer 1")
    args = parser.parse_args(arguments)
    installer = CliInstaller(repository_layout())
    try:
        if args.check:
            installer.check()
            print("CLI jest zainstalowane i odpowiada bieżącej wersji źródeł.")
        elif args.rollback:
            installer.rollback()
        else:
            changed = installer.install()
            print("CLI zainstalowano/zaktualizowano." if changed else "CLI już odpowiada tej wersji; bez zmian.")
            installer._report_optional_dependencies()
        return 0
    except InstallError as error:
        print(f"install-cli: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"install-cli: błąd systemu plików: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
