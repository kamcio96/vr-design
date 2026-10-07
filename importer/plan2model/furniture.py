"""Meble z rzutu: symbole wewnątrz pokoi → typ, obrys (także obrócony), przód i typowa wysokość.

Metoda:
1. Maska symboli. Na szarej podłodze meble są rysowane innym odcieniem (zwykle białe), więc symbolem
   jest wszystko, co odbiega od tonu podłogi. Na białej podłodze nie da się tego rozróżnić: „wylewamy”
   podłogę od ścian, a co zostaje otoczone liniami, to symbol.
2. Każdy kształt analizujemy w całości: obrócony prostokąt, okrągłość, przy których ścianach stoi
   i jakie „komórki” (obszary zamknięte liniami) ma w środku: poduchy kanapy, palniki płyty, komora zlewu.
3. Typ z reguł (wymiary w metrach + cechy rysunku), przód mebla od ściany albo w stronę stołu/TV.
   Kształty nieregularne (blat w kształcie L lub U) dzielimy na prostokąty i klasyfikujemy osobno.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any

import cv2
import numpy as np

from .rooms import RoomPx
from .walls import WallPx, extract_walls, wall_mask as drawn_walls

EDGE_STEP = 18  # różnica jasności tworząca krawędź; jasny znak wodny (≈13) jest poniżej
COLOR_SATURATION = 20  # czerwone wymiary, linie wymiarowe i żółte symbole usuwamy przed szukaniem krawędzi
LABEL_SATURATION = 60  # kolorowe ramki z numerami pomieszczeń
BRIDGE_PX = 15  # tyle pikseli linii mebla może przykryć usunięty czerwony napis
SEAL_PX = 5  # pogrubienie linii: domyka 1–3 pikselowe szczeliny w narożnikach
MIN_SIDE_M = 0.25
MIN_AREA_M2 = 0.12
MAX_AREA_M2 = 6.0
MIN_FILL = 0.8  # prostokątność; ćwiartka koła (łuk drzwi) ma ok. 0,78
FLOOR_TONE_TOLERANCE = 4  # obszar w kolorze podłogi to zamknięta kieszeń podłogi, nie mebel
SYMBOL_TONE_STEP = 12  # na szarej podłodze: piksel różniący się o tyle od podłogi należy do symbolu
MIN_SYMBOL_TONE_STEP = 4
TEXT_MAX_GRAY = 100
MIN_TEXT_FILL = 0.3
SHADED_STEP = 15
WHITE_FLOOR = 250
MIN_FLOOR_M2 = 1.0  # obszar przy ścianach o takiej powierzchni to podłoga (także druga, np. kafle w holu)
WATERMARK_TONES = (235, 251)  # jasnoszary znak wodny
NEAR_WALL_M = 0.15
SNAP_M = 0.12  # bok mebla tak blisko ściany dosuwamy do niej (linia ściany zasłania kawałek mebla)
CROSS_HITS = 0.65  # część przekątnej pokryta linią; krzyżyk bywa przerwany czerwonym napisem
BATHROOM_MAX_M2 = 8.0  # wanna, WC, prysznic tylko w małym pomieszczeniu
SNAP_ANGLE_DEG = 6  # prawie prosty kąt traktujemy jako prosty
RING_MAX_M = 0.22  # średnica pola grzewczego na rysunku płyty
PILLOW_M2 = (0.04, 0.35)  # poduszka pojedyncza albo podwójna
PILLOW_END = 0.3  # środek poduszki w tej części długości łóżka, licząc od wezgłowia
CHAIR_MAX_M = 0.65
MAX_SEAT_RATIO = 1.35
ROTATED_LINE_MAX_GRAY = 225
COUNTER_DEPTH_M = (0.45, 0.75)
SKEW_MIN_DEG = 10  # bok kształtu skośny o co najmniej tyle: analiza po obróceniu
OVAL_MIN_FILL = 0.55  # przy kilku cm na piksel mały owal wypełnia mniej niż π/4
TUB_INNER = 0.3  # misa wanny zajmuje co najmniej tyle prostokąta
CAR_MIN_M = (1.6, 3.6)  # samochód w garażu: szerokość i długość
CHAIR_GAP_M = 0.3  # krzesło najdalej tak od stołu lub biurka


@dataclass
class FurniturePx:
    """Mebel w pikselach: środek, szerokość (lokalne X) i głębokość (lokalne Z, przód–tył).

    `rotation` w stopniach: 0 = przód w stronę +Y obrazu (w dół rzutu), 90 = w lewo, 180 = w górę,
    270 = w prawo; ten sam kąt trafia do PlanModel (obrót wokół osi Y).
    """

    cx: float
    cy: float
    w: float
    d: float
    rotation: float
    type: str
    height: float
    params: dict[str, Any] = field(default_factory=dict)

    def corners(self) -> np.ndarray:
        a = math.radians(self.rotation)
        ux, uy = math.cos(a), math.sin(a)  # lokalne X na obrazie
        fx, fy = -math.sin(a), math.cos(a)  # przód
        pts = []
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            pts.append((self.cx + sx * self.w / 2 * ux + sy * self.d / 2 * fx, self.cy + sx * self.w / 2 * uy + sy * self.d / 2 * fy))
        return np.array(pts)

    def front(self) -> tuple[float, float]:
        a = math.radians(self.rotation)
        return -math.sin(a), math.cos(a)


# Typowe wysokości w m, gdy rzut ich nie podaje.
HEIGHTS = {
    "szafa": 2.2,
    "szafka": 0.9,
    "lozko": 0.5,
    "kanapa": 0.8,
    "fotel": 0.8,
    "wanna": 0.55,
    "stol": 0.75,
    "stol_okragly": 0.75,
    "stolik": 0.45,
    "tv": 0.5,  # szafka RTV; ekran viewer dokłada nad nią
    "blat": 0.9,
    "plyta": 0.9,
    "zlew": 0.9,
    "lodowka": 1.85,
    "prysznic": 2.0,
    "wc": 0.8,
    "umywalka": 0.85,
    "pralka": 0.85,
    "male": 0.45,  # krzesło, szafka nocna
    "krzeslo": 0.85,
    "biurko": 0.75,
    "samochod": 1.5,
    "mebel": 0.75,
}

# Meble stojące przy ścianie: tył od ściany. Siedziska wolnostojące patrzą na stół lub TV.
BACK_TO_WALL = {"kanapa", "szafa", "szafka", "blat", "plyta", "zlew", "tv", "wc", "umywalka", "pralka", "lodowka", "lozko", "wanna", "biurko"}
# Najmniejsza długość urządzenia w blacie (rysunek pokazuje tylko pola grzewcze lub samą komorę).
APPLIANCE_MIN_M = {"plyta": 0.58, "zlew": 0.5}
SEATS = {"fotel", "kanapa"}
TARGETS = {"stol", "stol_okragly", "stolik", "tv"}


@dataclass
class _Ctx:
    edges: np.ndarray  # linie pogrubione (do domykania kształtów)
    thin: np.ndarray  # linie cienkie uint8 0/255
    clean: np.ndarray  # jasność bez kolorowych napisów
    wall_mask: np.ndarray
    s: float
    room_m2: float
    room_center: tuple[float, float]
    pad: int  # o tyle px zdejmujemy obrys (pogrubiona linia konturu przy białej podłodze)
    colored: np.ndarray  # kolorowe napisy (np. czerwone „C.O.” w ramce kotła)
    all_walls: np.ndarray  # ściany razem ze skośnymi (do analizy kształtów ustawionych skosem)


def detect(
    img_bgr: np.ndarray,
    walls: list[WallPx],
    rooms: list[RoomPx],
    closets: list[RoomPx],
    meters_per_px: float,
) -> list[FurniturePx]:
    s = meters_per_px
    clean = _without_color(img_bgr)
    thin = _thin_edges(clean)
    edges = _edges(img_bgr)
    wall_mask = np.zeros(edges.shape, bool)
    for w in walls:
        wall_mask[w.y0 : w.y1, w.x0 : w.x1] = True
    labels = _label_frames(img_bgr, s)
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    colored = (hsv[..., 1] > LABEL_SATURATION) & (hsv[..., 2] > 120)
    all_walls = wall_mask | drawn_walls(img_bgr)

    found: list[FurniturePx] = []
    for room in rooms:
        room_mask = np.zeros(edges.shape, np.uint8)
        cv2.fillPoly(room_mask, [room.contour.reshape(-1, 1, 2)], 1)
        room_mask = room_mask.astype(bool) & ~wall_mask & ~labels
        found_symbols = _symbols(room_mask, edges, clean, wall_mask, s)
        if found_symbols is None:
            continue
        symbols, gray_floor = found_symbols
        x0, y0, x1, y1 = room.bbox
        pad = 0 if gray_floor else SEAL_PX // 2 + 1
        ctx = _Ctx(edges, thin, clean, wall_mask, s, room.area_px * s * s, ((x0 + x1) / 2, (y0 + y1) / 2), pad, colored, all_walls)
        items: list[FurniturePx] = []
        n, comp_labels, stats, _ = cv2.connectedComponentsWithStats(symbols.astype(np.uint8), connectivity=4)
        for i in range(1, n):
            if stats[i, cv2.CC_STAT_AREA] * s * s < MIN_AREA_M2 / 2:
                continue
            items += _analyze(comp_labels == i, ctx)
        _chairs(items, ctx)
        _orient_seats(items, ctx)
        found += items

    # Wnęki: zamknięte schowki za małe na pokój. Z krzyżykiem to szafa wnękowa na całą wnękę.
    for c in closets:
        if _has_cross(c.bbox, edges, thin):
            x0, y0, x1, y1 = c.bbox
            found.append(_axis_item((x0, y0, x1, y1), "szafa", wall_mask, s))
    return found


# ---------------------------------------------------------------- maska symboli


def _label_frames(img_bgr: np.ndarray, s: float) -> np.ndarray:
    """Wnętrza kolorowych ramek z numerami pomieszczeń (np. pomarańczowe „18.2”)."""
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    colored = ((hsv[..., 1] > LABEL_SATURATION) & (hsv[..., 2] > 120)).astype(np.uint8)
    out = np.zeros(colored.shape, bool)
    n, _, stats, _ = cv2.connectedComponentsWithStats(colored, connectivity=8)
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if min(w, h) * s >= 0.3 and area < 0.5 * w * h:  # pusta w środku: ramka, nie wypełniony symbol
            out[max(0, y - 2) : y + h + 2, max(0, x - 2) : x + w + 2] = True
    return out


def _symbols(
    room_mask: np.ndarray, edges: np.ndarray, clean: np.ndarray, wall_mask: np.ndarray, s: float
) -> tuple[np.ndarray, bool] | None:
    """Maska symboli mebli w pokoju i informacja, czy podłoga jest szara (wtedy kontur należy do mebla)."""
    floor, tones = _floor(room_mask, edges, clean, s)
    if floor is None:
        return None
    k = max(3, round(0.08 / s))  # usuwa same linie (łuki drzwi, kafle, kreski), zostają wypełnione kształty
    gray_floor = [t for t in tones if t < WHITE_FLOOR]
    if gray_floor:
        tone = min(gray_floor, key=lambda t: abs(t - float(np.median(clean[floor]))))
        near_wall = cv2.dilate(wall_mask.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
        # Na bardzo jasnej podłodze (np. 246) białe meble różnią się od niej o mniej niż SYMBOL_TONE_STEP.
        step = min(SYMBOL_TONE_STEP, max(MIN_SYMBOL_TONE_STEP, (255 - tone) / 2))
        cand = (np.abs(clean.astype(int) - int(tone)) >= step) & room_mask & ~near_wall
        # Poduchy kanapy i moduły szafy dzieli 1 px linia w kolorze podłogi – sklejamy je w jeden mebel.
        # Przy małej rozdzielczości (kilka cm na piksel) tylko 1 px, żeby nie skleić krzeseł ze stołem.
        c = max(2, min(3, round(0.055 / s)))
        cand = cv2.morphologyEx(cand.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((c, c), np.uint8))
    else:
        cand = (room_mask & ~floor).astype(np.uint8)
    out = cv2.morphologyEx(cand, cv2.MORPH_OPEN, np.ones((k, k), np.uint8)).astype(bool)
    # Kieszenie podłogi (np. między łukami drzwi) mają jej ton – to nie meble.
    n, lab, _, _ = cv2.connectedComponentsWithStats(out.astype(np.uint8), connectivity=4)
    for i in range(1, n):
        comp = lab == i
        t = float(np.median(clean[comp]))
        # Jasnoszary znak wodny odróżniamy tylko na białej podłodze; na szarej białe meble mają podobną medianę.
        watermark = not gray_floor and WATERMARK_TONES[0] <= t <= WATERMARK_TONES[1]
        # Numer pomieszczenia: grube czarne cyfry (meble mają cienki, szary kontur).
        text = float((clean[comp] < TEXT_MAX_GRAY).mean()) >= MIN_TEXT_FILL
        # Schody i kominek są wypełnione szarym, wyraźnie ciemniejszym od jasnej podłogi; meble są jaśniejsze.
        shaded = bool(gray_floor) and t <= tone - SHADED_STEP
        if any(abs(t - f) <= FLOOR_TONE_TOLERANCE for f in gray_floor) or watermark or text or shaded:
            out[comp] = False
    return out, bool(gray_floor)


def _floor(
    room_mask: np.ndarray, edges: np.ndarray, clean: np.ndarray, s: float
) -> tuple[np.ndarray | None, list[float]]:
    """Podłoga: wolne obszary stykające się ze ścianami, duże względem pokoju albo ≥ MIN_FLOOR_M2.

    Obszar w środku pokoju, otoczony liniami (np. łóżko), nigdy nie jest podłogą. Pokój może mieć
    kilka podłóg (szara w pokoju, kafle w holu), stąd lista tonów.
    """
    free = (room_mask & ~edges).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(free, connectivity=4)
    ring = room_mask & ~cv2.erode(room_mask.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
    touching = [i for i in range(1, n) if (ring & (labels == i)).any()]
    if not touching:
        return None, []
    biggest = max(stats[i, cv2.CC_STAT_AREA] for i in touching)
    min_px = min(0.25 * biggest, MIN_FLOOR_M2 / s / s)
    ids = [i for i in touching if stats[i, cv2.CC_STAT_AREA] >= min_px]
    tones = [float(np.median(clean[labels == i])) for i in ids]
    return np.isin(labels, ids), tones


# ---------------------------------------------------------------- analiza kształtu


@dataclass
class _Cell:
    """Obszar wewnątrz mebla zamknięty liniami rysunku."""

    x0: int
    y0: int
    x1: int
    y1: int
    area: int
    round: bool
    inner: bool = True  # nie dotyka obrysu kształtu (np. komora zlewu w blacie)

    @property
    def w(self) -> int:
        return self.x1 - self.x0

    @property
    def h(self) -> int:
        return self.y1 - self.y0


def _cells(comp: np.ndarray, thin: np.ndarray, box: tuple[int, int, int, int]) -> list[_Cell]:
    x0, y0, x1, y1 = box
    sub = comp[y0:y1, x0:x1].astype(np.uint8)
    filled = sub.copy()
    contours, _ = cv2.findContours(sub, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(filled, contours, -1, 1, -1)
    inner = cv2.erode(filled, np.ones((3, 3), np.uint8)).astype(bool) & (thin[y0:y1, x0:x1] == 0)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(inner.astype(np.uint8), connectivity=4)
    cells = []
    for i in range(1, n):
        cx, cy, w, h, area = stats[i]
        if area < 6:
            continue
        cnt, _ = cv2.findContours((lab == i).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        perim = cv2.arcLength(cnt[0], True) or 1.0
        circularity = 4 * math.pi * area / perim**2
        # Małe okręgi (kilka px) mają poszarpany obwód, więc dla nich wystarczy wypełnienie jak koła.
        roundish = circularity > 0.7 or (max(w, h) <= 8 and 0.55 <= area / (w * h) <= 0.92)
        inner_cell = cx > 1 and cy > 1 and cx + w < sub.shape[1] - 1 and cy + h < sub.shape[0] - 1
        cells.append(
            _Cell(x0 + cx, y0 + cy, x0 + cx + w, y0 + cy + h, int(area), roundish and 0.7 < w / h < 1.4, inner_cell)
        )
    return cells


def _analyze(comp: np.ndarray, ctx: _Ctx, rotated: bool = False) -> list[FurniturePx]:
    s = ctx.s
    ys, xs = np.nonzero(comp)
    box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    bw, bh = box[2] - box[0], box[3] - box[1]
    area = len(xs)
    cnt, _ = cv2.findContours(comp.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    contour = max(cnt, key=cv2.contourArea)
    (rcx, rcy), (rw, rh), rangle = cv2.minAreaRect(contour)
    hull_area = cv2.contourArea(cv2.convexHull(contour)) or 1.0
    (_, _), enclosing_r = cv2.minEnclosingCircle(contour)
    fill_circle = area / (math.pi * enclosing_r**2)
    fill_box = area / (bw * bh)
    if min(bw, bh) * s < 0.2 or area * s * s < 0.8 * MIN_AREA_M2:
        return []  # resztki linii (skrzydło drzwi, kawałek łuku)

    # Okrągły stół: koło wypełnia prawie całe koło opisane (obrócony kwadrat fotela tylko ok. 2/π).
    if 0.8 <= bw / bh <= 1.25 and fill_circle >= 0.9 and 0.5 <= max(bw, bh) * s <= 1.6:
        d = (bw + bh) / 2
        return [FurniturePx((box[0] + box[2]) / 2, (box[1] + box[3]) / 2, d, d, 0, "stol_okragly", HEIGHTS["stol_okragly"])]

    # Kształt wyraźnie obrócony (np. fotel ustawiony skosem): obrócony prostokąt.
    tilt = rangle % 90
    tilted = SNAP_ANGLE_DEG < tilt < 90 - SNAP_ANGLE_DEG and area / max(rw * rh, 1) > 0.75 and fill_box < 0.8
    if tilted:
        w_m, h_m = rw * s, rh * s
        kind = "fotel" if max(w_m, h_m) <= 1.1 else ("kanapa" if max(w_m, h_m) <= 2.6 else "mebel")
        # Szerokość wzdłuż dłuższego boku dla kanapy, dla fotela dowolnie (przód ustali _orient_seats).
        w, d, rot = (rw, rh, rangle) if rw >= rh else (rh, rw, rangle + 90)
        return [FurniturePx(rcx, rcy, w, d, rot % 360, kind, HEIGHTS[kind], {"tilted": True})]

    if fill_box >= 0.85 or (area / hull_area >= 0.95 and fill_box >= 0.75):
        return [_classify_box(comp, box, ctx)]

    # Kształt nieregularny ustawiony skosem (np. blat w V wzdłuż ściany skośnej): analiza po obróceniu.
    angle = _dominant_angle(contour)
    if not rotated and SKEW_MIN_DEG <= angle % 90 <= 90 - SKEW_MIN_DEG:
        return _analyze_rotated(comp, ctx, angle)

    # Kształt nieregularny: blat w L/U, kanapa narożna. Dzielimy na prostokąty.
    parts = [(p.x0, p.y0, p.x1, p.y1) for p in extract_walls(comp) if comp[p.y0 : p.y1, p.x0 : p.x1].mean() >= MIN_FILL]
    parts = [p for p in parts if min(p[2] - p[0], p[3] - p[1]) * s >= MIN_SIDE_M]
    if not parts:
        return []
    appliances = _appliances(comp, box, ctx)
    out: list[FurniturePx] = []
    kitchen = bool(appliances)
    for p in parts:
        # Ramię blatu pod oknem nie dotyka ściany, ale ma typową głębokość blatu.
        depth = min(p[2] - p[0], p[3] - p[1]) * s
        if kitchen and (_wall_sides(p, ctx) or COUNTER_DEPTH_M[0] <= depth <= COUNTER_DEPTH_M[1]):
            out.append(_axis_item(p, "blat", ctx.wall_mask, s))
        else:
            out.append(_classify_box(comp, p, ctx))
    return out + appliances


def _dominant_angle(contour: np.ndarray) -> float:
    """Kierunek najdłuższego boku obrysu w stopniach (0–180, kąt na obrazie)."""
    poly = cv2.approxPolyDP(contour, 2.0, True)[:, 0, :].astype(float)
    edges = np.roll(poly, -1, axis=0) - poly
    k = int(np.argmax(np.hypot(edges[:, 0], edges[:, 1])))
    return math.degrees(math.atan2(edges[k, 1], edges[k, 0])) % 180


def _analyze_rotated(comp: np.ndarray, ctx: _Ctx, angle: float) -> list[FurniturePx]:
    """Analiza kształtu po obróceniu obrazu tak, by jego boki były poziome i pionowe.

    Wyniki wracają do układu rzutu: środek przez odwrotne przekształcenie, obrót mebla o ten sam kąt.
    """
    h, w = comp.shape
    ys, xs = np.nonzero(comp)
    center = (float(xs.mean()), float(ys.mean()))
    m = cv2.getRotationMatrix2D(center, angle, 1.0)  # obraz obrócony o `angle`: bok kształtu poziomo

    def rot(a: np.ndarray, interp: int = cv2.INTER_NEAREST) -> np.ndarray:
        return cv2.warpAffine(a, m, (w, h), flags=interp)

    def rot_mask(a: np.ndarray) -> np.ndarray:
        return rot(a.astype(np.uint8)).astype(bool)

    rc = m @ np.array([*ctx.room_center, 1.0])
    # Kreski wyznaczamy na nowo z obróconego obrazu: obrócona 1-pikselowa kreska się rwie. Same ciemne
    # piksele, bez gradientu, który przy kilku cm na piksel zalewa wnętrza małych okręgów (pola płyty).
    clean = rot(ctx.clean, cv2.INTER_LINEAR)
    thin = ((clean < ROTATED_LINE_MAX_GRAY) * 255).astype(np.uint8)
    edges = cv2.morphologyEx((thin > 0).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    rctx = replace(
        ctx,
        edges=cv2.dilate(edges, np.ones((SEAL_PX, SEAL_PX), np.uint8)).astype(bool),
        thin=thin,
        clean=clean,
        wall_mask=rot_mask(ctx.all_walls),
        colored=rot_mask(ctx.colored),
        all_walls=rot_mask(ctx.all_walls),
        room_center=(float(rc[0]), float(rc[1])),
    )
    inv = cv2.invertAffineTransform(m)
    out = []
    for it in _analyze(rot_mask(comp), rctx, rotated=True):
        cx, cy = inv @ np.array([it.cx, it.cy, 1.0])
        # Obrót obrazu o `angle` (przeciwnie do wskazówek na ekranie) zmniejsza kąt mebla o tyle samo.
        out.append(replace(it, cx=float(cx), cy=float(cy), rotation=(it.rotation + angle) % 360))
    return out


def _classify_box(comp: np.ndarray, box: tuple[int, int, int, int], ctx: _Ctx) -> FurniturePx:
    s = ctx.s
    g = ctx.pad
    snapped = _snap_to_walls((box[0] + g, box[1] + g, box[2] - g, box[3] - g), ctx.wall_mask, round(SNAP_M / s))
    x0, y0, x1, y1 = snapped
    short, long_ = sorted(((x1 - x0) * s, (y1 - y0) * s))
    sides = _wall_sides(snapped, ctx)
    cells = _cells(comp, ctx.thin, box)
    big_cells = [c for c in cells if min(c.w, c.h) * s >= 0.25]
    small_round = [c for c in cells if c.round and 0.04 <= max(c.w, c.h) * s / 2 <= 0.16]
    bathroom = ctx.room_m2 <= BATHROOM_MAX_M2
    fill = comp[box[1] : box[3], box[0] : box[2]].mean()

    kind, params = "mebel", {}
    if long_ >= 0.75 and _modules_with_cross(snapped, ctx):
        kind, params = "szafa", {"modules": _modules_with_cross(snapped, ctx)}
    elif bathroom and len(sides) >= 2 and 0.7 <= short and long_ <= 1.2 and fill < 0.97 and _rounded_corner(comp, box):
        kind = "prysznic"
    elif 0.5 <= short <= 1.15 and 1.4 <= long_ <= 2.8 and _seat_cells(big_cells, snapped, s) >= 2:
        kind, params = "kanapa", {"seats": _seat_cells(big_cells, snapped, s)}
    elif (
        not bathroom
        and 1.0 <= long_ <= 2.2
        and 0.25 <= short <= 0.6
        and _has_screen(ctx.thin, box, s)
        and not ctx.colored[box[1] : box[3], box[0] : box[2]].any()  # kreska po usuniętym napisie to nie ekran
    ):
        kind = "tv"
    elif bathroom and sides and 0.6 <= short <= 1.1 and 1.4 <= long_ <= 2.1 and any(
        c.inner and c.area >= TUB_INNER * (x1 - x0) * (y1 - y0) for c in cells
    ):
        kind = "wanna"  # wanna: wewnątrz duża misa
    elif bathroom and 0.3 <= short <= 0.55 and 0.45 <= long_ <= 0.8 and (
        (sides and fill < 0.9) or any(_oval(c) and c.area >= 0.3 * (x1 - x0) * (y1 - y0) for c in cells)
    ):
        kind = "wc"  # WC bywa przed półką instalacyjną, nie przy samej ścianie
    elif bathroom and sides and 0.25 <= short <= 0.6 and 0.35 <= long_ <= 2.0:
        # Umywalka ma okrągłą lub owalną misę; płytki prostokąt bez niej przy ścianie łazienki to pralka.
        if any(_oval(c) and max(c.w, c.h) * s >= 0.15 for c in cells):
            kind = "umywalka"
        else:
            kind = "pralka" if 0.4 <= short and long_ <= 0.7 else "szafka"
    elif 0.75 <= short <= 1.6 and 1.7 <= long_ <= 2.4 and _pillow(cells, snapped, s):
        kind = "lozko"
    elif not sides and 0.55 <= short <= 1.1 and long_ <= 1.1 and len(big_cells) >= 2:
        kind = "fotel"
    elif not sides and not bathroom and short >= 0.35 and long_ >= 0.5 and short * long_ < 0.8 and len(big_cells) <= 1:
        kind = "stolik"
    else:
        kind = classify(snapped, ctx.edges, ctx.thin, ctx.wall_mask, s, ctx.room_m2)
        if kind == "szafka" and len(small_round) >= 3:
            kind = "blat"
    item = _axis_item(snapped, kind, ctx.wall_mask, s, params)
    if kind == "kanapa":
        _face_away_from_backrest(item, cells, snapped, ctx)
    if kind == "prysznic":
        _face_room(item, ctx)
    return item


def _axis_item(
    box: tuple[int, int, int, int], kind: str, wall_mask: np.ndarray, s: float, params: dict[str, Any] | None = None
) -> FurniturePx:
    """Prostokąt osiowy; przód od najbliższej ściany (meble przyścienne), inaczej w dół rzutu."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rot = 0.0
    if kind in BACK_TO_WALL:
        side = _nearest_wall_side(box, wall_mask, s, prefer_long=kind not in {"wc"})
        rot = {"top": 0.0, "left": 270.0, "bottom": 180.0, "right": 90.0}.get(side, 0.0)
    width, depth = (w, h) if rot in (0.0, 180.0) else (h, w)
    return FurniturePx(cx, cy, width, depth, rot, kind, HEIGHTS[kind], params or {})


