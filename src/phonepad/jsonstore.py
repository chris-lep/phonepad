"""Small JSON state files shared by the server and the CLI.

Writes are atomic (temp file + rename, mode 0600) and read-modify-write cycles hold an
exclusive `flock` on a sidecar lock file, so `phonepad revoke` and a pairing in the running
server cannot lose each other's changes.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypeVar

from phonepad.paths import ensure_private_dir

T = TypeVar("T")


class StateFileError(RuntimeError):
    """A state file exists but cannot be read or is not a JSON object."""


class JsonFile:
    """A JSON object stored in `path`. A missing file reads as `default()`.

    A file that exists but cannot be read raises `StateFileError` when `strict`, so a
    temporary read error (or a corrupt file) is never mistaken for "no devices" and never
    overwritten with the default. Non-strict files (the pairing code) read as `default()`.
    """

    def __init__(
        self, path: Path, default: Callable[[], dict[str, Any]], *, strict: bool = True
    ) -> None:
        self.path = path
        self._default = default
        self._strict = strict

    def read(self) -> dict[str, Any]:
        try:
            with self.path.open(encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            return self._default()
        except (OSError, ValueError) as exc:
            if self._strict:
                raise StateFileError(f"cannot read {self.path}: {exc}") from exc
            return self._default()
        if isinstance(data, dict):
            return data
        if self._strict:
            raise StateFileError(f"{self.path} does not contain a JSON object")
        return self._default()

    @contextmanager
    def _locked(self) -> Iterator[None]:
        ensure_private_dir(self.path.parent)
        lock = self.path.with_name(self.path.name + ".lock")
        fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def update(self, change: Callable[[dict[str, Any]], T]) -> T:
        """Apply `change` to the current data under the lock and save the result.

        `change` mutates the data in place and returns a value for the caller.
        """
        with self._locked():
            data = self.read()
            result = change(data)
            self._write(data)
            return result

    def delete(self) -> None:
        with self._locked():
            self.path.unlink(missing_ok=True)

    def _write(self, data: dict[str, Any]) -> None:
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=f".{self.path.name}.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, sort_keys=True)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            Path(tmp).replace(self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
