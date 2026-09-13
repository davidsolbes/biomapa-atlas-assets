#!/usr/bin/env bash
# S0: exporta skeleton + viscera, empaqueta hasta ≤ 15 MB y regenera el manifiesto.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MAX_BYTES=$((15 * 1024 * 1024))
# Ratios a probar (decimate Blender + simplify gltfpack) hasta caber en 15 MB.
RATIOS=(1 0.5 0.25 0.12 0.06)

have_blender=0
if command -v blender >/dev/null 2>&1 || [[ -x /Applications/Blender.app/Contents/MacOS/Blender ]]; then
  have_blender=1
fi

if [[ "$have_blender" -eq 0 ]]; then
  echo "Blender no disponible: se genera manifiesto con file: null en todos los sistemas."
  node "$ROOT/pipeline/build-manifest.mjs"
  exit 0
fi

if ! find "$ROOT/source" -iname '*.blend' -print -quit 2>/dev/null | grep -q .; then
  echo "No hay .blend. Corre: npm run fetch:source"
  node "$ROOT/pipeline/build-manifest.mjs"
  exit 0
fi

pack_under_budget() {
  local system="$1"
  local ratio
  for ratio in "${RATIOS[@]}"; do
    bash "$ROOT/pipeline/export.sh" "$system" "$ratio"
    bash "$ROOT/pipeline/pack.sh" "$system" "$ratio"
    local bytes
    bytes="$(wc -c < "$ROOT/dist/${system}.glb" | tr -d ' ')"
    echo "$system ratio=$ratio bytes=$bytes"
    if [[ "$bytes" -le "$MAX_BYTES" ]]; then
      mkdir -p "$ROOT/dist"
      echo "$ratio" > "$ROOT/dist/.${system}.ratio"
      return 0
    fi
  done
  echo "Aviso: $system no bajó de 15 MB ni con ratio ${RATIOS[-1]}." >&2
  echo "${RATIOS[-1]}" > "$ROOT/dist/.${system}.ratio"
}

pack_under_budget skeleton
pack_under_budget viscera
node "$ROOT/pipeline/build-manifest.mjs"