def _nearest_wall_side(box: tuple[int, int, int, int], wall_mask: np.ndarray, s: float, prefer_long: bool = True) -> str | None:
    """Strona prostokąta przylegająca do ściany (tył mebla). Przy kilku – dłuższa (np. blat, kanapa)."""
    x0, y0, x1, y1 = box
    reach = max(2, round(0.3 / s))
    h, w = wall_mask.shape
    cover = {
        "top": wall_mask[max(0, y0 - reach) : y0, x0:x1].any(axis=0).mean() if y0 > 0 else 0,
        "bottom": wall_mask[y1 : min(h, y1 + reach), x0:x1].any(axis=0).mean() if y1 < h else 0,
        "left": wall_mask[y0:y1, max(0, x0 - reach) : x0].any(axis=1).mean() if x0 > 0 else 0,
        "right": wall_mask[y0:y1, x1 : min(w, x1 + reach)].any(axis=1).mean() if x1 < w else 0,
    }
    # Odległość do ściany: bliższa wygrywa przy podobnym pokryciu.
    dist = {}
    for side in cover:
        for d in range(reach + 1):
            if side == "top" and y0 - d - 1 >= 0 and wall_mask[y0 - d - 1, x0:x1].mean() > 0.5:
                break
            if side == "bottom" and y1 + d < h and wall_mask[y1 + d, x0:x1].mean() > 0.5:
                break
            if side == "left" and x0 - d - 1 >= 0 and wall_mask[y0:y1, x0 - d - 1].mean() > 0.5:
                break
            if side == "right" and x1 + d < w and wall_mask[y0:y1, x1 + d].mean() > 0.5:
                break
        dist[side] = d
    candidates = [k for k in cover if cover[k] > 0.5 and dist[k] < reach]
    if not candidates:
        return None
    length = {"top": x1 - x0, "bottom": x1 - x0, "left": y1 - y0, "right": y1 - y0}
    if prefer_long:
        return max(candidates, key=lambda k: (length[k] - 3 * dist[k], -dist[k]))
    return min(candidates, key=lambda k: (length[k], dist[k]))


