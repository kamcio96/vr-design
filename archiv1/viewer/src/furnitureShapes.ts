import { Local } from './parts';

// Kształty mebli z prostych brył, w układzie lokalnym mebla: szerokość w (X), głębokość d (Z),
// wysokość h; przód w +Z, tył (ściana, oparcie) w −Z. Typy nadaje importer (plan2model/furniture.py).
export type ShapeParams = Record<string, unknown>;
type Builder = (l: Local, w: number, d: number, h: number, p: ShapeParams) => void;

const sofa: Builder = (l, w, d, h, p) => {
  const seats = Math.max(1, Math.min(4, Number(p.seats ?? Math.round(w / 0.65)) || 1));
  const arm = Math.min(0.18, w * 0.14);
  const back = Math.min(0.22, d * 0.28);
  const seatTop = 0.45;
  // stopki
  for (const sx of [-1, 1]) for (const sz of [-1, 1]) l.slab('ciemny', sx * (w / 2 - 0.06), sz * (d / 2 - 0.06), 0.04, 0.04, 0, 0.06);
  l.slab('tkanina', 0, 0, w, d, 0.06, 0.32); // rama
  l.slab('tkanina', 0, -d / 2 + back / 2, w, back, 0.32, h); // oparcie
  for (const sx of [-1, 1]) l.slab('tkanina', sx * (w / 2 - arm / 2), 0, arm, d, 0.32, 0.62); // podłokietniki
  const inner = w - 2 * arm;
  const cw = inner / seats;
  const seatDepth = d - back;
  for (let i = 0; i < seats; i++) {
    const cx = -inner / 2 + cw * (i + 0.5);
    l.slab('poducha', cx, -d / 2 + back + seatDepth / 2, cw - 0.02, seatDepth - 0.02, 0.32, seatTop); // siedzisko
    l.box('poducha', cx, (seatTop + h) / 2 - 0.02, -d / 2 + back + 0.07, cw - 0.03, h - seatTop - 0.06, 0.14); // poducha oparcia
  }
  // Poduszki ozdobne oparte o oparcie, lekko obrócone; koc przerzucony przez siedzisko i podłokietnik.
  const pillows = Math.max(0, Math.min(4, Number(p.pillows ?? 0) || 0));
  for (let i = 0; i < pillows; i++) {
    const t = pillows === 1 ? 0.5 : i / (pillows - 1);
    const cx = (-inner / 2 + 0.22) + t * (inner - 0.44);
    l.box('poducha_dekor', cx, seatTop + 0.17, -d / 2 + back + 0.17, 0.34, 0.3, 0.1, (i % 2 ? -1 : 1) * 0.2);
  }
  if (p.throw) {
    const tx = inner / 2 - cw / 2;
    l.slab('koc', tx, -d / 2 + back + seatDepth / 2 + 0.05, cw * 0.8, seatDepth * 0.7, seatTop, seatTop + 0.03);
    l.slab('koc', w / 2 - arm / 2, 0.05, arm + 0.02, d * 0.55, 0.62, 0.645);
    l.box('koc', w / 2 + 0.005, 0.45, 0.05, 0.02, 0.36, d * 0.55);
  }
};

const roundTable: Builder = (l, w, _d, h) => {
  l.cylinder('drewno', 0, 0, w / 2, h - 0.03, h, { segments: 32 });
  l.cylinder('ciemny', 0, 0, 0.04, 0.03, h - 0.03);
  l.cylinder('ciemny', 0, 0, Math.min(0.25, w * 0.35), 0, 0.03);
};

const table: Builder = (l, w, d, h) => {
  l.slab('drewno', 0, 0, w, d, h - 0.04, h);
  const leg = 0.05;
  for (const sx of [-1, 1]) for (const sz of [-1, 1]) l.slab('drewno', sx * (w / 2 - leg), sz * (d / 2 - leg), leg, leg, 0, h - 0.04);
};

