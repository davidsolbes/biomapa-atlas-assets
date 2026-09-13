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
npm run manifest              # regenera manifest/atlas-manifest.json
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
S1 exporta los seis. `viscera` incluye `6: Lymphoid organs` (bazo). `skin` es
solo apéndices (Integument). Las arterias/venas de `vessels` son CURVE y no
salen como MESH.

## Colecciones del Startup.blend (verificado 2026-09-12)

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

| Sistema | `sourceCollection` | Hijas relevantes |
|---------|--------------------|------------------|
| `skeleton` | `Skeletal system` | Axial / appendicular, cráneo, dientes, cartílagos, columna, tórax, miembros |
| `viscera` | `Visceral systems` | `Digestive system`, `Respiratory system`, `Urinary system`, `Genital systems'`, `Endocrine glands`, `Thoracic cavity`, `Abdominopelvic cavity`, `Lymphoid system` |

**Rótulos.** No hay colecciones cuyo nombre contenga `label`, `text` o
`annotation`. Los rótulos de Z-Anatomy son objetos `FONT` (sufijo `.t`),
`CURVE` y mallas en MAYÚSCULAS (`AXIAL SKELETON`, `BONES OF UPPER LIMB`,
`BONES OF HAND`). `export_system.py` exporta solo `MESH` y excluye esas
mayúsculas. El manifiesto registra `excludedObjects` por sistema.

**Decimación.** Sin modificador Blender `DECIMATE`. Empaquetado
`gltfpack -cc -tc -kn`; `-si` solo si el GLB supera 15 MB (0.7 → 0.5 → 0.35).
`-kn` conserva nombres de nodo/malla (sin eso gltfpack fusiona y el clic
del visor pierde el término). `simplifyRatio` en el manifiesto es `1` si
no hubo simplify.

**Ganglios.** Aparecen en `viscera` porque `Lymphoid system` es hija de
`Visceral systems`. El bazo queda fuera (colección hermana
`6: Lymphoid organs`); va en `notes` del sistema.

## Cómo publicar a R2 (`atlas/v0.2.0/`)

David publica. No hay push ni credenciales en este repo.

```bash
# 1) regenerar (si hace falta)
npm run build:all

# 2) subir dist/ al prefijo inmutable (nombres de variables; valores en el entorno)
#    wrangler / aws s3 — ejemplo con AWS CLI compatible R2:
# aws s3 sync dist/ s3://$R2_BUCKET/atlas/v0.2.0/ \
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

## Licencia

Assets derivados: [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
Ver `LICENSE-ASSETS` y `ATTRIBUTIONS.md`.