def _wall_sides(box: tuple[int, int, int, int], ctx: _Ctx) -> list[str]:
    x0, y0, x1, y1 = box
    near = max(2, round(NEAR_WALL_M / ctx.s))
    m = ctx.wall_mask
    h, w = m.shape
    sides = []
    if m[max(0, y0 - near) : y0, x0:x1].any(axis=0).mean() > 0.5:
        sides.append("top")
    if m[y1 : min(h, y1 + near), x0:x1].any(axis=0).mean() > 0.5:
        sides.append("bottom")
    if m[y0:y1, max(0, x0 - near) : x0].any(axis=1).mean() > 0.5:
        sides.append("left")
    if m[y0:y1, x1 : min(w, x1 + near)].any(axis=1).mean() > 0.5:
        sides.append("right")
    return sides


def _pillow(cells: list[_Cell], box: tuple[int, int, int, int], s: float) -> bool:
    """Łóżko: duża komórka (kołdra) i mniejsza przy jednym z krótszych boków (poduszka)."""
    x0, y0, x1, y1 = box
    horizontal = (x1 - x0) >= (y1 - y0)
    lo, hi = (x0, x1) if horizontal else (y0, y1)
    end = PILLOW_END * (hi - lo)
    duvet = any(c.area * s * s >= 0.4 for c in cells)
    for c in cells:
        a = c.area * s * s
        mid = (c.x0 + c.x1) / 2 if horizontal else (c.y0 + c.y1) / 2
        if PILLOW_M2[0] <= a <= PILLOW_M2[1] and (mid - lo <= end or hi - mid <= end):
            return duvet
    return False


