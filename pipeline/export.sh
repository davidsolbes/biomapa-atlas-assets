#!/usr/bin/env bash
# Envuelve export_system.py: resuelve Blender, .blend y colección por id de sistema.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SYSTEM="${1:-}"
DECIMATE="${2:-}"

if [[ -z "$SYSTEM" ]]; then
  echo "Uso: pipeline/export.sh <sistema> [decimate_ratio]" >&2
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

# Nombres de colección en Z-Anatomy (inglés del template). El script Python
# también acepta alias si el nombre exacto no existe.
case "$SYSTEM" in
  skin) COLLECTION="Integumentary" ;;
  muscles) COLLECTION="Muscular system" ;;
  skeleton) COLLECTION="Skeletal system" ;;
  vessels) COLLECTION="Cardiovascular system" ;;
  nerves) COLLECTION="Nervous system" ;;
  viscera) COLLECTION="Visceral systems" ;;
  *) echo "Sistema desconocido: $SYSTEM" >&2; exit 1 ;;
esac

OUT="$ROOT/dist/raw/${SYSTEM}.glb"
mkdir -p "$(dirname "$OUT")"

ARGS=(--blend "$BLEND" --collection "$COLLECTION" --out "$OUT")
if [[ -n "$DECIMATE" ]]; then
  ARGS+=(--decimate "$DECIMATE")
fi

echo "Exportando $SYSTEM desde $BLEND (colección '$COLLECTION')"
"$BLENDER_BIN" -b -P "$ROOT/pipeline/export_system.py" -- "${ARGS[@]}"
