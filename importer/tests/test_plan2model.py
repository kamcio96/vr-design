from pathlib import Path

import cv2
import numpy as np
import pytest

from plan2model import ocr
from plan2model.__main__ import convert

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
needs_ocr = pytest.mark.skipif(not ocr.available(), reason="brak Tesseracta (sudo apt install tesseract-ocr tesseract-ocr-pol)")


def synthetic_plan(path: Path) -> None:
    """Prosty rzut 10 × 8 m przy 50 px/m: ściany zewnętrzne 0,4 m, działowa 0,12 m z drzwiami 0,9 m."""
    px = 50
    img = np.full((600, 700, 3), 255, np.uint8)
    x0, y0 = 100, 100  # lewy górny róg obrysu
    t = int(0.4 * px)
    black = (20, 20, 20)
    cv2.rectangle(img, (x0, y0), (x0 + 10 * px - 1, y0 + t - 1), black, -1)  # góra
    cv2.rectangle(img, (x0, y0 + 8 * px - t), (x0 + 10 * px - 1, y0 + 8 * px - 1), black, -1)  # dół
    cv2.rectangle(img, (x0, y0), (x0 + t - 1, y0 + 8 * px - 1), black, -1)  # lewa
    # prawa ściana z oknem 1,5 m
    cv2.rectangle(img, (x0 + 10 * px - t, y0), (x0 + 10 * px - 1, y0 + 3 * px), black, -1)
    cv2.rectangle(img, (x0 + 10 * px - t, y0 + int(4.5 * px)), (x0 + 10 * px - 1, y0 + 8 * px - 1), black, -1)
    # działowa w x = 4 m, drzwi 0,9 m od 5 m do 5,9 m
    xp = x0 + 4 * px
    cv2.rectangle(img, (xp, y0 + t), (xp + 5, y0 + 5 * px), black, -1)
    cv2.rectangle(img, (xp, y0 + int(5.9 * px)), (xp + 5, y0 + 8 * px - t), black, -1)
    cv2.imwrite(str(path), img)


def test_synthetic_plan_manual_scale(tmp_path):
    path = tmp_path / "plan.png"
    synthetic_plan(path)
    r = convert(path, width_m=10.0)

    w, h = r.plan["source"]["outlineSize"]
    assert w == pytest.approx(10.0, abs=0.02)
    assert h == pytest.approx(8.0, abs=0.03)

    thicknesses = sorted(wall["thickness"] for wall in r.plan["walls"])
    assert thicknesses[0] == pytest.approx(0.12, abs=0.03)  # działowa
    assert thicknesses[-1] == pytest.approx(0.4, abs=0.03)  # zewnętrzna

    # Drzwi i okno zamknięte zaślepkami → dwa pokoje w świetle ścian: 3,6 × 7,2 m i 5,48 × 7,2 m.
    areas = sorted(room["area"] for room in r.plan["rooms"])
    assert len(areas) == 2
    assert areas[0] == pytest.approx(3.6 * 7.2, rel=0.03)
    assert areas[1] == pytest.approx(5.48 * 7.2, rel=0.03)

    for wall in r.plan["walls"]:
        assert wall["height"] == 2.6


@needs_ocr
def test_fixture_test1_scale_from_ocr():
    r = convert(FIXTURES / "test1" / "test1.png")

    # Na rzucie: wymiary zewnętrzne 990 × 700 cm.
    assert r.scale.method == "ocr-outline"
    w, h = r.plan["source"]["outlineSize"]
    assert w == pytest.approx(9.9, rel=0.02)
    assert h == pytest.approx(7.0, rel=0.02)

    # Wymiary pokoi z rzutu zgadzają się z odległościami między wykrytymi ścianami.
    checks = [c for c in r.checks if not c.misread]
    assert len(checks) >= 5
    assert all(c.ok for c in checks)

    assert 20 <= len(r.plan["walls"]) <= 40
    assert 4 <= len(r.plan["rooms"]) <= 7


