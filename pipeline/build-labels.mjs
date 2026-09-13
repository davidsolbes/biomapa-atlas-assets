#!/usr/bin/env node
/**
 * Etiquetas en español desde TA2.csv para cada meshName del manifiesto.
 * Misma limpieza que meshNameToQuery (Biomapa): quita .l/.r/.s/.t/.001 y paréntesis.
 */
import { copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const MANIFEST = join(ROOT, 'manifest', 'atlas-manifest.json');
const TA2 = join(ROOT, 'source', 'z-anatomy', 'TA2.csv');
const OUT_LABELS = join(ROOT, 'manifest', 'labels.es.json');
const OUT_MISSING = join(ROOT, 'manifest', 'labels.missing.json');

function meshNameToQuery(meshName) {
  let name = meshName.trim();
  if (!name) return '';

  let prev = '';
  while (name !== prev) {
    prev = name;
    name = name.replace(/\.(0*\d+)$/i, '');
    name = name.replace(/\.[LRlrst]$/, '');
  }

  name = name.replace(/^\((.*)\)\s*$/, '$1').trim();

  const letters = name.replace(/[^A-Za-zÀ-ÿ]/g, '');
  if (letters.length >= 3 && letters === letters.toUpperCase()) {
    return '';
  }

  name = name.replace(/_/g, ' ');
  name = name.replace(/([a-z])([A-Z])/g, '$1 $2');
  name = name.replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2');
  return name.replace(/\s+/g, ' ').trim().toLowerCase();
}

function stripAccents(value) {
  return value.normalize('NFD').replace(/\p{M}/gu, '');
}

function normalizeEn(value) {
  return stripAccents(value.toLowerCase())
    .replace(/[^a-z0-9]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function pluralVariants(normalized) {
  const variants = new Set([normalized]);
  if (!normalized) return variants;
  const words = normalized.split(' ');
  const last = words.at(-1) ?? '';
  const head = words.slice(0, -1);
  const join = (w) => [...head, w].join(' ').trim();

  if (last.endsWith('ies') && last.length > 4) {
    variants.add(join(`${last.slice(0, -3)}y`));
  } else if (last.endsWith('es') && last.length > 3 && !last.endsWith('ies')) {
    variants.add(join(last.slice(0, -2)));
  } else if (last.endsWith('s') && last.length > 3) {
    variants.add(join(last.slice(0, -1)));
  } else {
    variants.add(join(`${last}s`));
    if (last.endsWith('y') && last.length > 2) {
      variants.add(join(`${last.slice(0, -1)}ies`));
    } else {
      variants.add(join(`${last}es`));
    }
  }
  return variants;
}

function parseTa2Line(raw) {
  let line = raw.trim();
  if (!line) return null;
  if (line.charCodeAt(0) === 0xfeff) line = line.slice(1);
  if (line.startsWith('"') && line.endsWith('"')) {
    line = line.slice(1, -1);
  }
  const parts = line.split(';');
  if (parts.length < 5) return null;
  return {
    ta2Id: parts[0].trim(),
    english: parts[1].trim(),
    latin: parts[2].trim(),
    es: parts[4].trim(),
  };
}

function loadTa2Index() {
  if (!existsSync(TA2)) {
    throw new Error(`No está TA2.csv en ${TA2}`);
  }
  const lines = readFileSync(TA2, 'utf8').split(/\r?\n/);
  const exact = new Map();
  const loose = new Map();
  let rows = 0;
  for (const raw of lines) {
    const row = parseTa2Line(raw);
    if (!row || row.ta2Id === 'TA2ID' || !row.english) continue;
    rows += 1;
    const norm = normalizeEn(row.english);
    if (!norm) continue;
    if (!exact.has(norm)) exact.set(norm, row);
    for (const variant of pluralVariants(norm)) {
      if (!loose.has(variant)) loose.set(variant, row);
    }
  }
  return { exact, loose, rows };
}

function lookupTa2(query, index) {
  const norm = normalizeEn(query);
  if (!norm) return null;
  return index.exact.get(norm) ?? index.loose.get(norm) ?? null;
}

if (!existsSync(MANIFEST)) {
  throw new Error(`No hay manifiesto en ${MANIFEST}. Corre antes npm run manifest.`);
}

const manifest = JSON.parse(readFileSync(MANIFEST, 'utf8'));
const index = loadTa2Index();
const labels = {};
const missing = [];
const coverage = [];

for (const system of manifest.systems ?? []) {
  const names = system.meshNames ?? [];
  let found = 0;
  for (const meshName of names) {
    const key = meshNameToQuery(meshName);
    if (!key) {
      missing.push({ systemId: system.id, meshName, reason: 'rotulo' });
      continue;
    }
    if (labels[key]) {
      found += 1;
      continue;
    }
    const hit = lookupTa2(key, index);
    if (!hit || !hit.es) {
      missing.push({ systemId: system.id, meshName, key });
      continue;
    }
    labels[key] = { es: hit.es, ta2Id: hit.ta2Id, latin: hit.latin || null };
    found += 1;
  }
  coverage.push({
    systemId: system.id,
    found,
    total: names.length,
  });
}

mkdirSync(dirname(OUT_LABELS), { recursive: true });
writeFileSync(OUT_LABELS, `${JSON.stringify(labels, null, 2)}\n`);
writeFileSync(
  OUT_MISSING,
  `${JSON.stringify({ generatedAt: new Date().toISOString(), missing }, null, 2)}\n`,
);

const distManifestDir = join(ROOT, 'dist', 'manifest');
mkdirSync(distManifestDir, { recursive: true });
copyFileSync(OUT_LABELS, join(distManifestDir, 'labels.es.json'));
if (existsSync(OUT_MISSING)) {
  copyFileSync(OUT_MISSING, join(distManifestDir, 'labels.missing.json'));
}

console.log(`TA2 filas indexadas: ${index.rows}`);
console.log(`Etiquetas: ${Object.keys(labels).length} → ${OUT_LABELS}`);
for (const row of coverage) {
  const pct = row.total === 0 ? 0 : Math.round((row.found / row.total) * 100);
  console.log(`  ${row.systemId}: ${row.found}/${row.total} (${pct}%)`);
}
console.log(`Sin etiqueta: ${missing.length} → ${OUT_MISSING}`);
