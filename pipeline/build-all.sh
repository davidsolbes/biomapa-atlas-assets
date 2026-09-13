#!/usr/bin/env bash
# S1: exporta los 6 sistemas sin DECIMATE Blender; empaqueta con
# gltfpack -cc -tc -kn y solo añade -si si el GLB supera 15 MB (0.7 → 0.5 → 0.35).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MAX_BYTES=$((15 * 1024 * 1024))
SIMPLIFY_RATIOS=(1 0.7 0.5 0.35)
SYSTEMS=(skin muscles skeleton vessels nerves viscera)

have_blender=0
if command -v blender >/dev/null 2>&1 || [[ -x /Applications/Blender.app/Contents/MacOS/Blender ]]; then
  have_blender=1
fi

if [[ "$have_blender" -eq 0 ]]; then
  echo "Blender no disponible: se genera manifiesto con file: null en todos los sistemas."
  node "$ROOT/pipeline/build-manifest.mjs"
  node "$ROOT/pipeline/build-labels.mjs"
  exit 0
fi

if ! find "$ROOT/source" -iname '*.blend' -print -quit 2>/dev/null | grep -q .; then
  echo "No hay .blend. Corre: npm run fetch:source"
  node "$ROOT/pipeline/build-manifest.mjs"
  node "$ROOT/pipeline/build-labels.mjs"
  exit 0
fi

pack_under_budget() {
  local system="$1"
  bash "$ROOT/pipeline/export.sh" "$system"
  local ratio
  for ratio in "${SIMPLIFY_RATIOS[@]}"; do
    bash "$ROOT/pipeline/pack.sh" "$system" "$ratio"
    local bytes
    bytes="$(wc -c < "$ROOT/dist/${system}.glb" | tr -d ' ')"
    echo "$system si=$ratio bytes=$bytes"
    if [[ "$bytes" -le "$MAX_BYTES" ]]; then
      return 0
    fi
  done
  echo "Aviso: $system no bajó de 15 MB ni con -si ${SIMPLIFY_RATIOS[-1]}." >&2
}

for system in "${SYSTEMS[@]}"; do
  pack_under_budget "$system"
done
node "$ROOT/pipeline/build-manifest.mjs"
node "$ROOT/pipeline/build-labels.mjs"
