import * as THREE from 'three';
import { exportGlb } from './geometry/exportGlb';
import { buildPlan, isPlanModel, type PlanModel } from './geometry/planModel';

// Trzy etapy przygotowania modelu: 1) wgranie rzutu, 2) podgląd rozpoznania i akceptacja,
// 3) zapis modelu 3D (GLB budowany tutaj, w przeglądarce, bo tylko ona wczyta tekstury).

type Status = 'do-akceptacji' | 'zaakceptowany' | 'odrzucony' | 'blad';

interface ProjectInfo {
  name: string;
  status: Status;
  updated: string;
  image: string;
  options: { widthM?: number; areas?: Record<string, number>; wallsOnly?: boolean };
  report?: string;
  hasGlb?: boolean;
}

const STATUS_TEXT: Record<Status, string> = {
  'do-akceptacji': 'czeka na akceptację',
  zaakceptowany: 'zaakceptowany, model 3D gotowy',
  odrzucony: 'odrzucony',
  blad: 'błąd rozpoznania',
};

const SCALE_TEXT: Record<string, string> = {
  'ocr-outline': 'z wymiarów zewnętrznych odczytanych z rzutu',
  'areas-total': 'z sumy powierzchni pomieszczeń',
  'manual-width': 'z podanej szerokości budynku',
  'manual-scale': 'podana ręcznie',
};

const app = document.getElementById('app')!;

function esc(s: unknown): string {
  return String(s ?? '').replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

function setStep(step: number, done: number) {
  for (const li of document.querySelectorAll<HTMLElement>('#steps li')) {
    const n = Number(li.dataset.step);
    li.classList.toggle('active', n === step);
    li.classList.toggle('done', n <= done && n !== step);
  }
}

async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error ?? `Błąd serwera (${res.status})`);
  return data as T;
}

function fileUrl(name: string, file: string): string {
  return `/projects/${encodeURIComponent(name)}/${file}?t=${Date.now()}`;
}

// Powierzchnie wpisane po jednej w wierszu: „Pokój 18,08”, „Pokój=18.08” lub „Pokój: 18.08 m²”.
function parseAreas(text: string): Record<string, number> | string {
  const areas: Record<string, number> = {};
  for (const raw of text.split('\n')) {
    const line = raw.replace(/m²|m2/gi, '').trim();
    if (!line) continue;
    const m = line.match(/^(.*?)[\s=:]+(\d+(?:[.,]\d+)?)$/);
    if (!m || !m[1].trim()) return `Nie rozumiem wiersza „${raw.trim()}”. Wpisz np. Pokój 18,08`;
    areas[m[1].trim()] = Number(m[2].replace(',', '.'));
  }
  return areas;
}

// ---------- Etap 1: lista projektów i wgranie nowego rzutu ----------

