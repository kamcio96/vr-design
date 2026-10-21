import * as THREE from 'three';
import type { Point } from './planModel';

// Wymiary na podłodze: linie wymiarowe i napisy liczone przez importer (plan2model/dimensions.py,
// pole `annotations` w PlanModel). Wszystkie linie to jedna siatka, wszystkie napisy – druga
// (jeden atlas tekstury), więc wymiary dokładają 2 draw calle niezależnie od ich liczby.

export type DimKind = 'outline' | 'partition' | 'zone' | 'distance' | 'furniture';

export interface DimLine {
  a: Point;
  b: Point;
  offset: number; // m; dodatni: w +Z dla a→b w +X, w −X dla a→b w +Z (jak na PNG)
  text: string;
  kind: DimKind;
  at: number; // położenie napisu na linii, 0 = a, 1 = b
}

export interface DimLabel {
  at: Point;
  text: string;
  kind: DimKind;
}

export interface PlanAnnotations {
  lines: DimLine[];
  labels: DimLabel[];
}

// Te same kolory co na rzucie z wymiarami (PNG).
const COLORS: Record<DimKind, string> = {
  outline: '#1e1e1e',
  partition: '#1e1e1e',
  zone: '#c81e1e',
  distance: '#c81e1e',
  furniture: '#003c8c',
};
const TEXT_HEIGHT = { outline: 0.16, zone: 0.18 } as Partial<Record<DimKind, number>>;
const DEFAULT_TEXT_HEIGHT = 0.12; // wysokość prostokąta z napisem w metrach (litery ok. 10 cm)
const LINE_Y = 0.012; // nad podłogą pokoi (0,005), żeby nie migotało
const LABEL_Y = 0.014;
const LINE_W = 0.015;

export function buildAnnotations(a: PlanAnnotations): THREE.Group {
  const group = new THREE.Group();
  group.name = 'wymiary';
  group.add(buildLines(a.lines));
  // Napisy wymagają canvasu – w eksporcie GLB z wiersza poleceń (Node) ich nie ma.
  if (typeof document !== 'undefined') {
    const labels: Placed[] = [
      ...a.lines.map((l) => {
        const { pa, pb, d } = dimGeometry(l);
        const at = new THREE.Vector2().lerpVectors(pa, pb, l.at);
        return { text: l.text, kind: l.kind, at, vertical: Math.abs(d.y) > Math.abs(d.x) };
      }),
      ...a.labels.map((l) => ({ text: l.text, kind: l.kind, at: new THREE.Vector2(...l.at), vertical: false })),
    ];
    group.add(buildLabels(labels));
  }
  return group;
}

// Punkty w płaszczyźnie podłogi jako Vector2(x, z).
function dimGeometry(l: DimLine) {
  const a = new THREE.Vector2(...l.a);
  const b = new THREE.Vector2(...l.b);
  const d = b.clone().sub(a).normalize();
  const n = new THREE.Vector2(-d.y, d.x).multiplyScalar(l.offset);
  return { a, b, d, n, pa: a.clone().add(n), pb: b.clone().add(n) };
}

