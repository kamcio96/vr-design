import * as THREE from 'three';
import { GLTFExporter } from 'three/examples/jsm/exporters/GLTFExporter.js';

// GLB (glTF binarny) ma tę samą konwencję co projekt: metry, oś Y w górę.
// Plik otwiera się m.in. w Sketchfab, Blenderze i przeglądarkach glTF.
export async function exportGlb(obj: THREE.Object3D): Promise<ArrayBuffer> {
  const result = await new GLTFExporter().parseAsync(obj, { binary: true });
  return result as ArrayBuffer;
}
