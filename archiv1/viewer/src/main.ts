import * as THREE from 'three';
import { PointerLockControls } from 'three/examples/jsm/controls/PointerLockControls.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { VRButton } from 'three/examples/jsm/webxr/VRButton.js';
import { ARButton } from 'three/examples/jsm/webxr/ARButton.js';
import { buildPlan, isPlanModel } from './planModel';
import { exportGlb } from './exportGlb';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';

// Konwencje projektu: 1 jednostka = 1 m, oś Y w górę, podłoga na y = 0.
const EYE_HEIGHT = 1.6;
const WALK_SPEED = 1.4; // m/s, zwykły krok
const RUN_SPEED = 3.0;
const START = new THREE.Vector3(0, EYE_HEIGHT, 1.5);
const start = START.clone(); // punkt startu dla bieżącego modelu (klawisz R, wyjście z VR)
const SKY = new THREE.Color(0xbfd8ee);

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.xr.enabled = true;
renderer.xr.setReferenceSpaceType('local-floor');
document.body.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = SKY;

const camera = new THREE.PerspectiveCamera(70, window.innerWidth / window.innerHeight, 0.05, 200);
camera.position.copy(START);

// Neutralne oświetlenie liczone na bieżąco (bez lightmap). Mapa otoczenia (jasne, wirtualne wnętrze
// liczone raz przy starcie) daje odbicia na metalu, szkle i lustrze oraz miękkie światło rozproszone.
scene.environment = new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.04).texture;
scene.environmentIntensity = 0.5;
scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8a80, 1.4));
const sun = new THREE.DirectionalLight(0xffffff, 1.2);
sun.position.set(5, 10, 3);
scene.add(sun);

// Siatka co 1 m ułatwia ocenę skali.
const grid = new THREE.GridHelper(20, 20, 0x666666, 0x999999);
grid.position.y = 0.001;
scene.add(grid);

const ground = new THREE.Mesh(
  new THREE.PlaneGeometry(40, 40),
  new THREE.MeshStandardMaterial({ color: 0x9fb48a }),
);
ground.rotation.x = -Math.PI / 2;
scene.add(ground);

// ---------- przykładowy pokój 4 × 5 m ----------

function box(w: number, h: number, d: number, color: number, x: number, y: number, z: number) {
  const mesh = new THREE.Mesh(
    new THREE.BoxGeometry(w, h, d),
    new THREE.MeshStandardMaterial({ color }),
  );
  mesh.position.set(x, y, z);
  return mesh;
}

function sampleRoom() {
  const room = new THREE.Group();
  const W = 4; // szerokość (oś X)
  const D = 5; // głębokość (oś Z)
  const H = 2.6; // wysokość w świetle
  const T = 0.12; // grubość ściany działowej
  const wall = 0xf2efe8;

  // podłoga
  room.add(box(W, 0.02, D, 0xc8a679, 0, 0.01, 0));

  // ściana tylna (z = -D/2) z oknem 1,2 × 1,4 m na parapecie 0,9 m
  const winW = 1.2, winH = 1.4, sill = 0.9;
  const side = (W - winW) / 2;
  room.add(box(side, H, T, wall, -W / 2 + side / 2, H / 2, -D / 2));
  room.add(box(side, H, T, wall, W / 2 - side / 2, H / 2, -D / 2));
  room.add(box(winW, sill, T, wall, 0, sill / 2, -D / 2));
  room.add(box(winW, H - sill - winH, T, wall, 0, H - (H - sill - winH) / 2, -D / 2));

  // ściany boczne
  room.add(box(T, H, D, wall, -W / 2, H / 2, 0));
  room.add(box(T, H, D, wall, W / 2, H / 2, 0));

  // ściana przednia (z = +D/2) z drzwiami 0,9 × 2,05 m
  const doorW = 0.9, doorH = 2.05, doorX = 1.0;
  const leftW = W / 2 + doorX - doorW / 2;
  const rightW = W / 2 - doorX - doorW / 2;
  room.add(box(leftW, H, T, wall, -W / 2 + leftW / 2, H / 2, D / 2));
  room.add(box(rightW, H, T, wall, W / 2 - rightW / 2, H / 2, D / 2));
  room.add(box(doorW, H - doorH, T, wall, doorX, doorH + (H - doorH) / 2, D / 2));

  // proste bryły mebli
  room.add(box(2.0, 0.45, 0.9, 0x5a6b8c, -0.6, 0.225, -1.9)); // kanapa – siedzisko
  room.add(box(2.0, 0.4, 0.2, 0x5a6b8c, -0.6, 0.65, -2.25)); // kanapa – oparcie
  room.add(box(1.0, 0.45, 0.6, 0x7a5a3a, -0.6, 0.225, -0.6)); // stolik
  room.add(box(1.6, 0.5, 0.4, 0x333333, -0.6, 0.25, 2.2)); // szafka RTV
  room.add(box(1.2, 0.7, 0.05, 0x111111, -0.6, 1.0, 2.25)); // TV

  return room;
}

let model: THREE.Object3D = sampleRoom();
scene.add(model);

// ---------- sterowanie WASD + mysz ----------

