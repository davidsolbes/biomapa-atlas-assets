#!/usr/bin/env bash
# Envuelve export_system.py: resuelve Blender, .blend y colección por id de sistema.
# S0-FIX-01: exporta sin decimar en Blender.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SYSTEM="${1:-}"

if [[ -z "$SYSTEM" ]]; then
  echo "Uso: pipeline/export.sh <sistema>" >&2
  exit 1
fi

if command -v blender >/dev/null 2>&1; then
  BLENDER_BIN="blender"
elif [[ -x /Applications/Blender.app/Contents/MacOS/Blender ]]; then
  BLENDER_BIN="/Applications/Blender.app/Contents/MacOS/Blender"
else
  echo "Blender no está disponible. Instala con: brew install --cask blender" >&2
  exit 1
fi

BLEND="${BLEND_PATH:-}"
if [[ -z "$BLEND" ]]; then
  BLEND="$(find "$ROOT/source" -iname '*.blend' -print -quit 2>/dev/null || true)"
fi
if [[ -z "$BLEND" ]]; then
  echo "No hay .blend en source/. Corre primero: npm run fetch:source" >&2
  exit 1
fi

# Nombres taxonómicos en Z-Anatomy (sin el prefijo numérico de la colección de escena).
EXTRA_ARGS=()
case "$SYSTEM" in
  skin) COLLECTION="Integument" ;;
  muscles) COLLECTION="Muscular system" ;;
  skeleton) COLLECTION="Skeletal system" ;;
  vessels) COLLECTION="Cardiovascular system" ;;
  nerves) COLLECTION="Nervous system" ;;
  viscera)
    COLLECTION="Visceral systems"
    EXTRA_ARGS+=(--extra-collection "6: Lymphoid organs")
    ;;
  *) echo "Sistema desconocido: $SYSTEM" >&2; exit 1 ;;
esac

OUT="$ROOT/dist/raw/${SYSTEM}.glb"
mkdir -p "$(dirname "$OUT")"

echo "Exportando $SYSTEM desde $BLEND (colección '$COLLECTION', sin DECIMATE)"
CMD=("$BLENDER_BIN" -b -P "$ROOT/pipeline/export_system.py" -- \
  --blend "$BLEND" --collection "$COLLECTION" --out "$OUT")
if ((${#EXTRA_ARGS[@]})); then
  CMD+=("${EXTRA_ARGS[@]}")
fi
"${CMD[@]}"

META="$ROOT/dist/raw/${SYSTEM}.meta.json"
if [[ -f "$META" ]]; then
  python3 - "$META" "$ROOT/dist" "$SYSTEM" <<'PY'
import json, sys
from pathlib import Path
meta = json.loads(Path(sys.argv[1]).read_text())
dist = Path(sys.argv[2])
system = sys.argv[3]
(dist / f".{system}.collection").write_text(f"{meta.get('sourceCollection', '')}\n")
(dist / f".{system}.excluded").write_text(f"{int(meta.get('excludedObjects', 0))}\n")
print(f"sourceCollection={meta.get('sourceCollection')} excludedObjects={meta.get('excludedObjects')}")
PY
fi
