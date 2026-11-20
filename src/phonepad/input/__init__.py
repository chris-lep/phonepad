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
    X session or before `/dev/uinput` access is granted. A backend that fails unexpectedly is
    dropped and recreated on the next use. When the pointer fell back from `preferred_pointer`
    (uinput), each new phone session tries the preferred backend again.
    """

    def __init__(
        self,
        pointer_factory: Callable[[], PointerBackend],
        keyboard_factory: Callable[[], KeyboardBackend],
        preferred_pointer: str | None = None,
    ) -> None:
        self._pointer_factory = pointer_factory
        self._keyboard_factory = keyboard_factory
        self._preferred_pointer = preferred_pointer
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

    def _get_pointer(self) -> PointerBackend:
        if self._pointer is None:
            self._pointer = self._pointer_factory()
            log.info("pointer backend: %s", self._pointer.name)
        return self._pointer

    def _get_keyboard(self) -> KeyboardBackend:
        if self._keyboard is None:
            self._keyboard = self._keyboard_factory()
            log.info("keyboard backend: %s", self._keyboard.name)
        return self._keyboard

    async def pointer(self, action: Callable[[PointerBackend], None]) -> None:
        await self._guarded(lambda: action(self._get_pointer()), "pointer")

    async def keyboard(self, action: Callable[[KeyboardBackend], None]) -> None:
        await self._guarded(lambda: action(self._get_keyboard()), "keyboard")

    async def new_session(self) -> None:
        """A phone connected: upgrade a fallback pointer if possible, re-apply settings."""

        def prepare() -> None:
            current = self._pointer
            if current is not None and self._preferred_pointer not in (None, current.name):
                candidate = self._pointer_factory()
                if candidate.name == self._preferred_pointer:
                    log.info("pointer backend: %s (was %s)", candidate.name, current.name)
                    self._pointer = candidate
                    _close_quietly(current)
                else:
                    _close_quietly(candidate)
            self._get_pointer().prepare_session()

        await self._guarded(prepare, "pointer")

    async def _guarded(self, call: Callable[[], None], kind: str) -> None:
        def run() -> None:
            try:
                call()
            except InputUnavailableError:
                raise
            except Exception:
                # Unknown state: drop the backend so the next use creates a fresh one.
                if kind == "pointer":
                    backend: PointerBackend | KeyboardBackend | None = self._pointer
                    self._pointer = None
                else:
                    backend = self._keyboard
                    self._keyboard = None
                if backend is not None:
                    _close_quietly(backend)
                raise

        try:
            await self._run(run)
        except InputUnavailableError as exc:
            self.last_error = str(exc)
            raise
        except Exception as exc:
            log.exception("%s backend failed", kind)
            self.last_error = f"{type(exc).__name__}: {exc}"
            raise InputUnavailableError(self.last_error) from exc
        self.last_error = ""

    async def close(self) -> None:
        def close_all() -> None:
            for backend in (self._keyboard, self._pointer):
                if backend is not None:
                    _close_quietly(backend)

        await self._run(close_all)
        self._executor.shutdown(wait=True)


def _close_quietly(backend: PointerBackend | KeyboardBackend) -> None:
    try:
        backend.close()
    except Exception:
        log.exception("closing %s failed", backend.name)


def create_input_service(
    pointer_backend: PointerBackendName = "auto",
    record: Path | None = None,
    keymap_record: Path | None = None,
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
        return XTestKeyboard(session, keymap_record)

    preferred = "uinput" if pointer_backend == "auto" else None
    return InputService(make_pointer, make_keyboard, preferred)
