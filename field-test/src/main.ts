import * as THREE from 'three';

// Sonda do testu terenowego: sprawdza, jaki typ przestrzeni WebXR daje Quest
// (czy działa `unbounded`, czyli chodzenie bez granicy), mierzy dryf śledzenia
// na palikach i wysyła wyniki na laptopa. Konwencje: 1 jednostka = 1 m, Y w górę.

const REF_SPACES: XRReferenceSpaceType[] = ['unbounded', 'local-floor', 'local'];
const PATH_STEP = 0.05; // m, krótsze ruchy (drgania śledzenia) nie liczą się do dystansu
const TRACK_INTERVAL = 1; // s, co ile zapisujemy pozycję do śladu
const BTN_A = 4; // xr-standard: A/X
const BTN_B = 5; // xr-standard: B/Y

type Mode = 'immersive-ar' | 'immersive-vr';
type Vec = [number, number, number];

interface Marker {
  id: number;
  pos: Vec;
  placedAt: number; // s od startu sesji
  pathAtPlace: number;
  object: THREE.Object3D;
}

interface Measurement {
  markerId: number;
  at: number;
  offsetCm: Vec; // pozycja kontrolera minus pozycja znacznika
  horizontalCm: number;
  pathSinceMarkerM: number;
  maxDistanceM: number;
}

const report = {
  id: '',
  startedAt: '',
  mode: '' as Mode | '',
  referenceSpace: '',
  refSpaceErrors: {} as Record<string, string>,
  userAgent: navigator.userAgent,
  markers: [] as { id: number; pos: Vec; placedAt: number }[],
  measurements: [] as Measurement[],
  track: [] as [number, number, number][], // [s, x, z]
  pathM: 0,
  maxDistanceM: 0,
  endedAt: '',
};

// ---------- scena ----------

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(window.devicePixelRatio);
renderer.xr.enabled = true;
renderer.domElement.style.display = 'none';
document.body.appendChild(renderer.domElement);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(70, 1, 0.05, 100);
scene.add(new THREE.HemisphereLight(0xffffff, 0x444444, 2.5));

// Materiały siatki i znaczników współdzielą przezroczystość (przycisk A).
const fadeable: THREE.Material[] = [];
function fade<T extends THREE.Material>(m: T): T {
  m.transparent = true;
  fadeable.push(m);
  return m;
}

// Siatka 20 × 20 m co 1 m, środek w punkcie startu sesji.
const grid = new THREE.GridHelper(20, 20, 0xffd54a, 0x2fd6c8);
fade(grid.material as THREE.Material);
scene.add(grid);

// Kierunek „na wprost” w chwili startu (oś -Z) i krzyż w punkcie startu.
const forward = new THREE.Mesh(new THREE.BoxGeometry(0.04, 0.02, 3), fade(new THREE.MeshBasicMaterial({ color: 0xff4040 })));
forward.position.set(0, 0.01, -1.5);
scene.add(forward);
const origin = new THREE.Mesh(new THREE.RingGeometry(0.15, 0.2, 32), fade(new THREE.MeshBasicMaterial({ color: 0xff4040, side: THREE.DoubleSide })));
origin.rotation.x = -Math.PI / 2;
origin.position.y = 0.01;
scene.add(origin);

let opaque = true;
function toggleOpacity() {
  opaque = !opaque;
  for (const m of fadeable) m.opacity = opaque ? 1 : 0.25;
}

// ---------- znaczniki ----------

const markers: Marker[] = [];

function label(text: string) {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 128;
  const ctx = canvas.getContext('2d')!;
  ctx.fillStyle = '#ffd54a';
  ctx.font = 'bold 96px sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, 64, 64);
  const sprite = new THREE.Sprite(fade(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(canvas) })));
  sprite.scale.set(0.3, 0.3, 0.3);
  return sprite;
}

function placeMarker(pos: Vec, t: number) {
  const id = markers.length + 1;
  const object = new THREE.Group();
  // Słupek od podłogi do wysokości kontrolera + kulka dokładnie w punkcie pomiaru.
  const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.01, 0.01, 2, 8), fade(new THREE.MeshBasicMaterial({ color: 0xffd54a })));
  pole.position.set(pos[0], 1, pos[2]);
  const tip = new THREE.Mesh(new THREE.SphereGeometry(0.025, 16, 8), fade(new THREE.MeshBasicMaterial({ color: 0xff4040 })));
  tip.position.set(...pos);
  const tag = label(String(id));
  tag.position.set(pos[0], 2.2, pos[2]);
  object.add(pole, tip, tag);
  scene.add(object);
  for (const m of fadeable) m.opacity = opaque ? 1 : 0.25;

  markers.push({ id, pos, placedAt: t, pathAtPlace: report.pathM, object });
  report.markers.push({ id, pos: round3(pos), placedAt: round1(t) });
  hudNote = `Znacznik ${id} postawiony`;
  send();
}

