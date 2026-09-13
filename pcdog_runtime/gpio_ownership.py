"""Wspólna, międzyprocesowa blokada wyjść sterujących PcDog."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path


DEFAULT_OUTPUT_LOCK_PATH = Path("/run/pcdog-gpio-control.lock")


class OutputLockBusyError(RuntimeError):
    """GPIO17/18 są aktualnie własnością innego, zatwierdzonego trybu."""


class OutputLock:
    """Advisory lock współdzielony przez agenta i lokalną diagnostykę.

    Deskryptor może być przekazany do ``gpioset``. Wtedy aktywny proces
    utrzymujący fizyczne wyjście utrzymuje także blokadę międzyprocesową.
    """

    def __init__(self, path: Path = DEFAULT_OUTPUT_LOCK_PATH) -> None:
        self._path = path
        self._fd: int | None = None

    def acquire(self) -> int:
        if self._fd is not None:
            return self._fd
        try:
            fd = os.open(self._path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            try:
                os.close(fd)
            except UnboundLocalError:
                pass
            raise OutputLockBusyError("GPIO17/GPIO18 są zajęte przez innego właściciela") from error
        self._fd = fd
        return fd

    def release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def __enter__(self) -> "OutputLock":
        self.acquire()
        return self

    def __exit__(self, *_: object) -> None:
        self.release()
