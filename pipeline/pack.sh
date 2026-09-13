#!/usr/bin/env bash
# gltfpack: meshopt + texturas comprimidas + simplify opcional.
# Uso: npm run pack -- <sistema> [simplify_ratio]
#   -cc  meshopt compression
#   -tc  texture compression
#   -si  simplify (1 = sin simplificar)
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
npx gltfpack -i "$IN" -o "$OUT" -cc -tc -si "$RATIO"
BYTES="$(wc -c < "$OUT" | tr -d ' ')"
echo "Empaquetado $OUT (${BYTES} bytes, -si ${RATIO})"
