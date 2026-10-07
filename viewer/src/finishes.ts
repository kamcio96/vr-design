import * as THREE from 'three';
import { Local, MaterialName, PartSink } from './parts';
import type { PlanBalcony, PlanOpening, PlanWall, Point } from './planModel';

const FINISH = 0.01; // grubość okładziny (płytki); przylega do lica ściany

// Okładzina ścian pomieszczenia (np. płytki w łazience): cienkie panele wzdłuż krawędzi poligonu
// pokoju, które leżą na licach ścian. W miejscu drzwi i okien zostaje przerwa (nad drzwiami
// i pod oknem okładzina jest, tak jak ściana). Poligon pokoju z automatu przebiega o ok. 1 cm
// od lica ściany, więc panel sięga od lica do poligonu.
export function buildWallFinish(sink: PartSink, polygon: Point[], material: MaterialName, openings: PlanOpening[], height: number): void {
  const n = polygon.length;
  let area2 = 0;
  for (let i = 0; i < n; i++) {
    const [x0, z0] = polygon[i];
    const [x1, z1] = polygon[(i + 1) % n];
    area2 += x0 * z1 - x1 * z0;
  }
  const inwardSign = area2 > 0 ? 1 : -1; // wnętrze po lewej (normalna (−dz, dx)) dla dodatniego pola
  for (let i = 0; i < n; i++) {
    const p = polygon[i];
    const q = polygon[(i + 1) % n];
    const length = Math.hypot(q[0] - p[0], q[1] - p[1]);
    if (length < 0.05) continue;
    const dx = (q[0] - p[0]) / length;
    const dz = (q[1] - p[1]) / length;
    const nx = -dz * inwardSign;
    const nz = dx * inwardSign;
    const holes = openingSpans(p, dx, dz, length, openings);
    // Lokalny układ krawędzi: X wzdłuż p→q (od p); środek panelu 3 mm od poligonu w stronę ściany.
    const base = new THREE.Matrix4()
      .makeTranslation(p[0] - nx * (FINISH / 2 - 0.002), 0, p[1] - nz * (FINISH / 2 - 0.002))
      .multiply(new THREE.Matrix4().makeRotationY(-Math.atan2(dz, dx)));
    const l = new Local(sink, base);
    const panel = (t0: number, t1: number, y0: number, y1: number) => {
      if (t1 - t0 > 0.01 && y1 - y0 > 0.01) l.box(material, (t0 + t1) / 2, (y0 + y1) / 2, 0, t1 - t0, y1 - y0, FINISH);
    };
    let t = 0;
    for (const h of holes) {
      panel(t, h.t0, 0, height);
      panel(h.t0, h.t1, 0, h.bottom);
      panel(h.t0, h.t1, h.top, height);
      t = Math.max(t, h.t1);
    }
    panel(t, length, 0, height);
  }
}

interface Span {
  t0: number;
  t1: number;
  bottom: number;
  top: number;
}

// Otwory leżące na tej krawędzi (równoległe, w odległości do połowy grubości ściany + zapas),
// rzutowane na nią jako przedziały [t0, t1] w metrach od początku krawędzi.
function openingSpans(p: Point, dx: number, dz: number, length: number, openings: PlanOpening[]): Span[] {
  const spans: Span[] = [];
  for (const o of openings) {
    if (o.type === 'folding') continue; // harmonijka stoi w pokoju, nie w ścianie
    const ox = o.b[0] - o.a[0];
    const oz = o.b[1] - o.a[1];
    const ol = Math.hypot(ox, oz);
    if (ol < 0.05 || Math.abs(dx * oz - dz * ox) / ol > 0.1) continue;
    const mx = (o.a[0] + o.b[0]) / 2 - p[0];
    const mz = (o.a[1] + o.b[1]) / 2 - p[1];
    if (Math.abs(mx * dz - mz * dx) > o.thickness / 2 + 0.08) continue;
    const ta = (o.a[0] - p[0]) * dx + (o.a[1] - p[1]) * dz;
    const tb = (o.b[0] - p[0]) * dx + (o.b[1] - p[1]) * dz;
    const t0 = Math.max(0, Math.min(ta, tb));
    const t1 = Math.min(length, Math.max(ta, tb));
    if (t1 - t0 > 0.05) spans.push({ t0, t1, bottom: o.type === 'window' ? o.sill : 0, top: o.height });
  }
  return spans.sort((a, b) => a.t0 - b.t0);
}

// Balkon: posadzka z obrzeżem płyty i balustrada z pionowych prętów na krawędziach,
// przy których nie stoi ściana budynku.
export function buildBalcony(sink: PartSink, b: PlanBalcony, walls: PlanWall[], floorMaterial: MaterialName): void {
  const l = new Local(sink, new THREE.Matrix4());
  const top = -0.03; // posadzka balkonu nieco niżej niż podłoga mieszkania
  l.flat(floorMaterial, b.polygon, top);
  const railing = b.railingHeight ?? 1.1;
  const n = b.polygon.length;
  for (let i = 0; i < n; i++) {
    const p = b.polygon[i];
    const q = b.polygon[(i + 1) % n];
    const length = Math.hypot(q[0] - p[0], q[1] - p[1]);
    if (length < 0.05) continue;
    const mid: Point = [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2];
    const edge = new Local(
      sink,
      new THREE.Matrix4().makeTranslation(p[0], 0, p[1]).multiply(new THREE.Matrix4().makeRotationY(-Math.atan2(q[1] - p[1], q[0] - p[0]))),
    );
    edge.box('cien', length / 2, top - 0.08, 0, length, 0.16, 0.04); // czoło płyty
    if (walls.some((w) => distanceToSegment(mid, w.a, w.b) <= w.thickness / 2 + 0.25)) continue;
    const bars = Math.max(2, Math.round(length / 0.11));
    for (let k = 0; k <= bars; k++) {
      const x = (length * k) / bars;
      const corner = k === 0 || k === bars;
      edge.box('stal_czarna', x, top + railing / 2, 0, corner ? 0.04 : 0.016, railing, corner ? 0.04 : 0.016);
    }
    edge.box('stal_czarna', length / 2, top + railing, 0, length + 0.04, 0.04, 0.05); // pochwyt
    edge.box('stal_czarna', length / 2, top + 0.1, 0, length, 0.03, 0.03);
  }
}

function distanceToSegment(p: Point, a: Point, b: Point): number {
  const vx = b[0] - a[0];
  const vz = b[1] - a[1];
  const len2 = vx * vx + vz * vz || 1e-9;
  const t = Math.max(0, Math.min(1, ((p[0] - a[0]) * vx + (p[1] - a[1]) * vz) / len2));
  return Math.hypot(p[0] - (a[0] + vx * t), p[1] - (a[1] + vz * t));
}
