"""Map rendering for gyro cleaning maps (256x256 grid)."""

from __future__ import annotations

import io
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

    # Latest point per cell wins; the path is drawn as a line on top
    cells: dict[tuple[int, int], int] = {}
    for p in valid:
        cells[(p["x"], p["y"])] = p.get("type", -1)

    for (x, y), ptype in cells.items():
        category = classify(ptype)
        if category == "path":
            category = "cleaned"
        draw.rectangle(box(x, y), fill=MAP_COLORS.get(category, MAP_COLORS["other"]))

    def center(x: int, y: int) -> tuple[float, float]:
        left, top, right, bottom = box(x, y)
        return (left + right) / 2, (top + bottom) / 2

    path = [center(p["x"], p["y"]) for p in valid if classify(p.get("type", -1)) == "path"]
    width = max(1, cell // 4)
    if len(path) > 1:
        draw.line(path, fill=MAP_COLORS["path"], width=width, joint="curve")
        # Most recent stretch stands out
        draw.line(path[-20:], fill=MAP_COLORS["recent"], width=width + 1, joint="curve")

    size = max(4.0, cell * 0.9)

    # Dock: green house at the origin
    ox, oy = center(MAP_ORIGIN, MAP_ORIGIN)
    draw.polygon(
        [(ox, oy - size), (ox + size, oy), (ox + size * 0.7, oy), (ox + size * 0.7, oy + size * 0.8),
         (ox - size * 0.7, oy + size * 0.8), (ox - size * 0.7, oy), (ox - size, oy)],
        fill=MAP_COLORS["start"],
    )

    # Robot: gold circle with a mark pointing in the direction of travel
    if robot_xy and robot_xy[0] in GRID and robot_xy[1] in GRID:
        rx, ry = center(*robot_xy)
        draw.ellipse(
            (rx - size, ry - size, rx + size, ry + size),
            fill=MAP_COLORS["robot"],
            outline=(0x28, 0x28, 0x28, 0xFF),
            width=2,
        )
        previous = next((p for p in reversed(path) if p != (rx, ry)), None)
        if previous and tuple(robot_xy) != (MAP_ORIGIN, MAP_ORIGIN):
            dx, dy = rx - previous[0], ry - previous[1]
            length = (dx * dx + dy * dy) ** 0.5
            draw.line(
                [(rx, ry), (rx + dx / length * size, ry + dy / length * size)],
                fill=(0x28, 0x28, 0x28, 0xFF),
                width=max(2, cell // 4),
            )

    if robot_xy and tuple(robot_xy) == (MAP_ORIGIN, MAP_ORIGIN):
        # Keep the docked robot visible on top of the dock
        rx, ry = center(*robot_xy)
        draw.ellipse(
            (rx - size * 0.6, ry - size * 0.6, rx + size * 0.6, ry + size * 0.6),
            fill=MAP_COLORS["robot"],
        )

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
