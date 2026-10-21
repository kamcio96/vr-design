// Eksport PlanModel JSON → GLB z wiersza poleceń:
//   npm run export-glb -- public/plans/test1/test1.json [wyjście.glb]
import { readFileSync, writeFileSync } from 'node:fs';
import { buildPlan, isPlanModel } from '../src/planModel';
import { exportGlb } from '../src/exportGlb';

// GLTFExporter w trybie binarnym używa przeglądarkowego FileReader, którego Node nie ma.
// Wystarczy mu readAsArrayBuffer i readAsDataURL z wynikiem w onloadend.
class NodeFileReader {
  result: ArrayBuffer | string | null = null;
  onloadend: (() => void) | null = null;
  readAsArrayBuffer(blob: Blob) {
    blob.arrayBuffer().then((buf) => {
      this.result = buf;
      this.onloadend?.();
    });
  }
  readAsDataURL(blob: Blob) {
    blob.arrayBuffer().then((buf) => {
      this.result = `data:${blob.type || 'application/octet-stream'};base64,${Buffer.from(buf).toString('base64')}`;
      this.onloadend?.();
    });
  }
}
(globalThis as any).FileReader ??= NodeFileReader;

const [input, outputArg] = process.argv.slice(2);
if (!input) {
  console.error('Użycie: npm run export-glb -- <plan.json> [wyjście.glb]');
  process.exit(1);
}
const output = outputArg ?? input.replace(/\.json$/i, '') + '.glb';

const data = JSON.parse(readFileSync(input, 'utf8'));
if (!isPlanModel(data)) {
  console.error(`${input} nie jest plikiem PlanModel.`);
  process.exit(1);
}
const glb = await exportGlb(buildPlan(data));
// W Node nie da się wczytać obrazów, więc GLB z wiersza poleceń ma same kolory materiałów.
console.warn('Uwaga: eksport z wiersza poleceń jest bez tekstur. GLB z teksturami: przycisk „Pobierz GLB” w viewerze.');
writeFileSync(output, Buffer.from(glb));
console.log(`Zapisano: ${output} (${(glb.byteLength / 1024).toFixed(0)} KB)`);
