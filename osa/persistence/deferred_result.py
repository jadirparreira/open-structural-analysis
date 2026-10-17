"""Keep saved result records compact until their values are inspected."""

from __future__ import annotations

import copy
import json
from collections.abc import Iterator, MutableMapping
from typing import Any


class DeferredResultMap(MutableMapping[str, Any]):
    """Independent JSON records exposed as ordinary result dictionaries.

    Analysis files may contain millions of nested sample dictionaries. Keeping
    unopened records as strings avoids allocating and garbage-collecting that
    entire object graph while opening the model. No reference to the source
    file is retained; replacing or deleting it cannot invalidate these values.
    """

    __slots__ = ("_encoded", "_values")

    def __init__(self, records: dict[str, str]) -> None:
        self._values: dict[str, Any] = records
        self._encoded = set(records)

    def __getitem__(self, key: str) -> Any:
        if key in self._encoded:
            self._values[key] = json.loads(self._values[key])
            self._encoded.remove(key)
        return self._values[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._values[key] = value
        self._encoded.discard(key)

    def __delitem__(self, key: str) -> None:
        del self._values[key]
        self._encoded.discard(key)

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def copy(self) -> dict[str, Any]:
        return dict(self.items())

    def __deepcopy__(self, memo: dict) -> dict[str, Any]:
        # dataclasses.asdict uses deepcopy for mapping values. Return ordinary
        # JSON-compatible dictionaries without expanding the live model cache.
        result = {}
        memo[id(self)] = result
        for key, value in self._values.items():
            result[key] = json.loads(value) if key in self._encoded else copy.deepcopy(value, memo)
        return result
