"""Filesystem safety utilities and atomic file writing for Templatte."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from types import TracebackType
from typing import IO, Any


def is_within_workspace(target: Path | str, workspace: Path | str) -> bool:
    """Verify that the target path resolves strictly within the workspace directory.

    Prevents directory traversal attacks (e.g. ../../etc/passwd).
    """
    target_path = Path(target).resolve()
    workspace_path = Path(workspace).resolve()
    try:
        return target_path.is_relative_to(workspace_path)
    except AttributeError:
        # Fallback for Python versions before is_relative_to (though >=3.10 is required)
        try:
            target_path.relative_to(workspace_path)
            return True
        except ValueError:
            return False


def normalize_workspace_path(path: Path | str, workspace: Path | str | None = None) -> str:
    """Normalize a path to a workspace-relative POSIX format with forward slashes.

    Strips any leading './' and converts backslashes to forward slashes (Invariant 2).
    """
    p = Path(path)
    if workspace is not None:
        ws = Path(workspace).resolve()
        resolved = p.resolve()
        if resolved.is_relative_to(ws):
            p = resolved.relative_to(ws)
    posix_str = p.as_posix()
    posix_str = posix_str.removeprefix("./")
    return posix_str


class AtomicFileWriter:
    """Context manager for atomic file writing via sibling temporary files.

    Writes changes to a sibling temporary file in the same directory, flushes and fsyncs,
    and replaces the target file atomically via os.replace upon successful exit.
    If an exception occurs within the context block, the temporary file is unlinked,
    leaving the target file untouched.
    """

    def __init__(
        self,
        target_path: Path | str,
        mode: str = "w",
        encoding: str | None = "utf-8",
        errors: str | None = None,
        newline: str | None = None,
    ) -> None:
        self.target_path = Path(target_path).resolve()
        self.mode = mode
        self.encoding = encoding if "b" not in mode else None
        self.errors = errors
        self.newline = newline
        self._temp_file: IO[Any] | None = None
        self._temp_path: Path | None = None

    def __enter__(self) -> IO[Any]:
        # Ensure parent directory exists
        self.target_path.parent.mkdir(parents=True, exist_ok=True)
        # Create sibling temp file
        prefix = f".{self.target_path.name}.tmp."
        tf = tempfile.NamedTemporaryFile(
            mode=self.mode,
            dir=self.target_path.parent,
            prefix=prefix,
            encoding=self.encoding,
            errors=self.errors,
            newline=self.newline,
            delete=False,
        )
        self._temp_file = tf
        self._temp_path = Path(tf.name)
        return tf

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._temp_file is not None and not self._temp_file.closed:
            if exc_type is None:
                self._temp_file.flush()
                try:
                    os.fsync(self._temp_file.fileno())
                except (AttributeError, OSError):
                    pass
            self._temp_file.close()

        if self._temp_path is not None:
            if exc_type is not None:
                # Discard temp file on error
                if self._temp_path.exists():
                    try:
                        self._temp_path.unlink()
                    except OSError:
                        pass
            else:
                # Atomically replace target
                os.replace(self._temp_path, self.target_path)


def atomic_write_text(
    target_path: Path | str,
    content: str,
    encoding: str = "utf-8",
) -> None:
    """Convenience helper to atomically write text content to a file."""
    with AtomicFileWriter(target_path, mode="w", encoding=encoding) as f:
        f.write(content)


def atomic_write_bytes(
    target_path: Path | str,
    content: bytes,
) -> None:
    """Convenience helper to atomically write binary bytes content to a file."""
    with AtomicFileWriter(target_path, mode="wb", encoding=None) as f:
        f.write(content)
