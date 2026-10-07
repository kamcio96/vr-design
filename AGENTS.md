# AGENTS.md

Instrukcje dla agentów AI (Claude Code, Codex, Cursor itp.) pracujących w tym repozytorium.

## Cel projektu i scenariusz użycia

Wizualizacja VR domów i mieszkań na podstawie ich rzutów, pokazywana **na miejscu, w skali 1:1**:

- Operator (właściciel firmy, jedna osoba) przygotowuje model przed wizytą, przyjeżdża do klienta z własnym sprzętem i prowadzi spacer.
- Klient **fizycznie chodzi** po pustej działce (dom), pustym mieszkaniu albo zastępczo po sali lub podwórku. Nie ma teleportu, liczy się prawdziwy ruch.
- **Dwie osoby w goglach jednocześnie** we wspólnej przestrzeni, widzą się nawzajem (awatary).
- **Wszystkim steruje operator z tabletu lub telefonu**: zmiany w modelu, kalibracja, przełączanie VR/MR, bezpieczeństwo. Klient tylko chodzi i ogląda.
- Właściciel nie programuje. **Cały kod powstaje z pomocą AI**, więc preferowane są rozwiązania w pełni tekstowe (kod i konfiguracja w plikach), bez ręcznej pracy w edytorach graficznych.

> Stan: repozytorium jest na etapie startowym. Kod jeszcze nie istnieje. Wybór technologii dla aplikacji na gogle czeka na wynik testu terenowego (patrz niżej).

## Zakres funkcjonalny

- **Wejście**: przede wszystkim PNG/JPG z publicznych stron z projektami domów. Dla projektów indywidualnych PDF. DXF/IFC od projektanta zdarzają się rzadko.
- **Automat PNG → model**:
  - ściany, drzwi, okna,
  - pomieszczenia z nazwami i powierzchniami (OCR),
  - proste bryły mebli (szafki, kanapa, TV): rozpoznawane z symboli na rzucie, a jeśli ich nie ma, domyślne wyposażenie według typu pomieszczenia.
- **Korekta**: edytor 2D w przeglądarce na laptopie, przed wizytą. Na miejscu tylko drobne poprawki. Cel: **≤ 1 h przygotowania** jednego projektu, wynik dopracowany.
- **Zakres budynku**: jedna kondygnacja, bez schodów. **Skosy tylko wtedy, gdy projekt jasno je opisuje** (typ dachu, kąt nachylenia, wysokość ścianki kolankowej, wpisywane ręcznie).
- **Na miejscu**:
  - kalibracja punktami kontrolerem i ręczna korekta (przesunięcie/obrót),
  - przełącznik pełne VR ↔ MR (passthrough),
  - zmiany na żywo: kolory i materiały (głównie ścian) oraz **przesuwanie drzwi i ścian** (np. pokój większy o 15 cm).
- **Bezpieczeństwo**: model staje się przezroczysty i prześwituje rzeczywistość (fade do passthrough) przy szybkim ruchu, przy brzegu skalibrowanego obszaru i na komendę operatora („pokaż rzeczywistość wszystkim”).
- **Oświetlenie**: w MVP neutralne, liczone na bieżąco. W etapie 2 słońce według kierunków świata, pory dnia i roku.

## Architektura (docelowa)

```
PNG/PDF ──automat──> PlanModel JSON ──edytor 2D──> PlanModel (poprawiony)
                     (laptop, przed wizytą)                │
                                                           ▼
                         laptop-serwer w LAN (offline, własny router)
                          │  pliki PlanModel, aplikacja, synchronizacja (WebSocket)
              ┌───────────┼──────────────┐
              ▼           ▼              ▼
          gogle A      gogle B     panel operatora (tablet/telefon)
     (geometria budowana z PlanModel na żywo)
```

