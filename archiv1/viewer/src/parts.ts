import * as THREE from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';
import { applyMetricUV, MaterialLibrary } from './materials';

// Nazwa materiału z katalogu (viewer/src/materials.ts albo PlanModel.materials).
export type MaterialName = string;

// Zbiera części (geometria + przekształcenie) pogrupowane po materiale i scala je na końcu:
// jeden materiał = jedna siatka, więc liczba draw calli nie rośnie z liczbą mebli (budżet Questa: < 150).
export class PartSink {
  private parts = new Map<MaterialName, THREE.BufferGeometry[]>();

  add(material: MaterialName, geometry: THREE.BufferGeometry, matrix: THREE.Matrix4): void {
    // Box/Cylinder/Sphere/Shape są indeksowane i mają te same atrybuty – tego wymaga mergeGeometries.
    geometry.applyMatrix4(matrix);
    let list = this.parts.get(material);
    if (!list) this.parts.set(material, (list = []));
    list.push(geometry);
  }

  build(library: MaterialLibrary, prefix: string): THREE.Mesh[] {
    const meshes: THREE.Mesh[] = [];
    for (const [name, list] of this.parts) {
      const merged = mergeGeometries(list, false);
      list.forEach((g) => g.dispose());
      if (!merged) continue;
      const tile = library.tile(name);
      if (tile) applyMetricUV(merged, tile);
      const mesh = new THREE.Mesh(merged, library.get(name));
      mesh.name = `${prefix}-${name}`;
      meshes.push(mesh);
    }
    return meshes;
  }
}

// Rysowanie w lokalnym układzie obiektu: X w prawo, Y w górę, Z do przodu; `base` przenosi do świata.
// `remap` podmienia materiały pojedynczego mebla (np. {"drewno": "bialy"} – biały blat stołu).
export class Local {
  constructor(
    private sink: PartSink,
    private base: THREE.Matrix4,
    private remap: Record<string, string> = {},
  ) {}

  private put(material: MaterialName, g: THREE.BufferGeometry, m: THREE.Matrix4): void {
    this.sink.add(this.remap[material] ?? material, g, this.base.clone().multiply(m));
  }

  // Prostopadłościan o środku (cx, cy, cz) i wymiarach (sx, sy, sz), opcjonalnie obrócony wokół Y.
  box(material: MaterialName, cx: number, cy: number, cz: number, sx: number, sy: number, sz: number, rotY = 0): void {
    if (sx <= 0 || sy <= 0 || sz <= 0) return;
    const m = new THREE.Matrix4().makeTranslation(cx, cy, cz);
    if (rotY) m.multiply(new THREE.Matrix4().makeRotationY(rotY));
    this.put(material, new THREE.BoxGeometry(sx, sy, sz), m);
  }

  // Prostopadłościan od y0 do y1 (wygodniej niż środek przy meblach stojących na podłodze).
  slab(material: MaterialName, cx: number, cz: number, sx: number, sz: number, y0: number, y1: number): void {
    this.box(material, cx, (y0 + y1) / 2, cz, sx, y1 - y0, sz);
  }

  // Walec pionowy (oś Y), opcjonalnie spłaszczony do elipsy (sx, sz = skala w X i Z) lub wycinek kąta.
  cylinder(
    material: MaterialName,
    cx: number,
    cz: number,
    radius: number,
    y0: number,
    y1: number,
    opts: { sx?: number; sz?: number; segments?: number; thetaStart?: number; thetaLength?: number; open?: boolean; radiusTop?: number } = {},
  ): void {
    const g = new THREE.CylinderGeometry(
      opts.radiusTop ?? radius,
      radius,
      y1 - y0,
      opts.segments ?? 24,
      1,
      opts.open ?? false,
      opts.thetaStart ?? 0,
      opts.thetaLength ?? Math.PI * 2,
    );
    const m = new THREE.Matrix4().makeTranslation(cx, (y0 + y1) / 2, cz);
    m.multiply(new THREE.Matrix4().makeScale(opts.sx ?? 1, 1, opts.sz ?? 1));
    this.put(material, g, m);
  }

  // Walec leżący, oś wzdłuż Z (np. drzwi pralki patrzące do przodu).
  disc(material: MaterialName, cx: number, cy: number, cz: number, radius: number, depth: number): void {
    const g = new THREE.CylinderGeometry(radius, radius, depth, 24);
    const m = new THREE.Matrix4().makeTranslation(cx, cy, cz).multiply(new THREE.Matrix4().makeRotationX(Math.PI / 2));
    this.put(material, g, m);
  }

  // Elipsoida o środku (cx, cy, cz) i półosiach rx, ry, rz, obrócona wokół Y i pochylona wokół X (liście).
  ellipsoid(material: MaterialName, cx: number, cy: number, cz: number, rx: number, ry: number, rz: number, rotY = 0, tiltX = 0, segments = 10): void {
    const g = new THREE.SphereGeometry(1, segments, Math.max(4, Math.round(segments * 0.6)));
    const m = new THREE.Matrix4()
      .makeTranslation(cx, cy, cz)
      .multiply(new THREE.Matrix4().makeRotationY(rotY))
      .multiply(new THREE.Matrix4().makeRotationX(tiltX))
      .multiply(new THREE.Matrix4().makeScale(rx, ry, rz));
    this.put(material, g, m);
  }

  // Płaski wielokąt [x, z] (lokalnie) na wysokości y, ściana skierowana w górę – np. posadzka balkonu.
  flat(material: MaterialName, points: [number, number][], y: number): void {
    const shape = new THREE.Shape(points.map(([x, z]) => new THREE.Vector2(x, -z)));
    const g = new THREE.ShapeGeometry(shape);
    g.rotateX(-Math.PI / 2);
    this.put(material, g, new THREE.Matrix4().makeTranslation(0, y, 0));
  }
}

// Macierz obiektu w (x, z) na wysokości `elevation` (0 = na podłodze), obróconego o `rotationDeg`
// wokół Y (konwencja PlanModel: 0 = przód w +Z, 90 = w −X).
export function placement(x: number, z: number, rotationDeg: number, elevation = 0): THREE.Matrix4 {
  return new THREE.Matrix4()
    .makeTranslation(x, elevation, z)
    .multiply(new THREE.Matrix4().makeRotationY(THREE.MathUtils.degToRad(-rotationDeg)));
}
