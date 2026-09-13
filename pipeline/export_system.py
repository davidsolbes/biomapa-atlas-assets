"""Blender headless: exporta una colección a glTF binario (.glb).

Uso:
  blender -b -P pipeline/export_system.py -- --blend <ruta> --collection <nombre> \\
      --out dist/raw/<sistema>.glb [--decimate <ratio>]

  blender -b -P pipeline/export_system.py -- --blend <ruta> --collection dummy \\
      --out /tmp/unused.glb --inventory [sistema]

Solo MESH (más CURVE convertidas a MESH en vessels/nerves). Excluye rótulos
(nombre en MAYÚSCULAS ≥ 3 letras), objetos en colecciones label/text/annotation,
perfiles de bisel/taper y nombres con caracteres de sustitución. Tras convertir
una curva se aplica la transformación de mundo. `--exclude-names` omite nombres
ya exportados por sistemas de mayor precedencia. Conserva nombres (sin .001).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

LABEL_HINTS = ("label", "text", "annotation")
CONVERTIBLE_TYPES = frozenset({"CURVE"})
INVENTORY_TYPES = ("MESH", "CURVE", "FONT", "EMPTY")
MIN_BEVEL_DEPTH = 0.0015
PROFILE_NAME_HINTS = ("bezier", "profile", "bevel", "taper")
# «circle» pero no «circulatory» / «circulation».
PROFILE_CIRCLE_HINT = "circle"

# Un objeto pertenece a un solo sistema. El pipeline encadena este orden.
SYSTEM_PRECEDENCE = (
    "skeleton",
    "muscles",
    "viscera",
    "vessels",
    "nerves",
    "skin",
)

SYSTEM_ALIASES: dict[str, tuple[str, ...]] = {
    "skin": ("integument", "integumentary", "skin", "dermal", "piel"),
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

CANDIDATE_COLLECTIONS = (
    "Skeletal system",
    "Muscular system",
    "Visceral systems",
    "6: Lymphoid organs",
    "Cardiovascular system",
    "Nervous system",
    "Integument",
    "9: Regions of human body",
)

FEMALE_REPRO_NAMES = (
    "uterus'",
    "ovary'",
    "uterine tube'",
    "vagina'",
    "female external genitalia'",
    "vulva'",
    "clitoris'",
)

SKIN_NAME_HINTS = ("skin", "body surface", "integument")
# Colecciones de superficie real — no «Body of femur» ni «Anterior surface of X».
SKIN_COLLECTION_EXACT = frozenset(
    {
        "skin",
        "integument",
        "skin appendages",
        "skin glands",
        "body surface",
        "body skin",
    }
)


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
        help="Solo diagnóstico. El pipeline S0-FIX-01 no decima en Blender.",
    )
    parser.add_argument(
        "--list-collections",
        action="store_true",
        help="Lista colecciones relevantes del .blend y sale",
    )
    parser.add_argument(
        "--inventory",
        nargs="?",
        const="all",
        default=None,
        help="Cuenta objetos por type en colecciones candidatas (o un sistema)",
    )
    parser.add_argument(
        "--extra-collection",
        action="append",
        default=[],
        help="Colección adicional (repetible). Se unen las mallas exportables.",
    )
    parser.add_argument(
        "--exclude-names",
        default=None,
        help="Archivo con un nombre por línea ya exportado por sistemas previos",
    )
    parser.add_argument(
        "--convert-curves",
        action="store_true",
        help="CURVE → MESH (vessels/nerves). Conserva el nombre original.",
    )
    parser.add_argument(
        "--search-skin-surface",
        action="store_true",
        help="Busca superficie corporal fuera de Integument y la une a skin",
    )
    parser.add_argument(
        "--system-id",
        default=None,
        help="Id de sistema (skeleton/muscles/…). Solo metadatos.",
    )
    return parser.parse_args(argv)


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


def _is_all_caps_label(name: str) -> bool:
    letters = [c for c in name if c.isalpha()]
    return len(letters) >= 3 and all(c.isupper() for c in letters)


def _collection_is_label(col) -> bool:
    n = col.name.lower()
    return any(hint in n for hint in LABEL_HINTS)


def _object_in_label_collection(obj) -> bool:
    return any(_collection_is_label(col) for col in obj.users_collection)


def _load_exclude_names(path: str | None) -> set[str]:
    if not path:
        return set()
    text = Path(path).read_text(encoding="utf-8")
    return {line.strip() for line in text.splitlines() if line.strip()}


def _invalid_name_reason(name: str) -> str | None:
    if not name or not name.strip():
        return "empty"
    if "?" in name or "\ufffd" in name:
        return "substitution"
    if any(ord(ch) < 32 for ch in name):
        return "control"
    return None


def _looks_like_profile_name(name: str) -> bool:
    n = name.lower()
    if any(hint in n for hint in PROFILE_NAME_HINTS):
        return True
    if PROFILE_CIRCLE_HINT in n and "circul" not in n:
        return True
    stripped = n
    for suffix in (".l", ".r", ".s", ".t"):
        if stripped.endswith(suffix):
            stripped = stripped[: -len(suffix)]
            break
    if stripped.endswith(("-curve", "_curve", ".curve")):
        return True
    return False


def _collect_profile_names() -> set[str]:
    import bpy

    names: set[str] = set()
    for obj in bpy.data.objects:
        if obj.type == "CURVE" and _looks_like_profile_name(obj.name):
            names.add(obj.name)
        data = getattr(obj, "data", None)
        if data is None:
            continue
        bevel = getattr(data, "bevel_object", None)
        taper = getattr(data, "taper_object", None)
        if bevel is not None:
            names.add(bevel.name)
        if taper is not None:
            names.add(taper.name)
    return names


def _is_group_helper(name: str) -> bool:
    """Z-Anatomy usa el sufijo .g para grupos/gizmos (planos sin volumen)."""
    return name.lower().endswith(".g")


def _should_exclude(
    obj, exclude_names: set[str], profile_names: set[str]
) -> str | None:
    if obj.name in exclude_names:
        return "precedence"
    if obj.name in profile_names:
        return "profile"
    invalid = _invalid_name_reason(obj.name)
    if invalid:
        return f"invalid_name:{invalid}"
    if _is_group_helper(obj.name):
        return "group_helper"
    if obj.type != "MESH":
        return f"type:{obj.type}"
    if _is_all_caps_label(obj.name):
        return "all_caps"
    if _object_in_label_collection(obj):
        return "label_collection"
    return None


def _count_types(collection) -> Counter:
    counts: Counter = Counter()
    for obj in _iter_collection_objects(collection):
        counts[obj.type] += 1
    return counts


def _format_type_counts(counts: Counter) -> str:
    parts = [f"{t}={counts.get(t, 0)}" for t in INVENTORY_TYPES]
    others = sum(n for t, n in counts.items() if t not in INVENTORY_TYPES)
    if others:
        parts.append(f"OTHER={others}")
    parts.append(f"total={sum(counts.values())}")
    return " ".join(parts)


def _female_repro_note() -> str:
    import bpy

    parts: list[str] = []
    for wanted in FEMALE_REPRO_NAMES:
        col = next(
            (c for c in bpy.data.collections if _normalize(c.name) == _normalize(wanted)),
            None,
        )
        if col is None:
            parts.append(f"{wanted}: colección no encontrada")
            continue
        n = sum(1 for obj in _iter_collection_objects(col) if obj.type == "MESH")
        parts.append(f"{col.name}: {n} MESH")
    if all(": 0 MESH" in p or "no encontrada" in p for p in parts):
        return (
            "Aparato reproductor femenino: colecciones Uterus'/Ovary'/Uterine tube'/"
            "Vagina'/Vulva' existen en el .blend pero no tienen objetos MESH "
            f"exportables ({'; '.join(parts)})."
        )
    return "Aparato reproductor femenino: " + "; ".join(parts)


def _list_collections() -> None:
    import bpy

    print("=== TOP-LEVEL (escena) ===")
    for col in bpy.context.scene.collection.children:
        print(
            f"- {col.name}  children={len(col.children)} objects={len(col.objects)}"
        )

    print("\n=== COLECCIONES label / text / annotation ===")
    hits = [c for c in bpy.data.collections if _collection_is_label(c)]
    if not hits:
        print(
            "(ninguna en este .blend; los rótulos son FONT/CURVE y mallas MAYÚSCULAS)"
        )
    for col in hits:
        print(f"- {col.name}  objects={len(col.objects)} children={len(col.children)}")

    print("\n=== SISTEMAS S0/S1 (nombre taxonómico, sin prefijo numérico) ===")
    for name in (
        "Skeletal system",
        "Visceral systems",
        "Muscular system",
        "Cardiovascular system",
        "Nervous system",
        "Integument",
        "6: Lymphoid organs",
    ):
        col = next((c for c in bpy.data.collections if c.name == name), None)
        if col is None:
            print(f"- {name}: no encontrada")
            continue
        children = ", ".join(c.name for c in col.children) or "(sin hijas)"
        print(f"- {col.name}  hijas: {children}")

    print("\n=== Aparato reproductor femenino (colecciones) ===")
    print(_female_repro_note())


def _inventory_one(name: str) -> None:
    col = _find_collection(name)
    if col is None:
        print(f"- {name}: no encontrada")
        return
    counts = _count_types(col)
    print(f"- {col.name}: {_format_type_counts(counts)}")
    curve_samples = [
        obj.name
        for obj in _iter_collection_objects(col)
        if obj.type == "CURVE" and not _is_all_caps_label(obj.name)
    ][:8]
    if curve_samples:
        print(f"    CURVE muestra: {', '.join(curve_samples)}")


def _inventory(target: str) -> None:
    print("=== INVENTARIO POR TIPO ===")
    print(f"Precedencia: {' > '.join(SYSTEM_PRECEDENCE)}")
    if target != "all":
        aliases = SYSTEM_ALIASES.get(_normalize(target))
        if aliases:
            _inventory_one(aliases[0])
            return
        _inventory_one(target)
        return
    for name in CANDIDATE_COLLECTIONS:
        _inventory_one(name)
    print("\n=== Colecciones Skin / Integument / Body surface ===")
    import bpy

    hits = [c for c in bpy.data.collections if _collection_looks_like_skin(c)]
    if not hits:
        print("(ninguna)")
    for col in hits:
        print(f"- {col.name}: {_format_type_counts(_count_types(col))}")
    print("\n=== MESH cuyo nombre sugiere superficie corporal ===")
    import bpy

    surface_hits = []
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        n = _normalize(obj.name)
        if any(h in n for h in SKIN_NAME_HINTS):
            surface_hits.append(obj.name)
    if not surface_hits:
        print("(ninguno)")
    else:
        for name in surface_hits[:40]:
            print(f"- {name}")
        if len(surface_hits) > 40:
            print(f"  … +{len(surface_hits) - 40}")
    print("\n=== Aparato reproductor femenino ===")
    print(_female_repro_note())


def _curve_has_volume(obj) -> bool:
    data = obj.data
    if getattr(data, "bevel_depth", 0) > 0:
        return True
    if getattr(data, "extrude", 0) > 0:
        return True
    if getattr(data, "bevel_object", None) is not None:
        return True
    return False


def _ensure_curve_volume(obj) -> None:
    if not _curve_has_volume(obj):
        obj.data.bevel_depth = MIN_BEVEL_DEPTH


def _ensure_in_view_layer(obj) -> bool:
    import bpy

    view = bpy.context.view_layer
    if obj.name in view.objects:
        return True
    scene_col = bpy.context.scene.collection
    if obj.name not in scene_col.objects:
        try:
            scene_col.objects.link(obj)
        except RuntimeError:
            return False
    return obj.name in view.objects


def _activate_object(obj) -> bool:
    import bpy

    if not _ensure_in_view_layer(obj):
        return False
    try:
        obj.hide_set(False)
    except RuntimeError:
        pass
    obj.hide_viewport = False
    obj.hide_render = False
    for other in bpy.context.view_layer.objects:
        other.select_set(False)
    try:
        obj.select_set(True)
    except RuntimeError:
        return False
    bpy.context.view_layer.objects.active = obj
    if getattr(obj, "mode", "OBJECT") != "OBJECT":
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except RuntimeError:
            return False
    return True


def _ops_override(obj):
    import bpy

    return bpy.context.temp_override(
        active_object=obj,
        object=obj,
        selected_objects=[obj],
        selected_editable_objects=[obj],
        view_layer=bpy.context.view_layer,
    )


def _ensure_single_user_data(obj) -> None:
    data = getattr(obj, "data", None)
    if data is not None and getattr(data, "users", 1) > 1:
        obj.data = data.copy()


def _apply_world_transform(obj) -> None:
    """Deja el objeto en su matrix_world sin parent.

    No se bakea la malla aquí: en Blender 5.2, convert()/to_mesh() ya deja
    vértices en espacio local y ``export_apply=True`` aplica el mundo una
    sola vez. Bakear + export_apply duplicaba escala (~3.3 m de alto).
    ``transform_apply`` con escala negativa (.l/.r) además volteaba
    geometría por el origen.
    """
    from mathutils import Matrix

    if getattr(obj, "library", None) is not None:
        try:
            obj.make_local()
        except RuntimeError:
            pass
    _ensure_single_user_data(obj)
    mw = obj.matrix_world.copy()
    if obj.parent is not None:
        obj.parent = None
        obj.matrix_parent_inverse = Matrix.Identity(4)
        obj.matrix_world = mw


def _convert_via_to_mesh(obj, desired: str):
    """Respaldo si convert() no tiene contexto editable."""
    import bpy

    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    temp_mesh = eval_obj.to_mesh()
    if temp_mesh is None or len(temp_mesh.vertices) == 0:
        if temp_mesh is not None:
            eval_obj.to_mesh_clear()
        return None
    mesh = temp_mesh.copy()
    mesh.name = desired
    eval_obj.to_mesh_clear()
    src_name = obj.name
    obj.name = f"{desired}.__curve_src__"
    new_obj = bpy.data.objects.new(desired, mesh)
    new_obj.matrix_world = obj.matrix_world.copy()
    for col in list(obj.users_collection):
        col.objects.link(new_obj)
    if new_obj.name != desired:
        new_obj.name = desired
    # El original queda como CURVE (no se exporta).
    if src_name == desired:
        pass
    return new_obj


def _convert_curve_to_mesh(obj):
    """CURVE → MESH, luego apply de la transform de mundo. Conserva el nombre."""
    import bpy

    desired = obj.name
    if not _activate_object(obj):
        new_obj = _convert_via_to_mesh(obj, desired)
        if new_obj is None:
            return None
        _apply_world_transform(new_obj)
        return new_obj
    if getattr(obj, "library", None) is not None:
        try:
            obj.make_local()
        except RuntimeError:
            pass
    with _ops_override(obj):
        bpy.ops.object.convert(target="MESH")
    mesh_obj = bpy.context.view_layer.objects.active
    if mesh_obj is None or mesh_obj.type != "MESH":
        new_obj = _convert_via_to_mesh(obj, desired)
        if new_obj is None:
            return None
        _apply_world_transform(new_obj)
        return new_obj
    if mesh_obj.name != desired:
        mesh_obj.name = desired
    verts = getattr(mesh_obj.data, "vertices", None)
    if verts is None or len(verts) == 0:
        return None
    _apply_world_transform(mesh_obj)
    return mesh_obj


def _convert_collection_curves(
    collection, exclude_names: set[str], profile_names: set[str]
) -> tuple[int, int, list[dict]]:
    import bpy

    candidates = []
    skipped_invalid: list[dict] = []
    for obj in list(_iter_collection_objects(collection)):
        if obj.type not in CONVERTIBLE_TYPES:
            continue
        if obj.name in exclude_names or obj.name in profile_names:
            continue
        invalid = _invalid_name_reason(obj.name)
        if invalid:
            skipped_invalid.append(
                {"name": obj.name, "reason": invalid, "when": "convert"}
            )
            continue
        if (
            _is_all_caps_label(obj.name)
            or _object_in_label_collection(obj)
            or _is_group_helper(obj.name)
        ):
            continue
        _ensure_curve_volume(obj)
        candidates.append(obj)
    bpy.context.view_layer.update()
    converted = 0
    failed = 0
    for obj in candidates:
        try:
            new_obj = _convert_curve_to_mesh(obj)
        except Exception as exc:  # noqa: BLE001 — inventario de fallos del convert
            print(f"  CURVE convert falló {obj.name}: {exc}")
            failed += 1
            continue
        if new_obj is None:
            failed += 1
            continue
        converted += 1
        if converted % 50 == 0:
            print(f"  CURVE→MESH progreso {converted}/{len(candidates)}")
    return converted, failed, skipped_invalid


def _looks_like_body_surface_name(name: str) -> bool:
    n = _normalize(name)
    if "skin" in n or "body surface" in n:
        return True
    if "integument" in n and "surface" in n:
        return True
    return False


def _collection_looks_like_skin(col) -> bool:
    n = _normalize(col.name)
    if n in SKIN_COLLECTION_EXACT:
        return True
    if n.startswith("skin "):
        return True
    return False


def _iter_skin_surface_objects(already: set[str]):
    import bpy

    for obj in bpy.data.objects:
        if obj.name in already:
            continue
        if obj.type != "MESH":
            continue
        if _is_all_caps_label(obj.name) or _object_in_label_collection(obj):
            continue
        if _looks_like_body_surface_name(obj.name):
            yield obj
            continue
        if any(_collection_looks_like_skin(col) for col in obj.users_collection):
            yield obj


def _select_object(obj) -> bool:
    import bpy

    if obj.name not in bpy.context.view_layer.objects:
        return False
    try:
        obj.hide_set(False)
    except RuntimeError:
        pass
    obj.hide_viewport = False
    obj.hide_render = False
    try:
        obj.select_set(True)
    except RuntimeError:
        return False
    return True


def _select_collection_meshes(
    collection, exclude_names: set[str], profile_names: set[str]
) -> tuple[int, int, int, int, list[str], list[dict]]:
    exported = 0
    excluded = 0
    excluded_prec = 0
    excluded_profiles = 0
    names: list[str] = []
    invalid: list[dict] = []
    for obj in _iter_collection_objects(collection):
        reason = _should_exclude(obj, exclude_names, profile_names)
        if reason is not None:
            if reason == "precedence":
                excluded_prec += 1
            elif reason == "profile":
                excluded_profiles += 1
            elif reason.startswith("invalid_name:"):
                invalid.append(
                    {
                        "name": obj.name,
                        "reason": reason.split(":", 1)[1],
                        "when": "export",
                    }
                )
            excluded += 1
            continue
        if not _select_object(obj):
            excluded += 1
            continue
        exported += 1
        names.append(obj.name)
    return exported, excluded, excluded_prec, excluded_profiles, names, invalid


def _write_meta(out_path: str, payload: dict) -> None:
    meta_path = Path(out_path).with_suffix(".meta.json")
    meta_path.write_text(f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n")
    names_path = Path(out_path).with_suffix(".names.txt")
    names_path.write_text(
        "".join(f"{n}\n" for n in payload.get("exportedNames", [])),
        encoding="utf-8",
    )
    skip = {"exportedNames", "invalidNames"}
    print(
        f"META {json.dumps({k: v for k, v in payload.items() if k not in skip}, ensure_ascii=False)}"
    )


def _export(args: argparse.Namespace) -> None:
    import bpy

    bpy.ops.wm.open_mainfile(filepath=args.blend)

    names = [c.name for c in _all_collections()]
    print("Colecciones (muestra):", ", ".join(names[:12]), "…")
    if args.list_collections:
        _list_collections()
        return
    if args.inventory is not None:
        _inventory(args.inventory)
        return

    collection = _find_collection(args.collection)
    if collection is None:
        raise SystemExit(
            f"No se encontró la colección '{args.collection}'. "
            f"Disponibles: {', '.join(names[:40])}…"
        )

    extras = []
    for extra_name in args.extra_collection:
        extra = _find_collection(extra_name)
        if extra is None:
            raise SystemExit(f"No se encontró la colección extra '{extra_name}'.")
        extras.append(extra)

    exclude_names = _load_exclude_names(args.exclude_names)
    profile_names = _collect_profile_names()
    print(f"Perfiles de bisel/taper identificados: {len(profile_names)}")
    converted = 0
    convert_failed = 0
    invalid_names: list[dict] = []
    if args.convert_curves:
        for col in (collection, *extras):
            conv, fail, skipped = _convert_collection_curves(
                col, exclude_names, profile_names
            )
            converted += conv
            convert_failed += fail
            invalid_names.extend(skipped)
        print(f"CURVE→MESH convertidas={converted} fallidas={convert_failed}")

    bpy.ops.object.select_all(action="DESELECT")
    exported = 0
    excluded = 0
    excluded_prec = 0
    excluded_profiles = 0
    exported_names: list[str] = []
    for col in (collection, *extras):
        exp, exc, prec, prof, col_names, invalid = _select_collection_meshes(
            col, exclude_names, profile_names
        )
        exported += exp
        excluded += exc
        excluded_prec += prec
        excluded_profiles += prof
        exported_names.extend(col_names)
        invalid_names.extend(invalid)

    skin_surface_found = 0
    if args.search_skin_surface:
        already = set(exported_names)
        for obj in _iter_skin_surface_objects(already):
            if obj.name in exclude_names:
                excluded_prec += 1
                excluded += 1
                continue
            if obj.name in profile_names:
                excluded_profiles += 1
                excluded += 1
                continue
            invalid = _invalid_name_reason(obj.name)
            if invalid:
                invalid_names.append(
                    {"name": obj.name, "reason": invalid, "when": "export"}
                )
                excluded += 1
                continue
            if not _select_object(obj):
                excluded += 1
                continue
            exported += 1
            skin_surface_found += 1
            exported_names.append(obj.name)
        print(f"Piel superficie extra: {skin_surface_found}")

    if exported == 0:
        raise SystemExit(f"La colección '{collection.name}' no tiene mallas exportables.")

    source_names = " + ".join([collection.name, *[e.name for e in extras]])
    female_note = _female_repro_note()

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
    print(
        f"Exportado {exported} mallas (excluidos {excluded}, "
        f"precedencia {excluded_prec}, perfiles {excluded_profiles}, "
        f"curvas {converted}) → {args.out}"
    )
    _write_meta(
        args.out,
        {
            "sourceCollection": source_names,
            "exportedObjects": exported,
            "excludedObjects": excluded,
            "excludedByPrecedence": excluded_prec,
            "convertedCurves": converted,
            "convertFailed": convert_failed,
            "excludedProfiles": excluded_profiles,
            "invalidNames": invalid_names,
            "skinSurfaceFound": skin_surface_found,
            "femaleReproductiveNote": female_note,
            "exportedNames": sorted(set(exported_names)),
            "systemId": args.system_id,
        },
    )


def main() -> None:
    args = _parse_args(_argv_after_double_dash(sys.argv))
    _export(args)


if __name__ == "__main__":
    main()