1. **Automat importu**: Python + OpenCV + OCR, uruchamiany na laptopie przed wizytą. Każdy format wejściowy ma osobny importer, a wszystkie produkują wyłącznie `PlanModel`.
2. **`PlanModel`**: jedyne źródło prawdy o budynku. Zawiera:
   - kondygnację,
   - ściany (oś jako odcinek + grubość + wysokość),
   - otwory (pozycja na ścianie, szerokość, wysokość, parapet),
   - pomieszczenia (poligon, nazwa, powierzchnia, materiały),
   - meble (typ, gabaryt, pozycja, obrót),
   - opcjonalny dach/skosy,
   - grupy materiałów z wariantami.

   Schemat wersjonowany, a zmiany schematu wymagają migracji.
3. **Edytor 2D** (web): poprawki wyniku automatu, skali, otworów i mebli. Operuje na `PlanModel`.
4. **Generator geometrii działa w goglach**: buduje meshe z `PlanModel` na bieżąco. To wymóg, bo przesunięcie ściany lub drzwi na miejscu musi od razu zmienić model 3D. Gotowy, „zamrożony” glTF wystarcza tylko dla mebli i assetów.
5. **Serwer w LAN** (laptop): serwuje aplikację i modele, synchronizuje stan między goglami i panelem operatora. Zmiana z panelu to zmiana `PlanModel`, rozsyłana do obu gogli.
6. **Panel operatora** (web na tablecie/telefonie):
   - zmiany materiałów i układu,
   - kalibracja,
   - VR/MR,
   - mapa z góry z pozycjami obu osób,
   - przycisk bezpieczeństwa.

## Wybór technologii (otwarte do testu terenowego)

- **Preferowany: WebXR** (TypeScript + Vite + Three.js) na Quest Browser, instalowany jako PWA działająca offline. Cały stos jest tekstowy, co pasuje do pracy wyłącznie z AI. Wymaga sprawdzenia:
  - eksperymentalnej przestrzeni `unbounded` w `immersive-ar` (chodzenie bez granicy),
  - kolokacji dwóch gogli (eksperymentalne Shared Spaces lub własne dopasowanie każdego z gogli do tych samych punktów).
- **Zapas: Unity + Meta XR SDK** (boundaryless i wspólne kotwice są tam oficjalnie wspierane). Minusem jest konieczność pracy w edytorze graficznym. Ewentualnie Godot + OpenXR, które jest bliższe stosowi tekstowemu.
- Niezależnie od wyniku: automat w Pythonie, edytor 2D i panel operatora jako aplikacje web, `PlanModel` w JSON.

## Ograniczenia sprzętu (Quest 3/3S)

- W pełnym VR granica bezpieczeństwa jest zawsze aktywna, maksymalnie **15 × 15 m**. Chodzenie bez granicy jest możliwe tylko w trybie MR (passthrough) albo po wyłączeniu „Physical Space Features” w trybie deweloperskim.
- Według forów (niepotwierdzone oficjalnie) istnieje limit ok. **20 m od punktu startu**. Kalibrację i start sesji robić **blisko środka domu**, nie w narożniku.
- Model przesuwa się względem terenu (dryf) na dużych obszarach. Wartości nie są znane. Potrzebna jest **ponowna kalibracja w trakcie spaceru**.
- WebXR na Questach pozwala na maksymalnie **8 trwałych kotwic** na sesję. Hit-test działa do ok. 5 m.
- **Bezpośrednie słońce na soczewkach trwale uszkadza ekrany w mniej niż minutę.** Zakładać zaślepki, gdy gogle nie są na głowie. Słabe światło psuje śledzenie. Jednolita trawa prawdopodobnie też (nie sprawdzono), więc przydają się paliki i kontrastowe znaczniki.

## Konwencje

- **1 jednostka = 1 metr**, oś **Y w górę** (konwencja glTF), podłoga na `y = 0`. Błędna skala w VR jest od razu widoczna.
- Skala z PNG: najpierw automatycznie z powierzchni pomieszczeń podanych na rzucie (dopasowanie m²), w razie potrzeby kalibracja dwoma punktami ze znanym wymiarem.
- Wartości domyślne, gdy importer ich nie zna:
  - wysokość w świetle 2,6 m,
  - grubość ścian: zewnętrzne ~0,4 m, nośne wewnętrzne ~0,25 m, działowe ~0,12 m.
