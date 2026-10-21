import * as THREE from 'three';
import { buildAnnotations, PlanAnnotations } from './annotations';
import { buildBalcony, buildWallFinish } from './finishes';
import { buildShape } from './furnitureShapes';
import { applyMetricUV, MaterialDef, MaterialLibrary } from './materials';
import { buildOpening } from './openingShapes';
import { Local, PartSink, placement } from './parts';

// PlanModel v4 – format zapisywany przez importer (importer/plan2model/planmodel.py).
// Punkty [x, z] w metrach: X w prawo na rzucie, Z w dół rzutu, środek budynku w (0, 0).
export type Point = [number, number];

export interface PlanWall {
  id: string;
  a: Point;
  b: Point;
  thickness: number;
  height: number;
}

export interface PlanRoom {
  id: string;
  name: string | null;
  polygon: Point[];
  area: number;
  areaOnPlan: number | null;
  materials?: { floor?: string; walls?: string } | null; // id z katalogu; brak = domyślne
}

// Otwór na osi ściany od a do b; sill/height = dół i góra otworu w m. Drzwi: zawias na końcu "a"
// albo "b", swing = +1, gdy skrzydło otwiera się w stronę wektora (−dz, dx) dla kierunku a→b.
// type "folding": drzwi harmonijkowe stojące w pokoju (bez nadproża), rysowane złożone przy końcu "a".
export interface PlanOpening {
  id: string;
  type: 'door' | 'window' | 'folding';
  a: Point;
  b: Point;
  thickness: number;
  sill: number;
  height: number;
  door?: { hinge: 'a' | 'b'; swing: number; openAngle?: number; leafMaterial?: string; frameMaterial?: string };
}

// Mebel: size = [szerokość (lokalne X), głębokość (lokalne Z, przód–tył), wysokość],
// position = środek podstawy, rotation = obrót wokół Y w stopniach; przy 0 przód patrzy w +Z,
// 90 = w −X. params: dodatkowe cechy z rysunku (np. seats kanapy, modules szafy, corner prysznica).
export interface PlanFurniture {
  id: string;
  type: string;
  size: [number, number, number];
  position: Point;
  rotation: number;
  params?: Record<string, unknown>;
  elevation?: number; // wysokość podstawy nad podłogą (obrazy, lustro, lampa wisząca, rzeczy na blacie)
  materials?: Record<string, string>; // podmiana materiałów tego mebla, np. {"drewno": "bialy"}
}

export interface PlanBalcony {
  polygon: Point[];
  railingHeight?: number;
  floorMaterial?: string;
}

export interface PlanModel {
  schemaVersion: number;
  units: 'm';
  source: { file: string; metersPerPixel: number; scaleMethod: string; outlineSize: Point };
  storey: { height: number };
  walls: PlanWall[];
  openings: PlanOpening[];
  rooms: PlanRoom[];
  furniture: PlanFurniture[];
  materials: Record<string, MaterialDef>;
  balconies: PlanBalcony[];
  annotations?: PlanAnnotations; // wymiary na podłodze (opcjonalne, plan2model --floor-dimensions)
}

export const SUPPORTED_SCHEMA = 4;

export function isPlanModel(data: unknown): data is PlanModel {
  return typeof data === 'object' && data !== null && 'schemaVersion' in data && 'walls' in data;
}

// Migracje starszych wersji do bieżącej. v1 → v2: doszła lista mebli. v2 → v3: otwory (w v2 zawsze
// puste) i umowa o przodzie mebli; stare meble miały rotation 0, więc dane się nie zmieniają.
export function migrate(plan: PlanModel): PlanModel {
  let p = plan;
  if (p.schemaVersion === 1) p = { ...p, schemaVersion: 2, furniture: [] };
  if (p.schemaVersion === 2) p = { ...p, schemaVersion: 3, openings: [] };
  // v3 → v4: katalog materiałów i balkony (puste = domyślne materiały viewera).
  if (p.schemaVersion === 3) p = { ...p, schemaVersion: 4, materials: {}, balconies: [] };
  return p;
}

// Geometria budowana na żywo z PlanModel: przesunięcie ściany w danych = nowa bryła po przebudowie.
export function buildPlan(input: PlanModel): THREE.Group {
  const plan = migrate(input);
  if (plan.schemaVersion !== SUPPORTED_SCHEMA) {
    throw new Error(`Nieobsługiwana wersja PlanModel: ${plan.schemaVersion} (obsługiwana: ${SUPPORTED_SCHEMA})`);
  }
  const group = new THREE.Group();
  group.name = 'plan';

  const library = new MaterialLibrary(plan.materials);

  // Ściany: osobne siatki (każda ze swoim id – do przesuwania na żywo), geometria w układzie świata,
  // żeby tekstura ściany (jeśli jest) miała wymiary w metrach.
  const wallTile = library.tile('sciana');
  for (const w of plan.walls) {
    const dx = w.b[0] - w.a[0];
    const dz = w.b[1] - w.a[1];
    const geometry = new THREE.BoxGeometry(Math.hypot(dx, dz), w.height, w.thickness);
    geometry.applyMatrix4(
      new THREE.Matrix4()
        .makeTranslation((w.a[0] + w.b[0]) / 2, w.height / 2, (w.a[1] + w.b[1]) / 2)
        .multiply(new THREE.Matrix4().makeRotationY(-Math.atan2(dz, dx))),
    );
    if (wallTile) applyMetricUV(geometry, wallTile);
    const mesh = new THREE.Mesh(geometry, library.get('sciana'));
    mesh.name = w.id;
    group.add(mesh);
  }

  const sink = new PartSink();
  for (const room of plan.rooms) {
    // Kształt rysujemy w płaszczyźnie XY jako (x, -z), a obrót o -90° wokół X kładzie go na podłodze w (x, 0, z).
    const floor = room.materials?.floor ?? 'podloga';
    const shape = new THREE.Shape(room.polygon.map(([x, z]) => new THREE.Vector2(x, -z)));
    const geometry = new THREE.ShapeGeometry(shape);
    geometry.rotateX(-Math.PI / 2);
    geometry.translate(0, 0.005, 0); // tuż nad gruntem, żeby nie migotało
    if (library.tile(floor)) applyMetricUV(geometry, library.tile(floor));
    const mesh = new THREE.Mesh(geometry, library.get(floor));
    mesh.name = room.id;
    group.add(mesh);
    // Okładzina ścian tylko wtedy, gdy pokój ma inne wykończenie niż domyślna farba.
    const walls = room.materials?.walls;
    if (walls && walls !== 'sciana') buildWallFinish(sink, room.polygon, walls, plan.openings, plan.storey.height);
  }

  // Meble, stolarka, balkony: części scalane po materiale (kilkanaście–kilkadziesiąt draw calli
  // niezależnie od liczby mebli).
  for (const f of plan.furniture) {
    const [w, d, h] = f.size;
    const base = placement(f.position[0], f.position[1], f.rotation, f.elevation ?? 0);
    buildShape(new Local(sink, base, f.materials ?? {}), f.type, w, d, h, f.params);
  }
  for (const o of plan.openings) buildOpening(sink, o, plan.storey.height);
  for (const b of plan.balconies) buildBalcony(sink, b, plan.walls, b.floorMaterial ?? 'cien');
  for (const mesh of sink.build(library, 'wyposazenie')) group.add(mesh);
  if (plan.annotations) group.add(buildAnnotations(plan.annotations));

  return group;
}