function buildLines(lines: DimLine[]): THREE.Mesh {
  const pos: number[] = [];
  const col: number[] = [];
  const seg = (p: THREE.Vector2, q: THREE.Vector2, color: THREE.Color, width = LINE_W) => {
    const d = q.clone().sub(p);
    if (d.lengthSq() < 1e-8) return;
    const s = new THREE.Vector2(-d.y, d.x).normalize().multiplyScalar(width / 2);
    const c = [p.clone().add(s), q.clone().add(s), q.clone().sub(s), p.clone().sub(s)];
    for (const i of [0, 1, 2, 0, 2, 3]) {
      pos.push(c[i].x, LINE_Y, c[i].y);
      col.push(color.r, color.g, color.b);
    }
  };
  for (const l of lines) {
    const color = new THREE.Color(COLORS[l.kind]);
    const { a, b, d, n, pa, pb } = dimGeometry(l);
    if (l.offset) {
      // linie pomocnicze od mierzonego punktu, 5 cm za linię wymiarową
      const over = n.clone().normalize().multiplyScalar(0.05);
      seg(a, pa.clone().add(over), color);
      seg(b, pb.clone().add(over), color);
    }
    seg(pa, pb, color);
    const tick = d.clone().add(new THREE.Vector2(d.y, -d.x)).multiplyScalar(0.05);
    for (const p of [pa, pb]) seg(p.clone().sub(tick), p.clone().add(tick), color, LINE_W * 2);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  geometry.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
  const material = new THREE.MeshBasicMaterial({
    vertexColors: true,
    side: THREE.DoubleSide,
    polygonOffset: true,
    polygonOffsetFactor: -2,
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.name = 'wymiary-linie';
  return mesh;
}

interface Placed {
  text: string;
  kind: DimKind;
  at: THREE.Vector2;
  vertical: boolean; // jak na PNG: czytany od dołu rzutu do góry (w −Z), góra liter w −X
}

function buildLabels(labels: Placed[]): THREE.Mesh {
  // Atlas: napisy układane wierszami na jednym canvasie.
  const PX = 64; // wysokość wiersza w pikselach
  const PAD = 10;
  const ATLAS_W = 2048;
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d')!;
  const font = (k: DimKind) => `${k === 'zone' ? 'bold ' : ''}${PX - 18}px sans-serif`;
  const boxes = labels.map((l) => {
    ctx.font = font(l.kind);
    return { w: Math.ceil(ctx.measureText(l.text).width) + 2 * PAD, x: 0, y: 0 };
  });
  let x = 0;
  let y = 0;
  for (const b of boxes) {
    if (x + b.w > ATLAS_W) {
      x = 0;
      y += PX;
    }
    b.x = x;
    b.y = y;
    x += b.w + 2;
  }
  canvas.width = ATLAS_W;
  canvas.height = THREE.MathUtils.ceilPowerOfTwo(y + PX);
  ctx.textBaseline = 'middle';
  labels.forEach((l, i) => {
    const b = boxes[i];
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(b.x, b.y, b.w, PX);
    ctx.fillStyle = COLORS[l.kind];
    ctx.font = font(l.kind);
    ctx.fillText(l.text, b.x + PAD, b.y + PX / 2 + 2);
  });

  const pos: number[] = [];
  const uv: number[] = [];
  labels.forEach((l, i) => {
    const b = boxes[i];
    const h = TEXT_HEIGHT[l.kind] ?? DEFAULT_TEXT_HEIGHT;
    const w = (h * b.w) / PX;
    // u – kierunek pisania, v – „góra” liter, oba w płaszczyźnie podłogi (x, z).
    const u = l.vertical ? new THREE.Vector2(0, -1) : new THREE.Vector2(1, 0);
    const v = l.vertical ? new THREE.Vector2(-1, 0) : new THREE.Vector2(0, -1);
    const corner = (su: number, sv: number) =>
      l.at.clone().add(u.clone().multiplyScalar((su * w) / 2)).add(v.clone().multiplyScalar((sv * h) / 2));
    const u0 = b.x / canvas.width;
    const u1 = (b.x + b.w) / canvas.width;
    const v0 = b.y / canvas.height; // góra napisu (flipY = false: v = 0 to górny wiersz canvasu)
    const v1 = (b.y + PX) / canvas.height;
    const quad: [number, number, number, number][] = [
      [-1, -1, u0, v1],
      [1, -1, u1, v1],
      [1, 1, u1, v0],
      [-1, 1, u0, v0],
    ];
    for (const k of [0, 1, 2, 0, 2, 3]) {
      const [su, sv, tu, tv] = quad[k];
      const p = corner(su, sv);
      pos.push(p.x, LABEL_Y, p.y);
      uv.push(tu, tv);
    }
  });
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  const texture = new THREE.CanvasTexture(canvas);
  texture.flipY = false;
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 8; // czytelność pod kątem, z wysokości oczu
  const material = new THREE.MeshBasicMaterial({
    map: texture,
    side: THREE.DoubleSide,
    polygonOffset: true,
    polygonOffsetFactor: -3,
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.name = 'wymiary-napisy';
  return mesh;
}
