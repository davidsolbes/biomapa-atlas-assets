# Atribuciones — Atlas 3D Biomapa

Texto copiado de la fuente Z-Anatomy (`Readme.md` / `License.txt` del commit
registrado). No se inventan autores.

## Origen

- **Proyecto:** Z-Anatomy — The libre 3D atlas of anatomy
- **Repositorio:** https://github.com/Z-Anatomy/Models-of-human-anatomy
- **Sitio:** https://www.z-anatomy.com/
- **Commit de origen:** `99cb24253f09e63dd99602da7e1ef7204aecf648`
  (2026-09-12; `source/SOURCE.json` se actualiza al re-clonar).
- **Autores (según el Readme de Z-Anatomy):**
  - Gauthier KERVYN (Design, 3D, anatomy)
  - Marcin ZIELINSKI (Blender add-on)
  - Lluis VINENT (Unity development)
  - Ana Teresa BIGIO (Portuguese translation of the anatomical structures)
  - Carlos TORRES VILLAR (Spanish translation of the anatomical structures)
  - Paola Perin, Daniele Cossellu, Elisa Vivado (Italian translation of the anatomical structures)
  - Jadwiga Palosz (Polish translation of the anatomical structures)
  - Shariar Ahmadpour (Parsi translation of the anatomical structures)
- **Licencia de Z-Anatomy:** Creative Commons Attribution-ShareAlike 4.0
  International (CC BY-SA 4.0)

Cita que pide Z-Anatomy para los modelos:

> “Z-Anatomy - The libre 3D atlas of anatomy - CC-BY-SA 4.0”

## Origen anterior

- **BodyParts3D** — The Database Center for Life Science
- **Autor del modelo original (según Z-Anatomy):** Kousaku OKUBO
- **Licencia:** CC BY-SA 2.1 Japan
- **Descarga original (enlace de Z-Anatomy):**
  https://dbarchive.biosciencedbc.jp/en/bodyparts3d/download.html

Cita que pide Z-Anatomy:

> “BodyParts3D - The Database Center for Life Science - CC-BY-SA 2.1 Japan”

Modelos de referencia / adaptados que lista Z-Anatomy (no usados como
export S0 independiente; se citan porque la fuente los declara):

- "Brainder" and "White matter" from the University of Washington
- "Cranial Nerves and Foramina - by University of Dundee, CAHID - CC-BY 4.0"
- "Anatomy of the Inner Ear - by University of Dundee School of Medicine - CC-BY-NC-SA 4.0"
- "Kidney - by Lissie Cowley - CC-BY-NC 4.0"

Definiciones de Z-Anatomy (no forman parte de estos GLB): Wikipedia CC-BY-SA 3.0.

## Licencia de estos assets

Los GLB y el manifiesto de este repo son **obras derivadas** y se publican
bajo **CC BY-SA 4.0**:

https://creativecommons.org/licenses/by-sa/4.0/

Ver `LICENSE-ASSETS`.

## Modificaciones

Por sistema (S1-FIX-02 / manifiesto `0.2.1`). Se actualizan al regenerar el
manifiesto:

- **Exclusividad:** un objeto pertenece a un solo sistema. Orden
  `skeleton > muscles > viscera > vessels > nerves > skin`.
- **CURVE → MESH** (vasos y nervios): duplicado + conversión a malla
  respetando bevel/profundidad; si la curva no tiene volumen se asigna
  `bevel_depth` 0.0015 m. Se conserva el nombre original (sin `.001`).
- **skeleton (Huesos):** colección taxonómica `Skeletal system`. Solo `MESH`.
  Rótulos excluidos. Sin decimación Blender. `gltfpack -cc -tc -kn`; `-si` solo
  si el GLB supera 15 MB (0.7 → 0.5 → 0.35).
- **viscera (Vísceras):** `Visceral systems` + `6: Lymphoid organs` (bazo).
  Aparato reproductor femenino: colecciones Uterus'/Ovary'/Uterine tube'
  existen en el `.blend` pero no tienen MESH exportable.
- **muscles:** `Muscular system`.
- **nerves:** `Nervous system` — encéfalo/médula MESH + nervios periféricos
  CURVE→MESH. Músculos enlazados por inervación se omiten por precedencia.
- **vessels:** `Cardiovascular system` — corazón MESH + arterias/venas
  CURVE→MESH.
- **skin:** `Integument` (apéndices: pelos y uñas). Colección `Skin` = 0 MESH;
  no hay superficie corporal en este `.blend`. S2 evaluará BodyParts3D.
- **Etiquetas en español:** `source/z-anatomy/TA2.csv` (Terminologia Anatomica
  2, misma licencia CC BY-SA 4.0 de Z-Anatomy) → `manifest/labels.es.json`.

El `-si` final, triángulos, colección de origen y exclusiones quedan en
`manifest/atlas-manifest.json` (`simplifyRatio`, `triangles`,
`sourceCollection`, `excludedObjects`, `excludedByPrecedence`,
`convertedCurves`, `bytes`, `modifications`).

## Cómo citar en Biomapa

Texto exacto que muestra `/atlas/licencias` (`attribution.citationText`):

> Atlas 3D de Biomapa basado en Z-Anatomy — The libre 3D atlas of anatomy (Gauthier Kervyn, diseño/3D/anatomía; Marcin Zielinski, add-on Blender), derivado de BodyParts3D — The Database Center for Life Science (Kousaku Okubo), CC BY-SA 4.0. Modelos de referencia adicionales según ATTRIBUTIONS.md de Z-Anatomy.
