from __future__ import annotations

import ast
import subprocess
import sys
import textwrap
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TASK_UTILS = ROOT / "libs" / "task_utils"
FILE_LOCK_MODULE = TASK_UTILS / "workbench_task_utils" / "file_lock.py"
sys.path.insert(0, str(TASK_UTILS))

from workbench_task_utils import exclusive_file_lock


def test_exclusive_file_lock_serializes_threads(tmp_path: Path) -> None:
    lock_path = tmp_path / "shared.lock"
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()

    def hold_first() -> None:
        with exclusive_file_lock(lock_path):
            first_entered.set()
            assert release_first.wait(5)

    def enter_second() -> None:
        with exclusive_file_lock(lock_path):
            second_entered.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(hold_first)
        assert first_entered.wait(5)
        second = executor.submit(enter_second)
        try:
            assert not second_entered.wait(0.1)
        finally:
            release_first.set()
        first.result(timeout=5)
        second.result(timeout=5)

    assert second_entered.is_set()
    assert lock_path.exists()


def test_exclusive_file_lock_releases_after_body_error(tmp_path: Path) -> None:
    lock_path = tmp_path / "failure.lock"

    with pytest.raises(RuntimeError, match="injected failure"):
        with exclusive_file_lock(lock_path):
            raise RuntimeError("injected failure")

    with exclusive_file_lock(lock_path):
        pass


def test_windows_backend_imports_without_fcntl_and_locks_first_byte(tmp_path: Path) -> None:
    lock_path = tmp_path / "windows.lock"
    script = textwrap.dedent(
        f"""
        import builtins
        import errno
        import importlib.util
        import os
        import sys
        import types

        calls = []
        fake_msvcrt = types.ModuleType("msvcrt")
        fake_msvcrt.LK_NBLCK = 1
        fake_msvcrt.LK_UNLCK = 2

        def locking(descriptor, mode, length):
            calls.append((mode, length, os.lseek(descriptor, 0, os.SEEK_CUR)))
            if mode == fake_msvcrt.LK_NBLCK and sum(call[0] == mode for call in calls) == 1:
                raise OSError(errno.EACCES, "lock is busy")

        fake_msvcrt.locking = locking
        sys.modules["msvcrt"] = fake_msvcrt

        original_import = builtins.__import__
        def guarded_import(name, *args, **kwargs):
            if name == "fcntl":
                raise AssertionError("Windows backend requested fcntl")
            return original_import(name, *args, **kwargs)

        original_os_name = os.name
        builtins.__import__ = guarded_import
        os.name = "nt"
        try:
            spec = importlib.util.spec_from_file_location("windows_file_lock", {str(FILE_LOCK_MODULE)!r})
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            os.name = original_os_name
            builtins.__import__ = original_import

        module.time.sleep = lambda _seconds: None
        with module.exclusive_file_lock({str(lock_path)!r}):
            pass

        assert calls == [(1, 1, 0), (1, 1, 0), (2, 1, 0)]
        assert os.path.getsize({str(lock_path)!r}) == 1
        """
    )

    result = subprocess.run(
        [sys.executable, "-S", "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_lock_consumers_do_not_import_fcntl_directly() -> None:
    consumers = [
        ROOT / "libs" / "kernel" / "workbench" / "kernel" / "version_registry.py",
        ROOT / "hardware" / "validation" / "tools" / "evidence.py",
    ]

    for consumer in consumers:
        tree = ast.parse(consumer.read_text(encoding="utf-8"))
        imported_modules = {
            alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
        }
        imported_modules.update(
            node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module is not None
        )
        assert "fcntl" not in imported_modules
