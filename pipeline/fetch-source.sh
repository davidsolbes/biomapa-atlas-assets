#!/usr/bin/env bash
# Clona el repo público de Z-Anatomy a source/ y escribe source/SOURCE.json.
# URL oficial vigente (2026-09-12): https://github.com/Z-Anatomy/Models-of-human-anatomy
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/source"
URL="https://github.com/Z-Anatomy/Models-of-human-anatomy.git"
DEST="$SRC/z-anatomy"

mkdir -p "$SRC"

if [[ -d "$DEST/.git" ]]; then
  echo "Actualizando clon existente en $DEST"
  git -C "$DEST" fetch --depth 1 origin master
  git -C "$DEST" checkout --force FETCH_HEAD
else
  echo "Clonando $URL (depth 1) → $DEST"
  git clone --depth 1 --branch master "$URL" "$DEST"
fi

COMMIT="$(git -C "$DEST" rev-parse HEAD)"
FECHA="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

cat > "$SRC/SOURCE.json" <<EOF
{
  "url": "$URL",
  "commit": "$COMMIT",
  "fecha": "$FECHA",
  "licencia": "CC BY-SA 4.0",
  "derivado_de": "BodyParts3D (CC BY-SA 2.1 JP)"
}
EOF

echo "SOURCE.json escrito: commit=$COMMIT"

ZIP="$DEST/Z-Anatomy.zip"
UNPACKED="$SRC/unpacked"
if [[ -f "$ZIP" ]]; then
  echo "Descomprimiendo plantilla Z-Anatomy.zip → $UNPACKED"
  rm -rf "$UNPACKED"
  mkdir -p "$UNPACKED"
  unzip -q -o "$ZIP" -d "$UNPACKED"
  echo "Blend encontrados:"
  find "$UNPACKED" -iname '*.blend' -print || true
else
  echo "Aviso: no se encontró Z-Anatomy.zip en el clon."
fi