def test_fixture_test1_manual_scale():
    r = convert(FIXTURES / "test1" / "test1.png", width_m=9.9)
    w, h = r.plan["source"]["outlineSize"]
    assert w == pytest.approx(9.9, abs=0.001)
    assert h == pytest.approx(7.0, rel=0.02)

    # Górna ściana zewnętrzna ok. 0,4 m (najgrubszy element to blok komina, więc nie bierzemy maksimum).
    top = min(r.plan["walls"], key=lambda wall: wall["a"][1])
    assert top["thickness"] == pytest.approx(0.43, abs=0.05)


def synthetic_furnished(path: Path) -> None:
    """Pokój 5 × 4 m (50 px/m), szara podłoga, białe meble z szarym konturem jak na rzutach z katalogów."""
    px = 50
    img = np.full((400, 500, 3), 255, np.uint8)
    x0, y0, t = 100, 100, int(0.4 * px)
    x1, y1 = x0 + 5 * px, y0 + 4 * px
    cv2.rectangle(img, (x0, y0), (x1 - 1, y1 - 1), (20, 20, 20), -1)
    cv2.rectangle(img, (x0 + t, y0 + t), (x1 - t - 1, y1 - t - 1), (232, 232, 232), -1)
    line = (170, 170, 170)

    def item(ax, ay, w, d):
        a = (x0 + t + int(ax * px), y0 + t + int(ay * px))
        b = (a[0] + int(w * px) - 1, a[1] + int(d * px) - 1)
        cv2.rectangle(img, a, b, (255, 255, 255), -1)
        cv2.rectangle(img, a, b, line, 1)
        return a, b

    item(1.0, 0.0, 1.6, 2.0)  # łóżko przy górnej ścianie
    a, b = item(3.0, 0.0, 1.2, 0.6)  # szafa z krzyżykiem
    cv2.line(img, a, b, line, 1)
    cv2.line(img, (a[0], b[1]), (b[0], a[1]), line, 1)
    item(0.0, 2.6, 2.0, 0.6)  # szafka przy dolnej ścianie
    cv2.imwrite(str(path), img)


def test_synthetic_furniture(tmp_path):
    path = tmp_path / "furnished.png"
    synthetic_furnished(path)
    r = convert(path, width_m=5.0)

    items = {f["type"]: f for f in r.plan["furniture"]}
    assert set(items) == {"lozko", "szafa", "szafka"}
    assert sorted(items["lozko"]["size"][:2]) == pytest.approx([1.6, 2.0], abs=0.05)
    assert sorted(items["szafa"]["size"][:2]) == pytest.approx([0.6, 1.2], abs=0.05)
    assert sorted(items["szafka"]["size"][:2]) == pytest.approx([0.6, 2.0], abs=0.05)
    assert items["szafa"]["size"][2] == pytest.approx(2.2)


def test_fixture_test1_furniture():
    r = convert(FIXTURES / "test1" / "test1.png", width_m=9.9)
    types = [f["type"] for f in r.plan["furniture"]]
    assert 15 <= len(types) <= 35
    assert "lozko" in types and "szafa" in types and "stol" in types
    for f in r.plan["furniture"]:
        x, z = f["position"]
        assert abs(x) < 4.95 and abs(z) < 3.5  # wewnątrz obrysu budynku
        assert 0 < f["size"][2] <= 2.6


TEST2_AREAS = {"Hol": 3.88, "Pokój": 18.08, "Łazienka": 4.30, "Kuchnia": 5.48, "Balkon": 2.85}


def test_fixture_test2_walls_from_areas():
    # Szare ściany, bez wymiarów na rzucie: skala z sumy powierzchni (31,74 m² bez balkonu).
    r = convert(FIXTURES / "test2" / "test2.png", areas=TEST2_AREAS, with_furniture=False)

    assert r.scale.method == "areas-total"
    w, h = r.plan["source"]["outlineSize"]
    assert w == pytest.approx(5.9, rel=0.05)
    assert h == pytest.approx(6.65, rel=0.05)
    assert 15 <= len(r.plan["walls"]) <= 30
    assert r.plan["furniture"] == []

    # Pokój, hol i kuchnia są otwarte na siebie, osobno wychodzi tylko łazienka (prysznic przy
    # pasie z kółkami należy do łazienki, więc jej powierzchnia zgadza się z rzutem).
    rooms = sorted(r.plan["rooms"], key=lambda room: room["area"])
    assert len(rooms) == 2
    assert rooms[0]["area"] == pytest.approx(4.30, rel=0.03)
    assert rooms[0]["name"] == "Łazienka"
    assert sum(room["area"] for room in rooms) == pytest.approx(31.74, rel=0.01)


