import { defineConfig, type Plugin } from 'vite';
import basicSsl from '@vitejs/plugin-basic-ssl';
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import type { IncomingMessage, ServerResponse } from 'node:http';
import { fileURLToPath } from 'node:url';

// Projekty: projects/<nazwa>/ z plikami rzut.<png|jpg>, model.json, model_debug.png, raport.txt,
// status.json, a po akceptacji model.glb.
const PROJECTS_DIR = fileURLToPath(new URL('./projects', import.meta.url));
const IMPORTER_DIR = fileURLToPath(new URL('../importer', import.meta.url));

type Status = 'do-akceptacji' | 'zaakceptowany' | 'odrzucony' | 'blad';

interface ProjectStatus {
  status: Status;
  updated: string;
  image: string; // nazwa pliku rzutu w katalogu projektu
  options: ImportOptions;
}

interface ImportOptions {
  widthM?: number;
  areas?: Record<string, number>;
  wallsOnly?: boolean;
}

const MIME: Record<string, string> = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.json': 'application/json; charset=utf-8',
  '.txt': 'text/plain; charset=utf-8',
  '.glb': 'model/gltf-binary',
};

// Nazwa projektu = nazwa katalogu: litery (także polskie), cyfry, - i _.
function safeName(name: string): string | null {
  const s = name.trim().replace(/\s+/g, '_').replace(/[^\p{L}\p{N}_-]/gu, '');
  return s && s.length <= 80 ? s : null;
}

function projectDir(name: string): string {
  return `${PROJECTS_DIR}/${name}`;
}

function readStatus(name: string): ProjectStatus | null {
  const file = `${projectDir(name)}/status.json`;
  return existsSync(file) ? (JSON.parse(readFileSync(file, 'utf8')) as ProjectStatus) : null;
}

function writeStatus(name: string, s: ProjectStatus) {
  writeFileSync(`${projectDir(name)}/status.json`, JSON.stringify(s, null, 2));
}

function readBody(req: IncomingMessage, limit = 50 * 1024 * 1024): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    let size = 0;
    req.on('data', (c: Buffer) => {
      size += c.length;
      if (size > limit) {
        reject(new Error('Plik jest za duży.'));
        req.destroy();
      } else chunks.push(c);
    });
    req.on('end', () => resolve(Buffer.concat(chunks)));
    req.on('error', reject);
  });
}

function sendJson(res: ServerResponse, code: number, data: unknown) {
  res.statusCode = code;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.end(JSON.stringify(data));
}

// Uruchamia istniejący automat (importer/plan2model) i zwraca kod wyjścia oraz cały wydruk.
function runImporter(args: string[]): Promise<{ code: number; output: string }> {
  return new Promise((resolve) => {
    const child = spawn('uv', ['run', '--project', IMPORTER_DIR, 'plan2model', ...args], { cwd: IMPORTER_DIR });
    let output = '';
    child.stdout.on('data', (d) => (output += d));
    child.stderr.on('data', (d) => (output += d));
    child.on('error', (err) => resolve({ code: -1, output: `Nie udało się uruchomić automatu (uv): ${err.message}` }));
    child.on('close', (code) => resolve({ code: code ?? -1, output }));
  });
}

// Etap 1: wgranie rzutu i rozpoznanie. Body = sam plik obrazu, ustawienia w adresie.
async function importPlan(req: IncomingMessage, res: ServerResponse, query: URLSearchParams) {
  const name = safeName(query.get('name') ?? '');
  if (!name) return sendJson(res, 400, { error: 'Podaj nazwę projektu (litery, cyfry, - lub _).' });
  const type = req.headers['content-type'] ?? '';
  const ext = type.includes('png') ? '.png' : type.includes('jpeg') ? '.jpg' : null;
  if (!ext) return sendJson(res, 400, { error: 'Obsługiwane są pliki PNG i JPG.' });

  const options: ImportOptions = {};
  const widthM = Number((query.get('widthM') ?? '').replace(',', '.'));
  if (widthM > 0) options.widthM = widthM;
  if (query.get('areas')) options.areas = JSON.parse(query.get('areas')!) as Record<string, number>;
  if (query.get('wallsOnly') === '1') options.wallsOnly = true;

  const dir = projectDir(name);
  // Ponowne wgranie zastępuje poprzedni wynik (także zaakceptowany model).
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir, { recursive: true });
  const image = `rzut${ext}`;
  writeFileSync(`${dir}/${image}`, await readBody(req));

  const args = [`${dir}/${image}`, '-o', `${dir}/model.json`];
  if (options.widthM) args.push('--width-m', String(options.widthM));
  for (const [room, m2] of Object.entries(options.areas ?? {})) args.push('--area', `${room}=${m2}`);
  if (options.wallsOnly) args.push('--walls-only');

  const { code, output } = await runImporter(args);
  writeFileSync(`${dir}/raport.txt`, output);
  const ok = code === 0 && existsSync(`${dir}/model.json`);
  writeStatus(name, { status: ok ? 'do-akceptacji' : 'blad', updated: new Date().toISOString(), image, options });
  sendJson(res, 200, { name, ok, report: output });
}