async function showHome() {
  setStep(1, 0);
  app.innerHTML = `
    <section>
      <h2>Nowy projekt: wgraj rzut</h2>
      <label>Nazwa projektu</label>
      <input type="text" id="name" placeholder="np. dom_kowalski" />
      <label>Rzut (PNG lub JPG)</label>
      <div class="drop" id="drop">Przeciągnij plik tutaj albo kliknij, żeby wybrać</div>
      <input type="file" id="file" accept="image/png,image/jpeg" hidden />
      <label>Skala <span class="hint">(zostaw puste, jeśli rzut ma wymiary zewnętrzne w cm; automat odczyta je sam)</span></label>
      <label class="hint">Szerokość budynku w metrach (zewnętrzna, poziomo na rzucie)</label>
      <input type="text" id="width" placeholder="np. 9,9" />
      <label class="hint">albo powierzchnie pomieszczeń z rzutu, po jednym w wierszu</label>
      <textarea id="areas" rows="5" placeholder="Pokój 18,08&#10;Łazienka 4,30&#10;Kuchnia 5,48"></textarea>
      <label><input type="checkbox" id="walls-only" /> bez mebli <span class="hint">(tylko ściany, drzwi, okna i pokoje)</span></label>
      <p><button class="primary" id="go">Rozpoznaj rzut</button> <span id="msg"></span></p>
    </section>
    <section>
      <h2>Projekty</h2>
      <div id="list">Wczytywanie…</div>
    </section>`;

  let file: File | null = null;
  const drop = document.getElementById('drop')!;
  const input = document.getElementById('file') as HTMLInputElement;
  const nameInput = document.getElementById('name') as HTMLInputElement;
  const pick = (f: File | undefined) => {
    if (!f) return;
    if (!/^image\/(png|jpeg)$/.test(f.type)) {
      drop.textContent = `To nie jest PNG ani JPG: ${f.name}`;
      return;
    }
    file = f;
    drop.textContent = `Wybrano: ${f.name}`;
    if (!nameInput.value) nameInput.value = f.name.replace(/\.[^.]+$/, '');
  };
  drop.addEventListener('click', () => input.click());
  input.addEventListener('change', () => pick(input.files?.[0]));
  drop.addEventListener('dragover', (e) => {
    e.preventDefault();
    drop.classList.add('over');
  });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', (e) => {
    e.preventDefault();
    drop.classList.remove('over');
    pick(e.dataTransfer?.files[0]);
  });

  const projects = await api<ProjectInfo[]>('/api/projects');
  document.getElementById('list')!.innerHTML = projects.length
    ? `<table>${projects
        .map(
          (p) => `<tr><td><a href="#/p/${encodeURIComponent(p.name)}">${esc(p.name)}</a></td>
            <td><span class="badge ${p.status}">${STATUS_TEXT[p.status]}</span></td>
            <td class="hint">${new Date(p.updated).toLocaleString('pl-PL')}</td></tr>`,
        )
        .join('')}</table>`
    : '<p class="hint">Brak projektów.</p>';

  const msg = document.getElementById('msg')!;
  const go = document.getElementById('go') as HTMLButtonElement;
  go.addEventListener('click', async () => {
    const name = nameInput.value.trim();
    const areas = parseAreas((document.getElementById('areas') as HTMLTextAreaElement).value);
    const width = (document.getElementById('width') as HTMLInputElement).value.trim();
    const error = !file
      ? 'Wybierz plik rzutu.'
      : !name
        ? 'Podaj nazwę projektu.'
        : typeof areas === 'string'
          ? areas
          : width && !(Number(width.replace(',', '.')) > 0)
            ? 'Szerokość budynku musi być liczbą metrów, np. 9,9'
            : null;
    if (error) {
      msg.innerHTML = `<span class="error">${esc(error)}</span>`;
      return;
    }
    if (projects.some((p) => p.name === name) && !confirm(`Projekt „${name}” już istnieje. Zastąpić go nowym rzutem?`)) return;

    const query = new URLSearchParams({ name });
    if (width) query.set('widthM', width);
    if (typeof areas !== 'string' && Object.keys(areas).length) query.set('areas', JSON.stringify(areas));
    if ((document.getElementById('walls-only') as HTMLInputElement).checked) query.set('wallsOnly', '1');

    go.disabled = true;
    msg.textContent = 'Automat rozpoznaje rzut (zwykle kilkanaście sekund)…';
    try {
      const r = await api<{ name: string }>(`/api/import?${query}`, {
        method: 'POST',
        headers: { 'Content-Type': file!.type },
        body: file,
      });
      location.hash = `#/p/${encodeURIComponent(r.name)}`;
    } catch (err) {
      msg.innerHTML = `<span class="error">${esc((err as Error).message)}</span>`;
      go.disabled = false;
    }
  });
}

// ---------- Etap 2: podgląd rozpoznania, etap 3: model 3D ----------

function summary(plan: PlanModel): string {
  const count = (type: string) => plan.openings.filter((o) => o.type === type).length;
  const types = new Map<string, number>();
  for (const f of plan.furniture) types.set(f.type, (types.get(f.type) ?? 0) + 1);
  const furniture = [...types].map(([t, n]) => (n > 1 ? `${t} ×${n}` : t)).join(', ');
  const rooms = plan.rooms
    .map(
      (r) => `<tr><td>${esc(r.name ?? '(bez nazwy)')}</td><td class="num">${r.area.toFixed(2)} m²</td>
        <td class="num hint">${r.areaOnPlan != null ? `${r.areaOnPlan.toFixed(2)} m²` : '–'}</td></tr>`,
    )
    .join('');
  const [w, d] = plan.source.outlineSize;
  return `
    <table>
      <tr><th>Skala</th><td>${esc(SCALE_TEXT[plan.source.scaleMethod] ?? plan.source.scaleMethod)}
        (${(plan.source.metersPerPixel * 100).toFixed(2)} cm na piksel)</td></tr>
      <tr><th>Wymiary zewnętrzne</th><td>${w.toFixed(2)} × ${d.toFixed(2)} m</td></tr>
      <tr><th>Wysokość ścian</th><td>${plan.storey.height.toFixed(2)} m</td></tr>
      <tr><th>Ściany</th><td>${plan.walls.length}</td></tr>
      <tr><th>Drzwi</th><td>${count('door') + count('folding')}</td></tr>
      <tr><th>Okna</th><td>${count('window')}</td></tr>
      <tr><th>Meble</th><td>${plan.furniture.length}${furniture ? ` <span class="hint">(${esc(furniture)})</span>` : ''}</td></tr>
    </table>
    <h3>Pomieszczenia</h3>
    <table><tr><th>Nazwa</th><th>Powierzchnia z modelu</th><th>Na rzucie</th></tr>${rooms}</table>`;
}