def test_fixture_test2_openings():
    r = convert(FIXTURES / "test2" / "test2.png", areas=TEST2_AREAS, with_furniture=False)
    doors = [o for o in r.plan["openings"] if o["type"] == "door"]
    windows = [o for o in r.plan["openings"] if o["type"] == "window"]
    assert len(doors) == 3
    assert len(windows) >= 1

    def width(o):
        return ((o["b"][0] - o["a"][0]) ** 2 + (o["b"][1] - o["a"][1]) ** 2) ** 0.5

    # Łazienka: drzwi w pionowej ściance działowej, zawias na dole (b), otwierane do holu (+X).
    bath = next(o for o in doors if o["a"][0] == o["b"][0])
    assert width(bath) == pytest.approx(0.86, abs=0.08)
    assert bath["door"]["hinge"] == "b" and bath["door"]["swing"] == -1
    # Wejście w dolnej ścianie, otwierane do środka (w górę rzutu, −Z).
    entry = max(doors, key=lambda o: o["a"][1])
    assert width(entry) == pytest.approx(1.0, abs=0.1)
    assert entry["door"]["swing"] == -1
    # Balkon w górnej ścianie, otwierany do pokoju (+Z), obok wąskie stałe okno.
    balcony = min((o for o in doors if o is not bath), key=lambda o: o["a"][1])
    assert balcony["door"]["swing"] == 1
    assert all(o["height"] == 2.05 for o in doors)


def test_fixture_test2_furniture():
    r = convert(FIXTURES / "test2" / "test2.png", areas=TEST2_AREAS)
    items = r.plan["furniture"]
    counts = {}
    for f in items:
        counts[f["type"]] = counts.get(f["type"], 0) + 1
    assert counts.get("kanapa") == 2
    assert all(f["params"]["seats"] == 3 for f in items if f["type"] == "kanapa")
    for kind in ("fotel", "stol_okragly", "stolik", "tv", "plyta", "zlew", "prysznic", "wc", "umywalka", "pralka"):
        assert counts.get(kind) == 1, kind
    assert counts.get("szafa") == 2
    assert counts.get("blat") == 3  # blat w kształcie U jako trzy prostokąty

    by_type = {f["type"]: f for f in items}
    # Fotel stoi skosem, okrągły stół ma ok. 0,65 m średnicy.
    assert by_type["fotel"]["rotation"] % 90 > 10
    assert by_type["stol_okragly"]["size"][0] == pytest.approx(0.65, abs=0.08)
    # Przód od ściany: TV przy ścianie kuchni patrzy w górę rzutu (180°), WC tyłem do dolnej ściany.
    assert by_type["tv"]["rotation"] == 180
    assert by_type["wc"]["rotation"] == 180
    assert by_type["plyta"]["rotation"] == 0
    # Żaden mebel w miejscu ramek z numerami pomieszczeń (np. „18.2” ok. (−0,46; −1,62) m).
    assert not any(abs(f["position"][0] + 0.46) < 0.2 and abs(f["position"][1] + 1.62) < 0.2 for f in items)


TEST3_AREAS = {
    "Wiatrołap 1": 5.9, "Przedpokój 2": 13.2, "Salon 3": 44.9, "Kuchnia 4": 9.0, "Spiżarnia 5": 1.7,
    "Łazienka 6": 5.1, "Łazienka 7": 6.8, "Pokój 8": 18.1, "Pokój 9": 11.7, "Pokój 10": 10.6,
    "Kotłownia 11": 10.6, "Garaż 12": 29.2,
}


