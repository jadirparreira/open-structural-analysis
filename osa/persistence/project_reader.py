"""Incremental JSON reading for large projects, including saved analysis results.

Decode individual entities with the standard JSON decoder instead of holding
the GIL while decoding an entire project. Buffers and temporary strings stay
small, so a Qt worker can load large files without starving the GUI thread.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any, TextIO

from .deferred_result import DeferredResultMap

_WHITESPACE = re.compile(r"[ \t\r\n]*")
_DELIMITER = re.compile(r"[ \t\r\n,\]}]")
_STRUCTURAL = re.compile(r'\\[\s\S]|["{}\[\]]')


class ProjectReader:
    """Read project containers one record at a time, preserving JSON values."""

    def __init__(
        self, stream: TextIO, *, chunk_size: int = 128 * 1024,
        progress: Callable[[], None] | None = None,
        yield_control: Callable[[], None] | None = None,
        defer_results: bool = False,
        skip_redundant_bars: bool = False,
    ) -> None:
        self.stream = stream
        self.chunk_size = chunk_size
        self.progress = progress
        self.yield_control = yield_control
        self.defer_results = defer_results
        self.skip_redundant_bars = skip_redundant_bars
        self._members_seen = False
        self.decoder = json.JSONDecoder()
        self.buffer = ""
        self.position = 0
        self.eof = False

    def _read_more(self) -> bool:
        if self.eof:
            return False
        chunk = self.stream.read(self.chunk_size)
        self.buffer = self.buffer[self.position:] + chunk
        self.position = 0
        self.eof = not chunk
        if self.progress is not None:
            self.progress()
        if self.yield_control is not None:
            self.yield_control()
        return bool(chunk)

    def _peek(self) -> str:
        while True:
            self.position = _WHITESPACE.match(self.buffer, self.position).end()
            if self.position < len(self.buffer):
                return self.buffer[self.position]
            if not self._read_more():
                return ""

    def _expect(self, token: str) -> None:
        if self._peek() != token:
            raise json.JSONDecodeError(f"Esperado '{token}'", self.buffer, self.position)
        self.position += 1

    def _value(self, *, defer: bool = False) -> Any:
        first = self._peek()
        if not first:
            raise json.JSONDecodeError("Esperado um valor", self.buffer, self.position)
        # A partial numeric token (e.g. 12e at a buffer boundary) is otherwise
        # accepted as the integer prefix by raw_decode. Read its delimiter first.
        if first not in '{["':
            while not _DELIMITER.search(self.buffer, self.position) and not self.eof:
                self._read_more()
        while True:
            try:
                value, end = self.decoder.raw_decode(self.buffer, self.position)
            except json.JSONDecodeError:
                if self.eof:
                    raise
                self._read_more()
            else:
                if defer:
                    value = self.buffer[self.position:end]
                self.position = end
                return value

    def _array(self, read_item: Callable[[], Any]) -> list[Any]:
        self._expect("[")
        result = []
        if self._peek() != "]":
            while True:
                result.append(read_item())
                if self._peek() != ",":
                    break
                self.position += 1
                if self._peek() == "]":
                    raise json.JSONDecodeError("Esperado um valor", self.buffer, self.position)
        self._expect("]")
        return result

    def _object(self, read_field: Callable[[str], Any]) -> dict[str, Any]:
        self._expect("{")
        result = {}
        if self._peek() != "}":
            while True:
                if self._peek() != '"':
                    raise json.JSONDecodeError("Esperado um nome de campo", self.buffer, self.position)
                key = self._value()
                self._expect(":")
                result[key] = read_field(key)
                if self._peek() != ",":
                    break
                self.position += 1
                if self._peek() == "}":
                    raise json.JSONDecodeError("Esperado um nome de campo", self.buffer, self.position)
        self._expect("}")
        return result

    def _result_field(self, key: str) -> Any:
        if key in {"node_results", "member_results"} and self._peek() == "{":
            records = self._object(lambda _: self._value(defer=self.defer_results))
            return DeferredResultMap(records) if self.defer_results else records
        return self._value()

    def _project_field(self, key: str) -> Any:
        if key == "members":
            self._members_seen = True
        if key == "bars" and self._members_seen and self.skip_redundant_bars and self._peek() == "[":
            def discard_record():
                self._value()
            self._array(discard_record)
            return []
        if key == "results" and self._peek() == "[":
            return self._array(lambda: self._object(self._result_field))
        if self._peek() == "[":
            return self._array(self._value)
        return self._value()

    def read(self) -> dict[str, Any]:
        result = self._object(self._project_field)
        if self._peek():
            raise json.JSONDecodeError("Dados após o modelo", self.buffer, self.position)
        return result

    def _skip_value(self) -> None:
        """Skip a preview's unrelated fields without allocating their trees."""
        if self._peek() not in {"{", "["}:
            self._value()
            return
        depth = 0
        in_string = False
        while True:
            last_end = self.position
            for match in _STRUCTURAL.finditer(self.buffer, self.position):
                token = match.group()
                last_end = match.end()
                if token.startswith("\\"):
                    continue
                if token == '"':
                    in_string = not in_string
                elif not in_string:
                    depth += 1 if token in {"{", "["} else -1
                    if depth == 0:
                        self.position = match.end()
                        return
            # Preserve an escape split between two buffers.
            self.position = len(self.buffer)
            if in_string and self.buffer.endswith("\\") and last_end < len(self.buffer):
                self.position -= 1
            if not self._read_more():
                raise json.JSONDecodeError("Valor incompleto", self.buffer, self.position)

    def read_thumbnail(self) -> dict[str, Any] | None:
        self._expect("{")
        while self._peek() != "}":
            if self._peek() != '"':
                raise json.JSONDecodeError("Esperado um nome de campo", self.buffer, self.position)
            key = self._value()
            self._expect(":")
            if key == "thumbnail":
                return self._value()
            self._skip_value()
            if self._peek() != ",":
                break
            self.position += 1
        self._expect("}")
        return None
