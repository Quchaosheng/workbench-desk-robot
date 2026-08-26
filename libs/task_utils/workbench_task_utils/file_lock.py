"""Cross-platform advisory file locking using only the Python standard library."""

from __future__ import annotations

import errno
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

_WINDOWS = os.name == "nt"

if _WINDOWS:
    import msvcrt
else:
    import fcntl

_LOCK_RETRY_SECONDS = 0.05
_thread_locks: dict[str, threading.Lock] = {}
_thread_locks_guard = threading.Lock()


def _normalized_path(lock_path: str | os.PathLike[str]) -> str:
    path = os.fspath(lock_path)
    if not isinstance(path, str):
        raise TypeError("lock path must resolve to a string")
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def _thread_lock_for(path: str) -> threading.Lock:
    with _thread_locks_guard:
        return _thread_locks.setdefault(path, threading.Lock())


def _ensure_lock_byte(descriptor: int) -> None:
    if os.fstat(descriptor).st_size:
        return
    os.lseek(descriptor, 0, os.SEEK_SET)
    if os.write(descriptor, b"\0") != 1:
        raise OSError(errno.EIO, "could not initialize lock file")


def _acquire_descriptor(descriptor: int) -> None:
    if not _WINDOWS:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        return

    while True:
        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise
            time.sleep(_LOCK_RETRY_SECONDS)
        else:
            return


def _release_descriptor(descriptor: int) -> None:
    if not _WINDOWS:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        return
    os.lseek(descriptor, 0, os.SEEK_SET)
    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)


@contextmanager
def exclusive_file_lock(lock_path: str | os.PathLike[str]) -> Iterator[None]:
    """Hold an exclusive advisory lock for one persistent sidecar file."""

    path = _normalized_path(lock_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0)

    with _thread_lock_for(path):
        descriptor = os.open(path, flags, 0o666)
        acquired = False
        try:
            if _WINDOWS:
                _ensure_lock_byte(descriptor)
            _acquire_descriptor(descriptor)
            acquired = True
            yield
        finally:
            try:
                if acquired:
                    _release_descriptor(descriptor)
            finally:
                os.close(descriptor)
