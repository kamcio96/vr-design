"""plan2model: rzut PNG/JPG → PlanModel JSON + obrazek kontrolny.

Użycie:
    uv run plan2model ../fixtures/test1/test1.png
    uv run plan2model rzut.png --width-m 9.9      # skala ręcznie, gdy OCR zawiedzie
    uv run plan2model rzut.png --walls-only --area Pokój=18.08 --area Łazienka=4.30   # skala z powierzchni
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from . import design, dimensions, furniture, ocr, openings, planmodel, rooms, scale, walls


@dataclass
class Result:
    plan: dict[str, Any]
    walls: list[walls.WallPx]
    rooms: list[rooms.RoomPx]
    outline: tuple[int, int, int, int]
    scale: scale.Scale
    tokens: list[ocr.Token] = field(default_factory=list)
    checks: list[scale.Check] = field(default_factory=list)
    patches: list[tuple[int, int, int, int]] = field(default_factory=list)
    furniture: list[furniture.FurniturePx] = field(default_factory=list)
    openings: list[openings.OpeningPx] = field(default_factory=list)
    areas: dict[str, float] = field(default_factory=dict)
    area_matches: list[scale.AreaMatch | None] = field(default_factory=list)


class ImportError_(Exception):
    """Błąd z komunikatem dla operatora."""


def convert(
    image_path: Path,
    width_m: float | None = None,
    meters_per_px: float | None = None,
    height: float = planmodel.DEFAULT_HEIGHT_M,
    areas: dict[str, float] | None = None,
    with_furniture: bool = True,
) -> Result:
    img = cv2.imread(str(image_path))
    if img is None:
        raise ImportError_(f"Nie można wczytać obrazu: {image_path}")

    raw = walls.wall_mask(img)
    found = walls.extract_walls(raw)
    if not found:
        raise ImportError_("Nie znaleziono żadnych ścian (ciemnych, grubych linii) na rzucie.")
    box = walls.outline(found)
    drawing = rooms.drawing(img, raw)
    width_px, height_px = box[2] - box[0], box[3] - box[1]

    tokens = ocr.read_tokens(img) if ocr.available() else []
    if meters_per_px:
        sc = scale.Scale(meters_per_px, "manual-scale")
    elif width_m:
        sc = scale.Scale(width_m / width_px, "manual-width")
    elif areas:
        sc = scale.from_areas(img.shape[:2], found, box, areas, drawing)
        if sc is None:
            raise ImportError_(
                "Nie udało się policzyć skali z powierzchni: brak zamkniętych pomieszczeń wewnątrz ścian.\n"
                "Podaj skalę ręcznie: --width-m <zewnętrzna szerokość budynku w metrach>"
            )
    else:
        if not ocr.available():
            raise ImportError_(
                "Brak programu Tesseract (odczyt tekstu). Zainstaluj: "
                "sudo apt install tesseract-ocr tesseract-ocr-pol\n"
                "albo podaj skalę ręcznie: --width-m <zewnętrzna szerokość budynku w metrach>"
            )
        sc = scale.from_outline(tokens, width_px, height_px)
        if sc is None:
            raise ImportError_(
                "Nie udało się odczytać wymiarów zewnętrznych budynku z rzutu.\n"
                "Podaj skalę ręcznie: --width-m <zewnętrzna szerokość budynku w metrach>"
            )

    closed, patches = rooms.closed_wall_mask(img.shape[:2], found, sc.meters_per_px, drawing)
    strips = rooms.narrow_strips(closed, box, sc.meters_per_px)
    found += strips
    found_rooms, closets = rooms.find_rooms(closed, box, sc.meters_per_px)
    checks = scale.check_dimensions(tokens, closed, box, sc)
    items = furniture.detect(img, found, found_rooms, closets, sc.meters_per_px) if with_furniture else []
    lines = furniture._thin_edges(furniture._without_color(img)) > 0
    holes = openings.detect(patches, strips, box, lines, sc.meters_per_px, rooms.outside(closed, box))
    plan = planmodel.build(image_path.name, found, found_rooms, items, box, sc, height, holes)
    matches: list[scale.AreaMatch | None] = []
    if areas:
        matches = scale.match_areas([room["area"] for room in plan["rooms"]], areas)
        for room, m in zip(plan["rooms"], matches):
            if m and not m.alternatives:
                room["name"], room["areaOnPlan"] = m.name, round(m.area_on_plan, 2)
    return Result(plan, found, found_rooms, box, sc, tokens, checks, patches, items, holes, areas or {}, matches)


def plan_furniture_px(r: Result) -> list[furniture.FurniturePx]:
    """Meble z r.plan (metry) z powrotem w pikselach rzutu – np. po zmianach z pliku projektu."""
    s = r.scale.meters_per_px
    px = planmodel.to_px(r.outline, s)
    return [
        furniture.FurniturePx(
            *px(*f["position"]), f["size"][0] / s, f["size"][1] / s,
            f["rotation"], f["type"], f["size"][2], f.get("params") or {},
        )
        for f in r.plan["furniture"]
    ]


def _same(a: furniture.FurniturePx, b: furniture.FurniturePx) -> bool:
    return a.type == b.type and abs(a.cx - b.cx) + abs(a.cy - b.cy) < 1


def added_furniture(r: Result) -> list[dict[str, Any]]:
    """Meble z r.plan, których nie wykrył automat (dodane albo przesunięte przez plik projektu)."""
    return [f for f, p in zip(r.plan["furniture"], plan_furniture_px(r)) if not any(_same(p, a) for a in r.furniture)]


# Kolory w obrazku kontrolnym (BGR): ścianki działowe z pliku projektu odróżnione od mebli.
DEBUG_COLORS = {"scianka_szklana": (230, 190, 60), "lamele": (40, 110, 170)}


def draw_debug(img: np.ndarray, r: Result, from_plan: bool = False) -> np.ndarray:
    """Obrazek kontrolny: ściany (niebieskie), zamknięte otwory (pomarańczowe), pokoje i wymiary.

    `from_plan`: meble rysowane z r.plan (po zmianach z pliku projektu), a nie z wyniku automatu.
    """
    out = img.copy()
    overlay = img.copy()
    for w in r.walls:
        cv2.rectangle(overlay, (w.x0, w.y0), (w.x1 - 1, w.y1 - 1), (230, 120, 0), -1)
    for x0, y0, x1, y1 in r.patches:
        cv2.rectangle(overlay, (x0, y0), (x1 - 1, y1 - 1), (0, 140, 255), -1)
    out = cv2.addWeighted(overlay, 0.6, out, 0.4, 0)
    shown = r.furniture
    if from_plan:
        shown = plan_furniture_px(r)
        # Meble usunięte przez plik projektu zamalowane kolorem podłogi, żeby symbol z rzutu nie mylił.
        for f in r.furniture:
            if not any(_same(k, f) for k in shown):
                pts = [f.corners().round().astype(np.int32).reshape(-1, 1, 2)]
                cv2.fillPoly(out, pts, (222, 222, 222))
                cv2.polylines(out, pts, True, (222, 222, 222), 3)
        shown = sorted(shown, key=lambda f: f.type in DEBUG_COLORS)  # ścianki na wierzchu
    s = r.scale.meters_per_px
    for room, data in zip(r.rooms, r.plan["rooms"]):
        cv2.polylines(out, [room.contour.reshape(-1, 1, 2)], True, (0, 170, 0), 2)
        x0, y0, x1, y1 = room.bbox
        label = f"{data['area']:.1f} m2"
        if data["name"]:
            label = f"{data['name']} {label}"
        cv2.putText(out, label, ((x0 + x1) // 2 - 25, (y0 + y1) // 2 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 120, 0), 1)
    for f in shown:
        pts = f.corners().round().astype(np.int32)
        color = DEBUG_COLORS.get(f.type)
        if color:
            cv2.fillPoly(out, [pts.reshape(-1, 1, 2)], color)
            continue
        cv2.polylines(out, [pts.reshape(-1, 1, 2)], True, (200, 0, 200), 1)
        fx, fy = f.front()
        tip = (int(f.cx + fx * f.d * 0.5), int(f.cy + fy * f.d * 0.5))
        cv2.arrowedLine(out, (int(f.cx), int(f.cy)), tip, (200, 0, 200), 1, tipLength=0.4)
        x0, y0 = pts.min(axis=0)
        cv2.putText(out, f.type, (int(x0) + 1, int(y0) + 9), cv2.FONT_HERSHEY_PLAIN, 0.7, (120, 0, 120), 1)
    for o in r.openings:
        a = (int(o.a[0]), int(o.a[1]))
        b = (int(o.b[0]), int(o.b[1]))
        cv2.line(out, a, b, (160, 0, 120) if o.type == "door" else (255, 170, 0), 3)
        if o.type == "door":
            cv2.polylines(out, [np.array(openings.arc_points(o), np.int32).reshape(-1, 1, 2)], False, (160, 0, 120), 1)
    for c in r.checks:
        color = (0, 170, 0) if c.ok else (150, 150, 150) if c.misread else (0, 0, 230)
        cv2.circle(out, (int(c.token.x), int(c.token.y)), 14, color, 2)
    for t in (r.scale.width_token, r.scale.height_token):
        if t:
            cv2.circle(out, (int(t.x), int(t.y)), 18, (200, 0, 200), 2)
    header = f"skala {s * 100:.3f} cm/px ({r.scale.method}), obrys {r.plan['source']['outlineSize'][0]:.2f} x {r.plan['source']['outlineSize'][1]:.2f} m"
    cv2.putText(out, header, (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    return out


def report(r: Result) -> str:
    s = r.scale
    w, h = r.plan["source"]["outlineSize"]
    lines = [f"Skala: {s.meters_per_px * 100:.3f} cm na piksel (metoda: {s.method})"]
    if s.width_token and s.height_token:
        lines.append(f"  z wymiarów zewnętrznych na rzucie: {s.width_token.text} × {s.height_token.text}")
    if s.method == "areas-total":
        indoor = {n: a for n, a in r.areas.items() if not scale.is_outdoor(n)}
        lines.append(f"  z sumy powierzchni: {sum(indoor.values()):.2f} m² ({', '.join(indoor)})")
        outdoor = [n for n in r.areas if scale.is_outdoor(n)]
        if outdoor:
            lines.append(f"  pominięte (poza ścianami): {', '.join(outdoor)}")
    lines.append(f"Obrys budynku: {w:.2f} × {h:.2f} m")
    doors = sum(o.type == "door" for o in r.openings)
    lines.append(
        f"Ściany: {len(r.walls)}, pomieszczenia: {len(r.rooms)}, drzwi: {doors}, okna: {len(r.openings) - doors}, meble: {len(r.furniture)}"
    )
    if r.furniture:
        counts: dict[str, int] = {}
        for f in r.furniture:
            counts[f.type] = counts.get(f.type, 0) + 1
        lines.append("  " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
    if r.areas:
        lines.append("Pomieszczenia (zmierzone / z rzutu):")
        for room, m in zip(r.plan["rooms"], r.area_matches):
            if m and m.alternatives:
                options = " albo ".join([m.name, *m.alternatives])
                lines.append(f"  niepewne ({options}): {m.measured_m2:.2f} m², nazwa do uzupełnienia w edytorze")
            elif m:
                lines.append(f"  {m.name}: {m.measured_m2:.2f} / {m.area_on_plan:.2f} m² ({m.error:+.1%})")
            else:
                lines.append(f"  bez dopasowania: {room['area']:.2f} m²")
    checks = [c for c in r.checks if not c.misread]
    if checks:
        ok = sum(c.ok for c in checks)
        lines.append(f"Kontrola wymiarami pokoi: {ok} z {len(checks)} zgodnych (±{scale.CHECK_TOLERANCE:.0%})")
        for c in sorted(checks, key=lambda c: -abs(c.error)):
            mark = "ok " if c.ok else "ŹLE"
            lines.append(f"  {mark} na rzucie {c.token.meters:.2f} m, zmierzone {c.measured_m:.2f} m ({c.error:+.1%})")
        misread = [c.token.text for c in r.checks if c.misread]
        if misread:
            lines.append(f"  pominięte pomyłki odczytu: {', '.join(misread)}")
    elif not r.tokens:
        lines.append("Kontrola wymiarami pokoi: pominięta (brak odczytu tekstu)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="plan2model", description="Rzut PNG/JPG → PlanModel JSON (ściany w metrach).")
    p.add_argument("image", type=Path, help="plik rzutu PNG/JPG")
    p.add_argument("-o", "--output", type=Path, help="plik wynikowy JSON (domyślnie obok obrazu)")
    p.add_argument("--width-m", type=float, help="zewnętrzna szerokość budynku w metrach (skala ręczna)")
    p.add_argument("--scale", type=float, help="skala ręczna w metrach na piksel")
    p.add_argument("--height", type=float, default=planmodel.DEFAULT_HEIGHT_M, help="wysokość ścian w metrach")
    p.add_argument(
        "--area",
        action="append",
        default=[],
        metavar="NAZWA=M2",
        help="powierzchnia pomieszczenia z rzutu, np. --area Pokój=18.08 (wiele razy); skala z ich sumy",
    )
    p.add_argument("--walls-only", action="store_true", help="bez wykrywania mebli (same ściany i pomieszczenia)")
    p.add_argument(
        "--design", type=Path, help="plik projektu JSON: materiały, dekoracje i poprawki nakładane na wynik automatu"
    )
    p.add_argument(
        "--dimensions", action="store_true",
        help="dodatkowo *_wymiary.png: rzut powiększony 3× z wymiarami (obrys, strefy i meble z pliku projektu)",
    )
    p.add_argument(
        "--floor-dimensions", action="store_true",
        help="wymiary (jak przy --dimensions) zapisane w PlanModel jako annotations – viewer rysuje je na podłodze",
    )
    args = p.parse_args(argv)

    areas: dict[str, float] = {}
    for item in args.area:
        name, sep, value = item.rpartition("=")
        try:
            areas[name.strip()] = float(value.replace(",", "."))
        except ValueError:
            sep = ""
        if not sep or not name.strip():
            p.error(f"--area {item!r}: oczekiwano NAZWA=M2, np. Pokój=18.08")

    try:
        r = convert(args.image, args.width_m, args.scale, args.height, areas, not args.walls_only)
    except ImportError_ as e:
        print(f"Błąd: {e}", file=sys.stderr)
        return 1

    spec: dict[str, Any] = {}
    if args.design:
        try:
            spec = design.load(args.design)
            r.plan = design.apply(r.plan, spec)
        except design.DesignError as e:
            print(f"Błąd: {e}", file=sys.stderr)
            return 1

    dims = None
    if args.dimensions or args.floor_dimensions:
        dims = dimensions.compute(r.plan, added_furniture(r), spec.get("zones"))
    if args.floor_dimensions:
        r.plan["annotations"] = dims

    out = args.output or args.image.with_suffix(".json")
    out.write_text(json.dumps(r.plan, ensure_ascii=False, indent=1), encoding="utf-8")
    debug_path = out.with_name(out.stem + "_debug.png")
    debug_img = draw_debug(cv2.imread(str(args.image)), r, from_plan=bool(args.design))
    cv2.imwrite(str(debug_path), debug_img)
    if args.dimensions:
        dims_path = out.with_name(out.stem + "_wymiary.png")
        cv2.imwrite(
            str(dims_path), dimensions.draw(debug_img, dims, r.outline, r.scale.meters_per_px, spec.get("zones"))
        )
    print(report(r))
    if args.design:
        print(
            f"Plik projektu {args.design.name}: po zmianach {len(r.plan['furniture'])} mebli i dekoracji, "
            f"{len(r.plan['openings'])} otworów, {len(r.plan['balconies'])} balkon(y), "
            f"{len(r.plan['materials'])} materiałów (obrazek kontrolny pokazuje meble po zmianach; "
            "materiały, otwory i balkony tylko w modelu)"
        )
    print(f"Zapisano: {out}\nPodgląd kontrolny: {debug_path}")
    if args.dimensions:
        print(f"Rzut z wymiarami: {dims_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
