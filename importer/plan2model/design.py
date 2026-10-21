"""Plik projektu: zmiany nakładane na PlanModel z automatu (materiały, dekoracje, poprawki układu).

Automat odczytuje z rzutu ściany, otwory i meble. Wygląd (deski, płytki, kolory), dekoracje, których
na rzucie nie ma, i zmiany układu (np. według wizualizacji dewelopera) zapisujemy osobno w JSON,
żeby można było ponownie uruchomić automat i dostać ten sam wynik. Tę rolę przejmie edytor 2D.

Strefy (`zones`: nazwa + poligon) opisują pokoje po podziale ściankami, tylko dla rzutu z wymiarami
(`--dimensions`); do PlanModel nie trafiają. Ścianki działowe niebędące murem dodajemy jako meble od podłogi
do sufitu: `lamele` (drewniane listwy), `scianka_szklana` (przesuwna, skrzydła ze `szklo`). Obrazek kontrolny pokazuje meble po zmianach.

Meble i otwory wskazujemy typem i przybliżonym położeniem (`near`, metry), a nie `id`, bo numeracja
zmienia się przy każdej poprawce automatu.

Format (wszystkie klucze opcjonalne):
    {
      "materials": {"dab": {"texture": "laminate_floor_02", "tileM": 1.7}, ...},
      "rooms": {"Łazienka": {"floor": "plytki", "walls": "plytki"}},
      "removeFurniture": [{"type": "stolik", "near": [1.2, -1.5]}],
      "updateFurniture": [{"type": "fotel", "near": [0, -2], "set": {"rotation": 300}}],
      "addFurniture": [{"type": "roslina", "size": [0.5, 0.5, 1.1], "position": [0, 0]}],
      "updateOpenings": [{"type": "door", "near": [0, 3.2], "set": {"door": {"leafMaterial": "czarny"}}}],
      "addOpenings": [...], "addWalls": [...], "balconies": [{"polygon": [...], "railingHeight": 1.1}]
    }
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

NEAR_M = 0.6  # tak daleko od podanego punktu może leżeć wskazany mebel lub otwór


class DesignError(Exception):
    """Błąd w pliku projektu, z komunikatem dla operatora."""


def load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise DesignError(f"Nie ma pliku projektu: {path}") from None
    except json.JSONDecodeError as e:
        raise DesignError(f"Plik projektu {path} nie jest poprawnym JSON (wiersz {e.lineno}): {e.msg}") from None


def apply(plan: dict[str, Any], design: dict[str, Any]) -> dict[str, Any]:
    """Zwraca nowy PlanModel z naniesionymi zmianami (wejście zostaje bez zmian)."""
    p = copy.deepcopy(plan)
    p["materials"] = {**p.get("materials", {}), **design.get("materials", {})}

    for name, mats in design.get("rooms", {}).items():
        rooms = [r for r in p["rooms"] if r["name"] == name]
        if not rooms:
            known = ", ".join(str(r["name"]) for r in p["rooms"])
            raise DesignError(f"Plik projektu: nie ma pomieszczenia „{name}” (są: {known}).")
        for r in rooms:
            r["materials"] = {**(r.get("materials") or {}), **mats}
        _check_materials(p, mats.values(), f"pomieszczenie „{name}”")

    for op in design.get("removeFurniture", []):
        p["furniture"].remove(_find(p["furniture"], op, "mebla", _furniture_center))
    for op in design.get("updateFurniture", []):
        _update(_find(p["furniture"], op, "mebla", _furniture_center), op.get("set", {}))
    for op in design.get("updateOpenings", []):
        _update(_find(p["openings"], op, "otworu", _opening_center), op.get("set", {}))

    for item in design.get("addFurniture", []):
        p["furniture"].append({"id": "", "rotation": 0, **_data(item)})
    for item in design.get("addOpenings", []):
        p["openings"].append({"id": "", "sill": 0.0, "height": 2.05, **_data(item)})
    for item in design.get("addWalls", []):
        p["walls"].append({"id": "", "height": p["storey"]["height"], **_data(item)})
    p["balconies"] = p.get("balconies", []) + [_data(b) for b in design.get("balconies", [])]

    for f in p["furniture"]:
        _check_materials(p, (f.get("materials") or {}).values(), f"mebel {f['type']}")
    # Nowe numery po zmianach: f1, f2…, o1…, w1…
    for prefix, items in (("f", p["furniture"]), ("o", p["openings"]), ("w", p["walls"])):
        for i, item in enumerate(items):
            item["id"] = f"{prefix}{i + 1}"
    return p


def _data(item: dict[str, Any]) -> dict[str, Any]:
    """Bez kluczy zaczynających się od „_” (komentarze w pliku projektu)."""
    return {k: v for k, v in item.items() if not k.startswith("_")}


def _furniture_center(f: dict[str, Any]) -> tuple[float, float]:
    return f["position"][0], f["position"][1]


def _opening_center(o: dict[str, Any]) -> tuple[float, float]:
    return (o["a"][0] + o["b"][0]) / 2, (o["a"][1] + o["b"][1]) / 2


def _find(items: list[dict[str, Any]], op: dict[str, Any], what: str, center) -> dict[str, Any]:
    kind, near = op.get("type"), op.get("near")
    if kind is None or near is None:
        raise DesignError(f"Plik projektu: wskazanie {what} wymaga pól „type” i „near” (jest: {op}).")
    candidates = [it for it in items if it["type"] == kind]
    if candidates:
        best = min(candidates, key=lambda it: math.dist(center(it), near))
        if math.dist(center(best), near) <= NEAR_M:
            return best
    raise DesignError(f"Plik projektu: nie znaleziono {what} typu „{kind}” w pobliżu {near} m (do {NEAR_M} m).")


def _update(item: dict[str, Any], changes: dict[str, Any]) -> None:
    """Zmiana pól; słowniki (params, materials, door) są łączone, a nie zastępowane."""
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(item.get(key), dict):
            item[key] = {**item[key], **value}
        else:
            item[key] = value


def _check_materials(plan: dict[str, Any], names, where: str) -> None:
    from_catalog = plan.get("materials", {})
    for name in names:
        if name not in from_catalog and name not in BUILTIN_MATERIALS:
            raise DesignError(f"Plik projektu: {where} używa nieznanego materiału „{name}”.")


# Materiały wbudowane w generator geometrii (studio/src/geometry/materials.ts). Plik projektu może dodawać nowe lub je nadpisywać.
BUILTIN_MATERIALS = {
    "tkanina", "poducha", "drewno", "bialy", "ceramika", "ciemny", "stal", "stal_czarna", "blat", "cien", "rama", "rama_okna",
    "skrzydlo", "szklo", "mebel", "sciana", "podloga", "abazur", "liscie", "doniczka", "lustro", "poducha_dekor",
    "koc", "lodyga", "ziemia", "obudowa", "fartuch", "dywan", "grafika",
}
