"""View-local break symbols and clipping for projected member linework."""

from __future__ import annotations

import math
from bisect import bisect_right
from itertools import pairwise


def member_break_linework(segments, owners, marks, *, return_symbols=False):
    """Replace selected member ends with zig-zags, preserving segment ownership.

    Each mark stores a projected axis, the chosen end (0=start, 1=end),
    and an optional position along the original member (0 to 1).
    Source geometry stays untouched so removing a mark restores the original end.
    """
    if not marks or len(segments) != len(owners):
        return (segments, owners, {}) if return_symbols else (segments, owners)
    result, sources = list(segments), list(owners)
    symbols = {}
    # Measure every end against the original view, including when both ends
    # are marked. This prevents the second symbol shifting after the first clip.
    for mark_index, mark in enumerate(marks):
        owner = str(mark.get("owner", ""))
        if not owner:
            continue
        try:
            ax, ay = (float(value) for value in mark["axis"])
            length = math.hypot(ax, ay)
            if not math.isfinite(length) or length < 1e-12:
                continue
            sign = 1.0 if int(mark["end"]) == 1 else -1.0
        except (KeyError, TypeError, ValueError):
            continue
        ax, ay = sign * ax / length, sign * ay / length
        nx, ny = -ay, ax

        def local(point, nx=nx, ny=ny, ax=ax, ay=ay):
            return point[0] * nx + point[1] * ny, point[0] * ax + point[1] * ay

        points = [local(point) for segment, source in zip(segments, owners)
                  if source == owner for point in segment]
        if not points:
            continue
        lo, hi = min(p[0] for p in points), max(p[0] for p in points)
        bottom, top = min(p[1] for p in points), max(p[1] for p in points)
        width, span = hi - lo, top - bottom
        if min(width, span) < 1e-10:
            continue
        middle = (lo + hi) / 2.0
        amplitude = min(width * 0.3, span * 0.12)
        station = top - min(width * 0.2, span * 0.18)
        if "position" in mark:
            position = float(mark["position"])
            if math.isfinite(position):
                position = min(0.98, max(0.02, position))
                station = bottom + (position if sign > 0 else 1.0 - position) * span
        us = (lo - width * 0.18, middle - width * 0.20,
              middle - width * 0.065, middle + width * 0.065,
              middle + width * 0.20, hi + width * 0.18)
        vs = (station, station, station + amplitude, station - amplitude, station, station)

        def boundary(u, us=us, vs=vs):
            index = max(0, min(len(us) - 2, bisect_right(us, u) - 1))
            return vs[index] + (vs[index + 1] - vs[index]) * (u - us[index]) / (us[index + 1] - us[index])

        clipped, clipped_owners = [], []
        for (start, end), source in zip(result, sources):
            if source != owner:
                clipped.append((start, end))
                clipped_owners.append(source)
                continue
            u0, v0 = local(start)
            u1, v1 = local(end)
            cuts = [0.0, 1.0]
            if abs(u1 - u0) > 1e-12:
                cuts.extend(t for u in us if 0.0 < (t := (u - u0) / (u1 - u0)) < 1.0)
            cuts.sort()
            intervals = []
            for first, last in pairwise(cuts):
                f0 = v0 + first * (v1 - v0) - boundary(u0 + first * (u1 - u0))
                f1 = v0 + last * (v1 - v0) - boundary(u0 + last * (u1 - u0))
                if f0 > 1e-10 and f1 > 1e-10:
                    continue
                if (f0 > 1e-10) != (f1 > 1e-10):
                    crossing = first + (last - first) * f0 / (f0 - f1)
                    if f0 > 1e-10:
                        first = crossing
                    else:
                        last = crossing
                if last - first > 1e-12:
                    if intervals and abs(intervals[-1][1] - first) < 1e-12:
                        intervals[-1] = intervals[-1][0], last
                    else:
                        intervals.append((first, last))
            for first, last in intervals:
                clipped.append(tuple(
                    tuple(start) if t == 0.0 else tuple(end) if t == 1.0 else
                    (float(start[0] + t * (end[0] - start[0])),
                     float(start[1] + t * (end[1] - start[1]))) for t in (first, last)
                ))
                clipped_owners.append(source)
        symbol = [(u * nx + v * ax, u * ny + v * ay) for u, v in zip(us, vs)]
        symbols[mark_index] = tuple(pairwise(symbol))
        clipped.extend(pairwise(symbol))
        clipped_owners.extend([owner] * (len(symbol) - 1))
        result, sources = clipped, clipped_owners
    linework = tuple(result), tuple(sources)
    return (*linework, symbols) if return_symbols else linework
