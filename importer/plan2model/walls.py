"""Wykrywanie ścian na rzucie: maska ciemnych pikseli → prostokąty ścian w pikselach."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

# Ściany są czarne/ciemnoszare i bez koloru. Czerwone wymiary, żółte elementy
# i jasny znak wodny odpadają na progu jasności (V) i nasycenia (S).
MAX_VALUE = 110
MAX_SATURATION = 80
# Na niektórych rzutach ściany są szare (np. jasność 122). Wtedy próg ustawiamy nad
# najczęstszą jasnością ciemnych pikseli bez koloru, czyli nad kolorem ścian.
BACKGROUND_VALUE = 200
WALL_VALUE_MARGIN = 20
MIN_FILL_RATIO = 0.6  # ile prostokąta ściany musi być faktycznie zamalowane
MIN_PIER_THICKNESS = 0.4  # słupek: grubość co najmniej taka część najgrubszej ściany


@dataclass
class WallPx:
    """Ściana jako prostokąt w pikselach, [x0, x1) × [y0, y1)."""

    x0: int
    y0: int
    x1: int
    y1: int
    horizontal: bool

    @property
    def thickness(self) -> int:
        return self.y1 - self.y0 if self.horizontal else self.x1 - self.x0

    @property
    def length(self) -> int:
        return self.x1 - self.x0 if self.horizontal else self.y1 - self.y0

    def axis(self) -> tuple[tuple[float, float], tuple[float, float]]:
        """Oś ściany (początek, koniec) w pikselach."""
        if self.horizontal:
            yc = (self.y0 + self.y1) / 2
            return (self.x0, yc), (self.x1, yc)
        xc = (self.x0 + self.x1) / 2
        return (xc, self.y0), (xc, self.y1)


def wall_value_threshold(hsv: np.ndarray) -> int:
    """Próg jasności ścian: MAX_VALUE dla czarnych ścian, wyżej dla szarych."""
    gray = (hsv[..., 1] < MAX_SATURATION) & (hsv[..., 2] < BACKGROUND_VALUE)
    if not gray.any():
        return MAX_VALUE
    peak = int(np.argmax(np.bincount(hsv[..., 2][gray], minlength=256)))
    return max(MAX_VALUE, peak + WALL_VALUE_MARGIN)


def wall_mask(img_bgr: np.ndarray) -> np.ndarray:
    """Maska bool pikseli, które mogą być ścianą (bez tekstu i drobnych symboli)."""
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    dark = (hsv[..., 2] < wall_value_threshold(hsv)) & (hsv[..., 1] < MAX_SATURATION)
    mask = dark.astype(np.uint8)

    # Cienkie kreski (tekst, linie wymiarowe, meble) mają 1–2 px – otwarcie je usuwa.
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

    # Drobne osobne kształty (cyfry, słupki pergoli) są mniejsze niż ~1,2 grubości ściany zewnętrznej.
    # Wyjątek: krótki, ale gruby kawałek ściany (słupek między dwoma oknami w narożniku); cyfry
    # i symbole mają cienkie kreski.
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 3)
    max_thickness = 2 * float(dist.max())
    min_size = 1.2 * max_thickness
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    thickness = np.zeros(n)
    np.maximum.at(thickness, labels.ravel(), 2 * dist.ravel())
    keep = np.zeros(n, bool)
    for i in range(1, n):
        w, h = stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
        pier = min(w, h) >= MIN_PIER_THICKNESS * max_thickness and thickness[i] >= MIN_PIER_THICKNESS * max_thickness
        keep[i] = max(w, h) >= min_size or pier
    return keep[labels]


def _run_lengths(mask: np.ndarray) -> np.ndarray:
    """Dla każdego piksela długość poziomego ciągu zamalowanych pikseli, w którym leży."""
    out = np.zeros(mask.shape, np.int32)
    padded = np.pad(mask.astype(np.int8), ((0, 0), (1, 1)))
    diff = np.diff(padded, axis=1)
    for r in range(mask.shape[0]):
        starts = np.flatnonzero(diff[r] == 1)
        ends = np.flatnonzero(diff[r] == -1)
        for s, e in zip(starts, ends):
            out[r, s:e] = e - s
    return out


def extract_walls(mask: np.ndarray) -> list[WallPx]:
    """Rozkłada maskę na poziome i pionowe prostokąty ścian.

    Piksel należy do ściany poziomej, gdy jego ciąg poziomy jest dłuższy niż pionowy.
    Skośne ściany nie są obsługiwane (wypadną na filtrze wypełnienia).
    """
    hrun = _run_lengths(mask)
    vrun = _run_lengths(mask.T).T
    walls: list[WallPx] = []
    for horizontal, part in ((True, mask & (hrun >= vrun)), (False, mask & (hrun < vrun))):
        # Ściany poziome liczymy na transponowanej masce, więc niżej zawsze „idziemy” wzdłuż wierszy.
        part = part.T if horizontal else part
        n, labels = cv2.connectedComponents(part.astype(np.uint8), connectivity=4)
        for i in range(1, n):
            for c0, r0, c1, r1 in _split_strip(labels == i):
                if horizontal:
                    walls.append(WallPx(r0, c0, r1, c1, True))
                else:
                    walls.append(WallPx(c0, r0, c1, r1, False))
    return walls


def _split_strip(comp: np.ndarray, tol: int = 2) -> list[tuple[int, int, int, int]]:
    """Dzieli pionowy pasek na prostokąty (c0, r0, c1, r1) tam, gdzie zmienia się jego szerokość.

    Dzięki temu cienka ściana sklejona z innym kształtem (łuk, kominek) nie przepada w całości.
    """
    rows = np.flatnonzero(comp.any(axis=1))
    groups: list[list[tuple[int, int, int]]] = []
    for r in rows:
        cols = np.flatnonzero(comp[r])
        c0, c1 = int(cols[0]), int(cols[-1]) + 1
        g = groups[-1] if groups else None
        if g and g[-1][0] == r - 1 and abs(g[0][1] - c0) <= tol and abs(g[0][2] - c1) <= tol:
            g.append((int(r), c0, c1))
        else:
            groups.append([(int(r), c0, c1)])

    rects = []
    for g in groups:
        r0, r1 = g[0][0], g[-1][0] + 1
        c0, c1 = min(x[1] for x in g), max(x[2] for x in g)
        if comp[r0:r1, c0:c1].mean() < MIN_FILL_RATIO:
            # Odstające piksele na styku z inną ścianą lub meblem (np. wezgłowie łóżka) pogrubiają
            # prostokąt cienkiej ścianki; wtedy liczy się jej typowa szerokość.
            c0, c1 = int(np.median([x[1] for x in g])), int(np.median([x[2] for x in g]))
        if c1 - c0 < 3 or r1 - r0 < 0.8 * (c1 - c0):
            continue  # za cienkie albo wyraźnie krótsze niż szerokie: kawałek łuku, nie ściana
        if comp[r0:r1, c0:c1].mean() < MIN_FILL_RATIO:
            continue
        rects.append((c0, r0, c1, r1))
    return rects


def outline(walls: list[WallPx]) -> tuple[int, int, int, int]:
    """Obrys zewnętrzny budynku (x0, y0, x1, y1) w pikselach."""
    return (
        min(w.x0 for w in walls),
        min(w.y0 for w in walls),
        max(w.x1 for w in walls),
        max(w.y1 for w in walls),
    )
