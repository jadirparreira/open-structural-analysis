"""Numerical assertions with explicit engineering tolerances."""

from __future__ import annotations

from collections.abc import Sequence
from math import isclose


def assert_close(
    actual: float,
    expected: float,
    *,
    abs_tol: float = 1e-9,
    rel_tol: float = 1e-9,
) -> None:
    """Assert a scalar and include the tolerances in the failure message."""
    assert isclose(actual, expected, rel_tol=rel_tol, abs_tol=abs_tol), (
        f"actual={actual!r} differs from expected={expected!r} "
        f"(abs_tol={abs_tol}, rel_tol={rel_tol})"
    )


def assert_vector_close(
    actual: Sequence[float],
    expected: Sequence[float],
    *,
    abs_tol: float = 1e-9,
    rel_tol: float = 1e-9,
) -> None:
    """Assert corresponding components of two engineering vectors."""
    assert len(actual) == len(expected)
    for actual_component, expected_component in zip(actual, expected):
        assert_close(
            actual_component,
            expected_component,
            abs_tol=abs_tol,
            rel_tol=rel_tol,
        )