- **Oświetlenie na bieżąco**, bez lightmap, bo edycja układu na miejscu je unieważnia. Mało świateł dynamicznych, proste materiały PBR, tekstury KTX2.
- Budżet wydajności Quest 3S: stabilne 72–90 FPS na każdych goglach, orientacyjnie < 300–500 tys. trójkątów i < 150 draw calli.
- Zmiana układu w trybie MR w prawdziwym mieszkaniu rozjedzie się z istniejącymi ścianami. Edycja układu ma sens głównie na działce i na sali.
- WebXR wymaga HTTPS także w LAN: certyfikat samopodpisany z `@vitejs/plugin-basic-ssl` (ostrzeżenie przeglądarki akceptuje się raz, także w goglach).

## Test terenowy (przed pisaniem właściwego kodu)

Cel: rozstrzygnąć WebXR vs Unity i potwierdzić, że spacer po całym domu na działce jest wykonalny.

1. 2× Quest 3S w trybie MR. Spacer 15–20 m po trawie (działka) i w pustym pomieszczeniu.
2. Pomiar dryfu: wirtualny znacznik nad palikiem, spacer po obwodzie domu, powrót. Zmierzyć odchyłkę w cm.
3. Sprawdzić limit ~20 m od startu i zachowanie granicy w VR i MR.
4. Śledzenie w pochmurny i słoneczny dzień oraz o zmierzchu.
5. Narzędzia:
   - gotowe aplikacje (Arkio, SketchUp Viewer),
   - strona testowa `field-test/` (instrukcja dla operatora: `field-test/README.md`).
6. Zapisać wyniki (dryf w cm na X m, maksymalny zasięg, problemy) w tym pliku i na ich podstawie wybrać stos.

## Komendy

Docelowe jeszcze nie ma. Uzupełnić po wyborze technologii i założeniu projektu (instalacja, dev server z HTTPS w LAN, testy, pojedynczy test, lint).

Strona testowa `viewer/` (Three.js, spacer WASD + mysz, przyciski VR/MR, wczytywanie GLB lub PlanModel JSON przeciągnięciem albo przez `?plan=plans/<nazwa>.json`):

- `cd viewer && npm install`: instalacja,
- `npm run dev`: serwer HTTPS w LAN (certyfikat samopodpisany z `@vitejs/plugin-basic-ssl`; ostrzeżenie przeglądarki trzeba raz zaakceptować, także w goglach),
- `npm run build`: sprawdzenie typów (`tsc`) i build,
- `npm run export-glb -- public/plans/test1/test1.json [wyjście.glb]`: eksport PlanModel do GLB (np. dla Sketchfab), ale **bez tekstur** (Node nie wczytuje obrazów); GLB z teksturami robi przycisk „Pobierz GLB” w viewerze,
- tekstury: `viewer/public/textures/` (CC0 z Poly Haven, 1k JPG: `_diff`, `_nor`, `_rough`; źródła i autorzy w `LICENSE.md`); materiały i ich domyślne wartości w `viewer/src/materials.ts`, współrzędne tekstur liczone w metrach (`applyMetricUV`), okładziny ścian pokoi i balkony w `viewer/src/finishes.ts`.

Strona testu terenowego `field-test/` (WebXR: typ przestrzeni, pomiar dryfu na palikach, port 5174):

- `cd field-test && npm install`: instalacja,
- `npm run dev`: serwer HTTPS w LAN; gogle wysyłają wyniki na `POST /api/results`, a serwer zapisuje je w `field-test/results/<id>.json` (poza gitem),
- `npm run typecheck`: sprawdzenie typów, `npm run build`: typy i build.

