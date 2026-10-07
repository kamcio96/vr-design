"""Wymiary: obrys, strefy (pokoje po podziale), gabaryty nowych mebli i położenie ścianek.

`compute` liczy je w metrach (do PlanModel jako `annotations` – viewer rysuje je na podłodze), `draw` rysuje
je na powiększonym obrazku kontrolnym. Wymiary w cm, powierzchnie w m². Napisy bez polskich
znaków, bo czcionki OpenCV ich nie mają. Strefy podaje plik projektu (`zones`), bo automat nie wie,
jak ścianki z pliku projektu dzielą pomieszczenie.
"""

from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np

from . import planmodel

SCALE = 3  # powiększenie rzutu, żeby napisy były czytelne
MARGIN = 80  # biały margines na linie wymiarowe obrysu
FONT = cv2.FONT_HERSHEY_SIMPLEX
PARTITIONS = ("lamele", "scianka_szklana")
OUTLINE_OFFSET_M = 0.35  # linie wymiarowe obrysu na zewnątrz budynku
PARTITION_OFFSET_M = 0.15  # długość ścianki obok niej
ZONE_LINE_M = 0.2  # odstęp linii w nazwie pokoju (nazwa, powierzchnia)
FRONT_GAP_M = 0.08  # gabaryt mebla obok niego, najchętniej przed frontem (w 3D pod meblem nie byłoby go widać)

# Kolory (BGR) i wielkość napisów na PNG według rodzaju wymiaru; viewer ma te same rodzaje.
COLORS = {"outline": (30, 30, 30), "partition": (30, 30, 30), "zone": (30, 30, 200), "distance": (30, 30, 200),
          "furniture": (140, 60, 0)}
TEXT_SCALE = {"outline": 0.7, "zone": 0.6}