function measure(pos: Vec, t: number) {
  if (markers.length === 0) {
    hudNote = 'Najpierw postaw znacznik (spust)';
    return;
  }
  const dist = (m: Marker) => Math.hypot(pos[0] - m.pos[0], pos[1] - m.pos[1], pos[2] - m.pos[2]);
  const nearest = markers.reduce((a, b) => (dist(b) < dist(a) ? b : a));
  const offset: Vec = [pos[0] - nearest.pos[0], pos[1] - nearest.pos[1], pos[2] - nearest.pos[2]];
  const m: Measurement = {
    markerId: nearest.id,
    at: round1(t),
    offsetCm: offset.map((v) => Math.round(v * 100)) as Vec,
    horizontalCm: Math.round(Math.hypot(offset[0], offset[2]) * 100),
    pathSinceMarkerM: round1(report.pathM - nearest.pathAtPlace),
    maxDistanceM: round1(report.maxDistanceM),
  };
  report.measurements.push(m);
  hudNote = `Znacznik ${m.markerId}: odchyłka ${m.horizontalCm} cm po ${m.pathSinceMarkerM} m`;
  send();
}

// ---------- HUD przy lewym kontrolerze ----------

const hudCanvas = document.createElement('canvas');
hudCanvas.width = 512;
hudCanvas.height = 320;
const hudCtx = hudCanvas.getContext('2d')!;
const hudTexture = new THREE.CanvasTexture(hudCanvas);
const hud = new THREE.Mesh(new THREE.PlaneGeometry(0.24, 0.15), new THREE.MeshBasicMaterial({ map: hudTexture, transparent: true }));
hud.visible = false;
scene.add(hud);
let hudNote = '';
let sendNote = '';

function drawHud(distance: number, fps: number) {
  const lines = [
    `Przestrzeń: ${report.referenceSpace}`,
    `Od startu: ${distance.toFixed(1)} m (max ${report.maxDistanceM.toFixed(1)} m)`,
    `Przebyto: ${report.pathM.toFixed(1)} m`,
    `FPS: ${fps}   Znaczniki: ${markers.length}`,
    hudNote,
    sendNote,
  ];
  hudCtx.fillStyle = 'rgba(0, 0, 0, 0.75)';
  hudCtx.fillRect(0, 0, hudCanvas.width, hudCanvas.height);
  hudCtx.fillStyle = '#fff';
  hudCtx.font = '30px sans-serif';
  lines.forEach((line, i) => hudCtx.fillText(line, 16, 44 + i * 48));
  hudTexture.needsUpdate = true;
}

// ---------- wysyłanie wyników ----------

async function send() {
  const body = JSON.stringify({ ...report, pathM: round1(report.pathM), maxDistanceM: round1(report.maxDistanceM) });
  try {
    localStorage.setItem(`field-test-${report.id}`, body);
  } catch {
    // brak localStorage (np. tryb prywatny) – zostaje wysyłka na laptopa
  }
  try {
    const res = await fetch('/api/results', { method: 'POST', body });
    sendNote = res.ok ? `Zapisano na laptopie ${new Date().toLocaleTimeString()}` : `Błąd zapisu: ${res.status}`;
  } catch {
    sendNote = 'Brak połączenia z laptopem';
  }
}

// ---------- sesja ----------

let refSpace: XRReferenceSpace | null = null;
let startTime = 0;
let lastSample: THREE.Vector2 | null = null;
let lastTrack = -Infinity;
const prevButtons = { a: false, b: false };
let frames = 0;
let fps = 0;
let fpsTime = 0;
let hudTime = 0;

async function start(mode: Mode) {
  const session = await navigator.xr!.requestSession(mode, {
    optionalFeatures: ['unbounded', 'local-floor', 'anchors', 'hit-test'],
  });

  // Pierwszy typ przestrzeni, który się uda, to główny wynik testu.
  report.refSpaceErrors = {};
  let chosen: XRReferenceSpaceType | null = null;
  for (const type of REF_SPACES) {
    try {
      await session.requestReferenceSpace(type);
      chosen = type;
      break;
    } catch (err) {
      report.refSpaceErrors[type] = String(err);
    }
  }
  if (!chosen) {
    await session.end();
    alert('Gogle nie udostępniły żadnej przestrzeni odniesienia.');
    return;
  }

  Object.assign(report, {
    id: `${new Date().toISOString().replace(/[:.]/g, '-')}_${mode === 'immersive-ar' ? 'MR' : 'VR'}_${chosen}`,
    startedAt: new Date().toISOString(),
    mode,
    referenceSpace: chosen,
    markers: [],
    measurements: [],
    track: [],
    pathM: 0,
    maxDistanceM: 0,
    endedAt: '',
  });
  for (const m of markers) scene.remove(m.object);
  markers.length = 0;
  lastSample = null;
  lastTrack = -Infinity;
  hudNote = sendNote = '';

  // W VR nie widać rzeczywistości – ciemne tło; w MR przezroczyste (passthrough).
  scene.background = mode === 'immersive-vr' ? new THREE.Color(0x101820) : null;

  renderer.xr.setReferenceSpaceType(chosen);
  await renderer.xr.setSession(session);
  refSpace = renderer.xr.getReferenceSpace();
  startTime = performance.now() / 1000;
  hud.visible = true;

  session.addEventListener('selectstart', (e) => onPress(e, 'select'));
  session.addEventListener('squeezestart', (e) => onPress(e, 'squeeze'));
  session.addEventListener('end', () => {
    report.endedAt = new Date().toISOString();
    hud.visible = false;
    refSpace = null;
    send();
  });
  send();
}