Automat importu `importer/` (Python przez `uv`; rzut PNG/JPG → `PlanModel` JSON v4 ze ścianami, drzwiami i oknami, pomieszczeniami i meblami; skala z wymiarów zewnętrznych odczytanych OCR albo z powierzchni pomieszczeń; viewer migruje starsze pliki v1–v3):

- PlanModel v4: katalog `materials` (`{texture, tileM, color, normalOnly, roughness, …}`), `rooms[].materials` (`{floor, walls}`; ściany inne niż farba dostają okładzinę z przerwami na otwory), w meblach `elevation` (montaż nad podłogą) i `materials` (podmiana materiałów jednego mebla, np. `{"drewno": "bialy"}`), `balconies` (`{polygon, railingHeight, floorMaterial}`), otwór `type: "folding"` (drzwi harmonijkowe), w drzwiach `door.leafMaterial`/`frameMaterial`,
- plik projektu `--design plik.json` (`importer/plan2model/design.py`): to, czego automat nie odczyta z rzutu (materiały, dekoracje, zmiany układu np. według wizualizacji dewelopera), nakładane na wynik automatu; meble i otwory wskazuje się typem i położeniem (`{"type": "stolik", "near": [x, z]}`), nie `id`; klucze zaczynające się od `_` to komentarze; przykład: `fixtures/test2/test2_3.design.json` (wygląd według `fixtures/test2/test2_wiz.png`),

- drzwi i okna (`importer/plan2model/openings.py`): przerwy w ścianach; łuk przy przerwie → drzwi (szerokość, zawias `a`/`b`, strona `swing`), przerwa w ścianie zewnętrznej bez łuku → okno (zewnętrzna = po jednej stronie przestrzeń poza budynkiem, także przy wcięciach obrysu); w ścianie zewnętrznej drzwi otwierają się do środka,
- ściany i pomieszczenia (`importer/plan2model/walls.py`, `rooms.py`): ściany jako prostokąty poziome/pionowe; do zamykania pomieszczeń dochodzą też ściany skośne i słupki z maski ciemnych pikseli, okna między słupkami ściany skośnej i szerokie bramy (równoległe kreski między kawałkami grubej ściany, `rooms.glazing`) oraz przerwy do 2 m w ściankach działowych, jeśli wzdłuż nich narysowano skrzydła drzwi przesuwnych; ściany skośne nie trafiają jeszcze do PlanModel (tylko do podziału na pomieszczenia),
- typy tylko z pliku projektu (dekoracje): `lampa_stojaca`, `lampa_wiszaca` (`params.ceilingAbove`), `roslina` (`params.kind: "monstera"`, `seed`), `dywan`, `obraz`, `lustro`, `ksiazki`, `wazon`, `stolik_boczny`, `kabina` (`params.glass`), `zabudowa` (`params.fridge`), `polka`, `kosmetyki`, `czajnik`, ścianki od podłogi do sufitu `lamele` i `scianka_szklana` (przesuwna, `params.panels`; błękitne szkło przez `materials: {"szklo": …}`); ponadto `kanapa.params.pillows/throw`, `wc.params.wallHung`, `blat.params.backsplash`, `tv.params.wall` (sam ekran na ścianie),
- `--dimensions`: dodatkowo `*_wymiary.png` (`importer/plan2model/dimensions.py`), czyli rzut powiększony 3× z wymiarami w cm: obrys, gabaryty mebli dodanych przez plik projektu, długość ścianek i odległość ich osi od ściany zewnętrznej oraz strefy z pliku projektu (`"zones": [{"name", "polygon"}]`, pokoje po podziale ściankami: powierzchnia, szerokość i głębokość w świetle; `zones` nie trafiają do PlanModel); gabaryty mebli i nazwy pokoi stawiane w wolnym miejscu obok mebla (nie pod nim), linie odległości ścianek przesuwane wzdłuż ścianki tak, żeby liczby nie zasłaniał mebel,
- `--floor-dimensions`: te same wymiary (`dimensions.compute`, w metrach) zapisane w PlanModel jako opcjonalne pole `annotations` (`{lines: [{a, b, offset, text, kind, at}], labels: [{at, text, kind}]}`; brak pola = brak wymiarów, schemat zostaje v4); viewer rysuje je na podłodze (`viewer/src/annotations.ts`: linie jedną siatką, napisy z jednego atlasu canvas, 2 draw calle); w eksporcie GLB z wiersza poleceń bez napisów (Node nie ma canvasu),
- z `--design` obrazek kontrolny pokazuje meble po zmianach (usunięte zamalowane, ścianki wypełnione kolorem); materiały, otwory i balkony z pliku projektu widać tylko w modelu,
- meble (`importer/plan2model/furniture.py`): kształt analizowany w całości (obrócony prostokąt, koło, komórki zamknięte liniami: poduchy, palniki, komora zlewu, krzyżyk szafy), typy: `kanapa` (`params.seats`), `fotel`, `stol_okragly`, `stol`, `stolik`, `szafa` (`params.modules`), `tv`, `blat`, `plyta`, `zlew`, `lodowka`, `prysznic` (`params.corner`), `wc`, `umywalka`, `pralka`, `wanna`, `lozko` (także pojedyncze, po poduszce przy krótszym boku), `krzeslo` (małe siedzisko przy stole lub biurku, przodem do niego), `biurko` (pusty prostokąt przy ścianie z krzesłem), `samochod` (w viewerze zwykła bryła), `szafka`, `male`, `mebel`; kształty ustawione skosem (np. blat w V wzdłuż ściany skośnej) analizowane po obróceniu obrazu; pomijane: numery pomieszczeń (czarne cyfry), schody i kominek (szare wypełnienie); przy `rotation = 0` przód mebla patrzy w +Z (w dół rzutu), 90 = w −X; przód od ściany albo (fotel) w stronę stołu/TV,
- viewer buduje z typów bryły zbliżone do mebli (`viewer/src/furnitureShapes.ts`) i stolarkę z nadprożami (`viewer/src/openingShapes.ts`); części są scalane po materiale (`viewer/src/parts.ts`), więc meble dokładają kilkanaście draw calli niezależnie od ich liczby,