const wardrobe: Builder = (l, w, d, h, p) => {
  l.slab('ciemny', 0, 0.02, w - 0.02, d - 0.06, 0, 0.08); // cokół cofnięty
  l.slab('bialy', 0, 0, w, d, 0.08, h);
  const modules = Math.max(1, Number(p.modules ?? 1) || 1);
  const doors = modules * (w / modules > 0.7 ? 2 : 1);
  const front = d / 2 + 0.003;
  for (let i = 1; i < doors; i++) l.box('ciemny', -w / 2 + (w * i) / doors, (h + 0.08) / 2, front, 0.006, h - 0.1, 0.004);
  for (let i = 0; i < doors; i++) {
    const left = -w / 2 + (w * i) / doors;
    const right = left + w / doors;
    const x = i % 2 === 0 ? right - 0.05 : left + 0.05; // uchwyty przy styku par drzwi
    l.box('stal', x, 1.05, front + 0.01, 0.015, 0.3, 0.02);
  }
};

const tv: Builder = (l, w, d, h, p) => {
  if (p.wall) {
    // Sam ekran zawieszony na ścianie (bez szafki RTV), środek ekranu na wysokości ok. 1,2 m.
    const sh = w * 0.57;
    l.box('ciemny', 0, Math.max(1.2, sh / 2 + 0.3), -d / 2 + 0.03, w, sh, 0.04);
    return;
  }
  const cabinet = Math.min(h, 0.45);
  l.slab('drewno', 0, 0, w, d, 0.05, cabinet);
  l.slab('ciemny', 0, 0, w - 0.04, d - 0.04, 0, 0.05);
  for (let i = 1; i < 3; i++) l.box('ciemny', -w / 2 + (w * i) / 3, cabinet / 2 + 0.025, d / 2 + 0.002, 0.005, cabinet - 0.07, 0.004);
  const sw = Math.min(1.25, w * 0.8);
  const sh = sw * 0.57;
  l.slab('ciemny', 0, -d / 6, 0.25, 0.18, cabinet, cabinet + 0.02); // podstawa
  l.slab('ciemny', 0, -d / 6, 0.05, 0.03, cabinet + 0.02, cabinet + 0.1);
  l.box('ciemny', 0, cabinet + 0.1 + sh / 2, -d / 6, sw, sh, 0.035); // ekran
};

const counter: Builder = (l, w, d, h, p) => {
  const top = Math.max(0.8, h);
  l.slab('ciemny', 0, -0.03, w, d - 0.08, 0, 0.1); // cokół
  l.slab('bialy', 0, -0.015, w, d - 0.03, 0.1, top - 0.04); // szafki
  l.slab('blat', 0, 0.005, w, d + 0.01, top - 0.04, top); // blat z nawisem
  const fronts = Math.max(1, Math.round(w / 0.6));
  for (let i = 1; i < fronts; i++) l.box('ciemny', -w / 2 + (w * i) / fronts, (top - 0.04 + 0.1) / 2, d / 2 - 0.013, 0.005, top - 0.16, 0.004);
  if (p.backsplash) l.box('fartuch', 0, top + 0.3, -d / 2 + 0.006, w, 0.6, 0.012); // płytki na ścianie nad blatem
};

const cooktop: Builder = (l, w, d, h) => {
  const top = Math.max(0.8, h);
  const pw = Math.min(w, 0.6);
  const pd = Math.min(d - 0.06, 0.52);
  l.slab('ciemny', 0, -0.01, pw, pd, top, top + 0.006);
  for (const sx of [-1, 1]) for (const sz of [-1, 1]) {
    l.cylinder('stal', sx * pw * 0.24, -0.01 + sz * pd * 0.24, Math.min(pw, pd) * 0.17, top + 0.006, top + 0.008, { open: true, segments: 24 });
  }
};

const sink: Builder = (l, w, d, h) => {
  const top = Math.max(0.8, h);
  const sw = Math.min(w, 0.8);
  const sd = Math.min(d - 0.1, 0.48);
  l.slab('stal', 0, 0, sw, sd, top, top + 0.004);
  l.slab('ciemny', -sw * 0.15, 0.01, sw * 0.55, sd * 0.75, top + 0.004, top + 0.006); // komora
  l.cylinder('stal', sw * 0.12, -sd / 2 - 0.02, 0.018, top, top + 0.3); // bateria
  l.box('stal', sw * 0.12, top + 0.3, -sd / 2 + 0.07, 0.025, 0.025, 0.18);
};