def test_fixture_test3_rooms_and_furniture():
    # Dom z szarymi ścianami, ścianą skośną z oknami między słupkami, bramą garażu i drzwiami przesuwnymi
    # (łazienka 7 – pokój 8); podłoga bardzo jasna (246), meble białe, mała rozdzielczość (ok. 3 cm/px).
    r = convert(FIXTURES / "test3" / "test3.png", areas=TEST3_AREAS)
    rooms = r.plan["rooms"]
    # Wszystkie pomieszczenia osobno, tylko kuchnia otwarta na przedpokój: 11 obszarów.
    assert len(rooms) == 11
    assert sum(room["area"] for room in rooms) == pytest.approx(166.8, rel=0.03)
    assert any(room["area"] == pytest.approx(29.2, rel=0.1) for room in rooms)  # garaż za bramą

    counts = {}
    for f in r.plan["furniture"]:
        counts[f["type"]] = counts.get(f["type"], 0) + 1
    assert counts.get("samochod") == 2
    assert counts.get("lozko") == 3  # podwójne w 8, pojedyncze z poduszką w 9 i 10
    assert counts.get("biurko") == 2
    assert counts.get("krzeslo") == 8  # 6 przy stole w jadalni i 2 przy biurkach
    assert counts.get("wc") == 2 and counts.get("umywalka") == 2
    assert counts.get("wanna") == 1 and counts.get("prysznic") == 1
    assert counts.get("plyta") == 1 and counts.get("zlew") == 1  # blat w kształcie V wzdłuż ściany skośnej
    assert counts.get("kanapa") == 2 and counts.get("fotel") == 1
    assert counts.get("tv") is None  # ramka „C.O.” w kotłowni to nie telewizor
    windows = [o for o in r.plan["openings"] if o["type"] == "window"]
    assert len(windows) >= 8  # okna w ścianach zewnętrznych poza prostokątem obrysu


def synthetic_symbols(path: Path) -> None:
    """Pokój 6 × 5 m (50 px/m) z szarą podłogą: okrągły stół, kanapa z 3 poduchami przy ścianie, drzwi z łukiem."""
    px = 50
    x0, y0, t = 100, 100, int(0.3 * px)
    x1, y1 = x0 + 6 * px, y0 + 5 * px
    img = np.full((y1 + 100, x1 + 100, 3), 255, np.uint8)
    dark, floor, line = (60, 60, 60), (222, 222, 222), (120, 120, 120)
    cv2.rectangle(img, (x0, y0), (x1 - 1, y1 - 1), dark, -1)
    cv2.rectangle(img, (x0 + t, y0 + t), (x1 - t - 1, y1 - t - 1), floor, -1)
    # Drzwi 0,9 m w dolnej ścianie, zawias po lewej, otwierane do środka.
    dx0, dx1 = x0 + 2 * px, x0 + 2 * px + int(0.9 * px)
    cv2.rectangle(img, (dx0, y1 - t), (dx1 - 1, y1 - 1), floor, -1)
    r = dx1 - dx0
    cv2.ellipse(img, (dx0, y1 - t), (r, r), 0, 270, 360, line, 1)
    cv2.line(img, (dx0, y1 - t), (dx0, y1 - t - r), line, 1)
    # Okrągły stół ⌀ 0,9 m na środku.
    cv2.circle(img, (x0 + 4 * px, y0 + int(2.2 * px)), int(0.45 * px), (255, 255, 255), -1)
    cv2.circle(img, (x0 + 4 * px, y0 + int(2.2 * px)), int(0.45 * px), line, 1)
    # Kanapa 2,1 × 0,9 m przy górnej ścianie: oparcie przy ścianie, trzy poduchy siedziska.
    sx0, sy0 = x0 + t + int(0.3 * px), y0 + t
    sw, sd = int(2.1 * px), int(0.9 * px)
    cv2.rectangle(img, (sx0, sy0), (sx0 + sw, sy0 + sd), (255, 255, 255), -1)
    cv2.rectangle(img, (sx0, sy0), (sx0 + sw, sy0 + sd), line, 1)
    back = int(0.2 * px)
    cv2.line(img, (sx0, sy0 + back), (sx0 + sw, sy0 + back), line, 1)
    for i in range(1, 3):
        x = sx0 + i * sw // 3
        cv2.line(img, (x, sy0 + back), (x, sy0 + sd), line, 1)
    cv2.imwrite(str(path), img)