- wymaga Tesseracta: `sudo apt install tesseract-ocr tesseract-ocr-pol`,
- `cd importer && uv run plan2model ../fixtures/test1/test1.png -o ../viewer/public/plans/test1/test1.json`: konwersja; obok JSON powstaje `*_debug.png` (ściany, zamknięte otwory, pokoje, meble z typem, sprawdzone wymiary), a w konsoli raport skali i kontroli wymiarów pokoi,
- `--width-m 9.9` albo `--scale <m/px>`: skala ręczna, gdy OCR nie odczyta wymiarów,
- `--area Pokój=18.08 --area Łazienka=4.30 …`: skala z sumy powierzchni pomieszczeń podanych na rzucie (balkon/taras pomijany w sumie), gdy rzut nie ma wymiarów w cm; pokoje dostają nazwy, jeśli powierzchnie jednoznacznie pasują. Przykład: `uv run plan2model ../fixtures/test2/test2.png --walls-only --area Hol=3.88 --area Pokój=18.08 --area Łazienka=4.30 --area Kuchnia=5.48 --area Balkon=2.85 -o ../viewer/public/plans/test2/test2.json`,
- `--walls-only`: bez wykrywania mebli (drzwi i okna zostają); `test2_2` to ten sam rzut z meblami: `uv run plan2model ../fixtures/test2/test2.png --area … -o ../viewer/public/plans/test2/test2_2.json`; `test2_3` to pełna wizualizacja: to samo z `--design ../fixtures/test2/test2_3.design.json -o ../viewer/public/plans/test2/test2_3.json`; `test2_4_1` to zmiany narysowane ręcznie na `fixtures/test2/test2_4.png` (sypialnia za lamelami i szklaną ścianą, bez dekoracji): to samo z `--design ../fixtures/test2/test2_4_1.design.json --dimensions -o ../viewer/public/plans/test2/test2_4_1.json` (rzut z wymiarami skopiowany jako `viewer/public/plans/test2/test2_4_1.png`); `test2_4_2` to ten sam model z wymiarami na podłodze w 3D: dodatkowo `--floor-dimensions -o ../viewer/public/plans/test2/test2_4_2.json`,
- `test3` (dom z garażem, pokoje oznaczone numerami 1–12 zamiast nazw): `uv run plan2model ../fixtures/test3/test3.png --area "Wiatrołap 1"=5.9 --area "Przedpokój 2"=13.2 --area "Salon 3"=44.9 --area "Kuchnia 4"=9.0 --area "Spiżarnia 5"=1.7 --area "Łazienka 6"=5.1 --area "Łazienka 7"=6.8 --area "Pokój 8"=18.1 --area "Pokój 9"=11.7 --area "Pokój 10"=10.6 --area "Kotłownia 11"=10.6 --area "Garaż 12"=29.2 -o …`; w `viewer/public/plans/test3/` na razie tylko `test3_debug.png` (pokoje i meble, bez modelu 3D); nazw pokoi automat nie dopasowuje (dwa pomieszczenia po 10,6 m², powierzchnie z rzutu odbiegają od rysunku o ok. 20 %), nazwy do uzupełnienia w edytorze albo przez odczyt numerów OCR w przyszłości,
- `uv run pytest`: testy, `uv run pytest -k synthetic`: pojedynczy test (testy OCR są pomijane bez Tesseracta),
- podgląd: `cd viewer && npm run dev`, potem `https://<IP>:5173/?plan=plans/test1/test1.json`.