const shower: Builder = (l, w, d, h, p) => {
  // Brodzik ćwiartka koła w narożniku przy dwóch ścianach; corner = "left-top" itd. (od strony ścian).
  const corner = String(p.corner ?? 'left-top');
  const sx = corner.startsWith('left') ? 1 : -1; // kierunek od narożnika w głąb pokoju
  const sz = corner.endsWith('top') ? 1 : -1;
  const cx = -sx * (w / 2);
  const cz = -sz * (d / 2);
  const r = Math.min(w, d);
  const start = sx > 0 ? (sz > 0 ? 0 : Math.PI / 2) : sz > 0 ? (3 * Math.PI) / 2 : Math.PI;
  const quarter = { thetaStart: start, thetaLength: Math.PI / 2, segments: 16 };
  l.cylinder('ceramika', cx, cz, r, 0, 0.06, quarter);
  l.cylinder('szklo', cx, cz, r - 0.02, 0.06, Math.min(h, 2.0), { ...quarter, open: true });
  l.cylinder('stal', cx + sx * 0.12, cz + sz * 0.12, 0.05, 1.95, 1.97); // deszczownica
  l.cylinder('stal', cx + sx * 0.04, cz + sz * 0.04, 0.012, 1.0, 1.97);
};

const toilet: Builder = (l, w, d, h, p) => {
  if (p.wallHung) {
    // WC podwieszane: obudowa stelaża (np. w płytkach) z przyciskiem i miska nad podłogą.
    const box = 0.22;
    l.slab('obudowa', 0, -d / 2 + box / 2, Math.max(w, 0.6), box, 0, Math.max(h, 1.15));
    l.box('stal', 0, 1.0, -d / 2 + box + 0.003, 0.24, 0.16, 0.008);
    const bd = Math.min(0.55, d - box + 0.1);
    const bz = -d / 2 + box + bd / 2 - 0.02;
    l.cylinder('ceramika', 0, bz, 0.5, 0.26, 0.4, { radiusTop: 0.5, sx: 0.36, sz: bd, segments: 24 });
    l.cylinder('ceramika', 0, bz - bd * 0.15, 0.5, 0.18, 0.26, { radiusTop: 0.5, sx: 0.22, sz: bd * 0.5, segments: 16 });
    l.cylinder('bialy', 0, bz, 0.5, 0.4, 0.425, { sx: 0.37, sz: bd, segments: 24 });
    return;
  }
  const tank = Math.min(0.2, d * 0.3);
  const bw = Math.min(w, 0.38);
  l.slab('ceramika', 0, -d / 2 + tank / 2, Math.min(w, 0.5), tank, 0, 0.82); // stelaż / zbiornik
  l.box('stal', 0, 0.72, -d / 2 + tank + 0.003, 0.2, 0.12, 0.006); // przycisk
  const bowlDepth = d - tank;
  const bz = -d / 2 + tank + bowlDepth / 2;
  l.cylinder('ceramika', 0, bz, 0.5, 0.05, 0.4, { radiusTop: 0.5, sx: bw, sz: bowlDepth, segments: 24 });
  l.cylinder('bialy', 0, bz, 0.5, 0.4, 0.43, { sx: bw, sz: bowlDepth, segments: 24 }); // deska
};

const washbasin: Builder = (l, w, d) => {
  l.slab('bialy', 0, -0.02, w - 0.04, d - 0.06, 0.2, 0.72); // szafka podumywalkowa
  l.slab('ceramika', 0, 0, w, d, 0.72, 0.85);
  l.cylinder('cien', 0, 0.02, 0.5, 0.85, 0.852, { sx: w * 0.62, sz: d * 0.6 }); // misa
  l.cylinder('stal', 0, -d / 2 + 0.06, 0.015, 0.85, 1.0);
  l.box('stal', 0, 1.0, -d / 2 + 0.11, 0.02, 0.02, 0.1);
};

