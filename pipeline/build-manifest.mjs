#!/usr/bin/env node
/**
 * Genera manifest/atlas-manifest.json (y copia a dist/manifest/)
 * a partir de dist/*.glb + source/SOURCE.json.
 */
import { createHash } from 'node:crypto';
import { copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const DIST = join(ROOT, 'dist');
const SOURCE_JSON = join(ROOT, 'source', 'SOURCE.json');

const SYSTEMS = [
  { id: 'skin', label: 'Piel', order: 1, defaultVisible: false },
  { id: 'muscles', label: 'Músculos', order: 2, defaultVisible: false },
  { id: 'skeleton', label: 'Huesos', order: 3, defaultVisible: true },
  { id: 'vessels', label: 'Vasos', order: 4, defaultVisible: false },
  { id: 'nerves', label: 'Nervios', order: 5, defaultVisible: false },
  { id: 'viscera', label: 'Vísceras', order: 6, defaultVisible: true },
];

const SOURCE_URL = 'https://github.com/Z-Anatomy/Models-of-human-anatomy';
const LICENSE_URL = 'https://creativecommons.org/licenses/by-sa/4.0/';
const CITATION =
  'Atlas 3D de Biomapa basado en Z-Anatomy — The libre 3D atlas of anatomy (Gauthier Kervyn, diseño/3D/anatomía; Marcin Zielinski, add-on Blender), derivado de BodyParts3D — The Database Center for Life Science (Kousaku Okubo), CC BY-SA 4.0. Modelos de referencia adicionales según ATTRIBUTIONS.md de Z-Anatomy.';

function readSource() {
  if (!existsSync(SOURCE_JSON)) {
    return { url: SOURCE_URL, commit: '', fecha: null };
  }
  return JSON.parse(readFileSync(SOURCE_JSON, 'utf8'));
}

function parseGlbJson(buf) {
  if (buf.length < 12) return null;
  const magic = buf.toString('utf8', 0, 4);
  if (magic !== 'glTF') return null;
  const jsonLength = buf.readUInt32LE(12);
  const jsonType = buf.toString('utf8', 16, 20);
  if (jsonType !== 'JSON') return null;
  const jsonStart = 20;
  const jsonEnd = jsonStart + jsonLength;
  if (jsonEnd > buf.length) return null;
  try {
    return JSON.parse(buf.subarray(jsonStart, jsonEnd).toString('utf8'));
  } catch {
    return null;
  }
}

function meshNamesFromGlb(buf) {
  const json = parseGlbJson(buf);
  if (!json) return [];
  const names = new Set();
  for (const mesh of json.meshes ?? []) {
    if (mesh?.name) names.add(mesh.name);
  }
  // gltfpack a menudo deja el nombre en el nodo padre, no en el que tiene `mesh`.
  for (const node of json.nodes ?? []) {
    if (node?.name) names.add(node.name);
  }
  return [...names].sort((a, b) => a.localeCompare(b));
}

function readRatio(systemId) {
  const p = join(DIST, `.${systemId}.ratio`);
  if (!existsSync(p)) return null;
  const n = Number.parseFloat(readFileSync(p, 'utf8').trim());
  return Number.isFinite(n) ? n : null;
}

const source = readSource();
const modifications = [];
const systems = SYSTEMS.map((meta) => {
  const filePath = join(DIST, `${meta.id}.glb`);
  if (!existsSync(filePath)) {
    return {
      id: meta.id,
      label: meta.label,
      file: null,
      bytes: 0,
      sha256: null,
      meshCount: 0,
      meshNames: [],
      defaultVisible: meta.defaultVisible,
      order: meta.order,
    };
  }
  const buf = readFileSync(filePath);
  const names = meshNamesFromGlb(buf);
  const ratio = readRatio(meta.id);
  const sha256 = createHash('sha256').update(buf).digest('hex');
  if (ratio != null && ratio < 1) {
    modifications.push(
      `${meta.id}: decimación Blender + gltfpack -si ${ratio} (≤ 15 MB)`,
    );
  } else {
    modifications.push(`${meta.id}: exportación glTF + gltfpack -cc -tc (sin simplify)`);
  }
  return {
    id: meta.id,
    label: meta.label,
    file: `${meta.id}.glb`,
    bytes: buf.length,
    sha256,
    meshCount: names.length,
    meshNames: names,
    defaultVisible: meta.defaultVisible,
    order: meta.order,
    decimateRatio: ratio,
  };
});

if (modifications.length === 0) {
  modifications.push(
    'S0: pipeline listo; ningún sistema exportado todavía (file: null).',
  );
}

const manifest = {
  version: '0.1.0',
  generatedAt: new Date().toISOString(),
  baseLicense: 'CC-BY-SA-4.0',
  attribution: {
    title: 'Z-Anatomy — The libre 3D atlas of anatomy',
    source: 'Z-Anatomy',
    sourceUrl: source.url ?? SOURCE_URL,
    sourceCommit: source.commit ?? '',
    derivedFrom: 'BodyParts3D',
    license: 'CC BY-SA 4.0',
    licenseUrl: LICENSE_URL,
    modifications,
    citationText: CITATION,
  },
  systems,
};

const outGit = join(ROOT, 'manifest', 'atlas-manifest.json');
const outDist = join(DIST, 'manifest', 'atlas-manifest.json');
mkdirSync(dirname(outGit), { recursive: true });
mkdirSync(dirname(outDist), { recursive: true });
const text = `${JSON.stringify(manifest, null, 2)}\n`;
writeFileSync(outGit, text);
writeFileSync(outDist, text);
if (existsSync(join(ROOT, 'ATTRIBUTIONS.md'))) {
  copyFileSync(join(ROOT, 'ATTRIBUTIONS.md'), join(DIST, 'ATTRIBUTIONS.md'));
}
console.log(`Manifiesto escrito: ${outGit}`);
for (const s of systems) {
  console.log(`  ${s.id}: ${s.file ?? 'null'} ${s.bytes} bytes`);
}
