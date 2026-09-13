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
    "sourceCollection taxonómica «Visceral systems» + «6: Lymphoid organs» (bazo y órganos linfoides). Precedencia skeleton > muscles > viscera: dientes, cartílagos y músculos compartidos quedan en el sistema anterior. Aparato reproductor femenino: colecciones Uterus'/Ovary'/Uterine tube'/Vagina'/Vulva' existen en el .blend pero no tienen objetos MESH exportables.",
  skeleton:
    'sourceCollection taxonómica «Skeletal system». En el .blend no hay colecciones label/text/annotation; se excluyen FONT/CURVE y mallas en MAYÚSCULAS (p. ej. AXIAL SKELETON, BONES OF HAND).',
  skin:
    'sourceCollection taxonómica «Integument» (pelos y uñas) más búsqueda de superficie corporal (skin / body surface / integument). Si no hay malla continua de piel, S2 evaluará BodyParts3D para piel, útero y ovario. «9: Regions of human body» no se exporta como skin.',
  muscles:
    'sourceCollection taxonómica «Muscular system». Precedencia skeleton > muscles. Solo MESH; se excluyen FONT y rótulos en MAYÚSCULAS.',
  vessels:
    'sourceCollection taxonómica «Cardiovascular system». Arterias y venas CURVE se convierten a MESH (bevel mínimo 0.0015 m si no tienen volumen) con transform de mundo aplicada. Se excluyen perfiles de bisel/taper y nombres con caracteres de sustitución. Precedencia skeleton > muscles > viscera > vessels.',
  nerves:
    'sourceCollection taxonómica «Nervous system» (no la colección plana «7: Nervous system & Sense organs»). Encéfalo/médula MESH + nervios periféricos CURVE→MESH con transform de mundo aplicada. Perfiles de bisel/taper excluidos. Músculos enlazados por inervación se omiten por precedencia (muscles > nerves).',
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

function readValidation() {
  const p = join(DIST, '.validation.json');
  if (!existsSync(p)) return {};
  try {
    return JSON.parse(readFileSync(p, 'utf8'));
  } catch {
    return {};
  }
}

function collectInvalidNames() {
  const all = [];
  for (const meta of SYSTEMS) {
    const p = join(DIST, 'raw', `${meta.id}.invalid-names.json`);
    if (!existsSync(p)) continue;
    try {
      const rows = JSON.parse(readFileSync(p, 'utf8'));
      const seen = new Set();
      for (const row of Array.isArray(rows) ? rows : []) {
        const name = row.name ?? '';
        const key = `${name}\t${row.reason ?? ''}`;
        if (seen.has(key)) continue;
        seen.add(key);
        all.push({
          name,
          systemId: meta.id,
          reason: row.reason ?? 'unknown',
          when: row.when ?? null,
        });
      }
    } catch {
      // sidecar ilegible: se omite
    }
  }
  const out = {
    generatedAt: new Date().toISOString(),
    count: all.length,
    names: all,
  };
  const dest = join(ROOT, 'manifest', 'names.invalid.json');
  writeFileSync(dest, `${JSON.stringify(out, null, 2)}\n`);
  return out;
}

const source = readSource();
const validation = readValidation();
const invalidNames = collectInvalidNames();
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
  const excludedByPrecedence =
    readSidecarNumber(meta.id, 'excludedByPrecedence') ??
    exportMeta?.excludedByPrecedence ??
    0;
  const convertedCurves =
    readSidecarNumber(meta.id, 'convertedCurves') ??
    exportMeta?.convertedCurves ??
    0;
  const excludedProfiles =
    readSidecarNumber(meta.id, 'excludedProfiles') ??
    exportMeta?.excludedProfiles ??
    0;
  const validationRow = validation[meta.id];
  const bbox = validationRow?.bbox ?? undefined;
  const validated = validationRow?.validated === true;
  const skinSurfaceFound =
    readSidecarNumber(meta.id, 'skinSurfaceFound') ??
    exportMeta?.skinSurfaceFound ??
    null;
  const siLabel = simplifyRatio != null && simplifyRatio < 1 ? simplifyRatio : 1;
  const curveNote =
    convertedCurves > 0 ? `; CURVE→MESH ${convertedCurves}` : '';
  if (siLabel < 1) {
    modifications.push(
      `${meta.id}: sin decimación Blender; exclusividad por precedencia; rótulos excluidos${curveNote}; gltfpack -cc -tc -kn -si ${siLabel} (≤ 15 MB)`,
    );
  } else {
    modifications.push(
      `${meta.id}: sin decimación Blender; exclusividad por precedencia; rótulos excluidos${curveNote}; gltfpack -cc -tc -kn (sin -si)`,
    );
  }
  let notes = SYSTEM_NOTES[meta.id];
  if (meta.id === 'skin' && skinSurfaceFound === 0) {
    notes =
      'sourceCollection taxonómica «Integument»: solo apéndices (pelos, uñas). No hay malla continua de piel en el .blend (búsqueda skin / body surface / integument = 0). S2 evaluará BodyParts3D para piel, útero y ovario. «9: Regions of human body» no se exporta como skin.';
  } else if (meta.id === 'skin' && skinSurfaceFound > 0) {
    notes = `${SYSTEM_NOTES.skin} Superficie corporal extra: ${skinSurfaceFound} MESH.`;
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
    excludedByPrecedence,
    convertedCurves,
    excludedProfiles,
    simplifyRatio: simplifyRatio ?? 1,
    triangles,
    notes,
    ...(bbox ? { bbox } : {}),
    validated,
  };
});

modifications.push(
  'CURVE→MESH en vessels y nerves: convert(target=MESH) + parent_clear KEEP_TRANSFORM + transform_apply (location/rotation/scale). Bevel mínimo 0.0015 m si la curva no tiene volumen. Nombres originales sin .001.',
);
modifications.push(
  'Perfiles de bisel/taper (bevel_object, taper_object y curvas circle/bezier/profile/bevel/taper) excluidos. Nombres con caracteres de sustitución listados en manifest/names.invalid.json.',
);
modifications.push(
  'Validación geométrica de cada GLB (nodos con nombre, altura ≤ 1.95 m, anchura ≤ 0.9 m, malla ≤ 1.2 m por eje).',
);
modifications.push(
  'Exclusividad por sistema (skeleton > muscles > viscera > vessels > nerves > skin).',
);
modifications.push(
  'Etiquetas en español desde source/z-anatomy/TA2.csv (Terminologia Anatomica 2; misma licencia CC BY-SA 4.0 de Z-Anatomy).',
);
if (modifications.length === 1) {
  modifications.unshift(
    'S1: pipeline listo; ningún sistema exportado todavía (file: null).',
  );
}

const manifest = {
  version: '0.2.2',
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
console.log(`Nombres inválidos: ${invalidNames.count} → manifest/names.invalid.json`);
for (const s of systems) {
  const extra =
    s.file == null
      ? ''
      : ` si=${s.simplifyRatio ?? 1} tris=${s.triangles ?? '?'} excl=${s.excludedObjects ?? '?'} prec=${s.excludedByPrecedence ?? 0} curves=${s.convertedCurves ?? 0} profiles=${s.excludedProfiles ?? 0} bbox=${s.bbox ? `[${s.bbox.join(',')}]` : 'n/a'} validated=${s.validated === true}`;
  console.log(`  ${s.id}: ${s.file ?? 'null'} ${s.bytes} bytes${extra}`);
}