function listProjects(res: ServerResponse) {
  const names = existsSync(PROJECTS_DIR)
    ? readdirSync(PROJECTS_DIR).filter((n) => statSync(projectDir(n)).isDirectory())
    : [];
  const list = names
    .map((name) => ({ name, ...readStatus(name) }))
    .filter((p) => p.status)
    .sort((a, b) => (b.updated ?? '').localeCompare(a.updated ?? ''));
  sendJson(res, 200, list);
}

function getProject(res: ServerResponse, name: string) {
  const s = readStatus(name);
  if (!s) return sendJson(res, 404, { error: `Nie ma projektu ${name}.` });
  const dir = projectDir(name);
  const report = existsSync(`${dir}/raport.txt`) ? readFileSync(`${dir}/raport.txt`, 'utf8') : '';
  sendJson(res, 200, { name, ...s, report, hasGlb: existsSync(`${dir}/model.glb`) });
}

// Etap 3: przeglądarka buduje GLB z model.json i odsyła go tutaj; zapis = akceptacja.
async function saveGlb(req: IncomingMessage, res: ServerResponse, name: string) {
  const s = readStatus(name);
  if (!s || s.status === 'blad') return sendJson(res, 400, { error: 'Projekt nie ma poprawnego rozpoznania.' });
  writeFileSync(`${projectDir(name)}/model.glb`, await readBody(req, 200 * 1024 * 1024));
  writeStatus(name, { ...s, status: 'zaakceptowany', updated: new Date().toISOString() });
  sendJson(res, 200, { ok: true });
}

function reject(res: ServerResponse, name: string) {
  const s = readStatus(name);
  if (!s) return sendJson(res, 404, { error: `Nie ma projektu ${name}.` });
  rmSync(`${projectDir(name)}/model.glb`, { force: true });
  writeStatus(name, { ...s, status: 'odrzucony', updated: new Date().toISOString() });
  sendJson(res, 200, { ok: true });
}

// Pliki projektów (rzut, obrazek kontrolny, JSON, GLB) pod /projects/<nazwa>/<plik>.
function serveFile(res: ServerResponse, name: string, file: string) {
  const ext = file.slice(file.lastIndexOf('.'));
  const path = `${projectDir(name)}/${file}`;
  if (!/^[\w.-]+$/.test(file) || !MIME[ext] || !existsSync(path)) {
    res.statusCode = 404;
    return res.end();
  }
  res.setHeader('Content-Type', MIME[ext]);
  res.setHeader('Cache-Control', 'no-store'); // po ponownym wgraniu ma być widać nowy obrazek
  if (ext === '.glb' || ext === '.json') res.setHeader('Content-Disposition', `attachment; filename="${name}${ext}"`);
  res.end(readFileSync(path));
}

function studioApi(): Plugin {
  return {
    name: 'studio-api',
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        const url = new URL(req.url ?? '/', 'http://localhost');
        const parts = url.pathname.split('/').filter(Boolean).map(decodeURIComponent);
        try {
          if (parts[0] === 'projects' && parts.length === 3) {
            const name = safeName(parts[1]);
            return name === parts[1] ? serveFile(res, name, parts[2]) : sendJson(res, 404, {});
          }
          if (parts[0] !== 'api') return next();
          if (parts[1] === 'import' && req.method === 'POST') return await importPlan(req, res, url.searchParams);
          if (parts[1] === 'projects' && parts.length === 2) return listProjects(res);
          const name = parts[2] && safeName(parts[2]);
          if (parts[1] === 'projects' && name && name === parts[2]) {
            if (parts.length === 3) return getProject(res, name);
            if (parts[3] === 'glb' && req.method === 'POST') return await saveGlb(req, res, name);
            if (parts[3] === 'reject' && req.method === 'POST') return reject(res, name);
          }
          sendJson(res, 404, { error: 'Nieznany adres.' });
        } catch (err) {
          sendJson(res, 500, { error: String(err) });
        }
      });
    },
  };
}

// HTTPS jak w reszcie projektu (certyfikat samopodpisany; ostrzeżenie przeglądarki akceptuje się raz).
export default defineConfig({
  plugins: [basicSsl(), studioApi()],
  server: {
    host: true,
    port: 5173,
    watch: { ignored: ['**/projects/**'] }, // nowe pliki projektów nie przeładowują strony
  },
});