const washer: Builder = (l, w, d, h) => {
  l.slab('bialy', 0, 0, w, d, 0, h);
  l.box('ciemny', 0, h - 0.06, d / 2 + 0.002, w - 0.04, 0.08, 0.004); // panel
  const r = Math.min(w, h) * 0.3;
  l.disc('stal', 0, h * 0.45, d / 2 + 0.01, r + 0.03, 0.02);
  l.disc('ciemny', 0, h * 0.45, d / 2 + 0.022, r, 0.006);
};

const bed: Builder = (l, w, d, h) => {
  l.slab('drewno', 0, 0, w, d, 0.05, 0.3);
  l.slab('bialy', 0, 0.02, w - 0.06, d - 0.06, 0.3, Math.max(h, 0.5));
  l.slab('drewno', 0, -d / 2 + 0.03, w, 0.06, 0.05, 0.95); // zagłówek
  const pillows = w > 1.2 ? 2 : 1;
  for (let i = 0; i < pillows; i++) l.slab('cien', -w / 2 + (w / pillows) * (i + 0.5), -d / 2 + 0.25, w / pillows - 0.12, 0.35, 0.5, 0.62);
};

const bathtub: Builder = (l, w, d, h) => {
  const t = 0.07;
  l.slab('ceramika', 0, 0, w, d, 0, 0.12);
  l.slab('ceramika', 0, -d / 2 + t / 2, w, t, 0.12, h);
  l.slab('ceramika', 0, d / 2 - t / 2, w, t, 0.12, h);
  l.slab('ceramika', -w / 2 + t / 2, 0, t, d - 2 * t, 0.12, h);
  l.slab('ceramika', w / 2 - t / 2, 0, t, d - 2 * t, 0.12, h);
};

const fridge: Builder = (l, w, d, h) => {
  l.slab('bialy', 0, 0, w, d, 0, h);
  l.box('ciemny', 0, h * 0.62, d / 2 + 0.002, w - 0.02, 0.006, 0.004);
  l.box('stal', w / 2 - 0.06, h * 0.75, d / 2 + 0.02, 0.02, 0.3, 0.03);
  l.box('stal', w / 2 - 0.06, h * 0.45, d / 2 + 0.02, 0.02, 0.3, 0.03);
};

const cabinet: Builder = (l, w, d, h) => {
  l.slab('bialy', 0, 0, w, d, 0, h - 0.03);
  l.slab('drewno', 0, 0, w, d, h - 0.03, h);
};

// ------------------------------------------------------------ dekoracje i wyposażenie z wizualizacji

const chair: Builder = (l, w, d, h) => {
  const seat = 0.46;
  for (const sx of [-1, 1]) for (const sz of [-1, 1]) {
    l.box('drewno', sx * (w / 2 - 0.06), seat / 2 - 0.03, sz * (d / 2 - 0.06), 0.03, seat - 0.06, 0.03);
  }
  l.slab('tkanina', 0, 0.02, w - 0.02, d - 0.06, seat - 0.07, seat); // siedzisko
  l.box('tkanina', 0, (seat + h) / 2, -d / 2 + 0.05, w - 0.02, h - seat, 0.07); // oparcie
  for (const sx of [-1, 1]) l.box('tkanina', sx * (w / 2 - 0.04), seat + 0.12, -d / 2 + 0.2, 0.06, 0.2, 0.3); // boki „muszli”
};

const floorLamp: Builder = (l, w, _d, h) => {
  // Trójnóg z drewna i biały abażur w kształcie bębna (jak na wizualizacji).
  const shadeH = Math.min(0.3, h * 0.2);
  const r = w / 2;
  for (let i = 0; i < 3; i++) {
    const a = (i * 2 * Math.PI) / 3;
    const fx = Math.sin(a) * r * 0.6;
    const fz = Math.cos(a) * r * 0.6;
    l.box('drewno', fx / 2, (h - shadeH) / 2, fz / 2, 0.025, h - shadeH, 0.025, a);
  }
  l.cylinder('abazur', 0, 0, r, h - shadeH, h, { radiusTop: r * 0.92, open: true, segments: 24 });
  l.cylinder('abazur', 0, 0, r * 0.3, h - shadeH * 0.6, h - shadeH * 0.55, { segments: 12 }); // żarówka
};

