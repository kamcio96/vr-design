import * as THREE from 'three';
import { Local, PartSink } from './parts';
import type { PlanOpening } from './planModel';

const FRAME = 0.05; // szerokość ościeżnicy / ramy okna
const LEAF = 0.04; // grubość skrzydła drzwi

// Otwór leży w przerwie między ścianami. Dokładamy nadproże, a dla okna murek pod parapetem,
// ramę i szybę; dla drzwi ościeżnicę i skrzydło otwarte o openAngle (jak łuk na rzucie).
export function buildOpening(sink: PartSink, o: PlanOpening, storeyHeight: number): void {
  const [ax, az] = o.a;
  const [bx, bz] = o.b;
  const dx = bx - ax;
  const dz = bz - az;
  const length = Math.hypot(dx, dz);
  if (length < 0.05) return;
  // Lokalny układ otworu: X wzdłuż a→b (od a w x = −length/2), Z w poprzek ściany (+Z = wektor (−dz, dx)).
  const base = new THREE.Matrix4()
    .makeTranslation((ax + bx) / 2, 0, (az + bz) / 2)
    .multiply(new THREE.Matrix4().makeRotationY(-Math.atan2(dz, dx)));
  const l = new Local(sink, base);
  const t = o.thickness;
  const top = Math.min(o.height, storeyHeight);

  if (o.type === 'folding') {
    folding(l, length, top, o.door?.leafMaterial ?? 'drewno');
    return;
  }
  l.slab('sciana', 0, 0, length, t, top, storeyHeight); // nadproże
  if (o.type === 'window') {
    l.slab('sciana', 0, 0, length, t, 0, o.sill); // murek pod parapetem
    const h = top - o.sill;
    l.box('rama_okna', 0, o.sill + FRAME / 2, 0, length, FRAME, 0.07);
    l.box('rama_okna', 0, top - FRAME / 2, 0, length, FRAME, 0.07);
    for (const sx of [-1, 1]) l.box('rama_okna', sx * (length / 2 - FRAME / 2), o.sill + h / 2, 0, FRAME, h, 0.07);
    l.box('szklo', 0, o.sill + h / 2, 0, length - 2 * FRAME, h - 2 * FRAME, 0.01);
    return;
  }

  // Ościeżnica: dwie pionowe listwy i górna, na całą grubość ściany.
  const frame = o.door?.frameMaterial ?? 'rama';
  for (const sx of [-1, 1]) l.box(frame, sx * (length / 2 - FRAME / 2), top / 2, 0, FRAME, top, t + 0.02);
  l.box(frame, 0, top - FRAME / 2, 0, length, FRAME, t + 0.02);

  const door = o.door;
  if (!door) return;
  const leafWidth = length - 2 * FRAME;
  const leafHeight = top - FRAME - 0.01;
  const hingeX = door.hinge === 'a' ? -length / 2 + FRAME : length / 2 - FRAME;
  const towardFree = door.hinge === 'a' ? 1 : -1; // kierunek od zawiasu do wolnej krawędzi (skrzydło zamknięte)
  const side = door.swing >= 0 ? 1 : -1;
  const hingeZ = side * (t / 2); // zawias na licu ściany po stronie otwierania
  const angle = THREE.MathUtils.degToRad(door.openAngle ?? 90);
  // Kierunek skrzydła po otwarciu: obrót od osi ściany w stronę `side`.
  const dirX = towardFree * Math.cos(angle);
  const dirZ = side * Math.sin(angle);
  const cx = hingeX + (dirX * leafWidth) / 2;
  const cz = hingeZ + (dirZ * leafWidth) / 2;
  const rot = -Math.atan2(dirZ, dirX);
  l.box(door.leafMaterial ?? 'skrzydlo', cx, leafHeight / 2 + 0.01, cz, leafWidth, leafHeight, LEAF, rot);
  // Klamka po obu stronach skrzydła, przy wolnej krawędzi.
  const hx = hingeX + dirX * (leafWidth - 0.07);
  const hz = hingeZ + dirZ * (leafWidth - 0.07);
  const nx = -dirZ;
  const nz = dirX;
  for (const s of [-1, 1]) l.box('stal', hx + s * nx * 0.04, 1.0, hz + s * nz * 0.04, 0.12, 0.02, 0.02, rot);
}

// Drzwi harmonijkowe otwarte: wąskie panele złożone w zygzak przy końcu "a" otworu (x = −length/2).
function folding(l: Local, length: number, height: number, material: string): void {
  const panels = Math.max(4, Math.round(length / 0.13));
  const pw = length / panels;
  const fold = THREE.MathUtils.degToRad(70); // kąt panelu względem linii drzwi
  const step = pw * Math.cos(fold); // ile zajmuje jeden złożony panel wzdłuż linii
  for (let i = 0; i < panels; i++) {
    const sign = i % 2 === 0 ? 1 : -1;
    const x = -length / 2 + step * (i + 0.5);
    l.box(material, x, height / 2, 0, pw, height - 0.02, 0.018, sign * fold); // zygzak: kolejne panele obrócone ±70°
  }
  l.box('stal', -length / 2 + (step * panels) / 2, height + 0.01, 0, step * panels + 0.02, 0.02, 0.03); // szyna
}
