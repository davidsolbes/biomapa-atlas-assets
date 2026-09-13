"""Blender headless: exporta una colección a glTF binario (.glb).

Uso:
  blender -b -P pipeline/export_system.py -- --blend <ruta> --collection <nombre> \\
      --out dist/raw/<sistema>.glb [--decimate <ratio>]

Conserva los nombres de objeto. Si --collection no coincide, prueba alias
case-insensitive y lista las colecciones disponibles al fallar.
"""

from __future__ import annotations

import argparse
import sys


def _argv_after_double_dash(argv: list[str]) -> list[str]:
    if "--" in argv:
        return argv[argv.index("--") + 1 :]
    return argv[1:]


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Exporta una colección Z-Anatomy a GLB")
    parser.add_argument("--blend", required=True, help="Ruta al .blend")
    parser.add_argument("--collection", required=True, help="Nombre de la colección")
    parser.add_argument("--out", required=True, help="Ruta de salida .glb")
    parser.add_argument(
        "--decimate",
        type=float,
        default=None,
        help="Ratio de decimación (0–1]. Omite el modificador si no se pasa.",
    )
    parser.add_argument(
        "--list-collections",
        action="store_true",
        help="Solo lista colecciones del .blend y sale",
    )
    return parser.parse_args(argv)


SYSTEM_ALIASES: dict[str, tuple[str, ...]] = {
    "skin": ("integumentary", "skin", "dermal", "piel"),
    "muscles": ("muscular system", "muscles", "muscular", "muscle"),
    "skeleton": ("skeletal system", "skeleton", "bones", "skeletal", "bone", "huesos"),
    "vessels": (
        "cardiovascular system",
        "vessels",
        "vascular",
        "arteries",
        "veins",
    ),
    "nerves": ("nervous system", "nerves", "neural", "nerve"),
    "viscera": (
        "visceral systems",
        "visceral system",
        "viscera",
        "organs",
        "internal organs",
        "digestive system",
        "vísceras",
        "visceras",
    ),
}


def _normalize(name: str) -> str:
    return " ".join(name.lower().replace("_", " ").split())


def _all_collections():
    import bpy

    return list(bpy.data.collections)


def _find_collection(requested: str):
    import bpy

    wanted = _normalize(requested)
    collections = _all_collections()
    for col in collections:
        if _normalize(col.name) == wanted:
            return col
    for aliases in SYSTEM_ALIASES.values():
        if wanted in aliases:
            for col in collections:
                if _normalize(col.name) in aliases:
                    return col
            break
    for col in collections:
        if wanted in _normalize(col.name) or _normalize(col.name) in wanted:
            return col
    return None


def _iter_collection_objects(collection):
    seen: set[str] = set()

    def walk(col):
        for obj in col.objects:
            if obj.name not in seen:
                seen.add(obj.name)
                yield obj
        for child in col.children:
            yield from walk(child)

    yield from walk(collection)


def _export(args: argparse.Namespace) -> None:
    import bpy

    bpy.ops.wm.open_mainfile(filepath=args.blend)

    names = [c.name for c in _all_collections()]
    print("Colecciones:", ", ".join(names) if names else "(ninguna)")
    if args.list_collections:
        return

    collection = _find_collection(args.collection)
    if collection is None:
        raise SystemExit(
            f"No se encontró la colección '{args.collection}'. "
            f"Disponibles: {', '.join(names)}"
        )

    bpy.ops.object.select_all(action="DESELECT")
    exported = 0
    ratio = None
    if args.decimate is not None:
        ratio = max(0.01, min(1.0, float(args.decimate)))
    for obj in _iter_collection_objects(collection):
        if obj.name not in bpy.context.view_layer.objects:
            continue
        try:
            obj.hide_set(False)
        except RuntimeError:
            pass
        obj.hide_viewport = False
        obj.hide_render = False
        try:
            obj.select_set(True)
        except RuntimeError:
            continue
        # No aplicar uno a uno (revienta el depsgraph). El export glTF usa export_apply.
        if ratio is not None and obj.type == "MESH":
            mesh = getattr(obj.data, "polygons", None)
            if mesh is not None and len(mesh) > 3:
                if "BiomapaDecimate" not in obj.modifiers:
                    mod = obj.modifiers.new(name="BiomapaDecimate", type="DECIMATE")
                    mod.ratio = ratio
        exported += 1

    if exported == 0:
        raise SystemExit(f"La colección '{collection.name}' no tiene objetos.")

    bpy.ops.export_scene.gltf(
        filepath=args.out,
        export_format="GLB",
        use_selection=True,
        export_apply=True,
        export_texcoords=True,
        export_normals=True,
        export_materials="EXPORT",
        export_cameras=False,
        export_lights=False,
        export_skins=False,
        export_animations=False,
        export_yup=True,
    )
    print(f"Exportado {exported} objetos → {args.out}")


def main() -> None:
    args = _parse_args(_argv_after_double_dash(sys.argv))
    _export(args)


if __name__ == "__main__":
    main()