def test_synthetic_symbols_and_door(tmp_path):
    path = tmp_path / "symbols.png"
    synthetic_symbols(path)
    r = convert(path, width_m=6.0)

    types = {f["type"]: f for f in r.plan["furniture"]}
    assert "stol_okragly" in types
    assert types["stol_okragly"]["size"][0] == pytest.approx(0.9, abs=0.08)
    assert "kanapa" in types
    assert types["kanapa"]["params"]["seats"] == 3
    assert types["kanapa"]["rotation"] == 0  # oparcie przy górnej ścianie, przód w dół rzutu

    doors = [o for o in r.plan["openings"] if o["type"] == "door"]
    assert len(doors) == 1
    d = doors[0]
    assert abs(d["b"][0] - d["a"][0]) == pytest.approx(0.9, abs=0.06)
    assert d["door"]["hinge"] == "a" and d["door"]["swing"] == -1  # zawias po lewej, do środka (−Z)


def test_area_matching_open_plan():
    from plan2model.scale import match_areas

    a, b = match_areas([27.4, 4.3], {"Pokój": 18.0, "Kuchnia": 9.4, "Łazienka": 4.3, "Balkon": 3.0})
    assert a.name == "Pokój + Kuchnia" and not a.alternatives
    assert b.name == "Łazienka" and not b.alternatives


def test_design_test2_3():
    from plan2model import design

    r = convert(FIXTURES / "test2" / "test2.png", areas=TEST2_AREAS)
    plan = design.apply(r.plan, design.load(FIXTURES / "test2" / "test2_3.design.json"))
    assert plan["schemaVersion"] == 4

    bath = next(room for room in plan["rooms"] if room["name"] == "Łazienka")
    assert bath["materials"] == {"floor": "plytki", "walls": "plytki"}
    assert plan["materials"]["podloga"]["texture"] == "laminate_floor_02"

    types = [f["type"] for f in plan["furniture"]]
    assert "stolik" not in types and "prysznic" not in types
    for kind in ("kabina", "krzeslo", "lampa_wiszaca", "dywan", "obraz", "roslina", "zabudowa"):
        assert kind in types, kind
    assert types.count("obraz") == 4 and types.count("krzeslo") == 2
    wc = next(f for f in plan["furniture"] if f["type"] == "wc")
    assert wc["params"]["wallHung"] and wc["materials"] == {"obudowa": "plytki"}
    assert all(not any(k.startswith("_") for k in f) for f in plan["furniture"])  # bez komentarzy
    assert len({f["id"] for f in plan["furniture"]}) == len(plan["furniture"])

    assert any(o["type"] == "folding" for o in plan["openings"])
    entry = max((o for o in plan["openings"] if o["type"] == "door"), key=lambda o: o["a"][1])
    assert entry["door"]["leafMaterial"] == "czarny"

    (balcony,) = plan["balconies"]
    xs = [x for x, _ in balcony["polygon"]]
    zs = [z for _, z in balcony["polygon"]]
    assert (max(xs) - min(xs)) * (max(zs) - min(zs)) == pytest.approx(2.85, rel=0.03)