def _seat_cells(cells: list[_Cell], box: tuple[int, int, int, int], s: float) -> int:
    """Poduchy siedziska: duże komórki ułożone wzdłuż dłuższego boku."""
    x0, y0, x1, y1 = box
    horizontal = (x1 - x0) >= (y1 - y0)
    length = (x1 - x0) if horizontal else (y1 - y0)
    seats = [c for c in cells if (c.w if horizontal else c.h) < 0.7 * length and min(c.w, c.h) * s >= 0.3]
    # Poduchy są jednakowe; komórki blatu (komora zlewu, szafka, zmywarka) mają różne długości.
    sizes = [c.w if horizontal else c.h for c in seats]
    if len(sizes) >= 2 and max(sizes) > MAX_SEAT_RATIO * min(sizes):
        return 0
    return min(len(seats), 4)


def _has_screen(thin: np.ndarray, box: tuple[int, int, int, int], s: float) -> bool:
    """TV: w szafce długa linia (ekran) równoległa do dłuższego boku, w środkowej części głębokości."""
    x0, y0, x1, y1 = box
    crop = thin[y0:y1, x0:x1] > 0
    if crop.shape[1] < crop.shape[0]:
        crop = crop.T  # dłuższy bok zawsze poziomo
    depth, length = crop.shape
    if depth < 6:
        return False
    rows = crop[round(0.25 * depth) : round(0.75 * depth) + 1, round(0.1 * length) : round(0.9 * length)]
    cover = rows.mean(axis=1) if rows.size else np.zeros(1)
    # Ekran jest krótszy niż szafka (nie jest jej przednią krawędzią) i zajmuje ok. połowę długości.
    return bool(((cover >= 0.4) & (cover <= 0.97)).any())