const pendantLamp: Builder = (l, w, _d, h, p) => {
  // elevation = dół abażuru; przewód do sufitu (params.ceiling, domyślnie 2,6 m nad podłogą).
  const ceilingAbove = Number(p.ceilingAbove ?? 1.0);
  l.cylinder('abazur', 0, 0, w / 2, 0, h, { open: true, segments: 28 });
  l.cylinder('abazur', 0, 0, w / 2 - 0.005, h - 0.01, h, { segments: 28 });
  l.cylinder('ciemny', 0, 0, 0.004, h, h + ceilingAbove, { segments: 6 });
};

// Prosty generator liczb z ziarna – ta sama roślina przy każdym przebudowaniu sceny.
function seeded(seed: number): () => number {
  let x = Math.floor(seed * 1e4) % 2147483647 || 1;
  return () => (x = (x * 16807) % 2147483647) / 2147483647;
}

const plant: Builder = (l, w, _d, h, p) => {
  const big = p.kind === 'monstera' || h > 0.8;
  const potH = Math.min(0.35, h * (big ? 0.28 : 0.4));
  const potR = w * (big ? 0.28 : 0.35);
  l.cylinder('doniczka', 0, 0, potR * 0.85, 0, potH, { radiusTop: potR, segments: 18 });
  l.cylinder('ziemia', 0, 0, potR * 0.95, potH - 0.02, potH - 0.01, { segments: 18 });
  const rnd = seeded(w * 7 + h * 13 + Number(p.seed ?? 0));
  const leaves = big ? 14 : 8;
  for (let i = 0; i < leaves; i++) {
    const a = rnd() * Math.PI * 2;
    const reach = (0.25 + rnd() * 0.75) * (w / 2);
    const y = potH + (0.2 + rnd() * 0.8) * (h - potH) * 0.85;
    const size = (big ? 0.16 : 0.07) + rnd() * (big ? 0.1 : 0.04);
    // łodyga od ziemi do liścia i liść jako spłaszczona, pochylona elipsoida
    const sx = Math.sin(a) * reach;
    const sz = Math.cos(a) * reach;
    l.box('lodyga', sx / 2, (potH + y) / 2, sz / 2, 0.012, y - potH, 0.012, a);
    l.ellipsoid('liscie', sx, y, sz, size, size * 0.06, size * 1.6, a, 0.6 + rnd() * 0.5, 14);
  }
};

const rug: Builder = (l, w, d) => l.slab('dywan', 0, 0, w, d, 0, 0.008);

const picture: Builder = (l, w, d, h) => {
  // elevation = dolna krawędź; przód (+Z) od ściany. Czarna rama, biały passe-partout, grafika.
  const f = 0.025;
  l.slab('ciemny', 0, 0, w, d, 0, h); // rama i tło
  l.box('bialy', 0, h / 2, d / 2 + 0.001, w - 2 * f, h - 2 * f, 0.002);
  l.box('grafika', 0, h / 2, d / 2 + 0.003, w * 0.6, h * 0.55, 0.002);
};

const mirror: Builder = (l, w, d, h) => {
  l.slab('ciemny', 0, 0, w, d, 0, h);
  l.box('lustro', 0, h / 2, d / 2 + 0.002, w - 0.03, h - 0.03, 0.003);
};

const books: Builder = (l, w, d, h) => {
  const rnd = seeded(w * 31 + d);
  const mats = ['bialy', 'ciemny', 'cien', 'drewno', 'poducha'];
  let x = -w / 2;
  for (let i = 0; x < w / 2 - 0.02; i++) {
    const bw = 0.02 + rnd() * 0.03;
    const bh = h * (0.7 + rnd() * 0.3);
    l.slab(mats[i % mats.length], x + bw / 2, 0, bw, d * (0.8 + rnd() * 0.2), 0, bh);
    x += bw + 0.002;
  }
};

