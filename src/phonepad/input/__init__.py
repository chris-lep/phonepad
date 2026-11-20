"""Input injection: backend selection and the single input thread."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TypeVar

from phonepad.config import PointerBackendName
from phonepad.input.base import InputUnavailableError, KeyboardBackend, PointerBackend

log = logging.getLogger(__name__)

T = TypeVar("T")

__all__ = ["InputService", "InputUnavailableError", "create_input_service"]


class InputService:
    """Owns the backends and runs every call on one thread, in arrival order.

    The pointer is created at start, the keyboard on first use (it needs X). A backend that
    cannot be created is retried on the next use, so the server survives starting before the
    X session or before `/dev/uinput` access is granted.
    """

    def __init__(
        self,
        pointer_factory: Callable[[], PointerBackend],
        keyboard_factory: Callable[[], KeyboardBackend],
    ) -> None:
        self._pointer_factory = pointer_factory
        self._keyboard_factory = keyboard_factory
        self._pointer: PointerBackend | None = None
        self._keyboard: KeyboardBackend | None = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="phonepad-input")
        self.last_error = ""

    async def _run(self, fn: Callable[[], T]) -> T:
        return await asyncio.get_running_loop().run_in_executor(self._executor, fn)

    async def start(self) -> None:
        try:
            await self.pointer(lambda _pointer: None)
        except InputUnavailableError as exc:
            log.warning("pointer not available yet: %s", exc)

    @property
    def pointer_name(self) -> str:
        return self._pointer.name if self._pointer else "none"

    @property
    def keyboard_name(self) -> str:
        return self._keyboard.name if self._keyboard else "not started"

    async def pointer(self, action: Callable[[PointerBackend], None]) -> None:
        def call() -> None:
            if self._pointer is None:
                self._pointer = self._pointer_factory()
                log.info("pointer backend: %s", self._pointer.name)
            action(self._pointer)

        await self._guarded(call)

    async def keyboard(self, action: Callable[[KeyboardBackend], None]) -> None:
        def call() -> None:
            if self._keyboard is None:
                self._keyboard = self._keyboard_factory()
                log.info("keyboard backend: %s", self._keyboard.name)
            action(self._keyboard)

        await self._guarded(call)

    async def _guarded(self, call: Callable[[], None]) -> None:
        try:
            await self._run(call)
        except InputUnavailableError as exc:
            self.last_error = str(exc)
            raise
        except Exception as exc:
            log.exception("input backend failed")
            self.last_error = f"{type(exc).__name__}: {exc}"
            raise InputUnavailableError(self.last_error) from exc

    async def close(self) -> None:
        def close_all() -> None:
            for backend in (self._keyboard, self._pointer):
                if backend is not None:
                    try:
                        backend.close()
                    except Exception:
                        log.exception("closing %s failed", backend.name)

        await self._run(close_all)
        self._executor.shutdown(wait=True)


def create_input_service(
    pointer_backend: PointerBackendName = "auto", record: Path | None = None
) -> InputService:
    """Backends for this system, or recording backends when `record` is given."""
    if record is not None:
        from phonepad.input.recording import Recorder, RecordingKeyboard, RecordingPointer

        recorder = Recorder(record)
        return InputService(lambda: RecordingPointer(recorder), lambda: RecordingKeyboard(recorder))

    from phonepad.input.xtest import XSession, XTestKeyboard, XTestPointer

    session = XSession()  # shared by keyboard and pointer fallback; used on the input thread only

    def make_pointer() -> PointerBackend:
        if pointer_backend in ("auto", "uinput"):
            from phonepad.input.uinput import UinputPointer

            try:
                return UinputPointer()
            except InputUnavailableError as exc:
                if pointer_backend == "uinput":
                    raise
                log.warning("%s; falling back to the XTest pointer", exc)
        return XTestPointer(session)

    def make_keyboard() -> KeyboardBackend:
        return XTestKeyboard(session)

    return InputService(make_pointer, make_keyboard)
