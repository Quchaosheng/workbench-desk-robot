"""Shared utilities used across Workbench task boundaries."""

from .file_lock import exclusive_file_lock

__all__ = ["exclusive_file_lock"]
