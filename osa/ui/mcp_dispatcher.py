"""Execute MCP requests on the Qt thread that owns the live model and widgets."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal, Slot


@dataclass
class _Call:
    function: Callable[..., Any]
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    done: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: Exception | None = None


class McpQtDispatcher(QObject):
    """Serialize MCP access with ordinary GUI edits on Qt's event thread."""

    requested = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._state_lock = threading.Lock()
        self._active = True
        self._pending: list[_Call] = []
        self.requested.connect(self._execute)

    def resume(self) -> None:
        with self._state_lock:
            self._active = True

    def suspend(self) -> None:
        """Reject queued requests before the HTTP listener is stopped."""
        with self._state_lock:
            self._active = False
            for request in self._pending:
                request.error = RuntimeError("O servidor MCP foi desativado.")
                request.done.set()
            self._pending.clear()

    def call(self, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if QThread.currentThread() == self.thread():
            with self._state_lock:
                if not self._active:
                    raise RuntimeError("O servidor MCP foi desativado.")
            return function(*args, **kwargs)
        request = _Call(function, args, kwargs)
        with self._state_lock:
            if not self._active:
                raise RuntimeError("O servidor MCP foi desativado.")
            self._pending.append(request)
        self.requested.emit(request)
        request.done.wait()
        if request.error is not None:
            raise request.error
        return request.result

    @Slot(object)
    def _execute(self, request: _Call) -> None:
        if request.done.is_set():
            return
        try:
            request.result = request.function(*request.args, **request.kwargs)
        except Exception as error:  # noqa: BLE001 - relay application errors to the caller
            request.error = error
        finally:
            with self._state_lock:
                if request in self._pending:
                    self._pending.remove(request)
            request.done.set()