async function showProject(name: string) {
  app.innerHTML = 'Wczytywanie…';
  let p: ProjectInfo;
  try {
    p = await api<ProjectInfo>(`/api/projects/${encodeURIComponent(name)}`);
  } catch (err) {
    app.innerHTML = `<section><p class="error">${esc((err as Error).message)}</p><a href="#/">← Projekty</a></section>`;
    return;
  }
  const accepted = p.status === 'zaakceptowany';
  setStep(accepted ? 3 : 2, accepted ? 3 : 1);

  const report = `<details><summary>Pełny raport automatu</summary><pre>${esc(p.report)}</pre></details>`;
  if (p.status === 'blad') {
    app.innerHTML = `
      <section>
        <h2>${esc(p.name)}: automat nie rozpoznał rzutu</h2>
        <pre class="error">${esc(p.report)}</pre>
        <p>Najczęściej brakuje skali: wróć i podaj szerokość budynku albo powierzchnie pomieszczeń.</p>
        <button class="primary" id="back">← Wgraj ponownie</button>
      </section>`;
    document.getElementById('back')!.addEventListener('click', () => (location.hash = '#/'));
    return;
  }

  const plan = await (await fetch(fileUrl(name, 'model.json'))).json();
  if (!isPlanModel(plan)) {
    app.innerHTML = `<section class="error">Plik model.json projektu ${esc(name)} jest uszkodzony.</section>`;
    return;
  }

  const actions = accepted
    ? `<p>Model 3D zapisany. Pobierz:
         <a href="${fileUrl(name, 'model.glb')}" download="${esc(name)}.glb">model 3D (GLB)</a> ·
         <a href="${fileUrl(name, 'model.json')}" download="${esc(name)}.json">PlanModel (JSON)</a></p>
       <p><button id="rebuild">Zbuduj model 3D ponownie</button> <button class="danger" id="reject">Cofnij akceptację</button>
       <span id="msg"></span></p>`
    : `<p>Sprawdź, czy ściany, drzwi, okna, pokoje i meble zostały rozpoznane poprawnie.</p>
       <p><button class="primary" id="accept">Akceptuję – utwórz model 3D</button>
       <button class="danger" id="reject" ${p.status === 'odrzucony' ? 'disabled' : ''}>Odrzuć</button>
       <button id="back">← Wgraj ponownie z innymi ustawieniami</button> <span id="msg"></span></p>`;

  app.innerHTML = `
    <section>
      <h2>${esc(p.name)} <span class="badge ${p.status}">${STATUS_TEXT[p.status]}</span></h2>
      ${actions}
    </section>
    <section>
      <h2>Rozpoznane elementy</h2>
      <div class="images">
        <figure><img src="${fileUrl(name, p.image)}" alt="rzut" /><figcaption class="hint">Wgrany rzut</figcaption></figure>
        <figure><img src="${fileUrl(name, 'model_debug.png')}" alt="rozpoznanie" />
          <figcaption class="hint">Rozpoznanie automatu: ściany, otwory, pokoje, meble z typem, sprawdzone wymiary</figcaption></figure>
      </div>
    </section>
    <section>${summary(plan)}${report}</section>`;

  const msg = document.getElementById('msg')!;
  document.getElementById('back')?.addEventListener('click', () => (location.hash = '#/'));
  document.getElementById('reject')!.addEventListener('click', async () => {
    await api(`/api/projects/${encodeURIComponent(name)}/reject`, { method: 'POST' });
    showProject(name);
  });
  const build = async (btn: HTMLButtonElement) => {
    btn.disabled = true;
    try {
      msg.textContent = 'Buduję model 3D i wczytuję tekstury…';
      const glb = await buildGlb(plan);
      msg.textContent = `Zapisuję (${(glb.byteLength / 1024 / 1024).toFixed(1)} MB)…`;
      await api(`/api/projects/${encodeURIComponent(name)}/glb`, { method: 'POST', body: glb });
      showProject(name);
    } catch (err) {
      msg.innerHTML = `<span class="error">${esc((err as Error).message)}</span>`;
      btn.disabled = false;
    }
  };
  for (const id of ['accept', 'rebuild']) {
    const btn = document.getElementById(id) as HTMLButtonElement | null;
    btn?.addEventListener('click', () => build(btn));
  }
}

// Model budowany z PlanModel tym samym kodem co w goglach; tekstury wczytują się w tle,
// więc eksport czeka, aż wszystkie obrazy będą gotowe (najwyżej 30 s).
async function buildGlb(plan: PlanModel): Promise<ArrayBuffer> {
  const group = buildPlan(plan);
  const textures = new Set<THREE.Texture>();
  group.traverse((o) => {
    const m = (o as THREE.Mesh).material as THREE.MeshStandardMaterial | undefined;
    for (const t of [m?.map, m?.normalMap, m?.roughnessMap]) if (t) textures.add(t);
  });
  const ready = () =>
    [...textures].every((t) => {
      const img = t.image as HTMLImageElement | HTMLCanvasElement | undefined;
      return img && (!(img instanceof HTMLImageElement) || (img.complete && img.naturalWidth > 0));
    });
  const start = performance.now();
  while (!ready()) {
    if (performance.now() - start > 30000) throw new Error('Nie udało się wczytać tekstur (brak plików w public/textures?).');
    await new Promise((r) => setTimeout(r, 100));
  }
  return exportGlb(group);
}

function route() {
  const m = location.hash.match(/^#\/p\/(.+)$/);
  if (m) showProject(decodeURIComponent(m[1]));
  else showHome();
}

window.addEventListener('hashchange', route);
route();
