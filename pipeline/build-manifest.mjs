#!/usr/bin/env node
/**
 * Genera manifest/atlas-manifest.json (y copia a dist/manifest/)
 * a partir de dist/*.glb + source/SOURCE.json + sidecars del pipeline.
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

const SYSTEM_NOTES = {
  viscera:
    "sourceCollection taxonómica «Visceral systems» + «6: Lymphoid organs» (bazo y órganos linfoides). Digestivo, respiratorio, urinario, reproductor masculino, endocrino, cavidades y Lymphoid system. Aparato reproductor femenino: colecciones Uterus'/Ovary'/Uterine tube'/Vagina'/Vulva' existen en el .blend pero no tienen objetos MESH exportables. Rótulos: FONT (.t), CURVE y mallas en MAYÚSCULAS.",
  skeleton:
    'sourceCollection taxonómica «Skeletal system». En el .blend no hay colecciones label/text/annotation; se excluyen FONT/CURVE y mallas en MAYÚSCULAS (p. ej. AXIAL SKELETON, BONES OF HAND).',
  skin:
    'sourceCollection taxonómica «Integument»: solo apéndices (pelos, uñas; ~14 MESH). No hay malla continua de piel. «9: Regions of human body» son regiones de superficie, no se exportan como skin.',
  muscles:
    'sourceCollection taxonómica «Muscular system». Solo MESH; se excluyen FONT y rótulos en MAYÚSCULAS.',
  vessels:
    'sourceCollection taxonómica «Cardiovascular system». La mayoría de arterias/venas son CURVE (no MESH); solo se exportan cavidades y válvulas cardíacas (~22 MESH).',
  nerves:
    'sourceCollection taxonómica «Nervous system» (no la colección plana «7: Nervous system & Sense organs»). Solo MESH; CURVE de nervios periféricos quedan fuera.',
};

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
  for (const node of json.nodes ?? []) {
    if (node?.name) names.add(node.name);
  }
  return [...names].sort((a, b) => a.localeCompare(b));
}

function triangleCountFromGlb(buf) {
  const json = parseGlbJson(buf);
  if (!json?.accessors) return 0;
  let tris = 0;
  for (const mesh of json.meshes ?? []) {
    for (const prim of mesh.primitives ?? []) {
      if (prim.indices != null) {
        const acc = json.accessors[prim.indices];
        if (acc?.count) tris += Math.floor(acc.count / 3);
      } else if (prim.attributes?.POSITION != null) {
        const acc = json.accessors[prim.attributes.POSITION];
        if (acc?.count) tris += Math.floor(acc.count / 3);
      }
    }
  }
  return tris;
}

function readSidecarNumber(systemId, suffix) {
  const p = join(DIST, `.${systemId}.${suffix}`);
  if (!existsSync(p)) return null;
  const n = Number.parseFloat(readFileSync(p, 'utf8').trim());
  return Number.isFinite(n) ? n : null;
}

function readSidecarText(systemId, suffix) {
  const p = join(DIST, `.${systemId}.${suffix}`);
  if (!existsSync(p)) return null;
  const t = readFileSync(p, 'utf8').trim();
  return t || null;
}

function readExportMeta(systemId) {
  const p = join(DIST, 'raw', `${systemId}.meta.json`);
  if (!existsSync(p)) return null;
  try {
    return JSON.parse(readFileSync(p, 'utf8'));
  } catch {
    return null;
  }
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
  const exportMeta = readExportMeta(meta.id);
  const simplifyRatio = readSidecarNumber(meta.id, 'ratio');
  const excludedFromFile = readSidecarNumber(meta.id, 'excluded');
  const collectionFromFile = readSidecarText(meta.id, 'collection');
  const trisFromPack = readSidecarNumber(meta.id, 'triangles');
  const triangles = trisFromPack ?? triangleCountFromGlb(buf);
  const sha256 = createHash('sha256').update(buf).digest('hex');
  const siLabel = simplifyRatio != null && simplifyRatio < 1 ? simplifyRatio : 1;
  if (siLabel < 1) {
    modifications.push(
      `${meta.id}: sin decimación Blender; rótulos excluidos; gltfpack -cc -tc -kn -si ${siLabel} (≤ 15 MB)`,
    );
  } else {
    modifications.push(
      `${meta.id}: sin decimación Blender; rótulos excluidos; gltfpack -cc -tc -kn (sin -si)`,
    );
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
    sourceCollection:
      collectionFromFile ?? exportMeta?.sourceCollection ?? undefined,
    excludedObjects:
      excludedFromFile ?? exportMeta?.excludedObjects ?? undefined,
    simplifyRatio: simplifyRatio ?? 1,
    triangles,
    notes: SYSTEM_NOTES[meta.id],
  };
});

modifications.push(
  'Etiquetas en español desde source/z-anatomy/TA2.csv (Terminologia Anatomica 2; misma licencia CC BY-SA 4.0 de Z-Anatomy).',
);
if (modifications.length === 1) {
  modifications.unshift(
    'S1: pipeline listo; ningún sistema exportado todavía (file: null).',
  );
}

const manifest = {
  version: '0.2.0',
  generatedAt: new Date().toISOString(),
  baseLicense: 'CC-BY-SA-4.0',
  labelsFile: 'manifest/labels.es.json',
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
  const extra =
    s.file == null
      ? ''
      : ` si=${s.simplifyRatio ?? 1} tris=${s.triangles ?? '?'} excl=${s.excludedObjects ?? '?'}`;
  console.log(`  ${s.id}: ${s.file ?? 'null'} ${s.bytes} bytes${extra}`);
}
