"""Drzwi i okna: przerwy w ścianach (zaślepki z rooms.closed_wall_mask) z łukiem drzwi albo bez.

Drzwi rysuje się jako ćwiartkę koła: środek w zawiasie na licu ściany, promień = szerokość skrzydła.
Dla każdej przerwy szukamy takiego łuku (położenie zawiasu, kierunek, strona). Przerwa w ścianie
zewnętrznej bez łuku to okno. Przerwa w ścianie wewnętrznej bez łuku to przejście bez drzwi (pomijamy).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

from .walls import WallPx

MIN_GAP_M = 0.5  # krótsze zaślepki to domknięte narożniki, nie otwory
MIN_DOOR_M = 0.6
MAX_DOOR_M = 1.2
MIN_ARC_COVERAGE = 0.6  # jaka część łuku musi leżeć na linii rysunku
DOOR_HEIGHT_M = 2.05
WINDOW_SILL_M = 0.85
WINDOW_TOP_M = 2.05
LEAF_WEIGHT = 0.5
ARC_MIN_ASPECT = 0.7  # najkrótsze skrzydło względem szerokości drzwi
OUTSIDE_REACH_PX = 4  # tyle pikseli za licem ściany sprawdzamy, czy to już zewnętrze
FULL_DOOR = 0.85  # łuk krótszy niż ta część przerwy: drzwi + stałe okno obok (np. drzwi balkonowe)


@dataclass
class OpeningPx:
    """Otwór na osi ściany: od a do b (piksele), zawias i strona otwierania dla drzwi."""

    type: str  # "door" | "window"
    a: tuple[float, float]
    b: tuple[float, float]
    thickness: int
    hinge: str | None = None  # "a" | "b"
    swing: int = 0  # +1: drzwi otwierają się w stronę wektora (-dz, dx) dla kierunku a→b


@dataclass
class _Gap:
    x0: int
    y0: int
    x1: int
    y1: int
    horizontal: bool  # przerwa w ścianie poziomej (biegnie wzdłuż X)


def detect(
    patches: list[tuple[int, int, int, int]],
    strips: list[WallPx],
    outline: tuple[int, int, int, int],
    lines: np.ndarray,
    meters_per_px: float,
    outside: np.ndarray | None = None,
) -> list[OpeningPx]:
    """`lines`: maska bool linii rysunku (łuki, skrzydła drzwi).

    `outside`: maska przestrzeni poza budynkiem (rooms.outside). Bez niej ścianą zewnętrzną jest
    tylko ta na prostokącie obrysu, co wystarcza dla budynku bez wcięć.
    """
    s = meters_per_px
    lines = cv2.dilate(lines.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    found: list[OpeningPx] = []
    for gap in _gaps(patches, strips, s):
        out_side = _outside_side(gap, outside) if outside is not None else None
        exterior = out_side is not None if outside is not None else _touches_outline(gap, outline)
        # W ścianie zewnętrznej drzwi otwierają się do środka; po drugiej stronie bywają linie
        # balkonu lub elewacji, które udają łuk.
        inner = -out_side if out_side is not None else _inner_side(gap, outline)
        sides = (inner,) if exterior else (1, -1)
        door = _find_door(gap, lines, s, sides)
        if door is None:
            if exterior:
                found.append(_opening("window", gap, gap_lo(gap), gap_hi(gap)))
            continue
        lo, hi, hinge_at_lo, swing = door
        found.append(_opening("door", gap, lo, hi, "a" if hinge_at_lo else "b", swing))
        # Reszta przerwy obok drzwi (stałe skrzydło okna balkonowego).
        for r0, r1 in ((gap_lo(gap), lo), (hi, gap_hi(gap))):
            if (r1 - r0) * s >= 0.2 and exterior:
                found.append(_opening("window", gap, r0, r1))
    return found


def gap_lo(g: _Gap) -> int:
    return g.x0 if g.horizontal else g.y0


def gap_hi(g: _Gap) -> int:
    return g.x1 if g.horizontal else g.y1


def _gaps(patches: list[tuple[int, int, int, int]], strips: list[WallPx], s: float) -> list[_Gap]:
    """Zaślepki bez duplikatów, bez bardzo krótkich i bez tych, które tylko przedłużają wąski pasek przy ścianie."""
    gaps: list[_Gap] = []
    for x0, y0, x1, y1 in patches:
        w, h = x1 - x0, y1 - y0
        horizontal = w > h
        if max(w, h) * s < MIN_GAP_M:
            continue
        if any(_touches((x0, y0, x1, y1), (t.x0, t.y0, t.x1, t.y1)) for t in strips):
            continue
        g = _Gap(x0, y0, x1, y1, horizontal)
        dup = next((o for o in gaps if _overlap(o, g) > 0.7), None)
        if dup:  # ta sama przerwa zamknięta z obu stron, czasem o 1 px przesunięta: bierzemy sumę
            dup.x0, dup.y0, dup.x1, dup.y1 = min(dup.x0, x0), min(dup.y0, y0), max(dup.x1, x1), max(dup.y1, y1)
            continue
        gaps.append(g)
    return gaps


def _touches(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def _overlap(a: _Gap, b: _Gap) -> float:
    ix = max(0, min(a.x1, b.x1) - max(a.x0, b.x0))
    iy = max(0, min(a.y1, b.y1) - max(a.y0, b.y0))
    smaller = min((a.x1 - a.x0) * (a.y1 - a.y0), (b.x1 - b.x0) * (b.y1 - b.y0))
    return ix * iy / smaller if smaller else 0.0


def _touches_outline(g: _Gap, outline: tuple[int, int, int, int]) -> bool:
    x0, y0, x1, y1 = outline
    return g.x0 <= x0 + 1 or g.y0 <= y0 + 1 or g.x1 >= x1 - 1 or g.y1 >= y1 - 1


def _outside_side(g: _Gap, outside: np.ndarray) -> int | None:
    """Strona przerwy (±1 w poprzek ściany), po której jest zewnętrze, albo None (ściana wewnętrzna)."""
    h, w = outside.shape
    reach = OUTSIDE_REACH_PX
    if g.horizontal:
        m = (g.x1 - g.x0) // 4
        before = outside[max(0, g.y0 - reach) : g.y0, g.x0 + m : g.x1 - m]
        after = outside[g.y1 : min(h, g.y1 + reach), g.x0 + m : g.x1 - m]
    else:
        m = (g.y1 - g.y0) // 4
        before = outside[g.y0 + m : g.y1 - m, max(0, g.x0 - reach) : g.x0]
        after = outside[g.y0 + m : g.y1 - m, g.x1 : min(w, g.x1 + reach)]
    b = before.mean() if before.size else 0.0
    a = after.mean() if after.size else 0.0
    if max(a, b) < 0.5:
        return None
    return 1 if a > b else -1


def _inner_side(g: _Gap, outline: tuple[int, int, int, int]) -> int:
    """Strona przerwy (±1 w poprzek ściany) zwrócona do środka budynku."""
    if g.horizontal:
        return 1 if (g.y0 + g.y1) / 2 < (outline[1] + outline[3]) / 2 else -1
    return 1 if (g.x0 + g.x1) / 2 < (outline[0] + outline[2]) / 2 else -1


def _find_door(g: _Gap, lines: np.ndarray, s: float, sides: tuple[int, ...]) -> tuple[int, int, bool, int] | None:
    """Najlepszy łuk drzwi w przerwie: (początek, koniec, zawias na początku?, strona ±1) albo None.

    Sprawdzamy każde położenie zawiasu, kierunek i stronę, a dla nich naraz wszystkie promienie.
    Skrzydło bywa narysowane krótsze niż szerokość drzwi, więc łuk to ćwiartka elipsy
    (promień wzdłuż ściany r, w poprzek `across` ≥ ARC_MIN_ASPECT · r).
    """
    lo, hi = gap_lo(g), gap_hi(g)
    # Współrzędna poprzeczna lic ściany: łuk zaczyna się na licu po stronie otwierania.
    c0, c1 = (g.y0, g.y1) if g.horizontal else (g.x0, g.x1)
    r_min, r_max = round(MIN_DOOR_M / s), round(MAX_DOOR_M / s)
    pairs = np.array([(r, a) for r in range(r_min, r_max + 1) for a in range(round(ARC_MIN_ASPECT * r), r + 2)])
    if not len(pairs):
        return None
    angles = np.radians(np.linspace(12, 78, 24))  # bez skrajnych kątów, które leżą na ścianie i skrzydle
    d_along = pairs[:, :1] * np.cos(angles)  # (K, 24)
    d_across = pairs[:, 1:] * np.sin(angles)
    leaf_t = np.linspace(0.15, 0.85, 12)
    leaf_across = pairs[:, 1:] * leaf_t  # (K, 12)
    h, w = lines.shape

    def sample(along: np.ndarray, across: np.ndarray) -> np.ndarray:
        xs, ys = (along, across) if g.horizontal else (across, along)
        xs = np.round(xs).astype(int)
        ys = np.round(ys).astype(int)
        inside = (xs >= 0) & (ys >= 0) & (xs < w) & (ys < h)
        vals = lines[np.clip(ys, 0, h - 1), np.clip(xs, 0, w - 1)] & inside
        return vals.mean(axis=1)

    best: tuple[float, int, int, int, int, int] | None = None  # (ocena, promień, zawias, kierunek, strona, -)
    for hinge in range(lo, hi + 1):
        for direction in (1, -1):  # skrzydło zamknięte leży od zawiasu w stronę +/- osi przerwy
            room = (hi - hinge) if direction > 0 else (hinge - lo)
            fits = pairs[:, 0] <= room + 2
            if not fits.any():
                continue
            for side in sides:
                face = c1 if side > 0 else c0
                arc = sample(hinge + direction * d_along, face + side * d_across)
                ok = fits & (arc >= MIN_ARC_COVERAGE)
                if not ok.any():
                    continue
                # Linia skrzydła z zawiasu w poprzek ściany ustala położenie zawiasu.
                leaf = sample(np.full_like(leaf_across, hinge), face + side * leaf_across)
                score = np.where(ok, arc + LEAF_WEIGHT * leaf, -1.0)
                k = int(np.lexsort((pairs[:, 0], score))[-1])  # najwyższa ocena, przy remisie większy promień
                cand = (float(score[k]), int(pairs[k, 0]), hinge, direction, side, 0)
                if best is None or cand[:2] > best[:2]:
                    best = cand
    if best is None:
        return None
    _, r, hinge, direction, side, _ = best
    a, b = (hinge, min(hi, hinge + r)) if direction > 0 else (max(lo, hinge - r), hinge)
    if b - a >= FULL_DOOR * (hi - lo):
        a, b = lo, hi  # drzwi na całą przerwę; węższe zostawiają resztę na okno (patrz detect)
    # swing: +1 = strona wektora (-dz, dx); dla przerwy poziomej (a→b wzdłuż +X) to +Z, dla pionowej (+Z) to −X.
    swing = side if g.horizontal else -side
    return a, b, direction > 0, swing


def _opening(
    kind: str, g: _Gap, lo: int, hi: int, hinge: str | None = None, swing: int = 0
) -> OpeningPx:
    if g.horizontal:
        yc = (g.y0 + g.y1) / 2
        a, b, t = (float(lo), yc), (float(hi), yc), g.y1 - g.y0
    else:
        xc = (g.x0 + g.x1) / 2
        a, b, t = (xc, float(lo)), (xc, float(hi)), g.x1 - g.x0
    return OpeningPx(kind, a, b, t, hinge, swing)


def heights(kind: str) -> tuple[float, float]:
    """(parapet, góra otworu) w metrach."""
    return (0.0, DOOR_HEIGHT_M) if kind == "door" else (WINDOW_SILL_M, WINDOW_TOP_M)


def arc_points(o: OpeningPx) -> list[tuple[int, int]]:
    """Punkty łuku drzwi do obrazka kontrolnego."""
    (ax, ay), (bx, by) = o.a, o.b
    hx, hy = (ax, ay) if o.hinge == "a" else (bx, by)
    fx, fy = (bx, by) if o.hinge == "a" else (ax, ay)
    r = math.hypot(fx - hx, fy - hy)
    dx, dy = (bx - ax) / max(r, 1e-6), (by - ay) / max(r, 1e-6)
    nx, ny = -dy * o.swing, dx * o.swing
    ux, uy = (fx - hx) / max(r, 1e-6), (fy - hy) / max(r, 1e-6)
    pts = []
    for t in np.linspace(0, math.pi / 2, 16):
        pts.append((int(hx + r * (ux * math.cos(t) + nx * math.sin(t))), int(hy + r * (uy * math.cos(t) + ny * math.sin(t)))))
    return pts
