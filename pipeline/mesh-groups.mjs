/**
 * Clasifica mallas del manifiesto en grupos por aparato.
 * Preferencia: sidecar `meshGroups` (colección hija de Blender) → heurística de nombre.
 */

export const VISCERA_GROUP_DEFS = [
  { id: 'digestivo', label_es: 'Digestivo', defaultVisible: true },
  { id: 'respiratorio', label_es: 'Respiratorio', defaultVisible: true },
  { id: 'urinario', label_es: 'Urinario', defaultVisible: true },
  { id: 'reproductor', label_es: 'Reproductor', defaultVisible: true },
  { id: 'endocrino', label_es: 'Endocrino', defaultVisible: true },
  { id: 'linfatico_organos', label_es: 'Órganos linfáticos', defaultVisible: true },
  { id: 'linfatico_ganglios', label_es: 'Ganglios linfáticos', defaultVisible: false },
  { id: 'otros', label_es: 'Otros', defaultVisible: true },
];

export const SKELETON_GROUP_DEFS = [
  { id: 'craneo', label_es: 'Cráneo', defaultVisible: true },
  { id: 'columna', label_es: 'Columna', defaultVisible: true },
  { id: 'torax', label_es: 'Tórax', defaultVisible: true },
  { id: 'miembro_superior', label_es: 'Miembro superior', defaultVisible: true },
  { id: 'miembro_inferior', label_es: 'Miembro inferior', defaultVisible: true },
  { id: 'pelvis', label_es: 'Pelvis', defaultVisible: true },
];

function norm(name) {
  return String(name ?? '')
    .toLowerCase()
    .replace(/[_']/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

const VISCERA_COLLECTION_TO_ID = [
  ['digestive', 'digestivo'],
  ['respiratory', 'respiratorio'],
  ['urinary', 'urinario'],
  ['genital', 'reproductor'],
  ['endocrine', 'endocrino'],
  ['lymphoid', 'linfatico_organos'],
];

export function visceraGroupIdFromCollection(collectionName, meshName) {
  if (/\bnode/i.test(meshName)) return 'linfatico_ganglios';
  const n = norm(collectionName);
  for (const [needle, id] of VISCERA_COLLECTION_TO_ID) {
    if (n.includes(needle)) return id;
  }
  return null;
}

export function classifyVisceraGroup(meshName, collectionName) {
  if (/\bnode/i.test(meshName)) return 'linfatico_ganglios';
  const fromCol = collectionName
    ? visceraGroupIdFromCollection(collectionName, meshName)
    : null;
  if (fromCol && fromCol !== 'linfatico_organos') return fromCol;
  const n = norm(meshName);
  if (
    /\b(spleen|thymus|tonsil|tonsils)\b/.test(n) ||
    n.includes('palatine tonsil')
  ) {
    return 'linfatico_organos';
  }
  if (fromCol) return fromCol;
  if (
    /\b(liver|colon|duodenum|gallbladder|gingiva|omentum|pancreas|parotid|stomach|tongue|uvula|vermiform|appendix|taenia|mesocolon|sublingual|submandibular gland)\b/.test(
      n,
    )
  ) {
    return 'digestivo';
  }
  if (/\b(lung|lungs|trachea|epiglottis|pleura|bronch)\b/.test(n)) {
    return 'respiratorio';
  }
  if (/\b(kidney|renal pelvis|urinary bladder|ureter|urethra)\b/.test(n)) {
    return 'urinario';
  }
  if (
    /\b(penis|epididymis|prostate|seminal|testis|testes|scrotum|vas deferens)\b/.test(
      n,
    )
  ) {
    return 'reproductor';
  }
  if (
    /\b(adenohypophysis|neurohypophysis|pineal|suprarenal|adrenal|thyroid gland|parathyroid|hypophysis)\b/.test(
      n,
    )
  ) {
    return 'endocrino';
  }
  return 'otros';
}

const SKELETON_COLLECTION_TO_ID = [
  ['skull', 'craneo'],
  ['cranium', 'craneo'],
  ['cranial', 'craneo'],
  ['vertebral', 'columna'],
  ['spine', 'columna'],
  ['thoracic cage', 'torax'],
  ['thorax', 'torax'],
  ['upper limb', 'miembro_superior'],
  ['lower limb', 'miembro_inferior'],
  ['pelvic', 'pelvis'],
  ['pelvis', 'pelvis'],
];

export function classifySkeletonGroup(meshName, collectionName) {
  const col = norm(collectionName);
  for (const [needle, id] of SKELETON_COLLECTION_TO_ID) {
    if (col.includes(needle)) return id;
  }
  const n = norm(meshName);
  if (
    /\b(vertebra|atlas \(c1\)|axis \(c2\)|sacrum|coccyx|intervertebral|longitudinal ligament)\b/.test(
      n,
    )
  ) {
    return 'columna';
  }
  if (/\b(rib|sternum|costal|xiphoid|manubrium)\b/.test(n)) return 'torax';
  if (
    /\b(ilium|ischium|pubis|hip bone|pelvis|acetabulum|obturator foramen)\b/.test(n)
  ) {
    return 'pelvis';
  }
  if (
    /\b(femur|tibia|fibula|patella|tarsal|metatarsal|calcaneus|talus|navicular|cuneiform|cuboid|phalanx of .*foot|toe)\b/.test(
      n,
    )
  ) {
    return 'miembro_inferior';
  }
  if (
    /\b(humerus|radius|ulna|scapula|clavicle|carpal|metacarpal|scaphoid|lunate|triquetrum|pisiform|trapezium|trapezoid|capitate|hamate|phalanx of .*hand|finger)\b/.test(
      n,
    )
  ) {
    return 'miembro_superior';
  }
  if (
    /\b(mandible|maxilla|nasal|zygomatic|temporal|parietal|frontal|occipital|sphenoid|ethmoid|hyoid|tooth|teeth|incisor|canine|molar|premolar|vomer|lacrimal|palatine|concha|cranium|skull|orbit|arytenoid|cricoid|corniculate)\b/.test(
      n,
    )
  ) {
    return 'craneo';
  }
  return null;
}

export function buildSystemGroups(systemId, meshNames, meshGroups = {}) {
  const defs =
    systemId === 'viscera'
      ? VISCERA_GROUP_DEFS
      : systemId === 'skeleton'
        ? SKELETON_GROUP_DEFS
        : null;
  if (!defs) return undefined;

  const buckets = new Map(defs.map((d) => [d.id, []]));
  for (const name of meshNames) {
    const collection = meshGroups[name] ?? null;
    const id =
      systemId === 'viscera'
        ? classifyVisceraGroup(name, collection)
        : classifySkeletonGroup(name, collection);
    if (!id || !buckets.has(id)) continue;
    buckets.get(id).push(name);
  }

  const groups = defs
    .map((def) => ({
      id: def.id,
      label_es: def.label_es,
      meshNames: buckets.get(def.id) ?? [],
      defaultVisible: def.defaultVisible,
    }))
    .filter((g) => g.meshNames.length > 0);

  if (systemId === 'skeleton' && groups.length === 0) return undefined;
  return groups;
}
