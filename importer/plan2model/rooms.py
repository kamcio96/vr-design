"""Pomieszczenia: zamknięcie przerw drzwiowych i okiennych, potem wolne obszary między ścianami."""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

from .walls import WallPx

THICK_WALL_M = 0.25  # od tej grubości ściana jest zewnętrzna/nośna
MAX_GAP_THICK_M = 3.2  # najszersze okno lub drzwi tarasowe w grubej ścianie
MAX_GAP_THIN_M = 1.2  # najszersze drzwi w ścianie działowej
MAX_SLIDING_GAP_M = 2.0  # podwójne drzwi przesuwne (skrzydła narysowane wzdłuż ściany)
MIN_SLIDING_COVERAGE = 0.6
SLIDING_PANEL_REACH_PX = 4
SLIDING_FREE_PX = 8  # pas za skrzydłami, który ma być pustą podłogą
MAX_SLIDING_SIDE_LINES = 0.05
MIN_ROOM_M2 = 1.0
MIN_CLOSET_M2 = 0.3  # mniejsze zamknięte obszary to wnęki (np. szafa wnękowa), nie pokoje
# Przerwę zamykamy, gdy ściana po drugiej stronie zakrywa prawie całą szerokość przedłużenia.
# Zwykłe muśnięcie rogu innej ściany (np. bloku komina) nie wystarcza.
MIN_HIT_COVERAGE = 0.8
# Zamknięty pasek węższy niż to (np. kreskowanie kółkami przy ścianie zewnętrznej) jest częścią
# ściany, a nie wnęką. W 3D zostałaby po nim szczelina między dwiema ścianami.
MAX_STRIP_WIDTH_M = 0.35
MIN_STRIP_FILL = 0.8  # pasek musi wypełniać prawie cały swój prostokąt
# Okna i bramy z równoległych linii (`glazing`): od wąskiego okna do bramy garażu na dwa auta.
MIN_GLAZING_M = 0.5
MAX_GLAZING_M = 5.8
MAX_GLAZING_DEPTH_M = 0.6  # najdalej od siebie leżące linie jednego okna (grubość ściany)
MAX_GLAZING_ANGLE_DEG = 2
MIN_GLAZING_LINES_PX = 3  # bliżej leżące odcinki to ta sama kreska
LINE_MAX_GRAY = 225  # kreski rysunku (także jasne, przerywane linie okien) są ciemniejsze niż podłoga


@dataclass
class RoomPx:
    contour: np.ndarray  # (N, 2) piksele, uproszczony obrys
    area_px: int
    bbox: tuple[int, int, int, int]  # x0, y0, x1, y1


@dataclass
class Drawing:
    """To z rysunku, czego nie ma w prostokątach ścian: ściany skośne i słupki (`raw`, maska ciemnych
    pikseli z walls.wall_mask) oraz cienkie ciemne kreski (`lines`, np. ramy okien)."""

    raw: np.ndarray
    lines: np.ndarray


def drawing(img_bgr: np.ndarray, raw: np.ndarray) -> Drawing:
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    return Drawing(raw, (gray < LINE_MAX_GRAY) & ~raw)


