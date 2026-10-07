import { defineConfig, type Plugin } from 'vite';
import basicSsl from '@vitejs/plugin-basic-ssl';
import { mkdirSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const RESULTS_DIR = fileURLToPath(new URL('./results', import.meta.url));

// Gogle wysyłają wyniki pomiarów na laptopa: POST /api/results → results/<id>.json.
// Każda sesja ma własne id, kolejne wysyłki nadpisują jej plik pełnym stanem.
function resultsEndpoint(): Plugin {
  return {
    name: 'field-test-results',
    configureServer(server) {
      server.middlewares.use('/api/results', (req, res) => {
        if (req.method !== 'POST') {
          res.statusCode = 405;
          res.end();
          return;
        }
        let body = '';
        req.on('data', (chunk) => (body += chunk));
        req.on('end', () => {
          try {
            const data = JSON.parse(body);
            const id = String(data.id ?? Date.now()).replace(/[^\w-]/g, '_');
            mkdirSync(RESULTS_DIR, { recursive: true });
            writeFileSync(`${RESULTS_DIR}/${id}.json`, JSON.stringify(data, null, 2));
            res.statusCode = 200;
            res.end('ok');
          } catch (err) {
            res.statusCode = 400;
            res.end(String(err));
          }
        });
      });
    },
  };
}

// WebXR wymaga HTTPS także w LAN. basicSsl generuje certyfikat samopodpisany:
// przeglądarka (także w goglach) pokaże ostrzeżenie, które trzeba raz zaakceptować.
export default defineConfig({
  plugins: [basicSsl(), resultsEndpoint()],
  server: {
    host: true, // nasłuch na wszystkich interfejsach, żeby gogle w LAN widziały serwer
    port: 5174, // 5173 zajmuje viewer/
  },
});