const controls = new PointerLockControls(camera, renderer.domElement);
renderer.domElement.addEventListener('click', () => {
  if (!renderer.xr.isPresenting) controls.lock();
});

const keys = new Set<string>();
window.addEventListener('keydown', (e) => {
  keys.add(e.code);
  if (e.code === 'KeyR') {
    camera.position.copy(start);
    camera.rotation.set(0, 0, 0);
  }
});
window.addEventListener('keyup', (e) => keys.delete(e.code));

const clock = new THREE.Clock();

function move(dt: number) {
  if (!controls.isLocked || renderer.xr.isPresenting) return;
  const speed = (keys.has('ShiftLeft') || keys.has('ShiftRight') ? RUN_SPEED : WALK_SPEED) * dt;
  const forward = (keys.has('KeyW') ? 1 : 0) - (keys.has('KeyS') ? 1 : 0);
  const right = (keys.has('KeyD') ? 1 : 0) - (keys.has('KeyA') ? 1 : 0);
  controls.moveForward(forward * speed);
  controls.moveRight(right * speed);
  camera.position.y = EYE_HEIGHT;
}

// ---------- wczytywanie GLB i PlanModel (przeciągnij i upuść albo ?plan=adres.json) ----------

const loader = new GLTFLoader();
const dropOverlay = document.getElementById('drop')!;
let modelName = 'pokoj-testowy'; // nazwa pliku przy „Pobierz GLB”

function showModel(obj: THREE.Object3D) {
  scene.remove(model);
  model = obj;
  scene.add(model);
  camera.position.copy(start);
}

function loadPlan(data: unknown) {
  if (!isPlanModel(data)) throw new Error('To nie jest plik PlanModel (brak schemaVersion/walls).');
  // PlanModel ma środek budynku w (0, 0), więc startujemy w środku domu.
  start.set(0, EYE_HEIGHT, 0);
  showModel(buildPlan(data));
  modelName = data.source.file.replace(/\.[^.]+$/, '');
}

const planUrl = new URLSearchParams(location.search).get('plan');
if (planUrl) {
  fetch(planUrl)
    .then((res) => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    })
    .then(loadPlan)
    .catch((err) => alert(`Nie udało się wczytać planu ${planUrl}:\n${err}`));
}

window.addEventListener('dragover', (e) => {
  e.preventDefault();
  dropOverlay.style.display = 'flex';
});
window.addEventListener('dragleave', () => (dropOverlay.style.display = 'none'));
window.addEventListener('drop', async (e) => {
  e.preventDefault();
  dropOverlay.style.display = 'none';
  const file = e.dataTransfer?.files[0];
  if (!file) return;
  try {
    if (file.name.toLowerCase().endsWith('.json')) {
      loadPlan(JSON.parse(await file.text()));
      return;
    }
    const gltf = await loader.parseAsync(await file.arrayBuffer(), '');
    placeOnFloor(gltf.scene);
    start.copy(START);
    showModel(gltf.scene);
    modelName = file.name.replace(/\.[^.]+$/, '');
  } catch (err) {
    alert(`Nie udało się wczytać pliku ${file.name}:\n${err}`);
  }
});

// Pobranie bieżącego modelu jako GLB (np. do obejrzenia w Sketchfab).
document.getElementById('download-glb')!.addEventListener('click', async () => {
  const glb = await exportGlb(model);
  const link = document.createElement('a');
  link.href = URL.createObjectURL(new Blob([glb], { type: 'model/gltf-binary' }));
  link.download = `${modelName}.glb`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000); // natychmiastowe zwolnienie psuje pobieranie w części przeglądarek
});

// Środek modelu nad punktem (0, 0), spód na podłodze. Skali nie zmieniamy –
// model ma być w metrach, a błędna skala ma być od razu widoczna.
function placeOnFloor(obj: THREE.Object3D) {
  const bbox = new THREE.Box3().setFromObject(obj);
  const center = bbox.getCenter(new THREE.Vector3());
  obj.position.x -= center.x;
  obj.position.z -= center.z;
  obj.position.y -= bbox.min.y;
}

// ---------- VR / MR (passthrough) ----------

const vrButton = VRButton.createButton(renderer, { optionalFeatures: ['local-floor'] });
const arButton = ARButton.createButton(renderer, { optionalFeatures: ['local-floor'] });
document.body.appendChild(vrButton);
document.body.appendChild(arButton);
// Oba przyciski Three.js ustawiają się w tym samym miejscu – rozsuwamy je.
vrButton.style.left = 'calc(50% - 160px)';
arButton.style.left = 'calc(50% + 10px)';

renderer.xr.addEventListener('sessionstart', () => {
  const session = renderer.xr.getSession();
  // W MR (passthrough) tło i grunt muszą zniknąć, żeby było widać rzeczywistość.
  const passthrough = session?.environmentBlendMode === 'alpha-blend';
  scene.background = passthrough ? null : SKY;
  ground.visible = !passthrough;
  grid.visible = !passthrough;
});
renderer.xr.addEventListener('sessionend', () => {
  scene.background = SKY;
  ground.visible = true;
  grid.visible = true;
  camera.position.copy(start);
});

// ---------- pętla ----------

window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

renderer.setAnimationLoop(() => {
  move(clock.getDelta());
  renderer.render(scene, camera);
});