def glazing(d: Drawing, meters_per_px: float) -> list[np.ndarray]:
    """Okna i bramy, których nie zamknie zwykła reguła z closed_wall_mask: co najmniej dwie równoległe
    kreski łączące dwa kawałki grubej ściany. Szeroka brama garażu (prosta ściana, ponad
    MAX_GAP_THICK_M) albo okna między słupkami ściany skośnej (`_pier_windows`).

    Zwraca prostokąty (4 narożniki w pikselach) do zamalowania w masce ścian. Fronty szaf i blatów
    to jedna kreska albo opierają się o cienką ściankę, więc nie spełniają warunku.
    """
    s = meters_per_px
    raw = d.raw.astype(np.uint8)
    n, labels = cv2.connectedComponents(raw, connectivity=8)
    dist = cv2.distanceTransform(raw, cv2.DIST_L2, 3)
    thickness = np.zeros(n)
    np.maximum.at(thickness, labels.ravel(), 2 * dist.ravel())
    thick = (thickness >= THICK_WALL_M / s)[labels] & d.raw
    near_thick = cv2.dilate(thick.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)

    segs = cv2.HoughLinesP(
        d.lines.astype(np.uint8) * 255, 1, np.pi / 360, threshold=round(0.4 / s),
        minLineLength=round(MIN_GLAZING_M / s), maxLineGap=round(0.25 / s),
    )
    if segs is None:
        return []
    h, w = raw.shape

    def at(pt: np.ndarray, mask: np.ndarray) -> bool:
        return bool(mask[int(np.clip(pt[1], 0, h - 1)), int(np.clip(pt[0], 0, w - 1))])

    found = []
    for x0, y0, x1, y1 in segs.reshape(-1, 4):
        p, q = np.array([x0, y0], float), np.array([x1, y1], float)
        length = float(np.linalg.norm(q - p))
        u = (q - p) / length
        # Zwykłe okna w prostej ścianie zamyka reguła z closed_wall_mask; tu tylko szersze bramy.
        axis = abs(u[0]) >= math.cos(math.radians(MAX_GLAZING_ANGLE_DEG)) or abs(u[1]) >= math.cos(math.radians(MAX_GLAZING_ANGLE_DEG))
        if not axis or not MAX_GAP_THICK_M < length * s <= MAX_GLAZING_M:
            continue
        # Koniec kreski bywa tuż przed licem ściany albo już na nim: kilka pikseli od końca.
        ends = all(any(at(end + k * step, near_thick) for k in range(4)) for end, step in ((p, u), (q, -u)))
        if ends and not at((p + q) / 2, d.raw):
            found.append((p, q, u))

    rects = []
    for p, q, u in found:
        normal = np.array([-u[1], u[0]])
        span = float(np.dot(q - p, u))
        offsets = [0.0]
        for pj, qj, uj in found:
            if abs(float(np.dot(u, uj))) < math.cos(math.radians(MAX_GLAZING_ANGLE_DEG)):
                continue
            a, b = sorted((float(np.dot(pj - p, u)), float(np.dot(qj - p, u))))
            if min(b, span) - max(a, 0.0) < 0.7 * span:
                continue
            offsets.append(float(np.dot((pj + qj) / 2 - p, normal)))
        lo, hi = min(offsets), max(offsets)
        # Jedna kreska rysunku daje w transformacji Hougha kilka odcinków tuż obok siebie.
        if hi - lo < MIN_GLAZING_LINES_PX or (hi - lo) * s > MAX_GLAZING_DEPTH_M:
            continue
        p0, q0 = p - 3 * u, q + 3 * u  # domknięcie 1–2 pikseli do lica ściany
        corners = [p0 + lo * normal, q0 + lo * normal, q0 + hi * normal, p0 + hi * normal]
        rects.append(np.array(corners).round().astype(np.int32))
    return rects + _pier_windows(d, labels, thickness, s)


