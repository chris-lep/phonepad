"""Backends that record events instead of injecting them (tests, `--record-input`)."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from phonepad.protocol import Button


class Recorder:
    """Collects events in memory and optionally appends them to a JSON-lines file."""

    def __init__(self, path: Path | None = None) -> None:
        self.events: list[dict[str, Any]] = []
        self._path = path
        self._lock = threading.Lock()
        if path is not None:
            path.write_text("", encoding="utf-8")

    def record(self, **event: Any) -> None:
        with self._lock:
            self.events.append(event)
            if self._path is not None:
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(event, ensure_ascii=False) + "\n")


class RecordingPointer:
    name = "recording"

    def __init__(self, recorder: Recorder) -> None:
        self._rec = recorder

    def move(self, dx: int, dy: int) -> None:
        self._rec.record(kind="move", dx=dx, dy=dy)

    def scroll(self, dx: int, dy: int) -> None:
        self._rec.record(kind="scroll", dx=dx, dy=dy)

    def button(self, button: Button, pressed: bool) -> None:
        self._rec.record(kind="button", button=button, pressed=pressed)

    def prepare_session(self) -> None:
        pass

    def close(self) -> None:
        pass


class RecordingKeyboard:
    name = "recording"

    def __init__(self, recorder: Recorder) -> None:
        self._rec = recorder

    def key(self, key: str) -> None:
        self._rec.record(kind="key", key=key)

    def type_text(self, text: str) -> None:
        self._rec.record(kind="text", text=text)

    def close(self) -> None:
        pass
