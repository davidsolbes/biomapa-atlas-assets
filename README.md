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
npm run export:skeleton       # Blender headless → dist/raw/skeleton.glb
npm run export:viscera
npm run pack -- skeleton      # gltfpack meshopt → dist/skeleton.glb
npm run pack -- viscera 0.25  # segundo arg = -si (simplify)
npm run manifest              # regenera manifest/atlas-manifest.json
npm run build:all             # skeleton + viscera ≤ 15 MB + manifiesto
npm run serve                 # http://localhost:8787 (CORS) — sirve dist/
```

Fuente oficial vigente (2026-09-12):
`https://github.com/Z-Anatomy/Models-of-human-anatomy`

`npm run serve` expone `dist/`. El manifiesto se copia a
`dist/manifest/atlas-manifest.json` para que Biomapa lo pida en
`NEXT_PUBLIC_ATLAS_ASSETS_BASE_URL/manifest/atlas-manifest.json`.

Sistemas fijos: `skin`, `muscles`, `skeleton`, `vessels`, `nerves`, `viscera`.
En S0 solo se exportan `skeleton` y `viscera`; el resto queda `file: null`.

## Cómo publicar a R2

1. Generar `dist/*.glb` y `dist/manifest/atlas-manifest.json` con `npm run build:all`.
2. Subir el contenido de `dist/` al prefijo inmutable `atlas/v<semver>/` del
   bucket ya existente de Biomapa.
3. Variables (solo nombres; valores en el entorno de David / Railway, nunca aquí):
   - `R2_ACCOUNT_ID`
   - `R2_ACCESS_KEY_ID`
   - `R2_SECRET_ACCESS_KEY`
   - `R2_BUCKET`
4. En Biomapa, `NEXT_PUBLIC_ATLAS_ASSETS_BASE_URL` apunta a la URL pública de
   ese prefijo. En dev: `http://localhost:8787`.

Lectura pública, sin PII, caché larga. No commitear `.glb` ni secretos.

## Licencia

Assets derivados: [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
Ver `LICENSE-ASSETS` y `ATTRIBUTIONS.md`.
