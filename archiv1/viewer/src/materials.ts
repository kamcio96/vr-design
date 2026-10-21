import * as THREE from 'three';

// Definicja materiału w PlanModel (`materials`) i wbudowana. Tekstura to nazwa zestawu plików
// w public/textures: <texture>_diff.jpg (kolor), _nor.jpg (normalne), _rough.jpg (chropowatość).
// tileM: ile metrów zajmuje jedno powtórzenie tekstury. normalOnly: tylko faktura (normalne
// i chropowatość), kolor z `color` – np. tkanina w dowolnym odcieniu.
export interface MaterialDef {
  color?: number | string;
  texture?: string;
  tileM?: number;
  normalOnly?: boolean;
  roughness?: number;
  metalness?: number;
  transparent?: boolean;
  opacity?: number;
  emissive?: number | string;
  emissiveIntensity?: number;
  // Wzór rysowany w programie zamiast pliku: "linie" (dywan w czarne linie), "szkic" (grafika w ramie).
  pattern?: 'linie' | 'szkic';
}

// Wbudowane materiały mebli, stolarki i wykończeń. Plik projektu (PlanModel.materials) może je nadpisać.
export const DEFAULT_MATERIALS: Record<string, MaterialDef> = {
  tkanina: { color: 0x7d8792, roughness: 0.95 },
  poducha: { color: 0x949ea8, roughness: 0.95 },
  drewno: { color: 0xb08a60, roughness: 0.7 },
  bialy: { color: 0xefeeea, roughness: 0.6 },
  ceramika: { color: 0xfbfbfb, roughness: 0.25 },
  ciemny: { color: 0x2a2b2e, roughness: 0.4 },
  stal: { color: 0xb9bdc1, roughness: 0.3, metalness: 0.8 },
  stal_czarna: { color: 0x1f2022, roughness: 0.45, metalness: 0.6 },
  blat: { color: 0x8f7a63, roughness: 0.5 },
  cien: { color: 0xd3d8dc, roughness: 0.4 },
  rama: { color: 0xf6f6f4, roughness: 0.5 },
  rama_okna: { color: 0xf6f6f4, roughness: 0.5 },
  skrzydlo: { color: 0xe7e1d6, roughness: 0.6 },
  szklo: { color: 0xcfe6ee, roughness: 0.05, transparent: true, opacity: 0.28 },
  mebel: { color: 0xa8a39a, roughness: 0.8 },
  sciana: { color: 0xf2efe8, roughness: 0.9 },
  podloga: { texture: 'laminate_floor_02', tileM: 1.7, roughness: 0.6 },
  abazur: { color: 0xfaf7f0, roughness: 0.9, emissive: 0xfff1d6, emissiveIntensity: 0.35 },
  liscie: { color: 0x4f7a3a, roughness: 0.8 },
  doniczka: { color: 0xe9e6df, roughness: 0.7 },
  lustro: { color: 0xe4ecef, roughness: 0.03, metalness: 1.0 }, // odbija mapę otoczenia sceny
  poducha_dekor: { color: 0xc9cbcc, roughness: 0.95 },
  koc: { color: 0x5d6166, roughness: 1.0 },
  lodyga: { color: 0x3f5a2c, roughness: 0.9 },
  ziemia: { color: 0x3b2f25, roughness: 1.0 },
  obudowa: { color: 0xf2efe8, roughness: 0.9 }, // obudowa stelaża WC
  fartuch: { color: 0xd3d8dc, roughness: 0.5 }, // płytki nad blatem
  dywan: { color: 0xf3f3f1, roughness: 1.0, pattern: 'linie', tileM: 1.6 },
  grafika: { color: 0xffffff, roughness: 0.8, pattern: 'szkic', tileM: 0.5 },
};

// Średni kolor tekstury – używany, gdy obrazu nie da się wczytać (eksport GLB z wiersza poleceń).
const TEXTURE_COLORS: Record<string, number> = {
  laminate_floor_02: 0xc8a679,
  concrete_tiles_02: 0x8e8e8a,
  oak_veneer_01: 0xc9a77c,
};

// W Node (eksport GLB z wiersza poleceń) nie ma przeglądarki do wczytania obrazów: materiały bez tekstur.
const CAN_LOAD_IMAGES = typeof document !== 'undefined';
const TEXTURE_BASE: string = `${((import.meta as any).env?.BASE_URL ?? '/') as string}textures/`;

export class MaterialLibrary {
  private defs: Record<string, MaterialDef>;
  private cache = new Map<string, THREE.MeshStandardMaterial>();
  private textures = new Map<string, THREE.Texture>();
  private loader = CAN_LOAD_IMAGES ? new THREE.TextureLoader() : null;

  constructor(overrides: Record<string, MaterialDef> = {}) {
    this.defs = { ...DEFAULT_MATERIALS, ...overrides };
  }