Brak testów automatycznych w `viewer/` i `field-test/`; weryfikacja w Immersive Web Emulator lub w goglach. Zrzut ekranu sceny bez okna: Chromium z Playwrighta (`~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome`) pod `xvfb-run` z `--use-angle=swiftshader --enable-unsafe-swiftshader --screenshot` (sam headless bez `xvfb-run` nie tworzy kontekstu WebGL).

Układ plików: jeden katalog na projekt, wejścia w `fixtures/<projekt>/` (rzut PNG, wizualizacje, pliki projektu `*.design.json`), wyniki w `viewer/public/plans/<projekt>/` (PlanModel JSON, GLB, `*_debug.png`, `*_wymiary.png`), np. `fixtures/test2/` i `viewer/public/plans/test2/`, adres w viewerze `?plan=plans/test2/test2_4_2.json`.

Testy automatu: rzuty referencyjne w `fixtures/` (5–10 prawdziwych PNG ze stron z projektami), z asercjami na `PlanModel`: liczba ścian i otworów, wymiary w tolerancji, powierzchnie pomieszczeń zgodne z podanymi na rzucie.

## Sprzęt i narzędzia

Priorytet: najniższy koszt, bez specjalistycznego sprzętu.

- **2× Meta Quest 3S** (wspólna przestrzeń, passthrough, MR).
- **Laptop** jako serwer w terenie oraz stanowisko do przygotowania modeli.
- **Tani router Wi-Fi** zasilany z **powerbanku**: sieć offline dla gogli i tabletu.
- Tablet lub telefon jako panel operatora.
- Zaślepki na soczewki, paliki i kontrastowe znaczniki do kalibracji na działce.
- Kabel USB-C: `adb`, logi, instalacja aplikacji. Meta Quest Developer Hub, zdalne DevTools przez `chrome://inspect`.
- Oprogramowanie:
  - Python 3 + OpenCV + OCR (np. Tesseract z językiem polskim, `pol`), PyMuPDF dla PDF,
  - Node.js LTS + npm, Immersive Web Emulator (testy bez gogli).

## Otwarte

- Wynik testu terenowego, a od niego zależy wybór WebXR vs Unity.
- Rzeczywista wielkość dryfu i sposób ponownej kalibracji w trakcie spaceru.
- Sposób dopasowania dwóch gogli do wspólnego układu współrzędnych.
