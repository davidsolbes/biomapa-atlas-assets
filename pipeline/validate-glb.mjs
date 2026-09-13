#!/usr/bin/env node
/**
 * Validación geométrica de GLB empaquetados (S1-FIX-03).
 *
 * Falla si:
 *  (a) un nodo con malla no tiene nombre
 *  (b) la altura del sistema > 1.95 m o la anchura > 0.9 m
 *  (c) alguna malla individual excede 1.2 m en cualquier eje
 *
 * Escribe dist/.validation.json (bbox + validated por sistema).
 */
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const DIST = join(ROOT, 'dist');

const SYSTEMS = ['skin', 'muscles', 'skeleton', 'vessels', 'nerves', 'viscera'];
const MAX_SYSTEM_HEIGHT = 1.95;
const MAX_SYSTEM_WIDTH = 0.9;
const MAX_MESH_AXIS = 1.2;

export function parseGlbJson(buf) {
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

function mat4Identity() {
  return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
}

function mat4Multiply(a, b) {
  const out = new Array(16);
  for (let col = 0; col < 4; col++) {
    for (let row = 0; row < 4; row++) {
      out[col * 4 + row] =
        a[row] * b[col * 4] +
        a[4 + row] * b[col * 4 + 1] +
        a[8 + row] * b[col * 4 + 2] +
        a[12 + row] * b[col * 4 + 3];
    }
  }
  return out;
}

function mat4FromTRS(translation = [0, 0, 0], rotation = [0, 0, 0, 1], scale = [1, 1, 1]) {
  const [x, y, z, w] = rotation;
  const x2 = x + x;
  const y2 = y + y;
  const z2 = z + z;
  const xx = x * x2;
  const xy = x * y2;
  const xz = x * z2;
  const yy = y * y2;
  const yz = y * z2;
  const zz = z * z2;
  const wx = w * x2;
  const wy = w * y2;
  const wz = w * z2;
  const [sx, sy, sz] = scale;
  const r = [
    (1 - (yy + zz)) * sx,
    (xy + wz) * sx,
    (xz - wy) * sx,
    0,
    (xy - wz) * sy,
    (1 - (xx + zz)) * sy,
    (yz + wx) * sy,
    0,
    (xz + wy) * sz,
    (yz - wx) * sz,
    (1 - (xx + yy)) * sz,
    0,
    0,
    0,
    0,
    1,
  ];
  r[12] = translation[0];
  r[13] = translation[1];
  r[14] = translation[2];
  return r;
}

function nodeLocalMatrix(node) {
  if (Array.isArray(node.matrix) && node.matrix.length === 16) {
    return node.matrix.slice();
  }
  return mat4FromTRS(node.translation, node.rotation, node.scale);
}

function transformPoint(m, p) {
  const x = p[0];
  const y = p[1];
  const z = p[2];
  const w = m[3] * x + m[7] * y + m[11] * z + m[15] || 1;
  return [
    (m[0] * x + m[4] * y + m[8] * z + m[12]) / w,
    (m[1] * x + m[5] * y + m[9] * z + m[13]) / w,
    (m[2] * x + m[6] * y + m[10] * z + m[14]) / w,
  ];
}

function transformAabb(m, min, max) {
  const xs = [min[0], max[0]];
  const ys = [min[1], max[1]];
  const zs = [min[2], max[2]];
  let outMin = [Infinity, Infinity, Infinity];
  let outMax = [-Infinity, -Infinity, -Infinity];
  for (const x of xs) {
    for (const y of ys) {
      for (const z of zs) {
        const p = transformPoint(m, [x, y, z]);
        outMin = outMin.map((v, i) => Math.min(v, p[i]));
        outMax = outMax.map((v, i) => Math.max(v, p[i]));
      }
    }
  }
  return { min: outMin, max: outMax };
}

function unionAabb(a, b) {
  if (!a) return b;
  if (!b) return a;
  return {
    min: a.min.map((v, i) => Math.min(v, b.min[i])),
    max: a.max.map((v, i) => Math.max(v, b.max[i])),
  };
}

function aabbSize(box) {
  return [box.max[0] - box.min[0], box.max[1] - box.min[1], box.max[2] - box.min[2]];
}

function formatBox(box) {
  const [w, h, d] = aabbSize(box).map((n) => Number(n.toFixed(4)));
  return `[${w}, ${h}, ${d}]`;
}

function parentIndexMap(nodes) {
  const parentOf = new Array(nodes.length).fill(-1);
  nodes.forEach((node, i) => {
    for (const child of node.children ?? []) {
      parentOf[child] = i;
    }
  });
  return parentOf;
}

function worldMatrices(nodes, parentOf) {
  const cache = new Array(nodes.length);
  const walk = (i) => {
    if (cache[i]) return cache[i];
    const local = nodeLocalMatrix(nodes[i] ?? {});
    const p = parentOf[i];
    cache[i] = p >= 0 ? mat4Multiply(walk(p), local) : local;
    return cache[i];
  };
  nodes.forEach((_, i) => walk(i));
  return cache;
}

function inheritedName(nodes, parentOf, index, meshName) {
  let i = index;
  const seen = new Set();
  while (i >= 0 && !seen.has(i)) {
    seen.add(i);
    const n = typeof nodes[i]?.name === 'string' ? nodes[i].name.trim() : '';
    if (n) return n;
    i = parentOf[i] ?? -1;
  }
  return meshName;
}

function meshLocalAabb(json, mesh) {
  let box = null;
  for (const prim of mesh.primitives ?? []) {
    const accIndex = prim.attributes?.POSITION;
    if (accIndex == null) continue;
    const acc = json.accessors?.[accIndex];
    if (!acc?.min || !acc?.max) {
      return { error: 'sin min/max de POSITION' };
    }
    box = unionAabb(box, { min: acc.min, max: acc.max });
  }
  return { box };
}

export function validateGlbBuffer(buf, systemId) {
  const json = parseGlbJson(buf);
  const unnamed = [];
  const offenders = [];
  const errors = [];
  if (!json) {
    errors.push(`${systemId}: GLB ilegible`);
    return {
      systemId,
      bbox: null,
      validated: false,
      unnamed,
      offenders,
      errors,
    };
  }
  const nodes = json.nodes ?? [];
  const meshes = json.meshes ?? [];
  const parentOf = parentIndexMap(nodes);
  const worlds = worldMatrices(nodes, parentOf);
  let systemBox = null;

  nodes.forEach((node, index) => {
    if (node.mesh == null) return;
    const mesh = meshes[node.mesh];
    const meshName = typeof mesh?.name === 'string' ? mesh.name.trim() : '';
    const name = inheritedName(nodes, parentOf, index, meshName);
    if (!name) {
      unnamed.push({ index, mesh: node.mesh });
      errors.push(`${systemId}: nodo #${index} con malla sin nombre`);
    }
    if (!mesh) return;
    const local = meshLocalAabb(json, mesh);
    if (local.error) {
      const label = name || `#${index}`;
      errors.push(`${systemId}: ${label}: ${local.error}`);
      return;
    }
    if (!local.box) return;
    const world = transformAabb(worlds[index] ?? mat4Identity(), local.box.min, local.box.max);
    systemBox = unionAabb(systemBox, world);
    const size = aabbSize(world);
    if (size.some((axis) => axis > MAX_MESH_AXIS)) {
      const label = name || `#${index}`;
      offenders.push({ name: label, bbox: size.map((n) => Number(n.toFixed(4))) });
      errors.push(
        `${systemId}: malla "${label}" bbox ${formatBox(world)} excede ${MAX_MESH_AXIS} m en un eje`,
      );
    }
  });

  let bbox = null;
  if (systemBox) {
    const size = aabbSize(systemBox);
    bbox = size.map((n) => Number(n.toFixed(4)));
    const width = size[0];
    const height = size[1];
    if (height > MAX_SYSTEM_HEIGHT) {
      errors.push(
        `${systemId}: altura ${height.toFixed(4)} m > ${MAX_SYSTEM_HEIGHT} m (bbox ${formatBox(systemBox)})`,
      );
    }
    if (width > MAX_SYSTEM_WIDTH) {
      errors.push(
        `${systemId}: anchura ${width.toFixed(4)} m > ${MAX_SYSTEM_WIDTH} m (bbox ${formatBox(systemBox)})`,
      );
    }
  }

  return {
    systemId,
    bbox,
    validated: errors.length === 0,
    unnamed,
    offenders,
    errors,
  };
}

function main() {
  const results = {};
  let failed = false;
  for (const id of SYSTEMS) {
    const path = join(DIST, `${id}.glb`);
    if (!existsSync(path)) {
      results[id] = {
        systemId: id,
        bbox: null,
        validated: false,
        unnamed: [],
        offenders: [],
        errors: [`${id}: no existe ${path}`],
      };
      failed = true;
      console.error(`FAIL ${id}: no existe ${path}`);
      continue;
    }
    const report = validateGlbBuffer(readFileSync(path), id);
    results[id] = report;
    if (report.validated) {
      console.log(`OK ${id} bbox=[${report.bbox?.join(', ')}]`);
    } else {
      failed = true;
      const unnamedErrors = report.errors.filter((e) => e.includes('sin nombre'));
      const otherErrors = report.errors.filter((e) => !e.includes('sin nombre'));
      if (unnamedErrors.length) {
        console.error(`FAIL ${id}: ${unnamedErrors.length} nodos con malla sin nombre`);
      }
      for (const err of otherErrors) console.error(`FAIL ${err}`);
      for (const off of report.offenders) {
        console.error(`  infractor ${id} "${off.name}" bbox=[${off.bbox.join(', ')}]`);
      }
    }
  }
  const out = join(DIST, '.validation.json');
  writeFileSync(out, `${JSON.stringify(results, null, 2)}\n`);
  console.log(`Validación escrita: ${out}`);
  if (failed) {
    process.exit(1);
  }
}

const isMain = process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1];
if (isMain) {
  main();
}