def compute(
    plan: dict[str, Any], added: list[dict[str, Any]], zones: list[dict[str, Any]] | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Wymiary w metrach (układ PlanModel): linie wymiarowe i napisy, wspólne dla PNG i podłogi w 3D.

    Linia: {a, b, offset (m, dodatni: w +Z dla a→b w +X, w −X dla a→b w +Z), text, kind, at (0–1)}.
    Napis: {at, text, kind}.
    """
    lines: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []

    def line(a, b, text, kind, offset=0.0, at=0.5, slide=None):
        lines.append({"a": _r(a), "b": _r(b), "offset": offset, "text": text, "kind": kind, "at": at})
        if slide:
            lines[-1]["_slide"] = slide  # zakres, w którym linię wolno przesunąć (tylko do rozstawienia)

    outer, inner = _faces(plan["walls"])
    x0, z0, x1, z1 = outer
    line((x0, z1), (x1, z1), cm(x1 - x0), "outline", OUTLINE_OFFSET_M)
    line((x0, z0), (x0, z1), cm(z1 - z0), "outline", OUTLINE_OFFSET_M)

    obstacles = _obstacles(plan)
    taken: list[tuple[float, float, float, float]] = []  # prostokąty już postawionych napisów
    for f in added:
        if f["type"] in PARTITIONS:
            _partition(f, inner, line)
    for i, d in enumerate(lines):
        slide = d.pop("_slide", None)
        if slide:
            lines[i] = _free_distance(d, slide, obstacles)
    taken += [_line_text_box(d) for d in lines]
    # Potem gabaryty mebli (mają kilka możliwych miejsc), na końcu nazwy pokoi (szukane po całej strefie).
    for f in added:
        if f["type"] not in PARTITIONS:
            text = _size_text(f)
            at = _free_spot(f, text, obstacles, inner, taken)
            taken.append(_text_box(at, text))
            labels.append({"at": _r(at), "text": text, "kind": "furniture"})
    for zone in zones or []:
        _zone(zone, line, labels, obstacles, taken)
    return {"lines": lines, "labels": labels}


def draw(
    debug_img: np.ndarray,
    dims: dict[str, list[dict[str, Any]]],
    outline: tuple[int, int, int, int],
    meters_per_px: float,
    zones: list[dict[str, Any]] | None = None,
) -> np.ndarray:
    """PNG: obrazek kontrolny powiększony 3× z wymiarami z `compute`."""
    big = cv2.resize(debug_img, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_NEAREST)
    out = cv2.copyMakeBorder(big, MARGIN, MARGIN, MARGIN, MARGIN, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    to_img = planmodel.to_px(outline, meters_per_px)

    def P(p) -> tuple[int, int]:
        u, v = to_img(*p)
        return round(u * SCALE + MARGIN), round(v * SCALE + MARGIN)

    for zone in zones or []:
        pts = np.array([P(p) for p in zone["polygon"]], np.int32).reshape(-1, 1, 2)
        cv2.polylines(out, [pts], True, COLORS["zone"], 1, cv2.LINE_AA)
    px_per_m = SCALE / meters_per_px
    for d in dims["lines"]:
        k = d["kind"]
        dim_line(out, P(d["a"]), P(d["b"]), round(d["offset"] * px_per_m), d["text"], COLORS[k],
                 TEXT_SCALE.get(k, 0.5), d["at"])
    for lb in dims["labels"]:
        bold = lb["kind"] == "zone"
        label(out, lb["text"], P(lb["at"]), COLORS[lb["kind"]], TEXT_SCALE.get(lb["kind"], 0.5), 2 if bold else 1)
    return out


def cm(m: float) -> str:
    return str(round(m * 100))


def area(polygon: list[list[float]]) -> float:
    """Powierzchnia wielokąta (wzór Gaussa) w m²."""
    xs, zs = np.array(polygon, float).T
    return float(abs(np.dot(xs, np.roll(zs, -1)) - np.dot(zs, np.roll(xs, -1))) / 2)


def _r(p) -> list[float]:
    return [round(float(p[0]), 3), round(float(p[1]), 3)]


def _size_text(f: dict[str, Any]) -> str:
    w, d = f["size"][0], f["size"][1]
    return cm(w) if f["type"] == "tv" else f"{cm(w)}x{cm(d)}"


def _text_box(at, text: str, big: bool = False) -> tuple[float, float, float, float]:
    """Przybliżony prostokąt napisu na podłodze (x0, z0, x1, z1): litery ok. 10 cm (nazwy pokoi 15 cm)."""
    k = 1.5 if big else 1.0
    hw, hh = (0.025 * len(text) + 0.02) * k, 0.06 * k  # jak czcionka w viewerze (annotations.ts)
    return at[0] - hw, at[1] - hh, at[0] + hw, at[1] + hh


def _obstacles(plan: dict[str, Any]) -> list:
    """Testy „punkt w meblu / w ścianie” – tam napis na podłodze byłby niewidoczny."""
    rects = [_rect(o["position"], o["size"][:2], o["rotation"]) for o in plan["furniture"]]
    for wall in plan["walls"]:
        (ax, az), (bx, bz) = wall["a"], wall["b"]
        rects.append(_rect(((ax + bx) / 2, (az + bz) / 2), (math.hypot(bx - ax, bz - az), wall["thickness"]),
                           math.degrees(math.atan2(bz - az, bx - ax))))
    return rects


def _fits(box, obstacles, taken, inside) -> bool:
    x0, z0, x1, z1 = box
    if any(x0 < t[2] and t[0] < x1 and z0 < t[3] and t[1] < z1 for t in taken):
        return False
    # siatka punktów co ok. 4 cm – cienkie ścianki (szkło, lamele) też muszą zostać wykryte
    pts = [(x, z) for x in np.linspace(x0, x1, max(2, int((x1 - x0) / 0.04) + 1))
           for z in np.linspace(z0, z1, max(2, int((z1 - z0) / 0.04) + 1))]
    return all(inside(p) for p in pts) and not any(r(p) for r in obstacles for p in pts)


def _free_distance(d: dict[str, Any], slide: tuple[float, float], obstacles) -> dict[str, Any]:
    """Linia odległości ścianki od ściany przesunięta wzdłuż ścianki (odległość wszędzie ta sama) i liczba
    na niej tak, żeby liczby nie zasłaniał mebel; inaczej bez zmian."""
    (ax, az), (bx, bz) = d["a"], d["b"]
    vertical_line = abs(bz - az) > abs(bx - ax)  # linia pionowa = ścianka pozioma, przesuwamy w X
    base = ax if vertical_line else az
    lo, hi = slide[0] + 0.1, slide[1] - 0.1
    shifts = sorted(np.arange(lo, hi + 1e-9, 0.05), key=lambda c: abs(c - base))
    for c in shifts:
        moved = {**d, "a": _r((c, az) if vertical_line else (ax, c)), "b": _r((c, bz) if vertical_line else (bx, c))}
        for t in (d["at"], 0.5, 0.35, 0.65, 0.25, 0.75, 0.15, 0.85):
            cand = {**moved, "at": t}
            if _fits(_line_text_box(cand), obstacles, [], lambda p: True):
                return cand
    return d


def _line_text_box(d: dict[str, Any]) -> tuple[float, float, float, float]:
    """Prostokąt liczby na linii wymiarowej (przy liniach pionowych napis obrócony)."""
    (ax, az), (bx, bz) = d["a"], d["b"]
    length = math.hypot(bx - ax, bz - az) or 1
    ox, oz = -(bz - az) / length * d["offset"], (bx - ax) / length * d["offset"]
    at = (ax + ox + (bx - ax) * d["at"], az + oz + (bz - az) * d["at"])
    x0, z0, x1, z1 = _text_box(at, d["text"])
    if abs(bz - az) > abs(bx - ax):
        hw, hh = (x1 - x0) / 2, (z1 - z0) / 2
        return at[0] - hh, at[1] - hw, at[0] + hh, at[1] + hw
    return x0, z0, x1, z1


def _free_spot(f, text, obstacles, inner, taken) -> tuple[float, float]:
    """Miejsce na gabaryt mebla: przed frontem (też przesunięte w bok), z boku, za meblem – pierwsze,
    które nie wchodzi na meble, ściany i inne napisy; inaczej przed frontem."""
    a = math.radians(f["rotation"])
    fwd = (-math.sin(a), math.cos(a))
    side = (math.cos(a), math.sin(a))
    (x, z), (w, d) = f["position"], f["size"][:2]
    bx0, bz0, bx1, bz1 = _text_box((0.0, 0.0), text)
    # odstęp od mebla + pół napisu w danym kierunku (napis leży zawsze poziomo na rzucie)
    kf = d / 2 + FRONT_GAP_M + abs(fwd[0]) * bx1 + abs(fwd[1]) * bz1
    ks = w / 2 + FRONT_GAP_M + abs(side[0]) * bx1 + abs(side[1]) * bz1
    candidates = [(kf, 0.0), *((kf, t * w) for t in (0.3, -0.3, 0.5, -0.5)), (0.0, ks), (0.0, -ks), (-kf, 0.0)]
    spots = [(x + fwd[0] * kf_ + side[0] * s_, z + fwd[1] * kf_ + side[1] * s_) for kf_, s_ in candidates]

    def in_outline(p) -> bool:
        return inner[0] <= p[0] <= inner[2] and inner[1] <= p[1] <= inner[3]

    for at in spots:
        if _fits(_text_box(at, text), obstacles, taken, in_outline):
            return at
    return spots[0]


def _in_polygon(p, poly) -> bool:
    inside = False
    for (ax, az), (bx, bz) in zip(poly, poly[1:] + poly[:1]):
        if (az > p[1]) != (bz > p[1]) and p[0] < ax + (p[1] - az) * (bx - ax) / (bz - az):
            inside = not inside
    return inside


def _rect(center, size, rotation_deg):
    """Test „punkt w obróconym prostokącie” (rotation jak w PlanModel: lokalne X → (cos, sin))."""
    a = math.radians(rotation_deg)
    c, s = math.cos(a), math.sin(a)
    hw, hd = size[0] / 2 + 0.03, size[1] / 2 + 0.03

    def test(p) -> bool:
        dx, dz = p[0] - center[0], p[1] - center[1]
        return abs(dx * c + dz * s) <= hw and abs(-dx * s + dz * c) <= hd

    return test


def _faces(walls: list[dict[str, Any]]) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Lica zewnętrzne obrysu (x0, z0, x1, z1) i wewnętrzne lica ścian zewnętrznych."""
    corners = []
    for w in walls:
        a, b = np.array(w["a"], float), np.array(w["b"], float)
        d = (b - a) / (np.linalg.norm(b - a) or 1)
        n = np.array([-d[1], d[0]]) * w["thickness"] / 2
        corners += [a + n, a - n, b + n, b - n]
    c = np.array(corners)
    outer = (c[:, 0].min(), c[:, 1].min(), c[:, 0].max(), c[:, 1].max())
    # Wewnętrzne lico: grubość najgrubszej ściany leżącej licem na danej krawędzi obrysu.
    inner = list(outer)
    for w in walls:
        (ax, az), (bx, bz), t = w["a"], w["b"], w["thickness"]
        if abs(ax - bx) < 1e-3:  # pionowa
            if abs(ax - t / 2 - outer[0]) < 0.02:
                inner[0] = max(inner[0], ax + t / 2)
            if abs(ax + t / 2 - outer[2]) < 0.02:
                inner[2] = min(inner[2], ax - t / 2)
        elif abs(az - bz) < 1e-3:  # pozioma
            if abs(az - t / 2 - outer[1]) < 0.02:
                inner[1] = max(inner[1], az + t / 2)
            if abs(az + t / 2 - outer[3]) < 0.02:
                inner[3] = min(inner[3], az - t / 2)
    return outer, tuple(inner)


def _partition(f: dict[str, Any], inner: tuple[float, ...], line) -> None:
    """Długość ścianki i odległość jej osi od najbliższej równoległej ściany zewnętrznej."""
    (x, z), length, vertical = f["position"], f["size"][0], round(f["rotation"]) % 180 == 90
    if vertical:
        line((x, z - length / 2), (x, z + length / 2), cm(length), "partition", PARTITION_OFFSET_M)
        wall = inner[0] if x - inner[0] < inner[2] - x else inner[2]
        line((wall, z), (x, z), cm(abs(x - wall)), "distance", slide=(z - length / 2, z + length / 2))
    else:
        line((x - length / 2, z), (x + length / 2, z), cm(length), "partition", PARTITION_OFFSET_M)
        wall = inner[1] if z - inner[1] < inner[3] - z else inner[3]
        # Napis bliżej ściany zewnętrznej: przy ściance zwykle stoją meble z własnymi opisami.
        line((x, wall), (x, z), cm(abs(z - wall)), "distance", at=0.3, slide=(x - length / 2, x + length / 2))


def _zone(zone: dict[str, Any], line, labels: list[dict[str, Any]], obstacles, taken) -> None:
    """Strefa: nazwa i powierzchnia w środku, szerokość i głębokość w świetle.

    Szerokość mierzona tuż pod górną krawędzią strefy, głębokość tam, gdzie strefa jest najgłębsza
    (najbliżej lewej krawędzi) – przy strefach w kształcie L to wymiary między ścianami, a nie obrys.
    """
    poly = zone["polygon"]
    xs, zs = [p[0] for p in poly], [p[1] for p in poly]
    inset = zone.get("dimInset", 0.18)
    z = min(zs) + inset
    a, b = _span(poly, z, axis=0)
    line((a, z), (b, z), cm(b - a), "zone")
    columns = np.linspace(min(xs) + 0.01, max(xs) - 0.01, 200)
    depths = [np.subtract(*_span(poly, x, axis=1)[::-1]) for x in columns]
    deepest = columns[int(np.argmax(np.round(depths, 3)))]
    x = min(deepest + inset, max(xs) - 0.01)
    a, b = _span(poly, x, axis=1)
    line((x, a), (x, b), cm(b - a), "zone")
    # Dwie linie (nazwa, pod nią powierzchnia) – mieszczą się w wąskim przejściu między meblami.
    name, size = zone["name"], f"{area(poly):.2f} m2".replace(".", ",")
    at = zone.get("labelAt") or _zone_spot(poly, max(name, size, key=len), obstacles, taken)
    for text, dz in ((name, -ZONE_LINE_M / 2), (size, ZONE_LINE_M / 2)):
        p = (at[0], at[1] + dz)
        taken.append(_text_box(p, text, big=True))
        labels.append({"at": _r(p), "text": text, "kind": "zone"})


def _zone_spot(poly, text, obstacles, taken) -> tuple[float, float]:
    """Wolne miejsce na nazwę pokoju (nie na meblach) możliwie blisko środka strefy; siatka co 5 cm."""
    xs, zs = [p[0] for p in poly], [p[1] for p in poly]
    center = (float(np.mean(xs)), float(np.mean(zs)))
    grid = [(x, z) for x in np.arange(min(xs), max(xs), 0.05) for z in np.arange(min(zs), max(zs), 0.05)]
    grid.sort(key=lambda p: math.dist(p, center))
    for at in grid:
        x0, _, x1, _ = _text_box(at, text, big=True)
        box = (x0, at[1] - ZONE_LINE_M, x1, at[1] + ZONE_LINE_M)  # dwie linie
        if _fits(box, obstacles, taken, lambda p: _in_polygon(p, poly)):
            return float(at[0]), float(at[1])
    return center


def _span(poly: list[list[float]], c: float, axis: int) -> tuple[float, float]:
    """Najdłuższy odcinek wnętrza wielokąta na prostej: axis=0 – pozioma z = c, axis=1 – pionowa x = c."""
    k = 1 - axis  # współrzędna stała na prostej
    hits = []
    for p, q in zip(poly, poly[1:] + poly[:1]):
        if (p[k] - c) * (q[k] - c) < 0:
            t = (c - p[k]) / (q[k] - p[k])
            hits.append(p[axis] + t * (q[axis] - p[axis]))
    hits.sort()
    pairs = list(zip(hits[::2], hits[1::2])) or [(c, c)]
    return max(pairs, key=lambda ab: ab[1] - ab[0])


def dim_line(
    img: np.ndarray, a: tuple[int, int], b: tuple[int, int], offset: int, text: str, color, scale: float = 0.5,
    at: float = 0.5,
) -> None:
    """Linia wymiarowa z ukośnymi kreskami na końcach, odsunięta o `offset` px (dodatni: w dół dla a→b w prawo,
    w lewo dla a→b w dół); napis w punkcie `at` (0 = a, 1 = b)."""
    av, bv = np.array(a, float), np.array(b, float)
    d = (bv - av) / (np.linalg.norm(bv - av) or 1)
    n = np.array([-d[1], d[0]]) * offset
    pa, pb = av + n, bv + n
    if offset:
        for p, q in ((av, pa), (bv, pb)):  # linie pomocnicze od mierzonego punktu
            cv2.line(img, _i(p), _i(q + n / abs(offset) * 4), color, 1, cv2.LINE_AA)
    cv2.line(img, _i(pa), _i(pb), color, 1, cv2.LINE_AA)
    tick = (d + np.array([d[1], -d[0]])) * 5
    for p in (pa, pb):
        cv2.line(img, _i(p - tick), _i(p + tick), color, 2, cv2.LINE_AA)
    label(img, text, _i(pa + (pb - pa) * at), color, scale, vertical=abs(d[1]) > abs(d[0]))


def label(img: np.ndarray, text: str, center: tuple[int, int], color, scale: float = 0.5, thickness: int = 1,
          vertical: bool = False) -> None:
    """Napis na białym tle, wyśrodkowany w punkcie; pionowy obrócony o 90° (czytany od dołu)."""
    (tw, th), base = cv2.getTextSize(text, FONT, scale, thickness)
    patch = np.full((th + base + 4, tw + 6, 3), 255, np.uint8)
    cv2.putText(patch, text, (3, th + 2), FONT, scale, color, thickness, cv2.LINE_AA)
    if vertical:
        patch = cv2.rotate(patch, cv2.ROTATE_90_COUNTERCLOCKWISE)
    h, w = patch.shape[:2]
    x, y = center[0] - w // 2, center[1] - h // 2
    x0, y0 = max(x, 0), max(y, 0)
    x1, y1 = min(x + w, img.shape[1]), min(y + h, img.shape[0])
    if x1 > x0 and y1 > y0:
        img[y0:y1, x0:x1] = patch[y0 - y : y1 - y, x0 - x : x1 - x]


def _i(p) -> tuple[int, int]:
    return int(round(p[0])), int(round(p[1]))
