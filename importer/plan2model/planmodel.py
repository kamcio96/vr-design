"""Zapis wyniku jako PlanModel JSON (schemat v2). Jednostki: metry, X w prawo, Z w dół rzutu."""

from __future__ import annotations

from typing import Any

from . import openings as openings_
from .furniture import FurniturePx
from .rooms import RoomPx
from .scale import Scale
from .walls import WallPx

# v2: lista mebli (furniture); v3: drzwi i okna (openings), przód mebli, params;
# v4: katalog materiałów, materiały pomieszczeń i mebli, elevation, balkony, drzwi harmonijkowe.
SCHEMA_VERSION = 4
DEFAULT_HEIGHT_M = 2.6


def to_px(outline: tuple[int, int, int, int], meters_per_px: float):
    """Odwrotność zapisu w `build`: punkt PlanModel (x, z) w metrach → piksel rzutu (float)."""
    cx = (outline[0] + outline[2]) / 2
    cy = (outline[1] + outline[3]) / 2
    return lambda x, z: (cx + x / meters_per_px, cy + z / meters_per_px)


def build(
    source_file: str,
    walls: list[WallPx],
    rooms: list[RoomPx],
    furniture: list[FurniturePx],
    outline: tuple[int, int, int, int],
    scale: Scale,
    height: float = DEFAULT_HEIGHT_M,
    openings: list[openings_.OpeningPx] | None = None,
) -> dict[str, Any]:
    s = scale.meters_per_px
    cx = (outline[0] + outline[2]) / 2
    cy = (outline[1] + outline[3]) / 2

    def pt(x: float, y: float) -> list[float]:
        # Środek budynku w (0, 0) – start sesji i kalibracja odbywają się blisko środka domu.
        return [round((x - cx) * s, 3), round((y - cy) * s, 3)]

    return {
        "schemaVersion": SCHEMA_VERSION,
        "units": "m",
        "source": {
            "file": source_file,
            "metersPerPixel": round(s, 6),
            "scaleMethod": scale.method,
            "outlineSize": [round((outline[2] - outline[0]) * s, 3), round((outline[3] - outline[1]) * s, 3)],
        },
        "storey": {"height": height},
        "walls": [
            {
                "id": f"w{i + 1}",
                "a": pt(*w.axis()[0]),
                "b": pt(*w.axis()[1]),
                "thickness": round(w.thickness * s, 3),
                "height": height,
            }
            for i, w in enumerate(walls)
        ],
        # Otwór na osi ściany od a do b. sill/height: dół i góra otworu (m). Drzwi: zawias na końcu
        # "a" lub "b", swing = +1, gdy skrzydło otwiera się w stronę wektora (-dz, dx) dla kierunku a→b.
        "openings": [
            {
                "id": f"o{i + 1}",
                "type": o.type,
                "a": pt(*o.a),
                "b": pt(*o.b),
                "thickness": round(o.thickness * s, 3),
                "sill": openings_.heights(o.type)[0],
                "height": openings_.heights(o.type)[1],
                **({"door": {"hinge": o.hinge, "swing": o.swing, "openAngle": 90}} if o.type == "door" else {}),
            }
            for i, o in enumerate(openings or [])
        ],
        "rooms": [
            {
                "id": f"r{i + 1}",
                "name": None,
                "polygon": [pt(float(x), float(y)) for x, y in r.contour],
                "area": round(r.area_px * s * s, 2),
                "areaOnPlan": None,
                "materials": None,  # {floor, walls} z katalogu; None = domyślne viewera
            }
            for i, r in enumerate(rooms)
        ],
        # Meble: size = [szerokość (lokalne X), głębokość (lokalne Z, przód–tył), wysokość],
        # position = środek podstawy, rotation = obrót wokół osi Y w stopniach. Przy rotation = 0
        # przód patrzy w +Z (w dół rzutu), 90 = w −X, 180 = w −Z, 270 = w +X.
        "furniture": [
            {
                "id": f"f{i + 1}",
                "type": f.type,
                "size": [round(f.w * s, 3), round(f.d * s, 3), f.height],
                "position": pt(f.cx, f.cy),
                "rotation": round(f.rotation % 360, 1),
                **({"params": f.params} if f.params else {}),
            }
            for i, f in enumerate(furniture)
        ],
        # Materiały: id → {texture?, color?, tileM?, roughness?, metalness?, ...}; viewer ma też wbudowane.
        "materials": {},
        # Balkony: {polygon: [[x, z], ...], railingHeight}; posadzka tuż pod poziomem podłogi mieszkania.
        "balconies": [],
    }
