"""Skala rzutu (metry na piksel) z wymiarów odczytanych przez OCR i kontrola wymiarami pokoi."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import combinations

import numpy as np

from . import rooms as rooms_
from .ocr import Token
from .walls import WallPx

OUTLINE_TOLERANCE = 0.03  # szerokość i wysokość budynku muszą dać tę samą skalę z dokładnością 3 %
CHECK_TOLERANCE = 0.05  # wymiar pokoju „zgadza się”, gdy różni się o mniej niż 5 %
MISREAD_ERROR = 0.5  # różnica ponad 50 % to raczej źle odczytana liczba (np. „35” zamiast „335”) niż zła skala
OUTDOOR_WORDS = ("balkon", "taras", "loggia", "ogród")  # poza ścianami budynku, nie wchodzą do sumy
GROSS_TO_NET = 1.2  # obrys ze ścianami jest ok. 20 % większy niż suma powierzchni pomieszczeń (wstępna skala)
AREA_MATCH_TOLERANCE = 0.10  # wykryty pokój „pasuje” do powierzchni z rzutu przy różnicy do 10 %
# Inne przypisanie nazw gorsze o mniej niż tyle (suma błędów) oznacza, że z samych powierzchni
# nie da się ich rozróżnić (np. hol 3,88 m² i łazienka 4,30 m²). Wtedy nazwy nie nadajemy.
AREA_AMBIGUITY = 0.03


@dataclass
class Scale:
    meters_per_px: float
    method: str  # "ocr-outline" | "areas-total" | "manual-width" | "manual-scale"
    width_token: Token | None = None
    height_token: Token | None = None


@dataclass
class Check:
    token: Token
    measured_m: float

    @property
    def error(self) -> float:
        return (self.measured_m - self.token.meters) / self.token.meters

    @property
    def ok(self) -> bool:
        return abs(self.error) <= CHECK_TOLERANCE

    @property
    def misread(self) -> bool:
        return abs(self.error) > MISREAD_ERROR


def from_outline(tokens: list[Token], width_px: int, height_px: int) -> Scale | None:
    """Szuka pary wymiarów (szerokość, wysokość budynku), które dają tę samą skalę.

    Wymiary zewnętrzne rzutu odpowiadają zewnętrznemu obrysowi ścian. Z kilku pasujących par
    wybieramy największą, bo wymiary całkowite są największymi liczbami na rzucie.
    """
    dims = [t for t in tokens if not t.is_area]
    best: tuple[float, Token, Token] | None = None
    for a in dims:
        for b in dims:
            if a is b:
                continue
            sa, sb = a.meters / width_px, b.meters / height_px
            if abs(sa - sb) / ((sa + sb) / 2) > OUTLINE_TOLERANCE:
                continue
            if best is None or a.meters + b.meters > best[0]:
                best = (a.meters + b.meters, a, b)
    if best is None:
        return None
    _, a, b = best
    # Średnia ważona długością: obie liczby mają ten sam błąd zaokrąglenia (1 cm).
    return Scale((a.meters + b.meters) / (width_px + height_px), "ocr-outline", a, b)


def check_dimensions(
    tokens: list[Token],
    walls_closed: np.ndarray,
    outline: tuple[int, int, int, int],
    scale: Scale,
) -> list[Check]:
    """Porównuje wymiary pokoi z rzutu z odległością między ścianami zmierzoną w miejscu napisu.

    Napis poziomy → mierzymy w poziomie (od ściany po lewej do ściany po prawej), pionowy → w pionie.
    """
    x0, y0, x1, y1 = outline
    checks = []
    for t in tokens:
        if t.is_area or t in (scale.width_token, scale.height_token):
            continue
        x, y = int(round(t.x)), int(round(t.y))
        if not (x0 < x < x1 and y0 < y < y1) or walls_closed[y, x]:
            continue  # tylko wymiary wewnątrz budynku
        line = walls_closed[:, x] if t.vertical else walls_closed[y, :]
        pos = y if t.vertical else x
        before = np.flatnonzero(line[:pos])
        after = np.flatnonzero(line[pos:])
        if len(before) == 0 or len(after) == 0:
            continue
        span_px = (pos + after[0]) - (before[-1] + 1)
        checks.append(Check(t, span_px * scale.meters_per_px))
    return checks


def is_outdoor(name: str) -> bool:
    return any(word in name.lower() for word in OUTDOOR_WORDS)


def from_areas(
    shape: tuple[int, int],
    walls: list[WallPx],
    outline: tuple[int, int, int, int],
    areas: dict[str, float],
    drawing: rooms_.Drawing | None = None,
) -> Scale | None:
    """Skala z sumy powierzchni pomieszczeń podanych na rzucie (bez balkonów i tarasów).

    Suma ma odpowiadać wolnej powierzchni między ścianami. Domykanie przerw drzwiowych
    zależy od skali, więc zaczynamy od przybliżenia z obrysu i poprawiamy kilka razy.
    """
    total = sum(a for name, a in areas.items() if not is_outdoor(name))
    if total <= 0:
        return None
    s = math.sqrt(GROSS_TO_NET * total / ((outline[2] - outline[0]) * (outline[3] - outline[1])))
    for _ in range(5):
        closed, _ = rooms_.closed_wall_mask(shape, walls, s, drawing)
        rooms_.narrow_strips(closed, outline, s)
        found, closets = rooms_.find_rooms(closed, outline, s)
        free_px = sum(r.area_px for r in found + closets)
        if free_px == 0:
            return None
        new = math.sqrt(total / free_px)
        done = abs(new - s) / s < 0.001
        s = new
        if done:
            break
    return Scale(s, "areas-total")


@dataclass
class AreaMatch:
    names: list[str]  # kilka nazw, gdy pomieszczenia są otwarte na siebie (np. pokój z kuchnią)
    area_on_plan: float
    measured_m2: float
    alternatives: list[str] = field(default_factory=list)  # inne możliwe nazwy; niepuste = niepewne

    @property
    def name(self) -> str:
        return " + ".join(self.names)

    @property
    def error(self) -> float:
        return (self.measured_m2 - self.area_on_plan) / self.area_on_plan


def match_areas(measured_m2: list[float], areas: dict[str, float]) -> list[AreaMatch | None]:
    """Przypisuje wykrytym pokojom nazwy z rzutu według powierzchni.

    Pokój może odpowiadać kilku pomieszczeniom naraz, gdy nie dzieli ich ściana (np. pokój
    otwarty na hol i kuchnię). Szukamy przypisania, które obejmuje najwięcej nazw, a przy
    remisie ma najmniejszy łączny błąd. Każda nazwa trafia do najwyżej jednego pokoju.
    """
    indoor = [n for n in areas if not is_outdoor(n)]
    options: list[list[tuple[frozenset[str], float]]] = []
    for m in measured_m2:
        opts = []
        for k in range(1, len(indoor) + 1):
            for names in combinations(indoor, k):
                plan = sum(areas[n] for n in names)
                if abs(m - plan) / plan <= AREA_MATCH_TOLERANCE:
                    opts.append((frozenset(names), abs(m - plan) / plan))
        options.append(opts)

    found: list[tuple[int, float, list[frozenset[str] | None]]] = []

    def search(i: int, used: frozenset[str], chosen: list[frozenset[str] | None], err: float) -> None:
        if i == len(measured_m2):
            found.append((len(used), err, chosen.copy()))
            return
        search(i + 1, used, chosen + [None], err)
        for names, e in options[i]:
            if not used & names:
                search(i + 1, used | names, chosen + [names], err + e)

    search(0, frozenset(), [], 0.0)
    count, err, best = max(found, key=lambda f: (f[0], -f[1]))
    if count == 0:
        return [None] * len(measured_m2)
    close = [c for n, e, c in found if n == count and e - err < AREA_AMBIGUITY]

    def label(names: frozenset[str]) -> str:
        return " + ".join(n for n in indoor if n in names)

    result: list[AreaMatch | None] = []
    for i, (names, m) in enumerate(zip(best, measured_m2)):
        if names is None:
            result.append(None)
            continue
        others = {c[i] for c in close if c[i] is not None and c[i] != names}
        match = AreaMatch([n for n in indoor if n in names], sum(areas[n] for n in names), m)
        match.alternatives = sorted(label(o) for o in others)
        result.append(match)
    return result
