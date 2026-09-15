# biomapa-atlas-assets

Pipeline y assets **derivados** del atlas libre [Z-Anatomy](https://www.z-anatomy.com/)
para el visor `/atlas` de Biomapa.

Este repo es **independiente** del código de Biomapa (aislamiento de licencia
CC BY-SA 4.0). Versiona pipeline, manifiesto y atribuciones. Los `.glb` se
generan en `dist/` (git-ignored) y se publican a R2 bajo `atlas/v<semver>/`.

**No** guarda credenciales. El remoto lo crea David.

## Requisitos

- Node 20+
- [Blender](https://www.blender.org/) (cask): `brew install --cask blender`
- `gltfpack` y `serve` (devDependencies): `npm i -D gltfpack serve`

Verificar:

```bash
blender --version
# o
/Applications/Blender.app/Contents/MacOS/Blender --version
npx gltfpack -v
```

## Cómo regenerar

```bash
npm run fetch:source          # clona Z-Anatomy → source/ + source/SOURCE.json
npm run export:skeleton       # Blender headless → dist/raw/skeleton.glb (sin DECIMATE)
npm run export:viscera
npm run export:muscles
npm run export:nerves
npm run export:vessels
npm run export:skin
npm run pack -- skeleton      # gltfpack -cc -tc -kn (sin -si)
npm run pack -- viscera 0.7   # segundo arg = -si solo si hace falta (presupuesto 15 MB)
npm run validate              # geometría de dist/*.glb (nombres + bbox)
npm run manifest              # valida + regenera manifest/atlas-manifest.json
npm run labels                # TA2.csv → manifest/labels.es.json
npm run build:all             # export sin decimar + pack (1 → 0.7 → 0.5 → 0.35) + manifiesto + etiquetas
npm run serve                 # http://localhost:8787 (CORS) — sirve dist/
```

Listar colecciones del `.blend`:

```bash
blender -b -P pipeline/export_system.py -- \
  --blend source/unpacked/Z-Anatomy/Startup.blend \
  --collection dummy --out /tmp/unused.glb --list-collections
```

Fuente oficial vigente (2026-09-12):
`https://github.com/Z-Anatomy/Models-of-human-anatomy`

`npm run serve` expone `dist/`. El manifiesto se copia a
`dist/manifest/atlas-manifest.json` para que Biomapa lo pida en
`NEXT_PUBLIC_ATLAS_ASSETS_BASE_URL/manifest/atlas-manifest.json`.

Sistemas fijos: `skin`, `muscles`, `skeleton`, `vessels`, `nerves`, `viscera`.
S1-FIX-03 exporta los seis en orden de precedencia
(`skeleton > muscles > viscera > vessels > nerves > skin`): un objeto
pertenece a un solo sistema. `vessels` y `nerves` convierten CURVE → MESH
(bevel mínimo 0.0015 m) con el objeto en su transform de mundo (sin parent);
excluyen perfiles de bisel/taper, helpers `-curve` / `.g` y nombres con `?`.
`viscera` incluye `6: Lymphoid organs` (bazo) y omite el plano
`Lymphoid organs.g`. `skin` es apéndices (Integument); no hay malla continua
de piel en este `.blend` (colección `Skin` = 0 MESH). S2 evaluará BodyParts3D
para piel, útero y ovario.

**Validación geométrica.** `pipeline/validate-glb.mjs` (en `build:all` y
`npm run manifest`) falla si un nodo con malla no tiene nombre, si la
altura del sistema supera 1.95 m o la anchura 0.9 m, o si alguna malla
excede 1.2 m en un eje. El manifiesto guarda `bbox: [w,h,d]` y
`validated`. Nombres inválidos: `manifest/names.invalid.json`.

Inventario / sistema:

```bash
blender -b -P pipeline/export_system.py -- \
  --blend source/unpacked/Z-Anatomy/Startup.blend \
  --collection dummy --out /tmp/unused.glb --inventory all
# o --inventory nerves
```

## Colecciones del Startup.blend (verificado 2026-09-13)

Top-level de escena (prefijo numérico de Z-Anatomy):

1. `1: Skeletal system` (2218 objetos)
2. `2: Muscular insertions`
3. `3: Joints`
4. `4: Muscular system`
5. `5: Cardiovascular system`
6. `6: Lymphoid organs` (bazo y órganos linfoides; **no** es hija de vísceras)
7. `7: Nervous system & Sense organs`
8. `8: Visceral systems` (479 objetos, plana)
9. `9: Regions of human body`

El pipeline **no** usa esas colecciones planas. Matchea el nombre taxonómico
sin prefijo (el que tiene hijas):

| Sistema | `sourceCollection` | MESH | CURVE | FONT | EMPTY | OTHER | total |
|---------|--------------------|-----:|------:|-----:|------:|------:|------:|
| `skeleton` | `Skeletal system` | 804 | 0 | 489 | 0 | 0 | 1293 |
| `muscles` | `Muscular system` | 731 | 0 | 72 | 0 | 3 | 806 |
| `viscera` | `Visceral systems` | 177 | 45 | 0 | 0 | 0 | 222 |
| (extra) | `6: Lymphoid organs` | 220 | 0 | 56 | 0 | 0 | 276 |
| `vessels` | `Cardiovascular system` | 22 | 654 | 21 | 0 | 0 | 697 |
| `nerves` | `Nervous system` | 606 | 250 | 111 | 0 | 3 | 970 |
| `skin` | `Integument` | 14 | 1 | 0 | 0 | 0 | 15 |
| (no export) | `9: Regions of human body` | 299 | 0 | 44 | 0 | 0 | 343 |

`Nervous system` **enlaza músculos** (inervación): esos MESH se omiten por
precedencia. Los nervios periféricos son CURVE (`Cauda equina`,
`Nerve to quadratus femoris`…). `Cardiovascular system` tiene el corazón en
MESH y arterias/venas en CURVE. `Skin` (colección) = 0 MESH; `Skin appendages`
= pelos y uñas. No hay MESH cuyo nombre contenga `skin` / `body surface`.

| Sistema | `sourceCollection` | Hijas relevantes |
|---------|--------------------|------------------|
| `skeleton` | `Skeletal system` | Axial / appendicular, cráneo, dientes, cartílagos, columna, tórax, miembros |
| `viscera` | `Visceral systems` | `Digestive system`, `Respiratory system`, `Urinary system`, `Genital systems'`, `Endocrine glands`, `Thoracic cavity`, `Abdominopelvic cavity`, `Lymphoid system` |

**Rótulos.** No hay colecciones cuyo nombre contenga `label`, `text` o
`annotation`. Los rótulos de Z-Anatomy son objetos `FONT` (sufijo `.t`),
`CURVE` y mallas en MAYÚSCULAS (`AXIAL SKELETON`, `BONES OF UPPER LIMB`,
`BONES OF HAND`). `export_system.py` exporta `MESH` (y CURVE convertidas en
vasos/nervios) y excluye esas mayúsculas. El manifiesto registra
`excludedObjects`, `excludedByPrecedence` y `convertedCurves` por sistema.

**Decimación.** Sin modificador Blender `DECIMATE`. Empaquetado
`gltfpack -cc -tc -kn`; `-si` solo si el GLB supera 15 MB (0.7 → 0.5 → 0.35).
`-kn` conserva nombres de nodo/malla (sin eso gltfpack fusiona y el clic
del visor pierde el término). `simplifyRatio` en el manifiesto es `1` si
no hubo simplify.

## Publicar v0.2.3 (solo metadatos)

Los seis GLB **no cambian** respecto a v0.2.2 (`bytes` / `sha256` iguales). David
publica en R2:

1. Subir `manifest/atlas-manifest.json` y `manifest/labels.es.json` a
   `atlas/v0.2.3/manifest/`.
2. **Copiar** los seis `.glb` de `atlas/v0.2.2/` a `atlas/v0.2.3/` (o
   subirlos de nuevo). La app carga `<base>/<file>` relativo a
   `NEXT_PUBLIC_ATLAS_ASSETS_BASE_URL`.
3. En Biomapa: `atlas:seed-nodes --rename-version 0.2.2 0.2.3` (mismos
   `node_key`; sin re-embed).

**Ganglios.** Aparecen en `viscera` porque `Lymphoid system` es hija de
`Visceral systems` (y `6: Lymphoid organs`). En el manifiesto 0.2.3 el grupo
`linfatico_ganglios` tiene `defaultVisible: false`. El bazo / timo / amígdalas
van en `linfatico_organos`.

## Cómo publicar a R2 (`atlas/v0.2.2/`)

David publica. No hay push ni credenciales en este repo.

```bash
# 1) regenerar (si hace falta)
npm run build:all

# 2) subir dist/ al prefijo inmutable (nombres de variables; valores en el entorno)
#    wrangler / aws s3 — ejemplo con AWS CLI compatible R2:
# aws s3 sync dist/ s3://$R2_BUCKET/atlas/v0.2.2/ \
#   --endpoint-url https://$R2_ACCOUNT_ID.r2.cloudflarestorage.com
```

Variables (solo nombres; valores en el entorno de David / Railway, nunca aquí):
- `R2_ACCOUNT_ID`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_BUCKET`

En Biomapa, `NEXT_PUBLIC_ATLAS_ASSETS_BASE_URL` apunta a la URL pública de
ese prefijo. En dev: `http://localhost:8787`. Incluye `manifest/atlas-manifest.json`
y `manifest/labels.es.json`.

Lectura pública, sin PII, caché larga. No commitear `.glb` ni secretos.

## Fuentes externas (inventario)

Spike **ATLAS-FEM-00** (2026-09-14). Binarios en `source/external/` (git-ignored
vía `source/`). Metadatos: `source/external/SOURCES.json` (local). Resultado
versionado: `manifest/external-inventory.json`.

```bash
/Applications/Blender.app/Contents/MacOS/Blender -b -P pipeline/inventory-external.py -- \
  --out manifest/external-inventory.json
```

Fuentes medidas:
- **BodyParts3D 4.0** (`isa_BP3D_4.0_obj_99.zip`) — piel `FMA7163` → element
  `FJ2810.obj`; fémur/coxal para alineación a Z-Anatomy. CC BY-SA 2.1 JP.
- **HuBMAP HRA united-female v1.5** (`3d-vh-f-united.glb`) — cuerpo femenino
  (Visible Human Female). CC BY 4.0.

No publica a R2 ni modifica el manifiesto 0.2.3 / GLB de producción.

## Licencia

Assets derivados: [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
Ver `LICENSE-ASSETS` y `ATTRIBUTIONS.md`.