def test_design_test2_4_1_debug_shows_changes():
    from plan2model import design
    from plan2model.__main__ import DEBUG_COLORS, draw_debug, plan_furniture_px

    r = convert(FIXTURES / "test2" / "test2.png", areas=TEST2_AREAS)
    r.plan = design.apply(r.plan, design.load(FIXTURES / "test2" / "test2_4_1.design.json"))
    types = [f["type"] for f in r.plan["furniture"]]
    for kind in ("lamele", "scianka_szklana", "lozko", "biurko", "krzeslo"):
        assert kind in types, kind
    assert "fotel" not in types and "stolik" not in types and types.count("kanapa") == 1 and types.count("szafa") == 3

    # Meble z planu wracają w piksele tam, skąd automat je wziął (te, których plik projektu nie ruszał).
    by_type = {f.type: f for f in plan_furniture_px(r)}
    assert by_type["umywalka"].cx == pytest.approx(next(f.cx for f in r.furniture if f.type == "umywalka"), abs=0.5)

    out = draw_debug(cv2.imread(str(FIXTURES / "test2" / "test2.png")), r, from_plan=True)
    glass = by_type["scianka_szklana"]
    assert tuple(out[int(glass.cy), int(glass.cx)]) == DEBUG_COLORS["scianka_szklana"]


def test_dimensions_test2_4_1():
    from plan2model import design, dimensions
    from plan2model.__main__ import added_furniture, draw_debug

    spec = design.load(FIXTURES / "test2" / "test2_4_1.design.json")
    r = convert(FIXTURES / "test2" / "test2.png", areas=TEST2_AREAS)
    r.plan = design.apply(r.plan, spec)
    assert "zones" not in r.plan  # strefy tylko do rysunku, schemat PlanModel bez zmian

    bedroom, salon = spec["zones"]
    assert dimensions.area(bedroom["polygon"]) == pytest.approx(8.01, abs=0.01)
    assert dimensions._span(salon["polygon"], -2.8, axis=0) == pytest.approx((-0.233, 2.716))  # od lameli
    assert {f["type"] for f in added_furniture(r)} >= {"lamele", "scianka_szklana", "lozko", "biurko"}

    dims = dimensions.compute(r.plan, added_furniture(r), spec["zones"])
    texts = {d["kind"]: set() for d in dims["lines"]}
    for d in dims["lines"]:
        texts[d["kind"]].add(d["text"])
    assert texts["outline"] == {"583", "661"}
    assert {"245", "199", "174"} <= texts["distance"]  # osie lameli i szklanej ściany od ścian zewnętrznych
    assert {"Sypialnia", "8,01 m2"} <= {lb["text"] for lb in dims["labels"]}
    # Gabaryt łóżka przed jego frontem (w 3D na podłodze, nie pod łóżkiem).
    bed = next(f for f in r.plan["furniture"] if f["type"] == "lozko")
    at = next(lb["at"] for lb in dims["labels"] if lb["text"] == "110x196")
    assert at[1] > bed["position"][1] + bed["size"][1] / 2

    img = cv2.imread(str(FIXTURES / "test2" / "test2.png"))
    out = dimensions.draw(draw_debug(img, r, from_plan=True), dims, r.outline, r.scale.meters_per_px, spec["zones"])
    h, w = img.shape[:2]
    assert out.shape[:2] == (h * dimensions.SCALE + 2 * dimensions.MARGIN, w * dimensions.SCALE + 2 * dimensions.MARGIN)
    # linia wymiarowa szerokości obrysu w białym marginesie pod budynkiem
    row = out[-dimensions.MARGIN // 2 - 30 : -10, dimensions.MARGIN : -dimensions.MARGIN]
    assert (row.max(axis=2) < 100).any()


def test_design_errors_are_readable():
    from plan2model import design

    r = convert(FIXTURES / "test2" / "test2.png", areas=TEST2_AREAS, with_furniture=False)
    with pytest.raises(design.DesignError, match="nie ma pomieszczenia „Sypialnia”"):
        design.apply(r.plan, {"rooms": {"Sypialnia": {"floor": "podloga"}}})
    with pytest.raises(design.DesignError, match="nie znaleziono mebla typu „kanapa”"):
        design.apply(r.plan, {"removeFurniture": [{"type": "kanapa", "near": [0, 0]}]})
    with pytest.raises(design.DesignError, match="nieznanego materiału „marmur”"):
        design.apply(r.plan, {"rooms": {"Łazienka": {"floor": "marmur"}}})