def _pier_windows(d: Drawing, labels: np.ndarray, thickness: np.ndarray, s: float) -> list[np.ndarray]:
    """Okna między słupkami ściany skośnej: dwa grube kawałki ściany, a w szczelinie między nimi
    co najmniej dwie równoległe kreski. Ukośne, przerywane kreski są zbyt postrzępione dla
    transformacji Hougha, więc sprawdzamy przekroje w poprzek szczeliny.

    Tylko szczeliny skośne: proste przerwy zamyka zwykła reguła w closed_wall_mask.
    """
    h, w = labels.shape
    pieces = []
    for i in np.flatnonzero(thickness >= THICK_WALL_M / s):
        if i == 0:
            continue
        contours, _ = cv2.findContours((labels == i).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        pieces.append((i, np.concatenate([c[:, 0, :] for c in contours]).astype(float)))
    half = round(MAX_GLAZING_DEPTH_M / 2 / s)
    out = []
    for a in range(len(pieces)):
        for b in range(a + 1, len(pieces)):
            ia, pa = pieces[a]
            ib, pb = pieces[b]
            dd = np.linalg.norm(pa[:, None, :] - pb[None, :, :], axis=2)
            k = np.unravel_index(int(np.argmin(dd)), dd.shape)
            gap = float(dd[k])
            if not 0.3 <= gap * s <= MAX_GAP_THICK_M:
                continue
            p, q = pa[k[0]], pb[k[1]]
            u = (q - p) / gap
            angle = math.degrees(math.atan2(u[1], u[0])) % 90
            if min(angle, 90 - angle) < 10:
                continue
            normal = np.array([-u[1], u[0]])
            hits = 0
            samples = range(2, int(gap) - 1)
            for t in samples:
                c = p + t * u
                prof = [
                    d.lines[int(np.clip(y, 0, h - 1)), int(np.clip(x, 0, w - 1))]
                    for x, y in (c + o * normal for o in range(-half, half + 1))
                ]
                crossings = sum(1 for j in range(1, len(prof)) if prof[j] and not prof[j - 1])
                hits += crossings >= 2
            if samples and hits >= 0.7 * len(samples):
                width = round(0.5 * min(thickness[ia], thickness[ib]))
                corners = [p + width * normal, q + width * normal, q - width * normal, p - width * normal]
                out.append(np.array(corners).round().astype(np.int32))
    return out


def closed_wall_mask(
    shape: tuple[int, int], walls: list[WallPx], meters_per_px: float, drawing: Drawing | None = None
) -> tuple[np.ndarray, list[tuple[int, int, int, int]]]:
    """Maska ścian z dorysowanymi „zaślepkami” w miejscu drzwi i okien.

    Z każdego końca ściany idziemy dalej wzdłuż jej osi. Jeśli w zasięgu typowego otworu
    trafimy na inną ścianę zakrywającą całe przedłużenie, przerwa zostaje zamknięta.
    Z `drawing` dochodzą ściany skośne, słupki oraz okna i bramy wykryte przez `glazing`.
    Zwraca maskę i listę zaślepek (do podglądu).
    """
    mask = np.zeros(shape, bool)
    for w in walls:
        mask[w.y0 : w.y1, w.x0 : w.x1] = True

    closed = mask.copy()
    if drawing is not None:
        closed |= drawing.raw
        extra = np.zeros(shape, np.uint8)
        for poly in glazing(drawing, meters_per_px):
            cv2.fillPoly(extra, [poly.reshape(-1, 1, 2)], 1)
            cv2.polylines(extra, [poly.reshape(-1, 1, 2)], True, 1, 2)
        closed |= extra.astype(bool)
    patches = []
    for w in walls:
        thick = w.thickness * meters_per_px >= THICK_WALL_M
        max_gap = round((MAX_GAP_THICK_M if thick else MAX_GAP_THIN_M) / meters_per_px)
        found = _wall_gaps(mask, w, max_gap)
        if drawing is not None and not thick:
            # Szersza przerwa w ściance działowej: tylko z narysowanymi skrzydłami drzwi przesuwnych.
            wide = _wall_gaps(mask, w, round(MAX_SLIDING_GAP_M / meters_per_px))
            found += [g for g in wide if g not in found and _sliding_panels(drawing.lines, g, w.horizontal)]
        patches += found
    # Przedłużenie biegnące tuż przy równoległej ścianie to nie otwór, tylko koniec wąskiego pasa
    # (np. kreskowania przy ścianie zewnętrznej); zamknięcie odcięłoby kawałek pokoju.
    near = round(MAX_STRIP_WIDTH_M / meters_per_px)
    patches = [p for p in patches if not _along_parallel_wall(mask, p, near)]
    for x0, y0, x1, y1 in patches:
        closed[y0:y1, x0:x1] = True
    return closed, patches


def _wall_gaps(mask: np.ndarray, w: WallPx, max_gap: int) -> list[tuple[int, int, int, int]]:
    """Zaślepki przedłużające ścianę `w` do najbliższej ściany na jej osi (najwyżej `max_gap` pikseli)."""
    out = []
    if w.horizontal:
        band = mask[w.y0 : w.y1]
        ahead = band[:, w.x1 : w.x1 + max_gap].mean(axis=0) >= MIN_HIT_COVERAGE
        behind = band[:, max(0, w.x0 - max_gap) : w.x0].mean(axis=0)[::-1] >= MIN_HIT_COVERAGE
        if ahead.any() and (gap := int(np.argmax(ahead))) > 0:
            out.append((w.x1, w.y0, w.x1 + gap, w.y1))
        if behind.any() and (gap := int(np.argmax(behind))) > 0:
            out.append((w.x0 - gap, w.y0, w.x0, w.y1))
    else:
        band = mask[:, w.x0 : w.x1]
        ahead = band[w.y1 : w.y1 + max_gap].mean(axis=1) >= MIN_HIT_COVERAGE
        behind = band[max(0, w.y0 - max_gap) : w.y0].mean(axis=1)[::-1] >= MIN_HIT_COVERAGE
        if ahead.any() and (gap := int(np.argmax(ahead))) > 0:
            out.append((w.x0, w.y1, w.x1, w.y1 + gap))
        if behind.any() and (gap := int(np.argmax(behind))) > 0:
            out.append((w.x0, w.y0 - gap, w.x1, w.y0))
    return out


def _sliding_panels(lines: np.ndarray, gap: tuple[int, int, int, int], horizontal: bool) -> bool:
    """Skrzydła drzwi przesuwnych: kreski równoległe do ściany tuż przy przerwie, na większej jej części,
    a dalej po obu stronach pusta podłoga (oparcie kanapy czy kafle mają obok kolejne kreski)."""
    x0, y0, x1, y1 = gap
    m, far = SLIDING_PANEL_REACH_PX, SLIDING_PANEL_REACH_PX + SLIDING_FREE_PX
    if not horizontal:  # dalej zawsze przerwa pozioma: przerwa wzdłuż X, kreski nad i pod nią
        lines, (x0, y0, x1, y1) = lines.T, (y0, x0, y1, x1)
    cover = lines[max(0, y0 - m) : y1 + m, x0:x1].any(axis=0)
    sides = (lines[max(0, y0 - far) : max(0, y0 - m), x0:x1], lines[y1 + m : y1 + far, x0:x1])
    free = all(side.size and float(side.mean()) <= MAX_SLIDING_SIDE_LINES for side in sides)
    return bool(cover.size) and float(cover.mean()) >= MIN_SLIDING_COVERAGE and free


def _along_parallel_wall(mask: np.ndarray, patch: tuple[int, int, int, int], near: int) -> bool:
    x0, y0, x1, y1 = patch
    if max(x1 - x0, y1 - y0) <= near:
        return False  # krótka zaślepka (np. 1 px szczeliny w narożniku) zawsze zostaje
    if x1 - x0 < y1 - y0:  # pionowa zaślepka: szukamy ściany po lewej lub prawej
        side = np.concatenate([mask[y0:y1, max(0, x0 - near) : x0], mask[y0:y1, x1 : x1 + near]], axis=1)
        return bool(side.size) and bool((side.mean(axis=0) >= MIN_HIT_COVERAGE).any())
    side = np.concatenate([mask[max(0, y0 - near) : y0, x0:x1], mask[y1 : y1 + near, x0:x1]], axis=0)
    return bool(side.size) and bool((side.mean(axis=1) >= MIN_HIT_COVERAGE).any())


def find_rooms(
    closed: np.ndarray, outline: tuple[int, int, int, int], meters_per_px: float
) -> tuple[list[RoomPx], list[RoomPx]]:
    """Wolne obszary wewnątrz obrysu, które nie dotykają jego brzegu: (pokoje, wnęki)."""
    x0, y0, x1, y1 = outline
    free = np.zeros(closed.shape, np.uint8)
    free[y0:y1, x0:x1] = ~closed[y0:y1, x0:x1]
    n, labels, stats, _ = cv2.connectedComponentsWithStats(free, connectivity=4)
    min_px = MIN_CLOSET_M2 / meters_per_px**2
    room_px = MIN_ROOM_M2 / meters_per_px**2
    rooms, closets = [], []
    for i in range(1, n):
        rx, ry, rw, rh, area = stats[i]
        if rx <= x0 or ry <= y0 or rx + rw >= x1 or ry + rh >= y1:
            continue  # sięga brzegu obrysu, więc to zewnętrze (wcięcie budynku albo niezamknięty otwór)
        if area < min_px:
            continue
        contours, _ = cv2.findContours((labels == i).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contour = cv2.approxPolyDP(max(contours, key=cv2.contourArea), 1.5, True)[:, 0, :]
        room = RoomPx(contour, int(area), (int(rx), int(ry), int(rx + rw), int(ry + rh)))
        (rooms if area >= room_px else closets).append(room)
    return rooms, closets


def outside(closed: np.ndarray, outline: tuple[int, int, int, int]) -> np.ndarray:
    """Przestrzeń poza budynkiem: wolne obszary sięgające brzegu obrysu (jak w find_rooms) i wszystko za obrysem."""
    x0, y0, x1, y1 = outline
    free = np.zeros(closed.shape, np.uint8)
    free[y0:y1, x0:x1] = ~closed[y0:y1, x0:x1]
    n, labels, stats, _ = cv2.connectedComponentsWithStats(free, connectivity=4)
    edge = np.zeros(n, bool)
    for i in range(1, n):
        rx, ry, rw, rh, _ = stats[i]
        edge[i] = rx <= x0 or ry <= y0 or rx + rw >= x1 or ry + rh >= y1
    out = edge[labels]
    beyond = np.ones(closed.shape, bool)
    beyond[y0:y1, x0:x1] = False
    return out | beyond


def narrow_strips(
    closed: np.ndarray, outline: tuple[int, int, int, int], meters_per_px: float
) -> list[WallPx]:
    """Wąskie zamknięte paski między ścianami jako dodatkowe ściany. Dopisuje je też do maski `closed`."""
    x0, y0, x1, y1 = outline
    free = np.zeros(closed.shape, np.uint8)
    free[y0:y1, x0:x1] = ~closed[y0:y1, x0:x1]
    n, _, stats, _ = cv2.connectedComponentsWithStats(free, connectivity=4)
    max_px = MAX_STRIP_WIDTH_M / meters_per_px
    strips = []
    for i in range(1, n):
        rx, ry, rw, rh, area = stats[i]
        if rx <= x0 or ry <= y0 or rx + rw >= x1 or ry + rh >= y1:
            continue
        if min(rw, rh) <= max_px and area >= MIN_STRIP_FILL * rw * rh:
            strips.append(WallPx(int(rx), int(ry), int(rx + rw), int(ry + rh), horizontal=bool(rw > rh)))
            closed[ry : ry + rh, rx : rx + rw] = True
    return strips