const vase: Builder = (l, w, _d, h) => {
  l.cylinder('szklo', 0, 0, w / 2, 0, h * 0.45, { radiusTop: w * 0.35, segments: 16 });
  const rnd = seeded(w + h);
  for (let i = 0; i < 5; i++) {
    const a = rnd() * Math.PI * 2;
    const r = 0.03 + rnd() * 0.05;
    l.box('lodyga', Math.sin(a) * r / 2, h * 0.65, Math.cos(a) * r / 2, 0.006, h * 0.5, 0.006, a);
    l.ellipsoid(i % 2 ? 'liscie' : 'bialy', Math.sin(a) * r, h * (0.85 + rnd() * 0.15), Math.cos(a) * r, 0.025, 0.02, 0.025, 0, 0, 6);
  }
};

const sideTable: Builder = (l, w, _d, h) => {
  l.cylinder('stal_czarna', 0, 0, w / 2, h - 0.02, h, { segments: 24 });
  l.cylinder('stal_czarna', 0, 0, 0.015, 0, h - 0.02, { segments: 8 });
  l.cylinder('stal_czarna', 0, 0, w * 0.3, 0, 0.015, { segments: 16 });
};

const showerCabin: Builder = (l, w, d, h, p) => {
  // Kabina walk-in: brodzik równo z posadzką, szyby z listwą u góry, deszczownica przy tylnej ścianie.
  // params.glass: boki z szybą ("front", "left", "right"); szyba frontowa zostawia wejście przy prawym boku.
  const glass = (p.glass as string[] | undefined) ?? ['front', 'right'];
  const gh = Math.min(h, 2.0);
  l.slab('cien', 0, 0, w - 0.02, d - 0.02, 0.006, 0.012); // odpływ liniowy/brodzik
  l.box('stal', 0, 0.014, -d / 2 + 0.08, w * 0.7, 0.004, 0.05);
  if (glass.includes('front')) {
    const gw = w * 0.65;
    l.box('szklo', -w / 2 + gw / 2, gh / 2, d / 2, gw, gh, 0.008);
    l.box('stal_czarna', -w / 2 + gw / 2, gh, d / 2, gw, 0.02, 0.02);
  }
  for (const side of ['left', 'right'] as const) {
    if (!glass.includes(side)) continue;
    const x = side === 'left' ? -w / 2 : w / 2;
    l.box('szklo', x, gh / 2, 0, 0.008, gh, d);
    l.box('stal_czarna', x, gh, 0, 0.02, 0.02, d);
  }
  l.cylinder('stal_czarna', 0, -d / 2 + 0.25, 0.12, 2.0, 2.01, { segments: 20 }); // deszczownica
  l.box('stal_czarna', 0, 2.03, -d / 2 + 0.13, 0.015, 0.015, 0.26);
  l.box('stal_czarna', -w / 4, 1.1, -d / 2 + 0.03, 0.02, 1.0, 0.02); // drążek z baterią
};

const tallUnit: Builder = (l, w, d, h, p) => {
  // Wysoka zabudowa kuchenna; params.fridge: lodówka w dolnej części (dwa fronty).
  l.slab('ciemny', 0, -0.03, w, d - 0.06, 0, 0.1);
  l.slab('bialy', 0, 0, w, d, 0.1, h);
  const front = d / 2 + 0.002;
  const split = p.fridge ? 0.1 + (h - 0.1) * 0.6 : (h + 0.1) / 2;
  l.box('ciemny', 0, split, front, w - 0.01, 0.005, 0.004);
  l.box('stal', w / 2 - 0.05, split - 0.35, front + 0.012, 0.015, 0.4, 0.02);
  l.box('stal', w / 2 - 0.05, split + 0.25, front + 0.012, 0.015, 0.3, 0.02);
};

const shelf: Builder = (l, w, d, h) => l.slab('bialy', 0, 0, w, d, 0, Math.max(h, 0.025));

const cosmetics: Builder = (l, w, d) => {
  const rnd = seeded(w * 17 + d);
  const mats = ['bialy', 'ceramika', 'stal', 'liscie', 'cien'];
  for (let i = 0; i < 5; i++) {
    const x = -w / 2 + ((i + 0.5) * w) / 5;
    const r = 0.025 + rnd() * 0.015;
    l.cylinder(mats[i], x, (rnd() - 0.5) * d * 0.4, r, 0, 0.1 + rnd() * 0.12, { segments: 10 });
  }
};