function elapsed() {
  return performance.now() / 1000 - startTime;
}

function onPress(e: XRInputSourceEvent, kind: 'select' | 'squeeze') {
  if (e.inputSource.handedness !== 'right' || !refSpace) return;
  const space = e.inputSource.gripSpace ?? e.inputSource.targetRaySpace;
  const pose = e.frame.getPose(space, refSpace);
  if (!pose) {
    hudNote = 'Brak pozycji kontrolera – spróbuj ponownie';
    return;
  }
  const p = pose.transform.position;
  const pos: Vec = [p.x, p.y, p.z];
  if (kind === 'select') placeMarker(pos, elapsed());
  else measure(pos, elapsed());
}

function update(time: number, frame: XRFrame) {
  if (!refSpace) return;
  const t = elapsed();

  const viewer = frame.getViewerPose(refSpace);
  if (viewer) {
    const { x, z } = viewer.transform.position;
    const here = new THREE.Vector2(x, z);
    const distance = here.length();
    report.maxDistanceM = Math.max(report.maxDistanceM, distance);
    if (!lastSample) lastSample = here;
    else if (here.distanceTo(lastSample) > PATH_STEP) {
      report.pathM += here.distanceTo(lastSample);
      lastSample = here;
    }
    if (t - lastTrack >= TRACK_INTERVAL) {
      report.track.push([round1(t), round2(x), round2(z)]);
      lastTrack = t;
    }

    frames++;
    if (time - fpsTime >= 1000) {
      fps = frames;
      frames = 0;
      fpsTime = time;
    }
    if (time - hudTime >= 250) {
      drawHud(distance, fps);
      hudTime = time;
    }
  }

  for (const source of frame.session.inputSources) {
    if (source.handedness === 'left' && source.gripSpace) {
      // HUD unosi się nad lewym kontrolerem, jak tarcza zegarka.
      const pose = frame.getPose(source.gripSpace, refSpace);
      if (pose) {
        hud.matrix.fromArray(pose.transform.matrix);
        hud.matrix.decompose(hud.position, hud.quaternion, hud.scale);
        hud.translateY(0.1);
        hud.rotateX(-Math.PI / 4);
      }
    }
    if (source.handedness === 'right' && source.gamepad) {
      const a = source.gamepad.buttons[BTN_A]?.pressed ?? false;
      const b = source.gamepad.buttons[BTN_B]?.pressed ?? false;
      if (a && !prevButtons.a) toggleOpacity();
      if (b && !prevButtons.b) send();
      prevButtons.a = a;
      prevButtons.b = b;
    }
  }
}

// Renderujemy tylko w goglach – strona startowa to zwykły HTML.
renderer.setAnimationLoop((time, frame) => {
  if (!frame) return;
  update(time, frame);
  renderer.render(scene, camera);
});

// ---------- strona startowa ----------

const status = document.getElementById('status')!;
const startMr = document.getElementById('start-mr') as HTMLButtonElement;
const startVr = document.getElementById('start-vr') as HTMLButtonElement;

async function init() {
  if (!navigator.xr) {
    status.textContent = window.isSecureContext
      ? 'Ta przeglądarka nie obsługuje WebXR. Otwórz stronę w przeglądarce gogli Quest.'
      : 'Strona nie jest otwarta przez HTTPS – WebXR nie zadziała.';
    return;
  }
  const [ar, vr] = await Promise.all([
    navigator.xr.isSessionSupported('immersive-ar'),
    navigator.xr.isSessionSupported('immersive-vr'),
  ]);
  startMr.disabled = !ar;
  startVr.disabled = !vr;
  status.textContent = ar || vr ? 'Gotowe. Stań przy pierwszym paliku i wybierz tryb.' : 'Gogle nie obsługują sesji immersyjnych.';
}

function bindStart(button: HTMLButtonElement, mode: Mode) {
  button.addEventListener('click', () =>
    start(mode).catch((err) => {
      status.textContent = `Nie udało się uruchomić sesji: ${err}`;
    }),
  );
}
bindStart(startMr, 'immersive-ar');
bindStart(startVr, 'immersive-vr');
init();

function round1(v: number) {
  return Math.round(v * 10) / 10;
}
function round2(v: number) {
  return Math.round(v * 100) / 100;
}
function round3(v: Vec): Vec {
  return v.map((x) => Math.round(x * 1000) / 1000) as Vec;
}
