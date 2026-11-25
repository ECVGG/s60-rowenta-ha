"""Map rendering for gyro cleaning maps (256x256 grid)."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from .const import (
    MAP_ORIGIN,
    MAP_GRID_SIZE,
    MAP_PADDING,
    MAP_MIN_CELL,
    MAP_MAX_CELL,
    MAP_MAX_DIMENSION,
    MAP_POINT_TYPES,
    MAP_COLORS,
)

GRID = range(MAP_GRID_SIZE)


def classify(ptype: int) -> str:
    for cat, types in MAP_POINT_TYPES.items():
        if ptype in types:
            return cat
    return "other"


def render_map(points: list[dict[str, Any]], robot_xy: tuple[int, int] | None = None) -> bytes:
    """Render gyro map points to PNG bytes."""
    valid = [
        p for p in points
        if isinstance(p, dict)
        and isinstance(p.get("x"), int)
        and isinstance(p.get("y"), int)
        and p["x"] in GRID
        and p["y"] in GRID
    ]

    if not valid:
        img = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    valid.sort(key=lambda p: p.get("index", 0))

    xs = [p["x"] for p in valid] + [MAP_ORIGIN]
    ys = [p["y"] for p in valid] + [MAP_ORIGIN]
    if robot_xy:
        xs.append(robot_xy[0])
        ys.append(robot_xy[1])

    min_x, max_x = min(xs) - MAP_PADDING, max(xs) + MAP_PADDING
    min_y, max_y = min(ys) - MAP_PADDING, max(ys) + MAP_PADDING
    w, h = max_x - min_x + 1, max_y - min_y + 1

    cell = max(MAP_MIN_CELL, min(MAP_MAX_CELL, MAP_MAX_DIMENSION // max(w, h)))
    gap = 1 if cell >= 8 else 0

    img = Image.new("RGBA", (w * cell, h * cell), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    def box(x: int, y: int) -> tuple[int, int, int, int]:
        left = (x - min_x) * cell
        top = (max_y - y) * cell
        return left, top, left + cell - 1 - gap, top + cell - 1 - gap

    # Latest point per cell wins
    cells: dict[tuple[int, int], int] = {}
    for p in valid:
        cells[(p["x"], p["y"])] = p.get("type", -1)

    for (x, y), ptype in cells.items():
        draw.rectangle(box(x, y), fill=MAP_COLORS.get(classify(ptype), MAP_COLORS["other"]))

    # Start marker (green ring at origin)
    inset = max(1, cell // 6)
    left, top, right, bottom = box(MAP_ORIGIN, MAP_ORIGIN)
    draw.ellipse(
        (left + inset, top + inset, right - inset, bottom - inset),
        outline=MAP_COLORS["start"],
        width=max(2, cell // 6),
    )

    # Robot position (gold circle with dark border)
    if robot_xy:
        rx, ry = robot_xy
        if rx in GRID and ry in GRID:
            left, top, right, bottom = box(rx, ry)
            draw.ellipse(
                (left - 2, top - 2, right + 2, bottom + 2),
                fill=MAP_COLORS["robot"],
                outline=(0x28, 0x28, 0x28, 0xFF),
                width=2,
            )

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


class MapStore:
    """Persistent map cache (memory + disk)."""

    def __init__(self, base_dir: Path) -> None:
        self._dir = base_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._mem: dict[str, bytes] = {}

    def _key(self, dev_id: str, map_id: str) -> str:
        return f"{dev_id}_{map_id}"

    def _path(self, dev_id: str, map_id: str) -> Path:
        return self._dir / f"{self._key(dev_id, map_id)}.png"

    def get(self, dev_id: str, map_id: str) -> bytes | None:
        key = self._key(dev_id, map_id)
        if key in self._mem:
            return self._mem[key]
        path = self._path(dev_id, map_id)
        if path.exists():
            try:
                data = path.read_bytes()
                self._mem[key] = data
                return data
            except OSError:
                pass
        return None

    def set(self, dev_id: str, map_id: str, data: bytes) -> None:
        key = self._key(dev_id, map_id)
        self._mem[key] = data
        try:
            self._path(dev_id, map_id).write_bytes(data)
        except OSError:
            pass

    def drop(self, dev_id: str, map_id: str) -> None:
        key = self._key(dev_id, map_id)
        self._mem.pop(key, None)
        try:
            self._path(dev_id, map_id).unlink(missing_ok=True)
        except OSError:
            pass