def _rounded_corner(comp: np.ndarray, box: tuple[int, int, int, int]) -> bool:
    """Prysznic narożny: kwadrat z jednym narożnikiem zaokrąglonym (łuk brodzika)."""
    x0, y0, x1, y1 = box
    sub = comp[y0:y1, x0:x1]
    k = max(3, min(x1 - x0, y1 - y0) // 4)
    corners = [sub[:k, :k].mean(), sub[:k, -k:].mean(), sub[-k:, :k].mean(), sub[-k:, -k:].mean()]
    return min(corners) < 0.75 and sorted(corners)[1] > 0.9


def _modules_with_cross(box: tuple[int, int, int, int], ctx: _Ctx) -> int:
    """Szafa: krzyżyk w każdym module (1–3 moduły wzdłuż dłuższego boku). Zwraca liczbę modułów albo 0."""
    x0, y0, x1, y1 = box
    horizontal = (x1 - x0) >= (y1 - y0)
    length, depth = ((x1 - x0), (y1 - y0)) if horizontal else ((y1 - y0), (x1 - x0))
    if depth * ctx.s < 0.4:
        return 0
    for k in range(1, 4):
        if length / k < 0.6 * depth:
            break
        step = length / k
        mods = [
            (round(x0 + i * step), y0, round(x0 + (i + 1) * step), y1) if horizontal else (x0, round(y0 + i * step), x1, round(y0 + (i + 1) * step))
            for i in range(k)
        ]
        if all(_has_cross(m, ctx.edges, ctx.thin) for m in mods):
            return k
    return 0


def _appliances(comp: np.ndarray, box: tuple[int, int, int, int], ctx: _Ctx) -> list[FurniturePx]:
    """Płyta (skupisko ≥ 3 małych okręgów) i zlew (komora w środku blatu) w kształcie blatu."""
    s = ctx.s
    cells = _cells(comp, ctx.thin, box)
    out: list[FurniturePx] = []
    rings = [c for c in cells if c.round and max(c.w, c.h) * s <= RING_MAX_M]
    used: set[int] = set()
    for c in rings:
        group = [j for j, o in enumerate(rings) if _dist(o, c) * s <= 0.5]
        if len(group) >= 3 and not used & set(group):
            used |= set(group)
            gx0 = min(rings[j].x0 for j in group)
            gy0 = min(rings[j].y0 for j in group)
            gx1 = max(rings[j].x1 for j in group)
            gy1 = max(rings[j].y1 for j in group)
            out.append(_on_counter((gx0, gy0, gx1, gy1), "plyta", comp, ctx))
    if not out:
        return []  # bez płyty to nie blat kuchenny (komórki w innych meblach udawałyby zlew)
    in_cooktop = {id(rings[j]) for j in used}
    # Zlew: największa komórka wewnątrz blatu (nie przy jego krawędzi) o rozmiarze komory.
    basins = [
        c
        for c in cells
        if c.inner and id(c) not in in_cooktop and 0.15 <= max(c.w, c.h) * s <= 0.6 and c.area >= 0.6 * c.w * c.h
        and not any(_dist(c, rings[j]) * s < 0.3 for j in used)
    ]
    if basins:
        b = max(basins, key=lambda c: c.area)
        out.append(_on_counter((b.x0, b.y0, b.x1, b.y1), "zlew", comp, ctx))
    return out


def _oval(c: _Cell) -> bool:
    """Misa umywalki: owal wypełnia ok. π/4 prostokąta (zaokrąglony prostokąt pralki – prawie cały)."""
    return OVAL_MIN_FILL <= c.area / (c.w * c.h) <= 0.86 and 0.5 <= c.w / c.h <= 2.0


def _dist(a: _Cell, b: _Cell) -> float:
    return math.hypot((a.x0 + a.x1 - b.x0 - b.x1) / 2, (a.y0 + a.y1 - b.y0 - b.y1) / 2)


def _on_counter(inner: tuple[int, int, int, int], kind: str, comp: np.ndarray, ctx: _Ctx) -> FurniturePx:
    """Urządzenie w blacie: obrys rozszerzony do głębokości blatu (od ściany do frontu)."""
    x0, y0, x1, y1 = inner
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    # Głębokość blatu w miejscu urządzenia: ciągły pas kształtu w poprzek.
    col = np.flatnonzero(comp[:, cx])
    row = np.flatnonzero(comp[cy, :])
    col = col[(col >= y0 - 40) & (col <= y1 + 40)] if len(col) else col
    row = row[(row >= x0 - 40) & (row <= x1 + 40)] if len(row) else row
    vertical_depth = (int(col.min()), int(col.max()) + 1) if len(col) else (y0, y1)
    horizontal_depth = (int(row.min()), int(row.max()) + 1) if len(row) else (x0, x1)
    half = round(APPLIANCE_MIN_M[kind] / ctx.s / 2)
    if (vertical_depth[1] - vertical_depth[0]) <= (horizontal_depth[1] - horizontal_depth[0]):
        # Blat biegnie poziomo: głębokość w pionie, długość urządzenia wzdłuż X.
        x0, x1 = min(x0, cx - half), max(x1, cx + half)
        box = (x0, vertical_depth[0], x1, vertical_depth[1])
    else:
        y0, y1 = min(y0, cy - half), max(y1, cy + half)
        box = (horizontal_depth[0], y0, horizontal_depth[1], y1)
    box = _snap_to_walls(box, ctx.wall_mask, round(SNAP_M / ctx.s))
    return _axis_item(box, kind, ctx.wall_mask, ctx.s)


def _face_away_from_backrest(item: FurniturePx, cells: list[_Cell], box: tuple[int, int, int, int], ctx: _Ctx) -> None:
    """Kanapa bez ściany za plecami: oparcie to wąska komórka wzdłuż jednego z dłuższych boków."""
    x0, y0, x1, y1 = box
    horizontal = (x1 - x0) >= (y1 - y0)
    length = (x1 - x0) if horizontal else (y1 - y0)
    for c in cells:
        along, across = (c.w, c.h) if horizontal else (c.h, c.w)
        if along >= 0.6 * length and across * ctx.s < 0.25:
            if horizontal:
                back_top = (c.y0 + c.y1) / 2 < (y0 + y1) / 2
                item.rotation = 0.0 if back_top else 180.0
            else:
                back_left = (c.x0 + c.x1) / 2 < (x0 + x1) / 2
                item.rotation = 270.0 if back_left else 90.0
            item.w, item.d = (x1 - x0, y1 - y0) if horizontal else (y1 - y0, x1 - x0)
            return


def _face_room(item: FurniturePx, ctx: _Ctx) -> None:
    """Prysznic narożny: łuk (przód) w stronę środka pomieszczenia; obrót o 45° zaokrąglamy do boku."""
    dx, dy = ctx.room_center[0] - item.cx, ctx.room_center[1] - item.cy
    item.params["corner"] = ("left" if dx > 0 else "right") + "-" + ("top" if dy > 0 else "bottom")
    item.rotation = 0.0


def _chairs(items: list[FurniturePx], ctx: _Ctx) -> None:
    """Małe siedziska tuż przy stole lub biurku to krzesła, przodem do niego.

    Pusty prostokąt przy ścianie, przy którym stoi krzesło, to biurko (bez krzesła: szafka, komoda).
    """
    s = ctx.s

    def gap(a: FurniturePx, b: FurniturePx) -> float:
        dx = abs(a.cx - b.cx) - (_extent(a)[0] + _extent(b)[0]) / 2
        dy = abs(a.cy - b.cy) - (_extent(a)[1] + _extent(b)[1]) / 2
        return max(dx, dy, 0.0) * s

    chairs = [it for it in items if it.type in {"male", "stolik"} and max(it.w, it.d) * s <= CHAIR_MAX_M]
    desks = [it for it in items if it.type in {"kanapa", "szafka", "mebel"} and not it.params and _desk_size(it, s)]
    tables = [it for it in items if it.type in {"stol", "stol_okragly"}] + desks
    for ch in chairs:
        near = [t for t in tables if t is not ch and gap(ch, t) <= CHAIR_GAP_M]
        if not near:
            continue
        t = min(near, key=lambda t: gap(ch, t))
        if t in desks:
            t.type, t.height = "biurko", HEIGHTS["biurko"]
        want = math.degrees(math.atan2(-(t.cx - ch.cx), t.cy - ch.cy))
        rot = round(want / 90) * 90 % 360  # przód krzesła do stołu
        w, d = _extent(ch)
        ch.w, ch.d = (w, d) if rot in (0, 180) else (d, w)
        ch.type, ch.height, ch.rotation = "krzeslo", HEIGHTS["krzeslo"], float(rot)


def _extent(it: FurniturePx) -> tuple[float, float]:
    """Wymiary prostokąta na obrazie (X, Y) dla mebla obróconego o wielokrotność 90°."""
    return (it.w, it.d) if round(it.rotation / 90) % 2 == 0 else (it.d, it.w)


def _desk_size(it: FurniturePx, s: float) -> bool:
    short, long_ = sorted((it.w * s, it.d * s))
    return 0.5 <= short <= 1.1 and 0.9 <= long_ <= 2.2


def _orient_seats(items: list[FurniturePx], ctx: _Ctx) -> None:
    """Fotel/kanapa bez ściany za plecami: przodem do najbliższego stołu lub TV (inaczej do środka pokoju)."""
    targets = [t for t in items if t.type in TARGETS]
    for it in items:
        if it.type not in SEATS:
            continue
        if it.type == "kanapa" and not it.params.get("tilted"):
            continue  # przód kanapy ustalony od ściany lub oparcia
        if targets:
            t = min(targets, key=lambda t: math.hypot(t.cx - it.cx, t.cy - it.cy))
            tx, ty = t.cx, t.cy
        else:
            tx, ty = ctx.room_center
        want = math.atan2(-(tx - it.cx), ty - it.cy)  # rotation, przy której przód patrzy na cel
        base = it.rotation
        options = [(base + k * 90) % 360 for k in range(4)]
        best = min(options, key=lambda r: abs((math.degrees(want) - r + 180) % 360 - 180))
        if round((best - base) / 90) % 2:
            it.w, it.d = it.d, it.w
        it.rotation = best


# ---------------------------------------------------------------- dotychczasowe narzędzia


def _snap_to_walls(box: tuple[int, int, int, int], wall_mask: np.ndarray, reach: int) -> tuple[int, int, int, int]:
    """Dosuwa boki prostokąta do lica ściany, jeśli ściana jest w zasięgu `reach` pikseli."""
    x0, y0, x1, y1 = box
    xm, ym = (x0 + x1) // 2, (y0 + y1) // 2
    h, w = wall_mask.shape
    left = np.flatnonzero(wall_mask[ym, max(0, x0 - reach) : x0])
    right = np.flatnonzero(wall_mask[ym, x1 : min(w, x1 + reach)])
    top = np.flatnonzero(wall_mask[max(0, y0 - reach) : y0, xm])
    bottom = np.flatnonzero(wall_mask[y1 : min(h, y1 + reach), xm])
    if len(left):
        x0 = max(0, x0 - reach) + int(left[-1]) + 1
    if len(right):
        x1 = x1 + int(right[0])
    if len(top):
        y0 = max(0, y0 - reach) + int(top[-1]) + 1
    if len(bottom):
        y1 = y1 + int(bottom[0])
    return x0, y0, x1, y1


def _without_color(img_bgr: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    colored = ((hsv[..., 1] > COLOR_SATURATION) & (hsv[..., 2] > 120)).astype(np.uint8)
    colored = cv2.dilate(colored, np.ones((3, 3), np.uint8))
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    return cv2.inpaint(gray, colored * 255, 3, cv2.INPAINT_TELEA)


def _thin_edges(clean: np.ndarray) -> np.ndarray:
    """Cienkie linie rysunku (uint8 0/255), bez pogrubiania – do wykrywania prostych."""
    grad = cv2.morphologyEx(clean, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
    return ((grad >= EDGE_STEP) * 255).astype(np.uint8)


def _edges(img_bgr: np.ndarray) -> np.ndarray:
    """Mapa linii mebli bez kolorowych napisów, z domkniętymi drobnymi przerwami."""
    thin = _thin_edges(_without_color(img_bgr))
    edges = cv2.morphologyEx((thin > 0).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))

    # Tam, gdzie usunęliśmy czerwony napis lub linię wymiarową, kontur mebla ma dziurę – dociągamy go
    # w poziomie i pionie, ale tylko w tych miejscach, żeby nie sklejać innych linii.
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    colored = ((hsv[..., 1] > COLOR_SATURATION) & (hsv[..., 2] > 120)).astype(np.uint8)
    colored = cv2.dilate(colored, np.ones((5, 5), np.uint8)).astype(bool)
    bridged = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((1, BRIDGE_PX), np.uint8)) | cv2.morphologyEx(
        edges, cv2.MORPH_CLOSE, np.ones((BRIDGE_PX, 1), np.uint8)
    )
    edges = edges.astype(bool) | (bridged.astype(bool) & colored)
    return cv2.dilate(edges.astype(np.uint8), np.ones((SEAL_PX, SEAL_PX), np.uint8)).astype(bool)


def classify(
    box: tuple[int, int, int, int],
    edges: np.ndarray,
    thin: np.ndarray,
    wall_mask: np.ndarray,
    s: float,
    room_m2: float,
) -> str:
    """Typ prostokąta z wymiarów (m), krzyżyka po przekątnych, położenia przy ścianie i wielkości pokoju."""
    x0, y0, x1, y1 = box
    short, long_ = sorted(((x1 - x0) * s, (y1 - y0) * s))
    near = round(NEAR_WALL_M / s)
    h, w = wall_mask.shape
    at_wall = wall_mask[max(0, y0 - near) : min(h, y1 + near), max(0, x0 - near) : min(w, x1 + near)].any()

    if short >= CAR_MIN_M[0] and long_ >= CAR_MIN_M[1]:
        return "samochod"
    if long_ >= 0.9 and short >= 0.4 and _has_cross(box, edges, thin):
        return "szafa"
    if short >= 1.3 and long_ >= 1.5:  # materac bez poduszek bywa prawie kwadratowy
        return "lozko"
    if 0.8 <= short <= 1.15 and 1.7 <= long_ <= 2.6:
        return "kanapa" if at_wall else "lozko"
    if 0.6 <= short <= 0.9 and 1.4 <= long_ <= 1.9 and at_wall and room_m2 <= BATHROOM_MAX_M2:
        return "wanna"
    if 0.7 <= short <= 1.2 and 1.0 <= long_ <= 2.2 and not at_wall:
        return "stol"
    if 0.45 <= short <= 0.8 and long_ >= 0.9 and at_wall:
        return "szafka"
    if long_ <= 0.65:
        return "male"
    return "mebel"


def _has_cross(box: tuple[int, int, int, int], edges: np.ndarray, thin: np.ndarray) -> bool:
    """Symbol szafy: krzyżyk po przekątnych prostokąta.

    Jedna przekątna musi być wyraźną prostą linią (gęste rysunki szafek kuchennych nie mają takiej
    długiej prostej), druga może być przerwana napisem, więc wystarczy, że jest w większości pokryta.
    """
    x0, y0, x1, y1 = box
    if min(x1 - x0, y1 - y0) < 8:
        return False
    coverage = [_coverage(edges, (x0, y0), (x1, y1)), _coverage(edges, (x0, y1), (x1, y0))]
    if min(coverage) < CROSS_HITS:
        return False
    crop = np.ascontiguousarray(thin[max(0, y0) : y1, max(0, x0) : x1])
    diag = math.hypot(x1 - x0, y1 - y0)
    lines = cv2.HoughLinesP(crop, 1, np.pi / 360, 15, minLineLength=int(0.6 * diag), maxLineGap=6)
    if lines is None:
        return False
    diag_angle = math.degrees(math.atan2(y1 - y0, x1 - x0))
    for lx0, ly0, lx1, ly1 in lines.reshape(-1, 4).tolist():
        angle = math.degrees(math.atan2(ly1 - ly0, lx1 - lx0))
        for target in (diag_angle, -diag_angle):
            if abs((angle - target + 90) % 180 - 90) < 8:
                return True
    return False


def _coverage(edges: np.ndarray, a: tuple[int, int], b: tuple[int, int]) -> float:
    """Jaka część odcinka a–b (bez 15 % na końcach) leży na linii."""
    t = np.linspace(0.15, 0.85, 40)
    xs = np.clip((a[0] + (b[0] - a[0]) * t).astype(int), 0, edges.shape[1] - 1)
    ys = np.clip((a[1] + (b[1] - a[1]) * t).astype(int), 0, edges.shape[0] - 1)
    return float(edges[ys, xs].mean())
