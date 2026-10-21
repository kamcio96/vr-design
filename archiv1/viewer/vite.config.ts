import { defineConfig } from 'vite';
import basicSsl from '@vitejs/plugin-basic-ssl';

// WebXR wymaga HTTPS także w LAN. basicSsl generuje certyfikat samopodpisany:
// przeglądarka (także w goglach) pokaże ostrzeżenie, które trzeba raz zaakceptować.
export default defineConfig({
  plugins: [basicSsl()],
  server: {
    host: true, // nasłuch na wszystkich interfejsach, żeby gogle w LAN widziały serwer
    port: 5173,
  },
});
