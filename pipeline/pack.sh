#!/usr/bin/env bash
# gltfpack: meshopt + texturas comprimidas. -si solo si el caller lo pide.
# Uso: npm run pack -- <sistema> [simplify_ratio]
#   -cc  meshopt compression
#   -tc  texture compression
#   -si  simplify (omitir o 1 = sin simplificar)
#   -v   stats (triángulos)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SYSTEM="${1:-}"
RATIO="${2:-1}"

if [[ -z "$SYSTEM" ]]; then
  echo "Uso: pipeline/pack.sh <sistema> [simplify_ratio]" >&2
  exit 1
fi

IN="$ROOT/dist/raw/${SYSTEM}.glb"
OUT="$ROOT/dist/${SYSTEM}.glb"

if [[ ! -f "$IN" ]]; then
  echo "No existe $IN. Corre primero npm run export:${SYSTEM}" >&2
  exit 1
fi

mkdir -p "$ROOT/dist"

# -kn conserva nodos/mallas con nombre (clic → término en el visor).
ARGS=(-i "$IN" -o "$OUT" -cc -tc -kn -v)
if [[ "$RATIO" != "1" ]]; then
  ARGS+=(-si "$RATIO")
fi

set +e
LOG="$(npx gltfpack "${ARGS[@]}" 2>&1)"
STATUS=$?
set -e
printf '%s\n' "$LOG"
if [[ "$STATUS" -ne 0 ]]; then
  echo "gltfpack falló con código $STATUS" >&2
  exit "$STATUS"
fi

TRIS="$(printf '%s\n' "$LOG" | sed -nE 's/.*[^0-9]([0-9]+) triangles.*/\1/p' | tail -n 1)"
if [[ -z "$TRIS" ]]; then
  TRIS="$(printf '%s\n' "$LOG" | grep -oE '[0-9]+ triangles' | tail -n 1 | grep -oE '[0-9]+' || true)"
fi

BYTES="$(wc -c < "$OUT" | tr -d ' ')"
echo "$RATIO" > "$ROOT/dist/.${SYSTEM}.ratio"
if [[ -n "$TRIS" ]]; then
  echo "$TRIS" > "$ROOT/dist/.${SYSTEM}.triangles"
  echo "Empaquetado $OUT (${BYTES} bytes, -si ${RATIO}, ${TRIS} triángulos)"
else
  echo "Empaquetado $OUT (${BYTES} bytes, -si ${RATIO}; triángulos no parseados de gltfpack -v)"
fi