const kettle: Builder = (l, w, _d, h) => {
  l.cylinder('ciemny', 0, 0, w * 0.45, 0, 0.02, { segments: 16 });
  l.cylinder('stal', 0, 0, w * 0.42, 0.02, h * 0.85, { radiusTop: w * 0.32, segments: 16 });
  l.box('ciemny', -w * 0.45, h * 0.55, 0, 0.03, h * 0.5, 0.03);
};

// ------------------------------------------------------------ ścianki działowe (od podłogi do sufitu)

const slats: Builder = (l, w, d, h) => {
  // Drewniane lamele: pionowe listwy 4 cm z prześwitami, listwa u dołu i u góry.
  const slat = 0.04;
  const count = Math.max(2, Math.round(w / 0.08));
  const step = (w - slat) / (count - 1);
  l.slab('drewno', 0, 0, w, d, 0, 0.04);
  l.slab('drewno', 0, 0, w, d, h - 0.04, h);
  for (let i = 0; i < count; i++) l.slab('drewno', -w / 2 + slat / 2 + i * step, 0, slat, d, 0.04, h - 0.04);
};

const slidingGlass: Builder = (l, w, d, h, p) => {
  // Przesuwna ściana szklana: szyny u dołu i u góry, skrzydła w cienkiej ramie na dwóch torach.
  const panels = Math.max(2, Number(p.panels ?? Math.round(w / 0.8)) || 2);
  const rail = 0.05;
  l.slab('rama_okna', 0, 0, w, d, 0, 0.02);
  l.slab('rama_okna', 0, 0, w, d, h - rail, h);
  const pw = w / panels + 0.03; // skrzydła zachodzą na siebie o 3 cm
  const f = 0.03; // szerokość ramy skrzydła
  for (let i = 0; i < panels; i++) {
    const cx = -w / 2 + (w * (i + 0.5)) / panels;
    const cz = (i % 2 ? 1 : -1) * d * 0.22;
    const x0 = Math.max(-w / 2 + pw / 2, Math.min(w / 2 - pw / 2, cx));
    const y0 = 0.02;
    const y1 = h - rail;
    l.slab('szklo', x0, cz, pw - 2 * f, 0.01, y0 + f, y1 - f);
    l.slab('rama_okna', x0, cz, pw, 0.03, y0, y0 + f);
    l.slab('rama_okna', x0, cz, pw, 0.03, y1 - f, y1);
    for (const sx of [-1, 1]) l.slab('rama_okna', x0 + sx * (pw / 2 - f / 2), cz, f, 0.03, y0 + f, y1 - f);
  }
};

const plainBox: Builder = (l, w, d, h) => l.slab('mebel', 0, 0, w, d, 0, h);

export const SHAPES: Record<string, Builder> = {
  kanapa: sofa,
  fotel: (l, w, d, h, p) => sofa(l, w, d, h, { ...p, seats: 1 }),
  stol_okragly: roundTable,
  stol: table,
  stolik: table,
  biurko: table,
  szafa: wardrobe,
  tv,
  blat: counter,
  plyta: cooktop,
  zlew: sink,
  prysznic: shower,
  wc: toilet,
  umywalka: washbasin,
  pralka: washer,
  lozko: bed,
  wanna: bathtub,
  lodowka: fridge,
  szafka: cabinet,
  krzeslo: chair,
  lampa_stojaca: floorLamp,
  lampa_wiszaca: pendantLamp,
  roslina: plant,
  dywan: rug,
  obraz: picture,
  lustro: mirror,
  ksiazki: books,
  wazon: vase,
  stolik_boczny: sideTable,
  kabina: showerCabin,
  zabudowa: tallUnit,
  polka: shelf,
  kosmetyki: cosmetics,
  czajnik: kettle,
  lamele: slats,
  scianka_szklana: slidingGlass,
};

export function buildShape(l: Local, type: string, w: number, d: number, h: number, params: ShapeParams = {}): void {
  (SHAPES[type] ?? plainBox)(l, w, d, h, params);
}