  def(name: string): MaterialDef {
    return this.defs[name] ?? DEFAULT_MATERIALS.mebel;
  }

  // Długość powtórzenia tekstury w m (0 = materiał bez tekstury, UV niepotrzebne).
  tile(name: string): number {
    const d = this.def(name);
    return d.texture || d.pattern ? (d.tileM ?? 1) : 0;
  }

  get(name: string): THREE.MeshStandardMaterial {
    let m = this.cache.get(name);
    if (m) return m;
    const d = this.def(name);
    m = new THREE.MeshStandardMaterial({
      name,
      // Kolor przy teksturze koloru mnoży obraz, więc domyślnie biały; bez tekstury – średni kolor obrazu.
      color: d.color ?? (d.texture && !d.normalOnly ? (this.loader ? 0xffffff : (TEXTURE_COLORS[d.texture] ?? 0xcccccc)) : 0xcccccc),
      roughness: d.roughness ?? 0.8,
      metalness: d.metalness ?? 0,
      transparent: d.transparent ?? false,
      opacity: d.opacity ?? 1,
      emissive: d.emissive ?? 0x000000,
      emissiveIntensity: d.emissiveIntensity ?? 1,
      depthWrite: !(d.transparent ?? false),
    });
    if (d.texture && this.loader) {
      if (!d.normalOnly) m.map = this.texture(`${d.texture}_diff.jpg`, true);
      m.normalMap = this.texture(`${d.texture}_nor.jpg`, false);
      m.roughnessMap = this.texture(`${d.texture}_rough.jpg`, false);
    }
    if (d.pattern && CAN_LOAD_IMAGES) m.map = patternTexture(d.pattern);
    this.cache.set(name, m);
    return m;
  }

  private texture(file: string, color: boolean): THREE.Texture {
    let t = this.textures.get(file);
    if (!t) {
      t = this.loader!.load(TEXTURE_BASE + file);
      t.wrapS = t.wrapT = THREE.RepeatWrapping;
      t.anisotropy = 4;
      if (color) t.colorSpace = THREE.SRGBColorSpace;
      t.userData.mimeType = 'image/jpeg'; // eksport GLB zapisze JPG zamiast dużo większego PNG
      this.textures.set(file, t);
    }
    return t;
  }
}

// Współrzędne tekstur w metrach dla geometrii w układzie świata: każdą ścianę rzutujemy na płaszczyznę
// prostopadłą do dominującej osi jej normalnej. Dzięki temu deska czy płytka ma ten sam rozmiar
// na podłodze, ścianie i meblu, niezależnie od wymiarów bryły.
export function applyMetricUV(geometry: THREE.BufferGeometry, tileM: number): void {
  const pos = geometry.getAttribute('position');
  const nor = geometry.getAttribute('normal');
  const uv = new Float32Array(pos.count * 2);
  for (let i = 0; i < pos.count; i++) {
    const x = pos.getX(i);
    const y = pos.getY(i);
    const z = pos.getZ(i);
    const ax = Math.abs(nor.getX(i));
    const ay = Math.abs(nor.getY(i));
    const az = Math.abs(nor.getZ(i));
    let u: number;
    let v: number;
    if (ay >= ax && ay >= az) [u, v] = [x, -z];
    else if (ax >= az) [u, v] = [z, y];
    else [u, v] = [x, y];
    uv[i * 2] = u / tileM;
    uv[i * 2 + 1] = v / tileM;
  }
  geometry.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
}

// Wzory rysowane na canvasie (bez plików): stałe ziarno, więc wygląd się nie zmienia między uruchomieniami.
function patternTexture(kind: 'linie' | 'szkic'): THREE.Texture {
  const size = 512;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const g = canvas.getContext('2d')!;
  g.fillStyle = '#f4f4f2';
  g.fillRect(0, 0, size, size);
  let x = 12345;
  const rnd = () => (x = (x * 16807) % 2147483647) / 2147483647;
  g.strokeStyle = '#1b1b1b';
  g.lineCap = 'round';
  if (kind === 'linie') {
    // Geometryczny dywan: proste czarne linie przecinające się pod różnymi kątami.
    g.lineWidth = 6;
    for (let i = 0; i < 16; i++) {
      g.beginPath();
      g.moveTo(rnd() * size, rnd() * size);
      g.lineTo(rnd() * size, rnd() * size);
      g.stroke();
    }
  } else {
    // Czarno-białe grafiki: kilka swobodnych krzywych.
    g.lineWidth = 3;
    for (let i = 0; i < 12; i++) {
      g.beginPath();
      g.moveTo(rnd() * size, rnd() * size);
      g.bezierCurveTo(rnd() * size, rnd() * size, rnd() * size, rnd() * size, rnd() * size, rnd() * size);
      g.stroke();
    }
  }
  const t = new THREE.CanvasTexture(canvas);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}
