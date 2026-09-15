"""Inventario headless de fuentes externas (BodyParts3D piel + HRA united-female).

Uso:
  /Applications/Blender.app/Contents/MacOS/Blender -b -P pipeline/inventory-external.py -- \\
    --out manifest/external-inventory.json

Sin decimar ni exportar GLB. Solo mide y escribe JSON.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "manifest" / "external-inventory.json"
EXTERNAL = REPO_ROOT / "source" / "external"
EXTRACTED = EXTERNAL / "extracted"
PARTS_LIST = EXTERNAL / "isa_parts_list_e.txt"
ZIP_PATH = EXTERNAL / "isa_BP3D_4.0_obj_99.zip"
HRA_GLB = EXTERNAL / "3d-vh-f-united.glb"
SKELETON_GLB = REPO_ROOT / "dist" / "raw" / "skeleton.glb"

# IDs preferidos (isa_parts_list_e.txt); fallbacks documentados en el JSON.
BP3D_TARGETS = {
    "skin": ["FMA7163"],
    "femur": ["FMA9611", "FMA24474", "FMA24475"],  # femur / right / left
    "hip_bone": ["FMA16585", "FMA16586", "FMA16587"],  # hip / right / left
}

REPRO_KEYWORDS = (
    "uterus",
    "ovary",
    "fallopian",
    "uterine tube",
    "vagina",
    "cervix",
    "mammary",
    "breast",
    "skin",
    "body",
)

SYSTEM_KEYWORDS: dict[str, tuple[str, ...]] = {
    "skin": (
        "skin",
        "integument",
        "epidermis",
        "dermis",
        "breast",
        "mammary",
        "nipple",
        "areola",
    ),
    "muscles": ("muscle", "muscular", "myo"),
    "skeleton": (
        "bone",
        "skeleton",
        "skeletal",
        "vertebra",
        "rib",
        "skull",
        "femur",
        "tibia",
        "fibula",
        "patella",
        "pelvis",
        "hip",
        "cartilage",
        "joint",
        "tooth",
        "teeth",
        "sacrum",
        "coccyx",
        "clavicle",
        "scapula",
        "humerus",
        "radius",
        "ulna",
        "sternum",
        "calcaneus",
        "talus",
        "metatarsal",
        "metacarpal",
        "phalanx",
        "ligament",
        "meniscus",
        "condyle",
    ),
    "vessels": (
        "artery",
        "vein",
        "vessel",
        "vascular",
        "aorta",
        "vena",
        "blood",
        "capillary",
    ),
    "nerves": (
        "nerve",
        "neural",
        "brain",
        "spinal_cord",
        "spinal cord",
        "ganglion",
        "plexus",
        "allen_",
        "cortex",
        "gyrus",
        "sulcus",
        "thalamus",
        "hippocamp",
        "amygdala",
        "ventricle",
        "white_matter",
        "caudate",
        "putamen",
    ),
    "viscera": (
        "liver",
        "lung",
        "heart",
        "kidney",
        "stomach",
        "intestin",
        "colon",
        "spleen",
        "pancrea",
        "bladder",
        "uterus",
        "ovary",
        "fallopian",
        "uterine",
        "vagina",
        "cervix",
        "thyroid",
        "viscera",
        "trachea",
        "esophag",
        "gallbladder",
        "adrenal",
        "prostate",
        "testis",
        "rectum",
        "anus",
        "urethra",
        "ureter",
        "lymph",
        "thymus",
        "tonsil",
        "duodenum",
        "jejunum",
        "ileum",
        "cecum",
        "appendix",
    ),
}

# Estimación cruda: ~bytes por triángulo empaquetado (meshopt+ktx) a si=1.
# Calibrado a ojo contra presupuesto ADR 0021 (≤15 MB/sistema).
BYTES_PER_TRI_SI1 = 28.0
ADR_BUDGET_BYTES = 15 * 1024 * 1024


def _argv_after_double_dash(argv: list[str]) -> list[str]:
    if "--" in argv:
        return argv[argv.index("--") + 1 :]
    return argv[1:]


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Inventario externo BP3D + HRA")
    p.add_argument("--out", default=str(DEFAULT_OUT), help="JSON de salida")
    p.add_argument(
        "--external-dir",
        default=str(EXTERNAL),
        help="Carpeta source/external",
    )
    p.add_argument(
        "--skeleton-glb",
        default=str(SKELETON_GLB),
        help="GLB skeleton Z-Anatomy (dist/raw)",
    )
    p.add_argument(
        "--skip-bp3d",
        action="store_true",
        help="Solo HRA (debug)",
    )
    p.add_argument(
        "--skip-hra",
        action="store_true",
        help="Solo BP3D (debug)",
    )
    return p.parse_args(argv)


def _log(msg: str) -> None:
    print(f"[inventory-external] {msg}", flush=True)


def _clear_scene() -> None:
    import bpy

    bpy.ops.wm.read_factory_settings(use_empty=True)


def _bbox_corners_world(obj) -> list[tuple[float, float, float]]:
    import mathutils

    corners = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
    return [(float(v.x), float(v.y), float(v.z)) for v in corners]


def _bbox_minmax(corners: list[tuple[float, float, float]]) -> dict:
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    zs = [c[2] for c in corners]
    mn = [min(xs), min(ys), min(zs)]
    mx = [max(xs), max(ys), max(zs)]
    size = [mx[i] - mn[i] for i in range(3)]
    center = [(mn[i] + mx[i]) / 2 for i in range(3)]
    return {
        "min": [round(v, 6) for v in mn],
        "max": [round(v, 6) for v in mx],
        "size": [round(v, 6) for v in size],
        "center": [round(v, 6) for v in center],
    }


def _mesh_stats(obj) -> dict:
    mesh = obj.data
    mesh.calc_loop_triangles()
    verts = len(mesh.vertices)
    tris = len(mesh.loop_triangles)
    # Non-manifold edges
    import bmesh

    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.edges.ensure_lookup_table()
    non_manifold = sum(1 for e in bm.edges if not e.is_manifold)
    # Connected components (islands) via vertices
    visited = set()
    islands = []
    vert_list = list(bm.verts)
    for v in vert_list:
        if v.index in visited:
            continue
        stack = [v]
        visited.add(v.index)
        comps = []
        while stack:
            cur = stack.pop()
            comps.append(cur)
            for e in cur.link_edges:
                other = e.other_vert(cur)
                if other.index not in visited:
                    visited.add(other.index)
                    stack.append(other)
        # area + bbox of island
        faces = {f for vv in comps for f in vv.link_faces}
        area = sum(f.calc_area() for f in faces)
        if comps:
            coords = [vv.co for vv in comps]
            mn = [min(c[i] for c in coords) for i in range(3)]
            mx = [max(c[i] for c in coords) for i in range(3)]
            size = [mx[i] - mn[i] for i in range(3)]
        else:
            mn = mx = size = [0, 0, 0]
            area = 0.0
        islands.append(
            {
                "verts": len(comps),
                "faces": len(faces),
                "area": round(float(area), 4),
                "bbox_size": [round(float(s), 4) for s in size],
                "bbox_min": [round(float(s), 4) for s in mn],
                "bbox_max": [round(float(s), 4) for s in mx],
            }
        )
    bm.free()
    islands.sort(key=lambda i: i["area"], reverse=True)
    # Heurística «externa»: mayor área, o la que envuelve el bbox global
    corners = _bbox_corners_world(obj)
    global_bb = _bbox_minmax(corners)
    gsize = global_bb["size"]
    external_idx = 0
    if islands:
        best_wrap = None
        best_score = -1.0
        for i, isl in enumerate(islands):
            # score: how close island bbox is to global bbox (product of size ratios)
            ratios = []
            for a, b in zip(isl["bbox_size"], gsize):
                if b <= 1e-9:
                    continue
                ratios.append(min(a / b, 1.0))
            score = (sum(ratios) / len(ratios)) if ratios else 0.0
            score = score * 0.5 + (isl["area"] / max(islands[0]["area"], 1e-9)) * 0.5
            if score > best_score:
                best_score = score
                best_wrap = i
        external_idx = best_wrap if best_wrap is not None else 0
        for i, isl in enumerate(islands):
            isl["external_candidate"] = i == external_idx
    return {
        "name": obj.name,
        "vertices": verts,
        "triangles": tris,
        "non_manifold_edges": non_manifold,
        "connected_components": len(islands),
        "external_components": 1 if islands else 0,
        "external_heuristic": "largest_area_or_bbox_wrap",
        "islands": islands[:20],  # cap detail
        "island_count_total": len(islands),
        "bbox_native": global_bb,
    }


def _import_obj(path: Path):
    import bpy

    before = {o.name for o in bpy.data.objects}
    # Blender 4.x: wm.obj_import; 3.x: import_scene.obj
    if hasattr(bpy.ops.wm, "obj_import"):
        bpy.ops.wm.obj_import(filepath=str(path))
    else:
        bpy.ops.import_scene.obj(filepath=str(path))
    return [o for o in bpy.data.objects if o.name not in before and o.type == "MESH"]


def _import_glb(path: Path):
    import bpy

    before = {o.name for o in bpy.data.objects}
    bpy.ops.import_scene.gltf(filepath=str(path))
    return [o for o in bpy.data.objects if o.name not in before]


def _find_mesh_by_name_hint(objects, hints: tuple[str, ...]):
    """Prioriza igualdad casefold; luego startswith; evita que 'femur' capture Femur.l al buscar .r."""
    hints_l = [h.lower() for h in hints]
    meshes = [o for o in objects if o.type == "MESH"]
    for h in hints_l:
        for obj in meshes:
            if obj.name.lower() == h:
                return obj
    for h in hints_l:
        for obj in meshes:
            if obj.name.lower().startswith(h):
                return obj
    for h in hints_l:
        # Solo substrings «largos» (≥6) para no confundir lados .l/.r
        if len(h) < 6:
            continue
        for obj in meshes:
            if h in obj.name.lower():
                return obj
    return None


def _load_parts_map(parts_path: Path) -> dict[str, dict]:
    """concept_id -> {bp_id, en} desde isa_parts_list_e.txt"""
    mapping = {}
    if not parts_path.exists():
        return mapping
    with parts_path.open(encoding="utf-8", errors="replace") as f:
        f.readline()
        for line in f:
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 3:
                continue
            concept, bp, en = cols[0], cols[1], cols[2]
            mapping[concept] = {"bp_id": bp, "en": en}
    return mapping


def _load_element_parts(element_path: Path) -> dict[str, list[str]]:
    """concept_id -> [FJ… element file ids]. Los OBJ del zip 99% se nombran FJ*.obj."""
    mapping: dict[str, list[str]] = {}
    if not element_path.exists():
        return mapping
    with element_path.open(encoding="utf-8", errors="replace") as f:
        f.readline()
        for line in f:
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 3:
                continue
            concept, _name, fj = cols[0], cols[1], cols[2]
            mapping.setdefault(concept, [])
            if fj not in mapping[concept]:
                mapping[concept].append(fj)
    return mapping


def _resolve_bp3d_files(
    zip_path: Path,
    extracted: Path,
    parts: dict[str, dict],
    elements: dict[str, list[str]],
) -> dict:
    """Extrae solo OBJ necesarios. Zip 99% usa element file id (FJ*.obj), no FMA/BP."""
    import zipfile

    extracted.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        namelist = zf.namelist()
        by_base = {Path(n).name.lower(): n for n in namelist if n.lower().endswith(".obj")}

    # Prefer sided bones for alignment (right femur / right hip).
    role_preferred_fma = {
        "skin": ["FMA7163"],
        "femur": ["FMA24474", "FMA9611", "FMA24475"],
        "hip_bone": ["FMA16586", "FMA16585", "FMA16587"],
    }

    resolved = {}
    for role, fma_ids in role_preferred_fma.items():
        chosen = None
        chosen_fma = None
        chosen_fj = None
        for fma in fma_ids:
            for fj in elements.get(fma, []):
                cand = f"{fj}.obj".lower()
                if cand in by_base:
                    chosen = by_base[cand]
                    chosen_fma = fma
                    chosen_fj = fj
                    break
            if chosen:
                break
        if not chosen:
            resolved[role] = {
                "ok": False,
                "requested_ids": fma_ids,
                "error": "OBJ not found in zip (via isa_element_parts FJ*)",
                "element_candidates": {f: elements.get(f, []) for f in fma_ids},
            }
            continue
        out_name = Path(chosen).name
        out_path = extracted / out_name
        with zipfile.ZipFile(zip_path) as zf:
            with zf.open(chosen) as src, out_path.open("wb") as dst:
                dst.write(src.read())
        info = parts.get(chosen_fma, {})
        note = (
            f"OBJ nombrado por element file id {chosen_fj}.obj "
            f"(isa_element_parts.txt); concept {chosen_fma}"
        )
        if chosen_fma != BP3D_TARGETS.get(role, [None])[0]:
            note += f"; id preferido de la spec {BP3D_TARGETS[role][0]} → equivalente {chosen_fma}"
        resolved[role] = {
            "ok": True,
            "fma_id": chosen_fma,
            "element_file_id": chosen_fj,
            "bp_id": info.get("bp_id"),
            "en": info.get("en") or elements and None,
            "zip_member": chosen,
            "path": str(out_path),
            "bytes": out_path.stat().st_size,
            "requested_ids": fma_ids,
            "note": note,
        }
        # Fill en from parts list if present
        if not resolved[role]["en"] and chosen_fma in parts:
            resolved[role]["en"] = parts[chosen_fma].get("en")
    return resolved


def _estimate_budget(triangles: int) -> dict:
    est_si1 = triangles * BYTES_PER_TRI_SI1
    return {
        "triangles": triangles,
        "est_bytes_si1": int(est_si1),
        "est_bytes_si_0_25": int(est_si1 * 0.25),
        "est_bytes_si_0_1": int(est_si1 * 0.1),
        "est_mb_si1": round(est_si1 / (1024 * 1024), 2),
        "est_mb_si_0_25": round(est_si1 * 0.25 / (1024 * 1024), 2),
        "est_mb_si_0_1": round(est_si1 * 0.1 / (1024 * 1024), 2),
        "adr_budget_mb": 15,
        "fits_si_0_25": est_si1 * 0.25 <= ADR_BUDGET_BYTES,
        "fits_si_0_1": est_si1 * 0.1 <= ADR_BUDGET_BYTES,
        "note": "Estimación proporcional (no se corrió gltfpack); factor empírico ~28 B/tri a si=1",
    }


def _centroid_from_bbox(bb: dict) -> list[float]:
    return list(bb["center"])


def _align_bp3d_to_zanatomy(femur_bp3d, femur_za, coxal_bp3d) -> dict:
    """Escala mm→m, rotación Z-up→Y-up (Rx -90°), traslación de centroides de fémur.

    Residuo: distancia media de esquinas de bbox del coxal tras la misma transform,
    comparado con… no hay coxal ZA emparejado 1:1 aquí; medimos residuo del fémur
    (esquinas BP3D transformadas vs bbox ZA) y del coxal vs su propio centro
    proyectado (control de consistencia de escala/rotación entre huesos).
    """
    import mathutils
    from mathutils import Matrix, Vector

    bb_bp = _bbox_minmax(_bbox_corners_world(femur_bp3d))
    bb_za = _bbox_minmax(_bbox_corners_world(femur_za))

    # Detect units: if BP3D size is ~hundreds, it's mm
    bp_height = max(bb_bp["size"])
    za_height = max(bb_za["size"])
    scale = (za_height / bp_height) if bp_height > 1e-9 else 0.001
    # Prefer canonical mm→m if close
    if 0.0005 < scale < 0.002:
        scale_used = 0.001
        scale_note = "canonical mm→m (0.001); measured ratio close"
    else:
        scale_used = scale
        scale_note = f"measured size ratio za/bp={scale:.6f}"

    # Z-up (BP3D) → Y-up (glTF/Z-Anatomy): rotate -90° around X
    # (x,y,z)_zup → (x,z,-y)_yup
    R = Matrix.Rotation(math.radians(-90.0), 4, "X")
    S = Matrix.Scale(scale_used, 4)

    c_bp = Vector(bb_bp["center"])
    c_za = Vector(bb_za["center"])
    c_bp_scaled_rot = R @ (S @ c_bp)
    T = Matrix.Translation(c_za - c_bp_scaled_rot)
    M = T @ R @ S

    def transform_corners(obj):
        out = []
        for c in _bbox_corners_world(obj):
            v = M @ Vector(c)
            out.append((float(v.x), float(v.y), float(v.z)))
        return out

    # Residuo fémur: mean distance of transformed BP corners to nearest ZA bbox corner
    za_corners = [Vector(c) for c in _bbox_corners_world(femur_za)]
    bp_t = [Vector(c) for c in transform_corners(femur_bp3d)]
    femur_dists = []
    for v in bp_t:
        d = min((v - z).length for z in za_corners)
        femur_dists.append(d)
    femur_residuo_m = sum(femur_dists) / len(femur_dists)
    femur_residuo_mm = femur_residuo_m * 1000.0

    # Control coxal: apply same M; compare bbox size to ZA hip bone if present,
    # else report transformed bbox and consistency of femur/coxal scale.
    coxal_result = None
    if coxal_bp3d is not None:
        cox_t = transform_corners(coxal_bp3d)
        cox_bb = _bbox_minmax(cox_t)
        # If we have ZA hip, compute corner residuo similarly
        coxal_result = {
            "bbox_transformed_m": cox_bb,
            "note": "misma matriz M del fémur aplicada al coxal (control)",
        }

    # Also compute residual of femur bbox centers after transform
    bp_center_t = M @ Vector(bb_bp["center"])
    center_err_m = (bp_center_t - c_za).length

    mat_list = [list(row) for row in M]

    # Axis convention check from raw (pre-transform) sizes
    axis_guess = {
        "bp3d_bbox_size": bb_bp["size"],
        "zanatomy_bbox_size": bb_za["size"],
        "bp3d_likely_up_axis": ["X", "Y", "Z"][max(range(3), key=lambda i: bb_bp["size"][i])],
        "zanatomy_likely_up_axis": ["X", "Y", "Z"][max(range(3), key=lambda i: bb_za["size"][i])],
        "assumed_bp3d": "Z-up millimeters",
        "assumed_zanatomy": "Y-up meters (glTF)",
    }

    return {
        "scale": scale_used,
        "scale_measured": scale,
        "scale_note": scale_note,
        "rotation": "Rx_-90deg (Z-up → Y-up)",
        "translation_m": [round(float(x), 6) for x in (c_za - c_bp_scaled_rot)],
        "matrix_4x4": mat_list,
        "femur_bp3d_bbox_native": bb_bp,
        "femur_zanatomy_bbox_m": bb_za,
        "femur_center_error_m": round(float(center_err_m), 6),
        "femur_residuo_mean_corner_m": round(float(femur_residuo_m), 6),
        "femur_residuo_mean_corner_mm": round(float(femur_residuo_mm), 3),
        "coxal_control": coxal_result,
        "axis_guess": axis_guess,
    }


def _map_system(name: str) -> str:
    raw = name.lower()
    n = raw.replace("_", " ").replace("-", " ")
    if raw.startswith("allen_"):
        return "nerves"
    for system in ("vessels", "nerves", "muscles", "skeleton", "viscera", "skin"):
        for kw in SYSTEM_KEYWORDS[system]:
            needle = kw.lower()
            hay = raw if "_" in needle else n
            if needle in hay:
                return system
    return "sin_sistema"


def _first_level_group(name: str) -> str:
    # Prefer prefix before ':' or '/' or first token
    for sep in (":", "/", "|"):
        if sep in name:
            return name.split(sep, 1)[0].strip() or name
    # camel / underscore groups — take leading capital words
    parts = re.split(r"[_\s\.]+", name)
    return parts[0] if parts else name


def _has_ontology_id(name: str) -> dict:
    return {
        "uberon": bool(re.search(r"UBERON[:_]?[0-9]+", name, re.I)),
        "fma": bool(re.search(r"FMA[:_]?[0-9]+", name, re.I)),
    }


def inventory_bp3d(external_dir: Path, skeleton_glb: Path) -> dict:
    import bpy

    zip_path = external_dir / "isa_BP3D_4.0_obj_99.zip"
    parts_path = external_dir / "isa_parts_list_e.txt"
    element_path = external_dir / "isa_element_parts.txt"
    extracted = external_dir / "extracted"
    parts = _load_parts_map(parts_path)
    elements = _load_element_parts(element_path)
    if not elements:
        return {
            "source": "BodyParts3D 4.0",
            "error": f"missing or empty {element_path} (FMA→FJ map)",
        }
    _log(f"Resolviendo / extrayendo OBJ BP3D ({len(elements)} conceptos en element_parts)…")
    resolved = _resolve_bp3d_files(zip_path, extracted, parts, elements)

    result = {
        "source": "BodyParts3D 4.0",
        "zip_bytes": zip_path.stat().st_size if zip_path.exists() else None,
        "resolved_parts": resolved,
        "skin": None,
        "alignment": None,
        "errors": [],
    }

    if not resolved.get("skin", {}).get("ok"):
        result["errors"].append("skin OBJ missing")
        return result

    _clear_scene()
    _log(f"Importando piel {resolved['skin']['path']}…")
    skin_objs = _import_obj(Path(resolved["skin"]["path"]))
    if not skin_objs:
        result["errors"].append("skin import produced 0 meshes")
        return result
    # join if multiple
    skin = skin_objs[0]
    if len(skin_objs) > 1:
        import bpy

        bpy.context.view_layer.objects.active = skin
        for o in skin_objs:
            o.select_set(True)
        bpy.ops.object.join()
        skin = bpy.context.view_layer.objects.active
    stats = _mesh_stats(skin)
    stats["obj_bytes"] = resolved["skin"]["bytes"]
    stats["fma_id"] = resolved["skin"]["fma_id"]
    stats["budget"] = _estimate_budget(stats["triangles"])
    result["skin"] = stats

    # Alignment: femur + coxal
    femur_path = resolved.get("femur", {})
    hip_path = resolved.get("hip_bone", {})
    if not femur_path.get("ok"):
        result["errors"].append("femur OBJ missing; alignment skipped")
        return result

    _clear_scene()
    _log("Importando fémur/coxal BP3D + skeleton Z-Anatomy…")
    femur_objs = _import_obj(Path(femur_path["path"]))
    coxal_objs = []
    if hip_path.get("ok"):
        coxal_objs = _import_obj(Path(hip_path["path"]))
    femur_bp = femur_objs[0] if femur_objs else None
    coxal_bp = coxal_objs[0] if coxal_objs else None
    if femur_bp is None:
        result["errors"].append("femur import failed")
        return result

    if not skeleton_glb.exists():
        result["errors"].append(f"skeleton GLB missing: {skeleton_glb}")
        return result

    za_objs = _import_glb(skeleton_glb)
    femur_za = _find_mesh_by_name_hint(za_objs, ("Femur.r", "Femur.l", "femur"))
    # Prefer right femur to match FMA24474 if that was chosen
    if femur_path.get("fma_id") == "FMA24475":
        femur_za = _find_mesh_by_name_hint(za_objs, ("Femur.l", "femur")) or femur_za
    else:
        femur_za = _find_mesh_by_name_hint(za_objs, ("Femur.r", "femur")) or femur_za

    # Emparejar lado: FMA16586 = right hip → Hip bone.r
    if hip_path.get("fma_id") == "FMA16587":
        hip_za = _find_mesh_by_name_hint(za_objs, ("Hip bone.l", "hip bone"))
    else:
        hip_za = _find_mesh_by_name_hint(za_objs, ("Hip bone.r", "hip bone"))

    if femur_za is None:
        result["errors"].append("Femur not found in Z-Anatomy skeleton.glb")
        result["zanatomy_mesh_sample"] = [o.name for o in za_objs if o.type == "MESH"][:30]
        return result

    align = _align_bp3d_to_zanatomy(femur_bp, femur_za, coxal_bp)
    align["bp3d_femur"] = {
        "fma_id": femur_path.get("fma_id"),
        "name": femur_bp.name,
        "triangles": len(femur_bp.data.loop_triangles) if False else None,
    }
    # ensure loop tris
    femur_bp.data.calc_loop_triangles()
    align["bp3d_femur"]["triangles"] = len(femur_bp.data.loop_triangles)
    femur_za.data.calc_loop_triangles()
    align["zanatomy_femur"] = {
        "name": femur_za.name,
        "triangles": len(femur_za.data.loop_triangles),
    }
    if coxal_bp is not None:
        coxal_bp.data.calc_loop_triangles()
        align["bp3d_coxal"] = {
            "fma_id": hip_path.get("fma_id"),
            "name": coxal_bp.name,
            "triangles": len(coxal_bp.data.loop_triangles),
        }
        # Residuo coxal vs hip ZA si existe
        if hip_za is not None:
            import mathutils
            from mathutils import Matrix, Vector

            M = Matrix(align["matrix_4x4"])
            za_corners = [Vector(c) for c in _bbox_corners_world(hip_za)]
            bp_t = [M @ Vector(c) for c in _bbox_corners_world(coxal_bp)]
            dists = [min((v - z).length for z in za_corners) for v in bp_t]
            mean_m = sum(dists) / len(dists)
            align["coxal_control"]["zanatomy_hip"] = hip_za.name
            align["coxal_control"]["residuo_mean_corner_m"] = round(float(mean_m), 6)
            align["coxal_control"]["residuo_mean_corner_mm"] = round(float(mean_m) * 1000.0, 3)
    result["alignment"] = align
    return result


def inventory_hra(external_dir: Path) -> dict:
    import bpy

    glb = external_dir / "3d-vh-f-united.glb"
    if not glb.exists():
        return {"error": f"missing {glb}", "bytes": None}

    _clear_scene()
    _log(f"Importando HRA GLB ({glb.stat().st_size} bytes)…")
    objs = _import_glb(glb)
    meshes = [o for o in objs if o.type == "MESH"]
    _log(f"HRA: {len(objs)} objetos, {len(meshes)} mallas")

    groups = Counter()
    group_tris = Counter()
    system_meshes: dict[str, list] = defaultdict(list)
    system_tris: Counter = Counter()
    ontology_counts = {"uberon": 0, "fma": 0, "neither": 0}
    keyword_hits = []
    mesh_rows = []
    all_corners = []

    for obj in meshes:
        obj.data.calc_loop_triangles()
        tris = len(obj.data.loop_triangles)
        verts = len(obj.data.vertices)
        g = _first_level_group(obj.name)
        groups[g] += 1
        group_tris[g] += tris
        system = _map_system(obj.name)
        system_meshes[system].append(obj.name)
        system_tris[system] += tris
        ont = _has_ontology_id(obj.name)
        if ont["uberon"]:
            ontology_counts["uberon"] += 1
        elif ont["fma"]:
            ontology_counts["fma"] += 1
        else:
            ontology_counts["neither"] += 1
        name_l = obj.name.lower()
        if any(k in name_l for k in REPRO_KEYWORDS):
            keyword_hits.append(
                {
                    "name": obj.name,
                    "triangles": tris,
                    "vertices": verts,
                    "system_guess": system,
                    "matched_keywords": [k for k in REPRO_KEYWORDS if k in name_l],
                }
            )
        corners = _bbox_corners_world(obj)
        all_corners.extend(corners)
        mesh_rows.append(
            {
                "name": obj.name,
                "triangles": tris,
                "vertices": verts,
                "group": g,
                "system_guess": system,
            }
        )

    total_bb = _bbox_minmax(all_corners) if all_corners else None
    # Height in meters: assume Y-up; take max axis as height candidate + report Y size
    height_m = None
    up_axis = None
    if total_bb:
        sizes = total_bb["size"]
        up_axis = ["X", "Y", "Z"][max(range(3), key=lambda i: sizes[i])]
        height_m = sizes[{"X": 0, "Y": 1, "Z": 2}[up_axis]]

    coverage = {}
    for sys_id in ("skin", "muscles", "skeleton", "vessels", "nerves", "viscera", "sin_sistema"):
        coverage[sys_id] = {
            "meshes": len(system_meshes.get(sys_id, [])),
            "triangles": int(system_tris.get(sys_id, 0)),
            "budget": _estimate_budget(int(system_tris.get(sys_id, 0))),
            "sample_names": system_meshes.get(sys_id, [])[:15],
        }

    # Tree first level
    tree = [
        {"group": g, "meshes": groups[g], "triangles": group_tris[g]}
        for g in sorted(groups.keys(), key=lambda x: (-groups[x], x))
    ]

    return {
        "source": "HuBMAP HRA united-female v1.5",
        "glb_bytes": glb.stat().st_size,
        "objects_total": len(objs),
        "meshes_total": len(meshes),
        "triangles_total": int(sum(system_tris.values())),
        "bbox_total": total_bb,
        "height_m": round(height_m, 4) if height_m is not None else None,
        "likely_up_axis": up_axis,
        "assumed_units": "meters (glTF)",
        "ontology_id_in_names": ontology_counts,
        "first_level_groups": tree,
        "keyword_meshes": keyword_hits,
        "coverage_by_system": coverage,
        "tentative_mapping_note": (
            "Heurística por keywords en el nombre; no es curación anatómica."
        ),
        # full mesh list can be large — include compact
        "all_mesh_names": [m["name"] for m in mesh_rows],
        "mesh_count_listed": len(mesh_rows),
    }


def main() -> int:
    args = _parse_args(_argv_after_double_dash(sys.argv))
    external_dir = Path(args.external_dir)
    out_path = Path(args.out)
    skeleton_glb = Path(args.skeleton_glb)

    _log(f"external={external_dir}")
    _log(f"out={out_path}")

    report = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": "biomapa-atlas-assets",
        "script": "pipeline/inventory-external.py",
        "bodyparts3d": None,
        "hra_united_female": None,
        "web_budget_summary": {},
    }

    if not args.skip_bp3d:
        try:
            report["bodyparts3d"] = inventory_bp3d(external_dir, skeleton_glb)
        except Exception as e:
            report["bodyparts3d"] = {"error": str(e)}
            _log(f"BP3D ERROR: {e}")

    if not args.skip_hra:
        try:
            report["hra_united_female"] = inventory_hra(external_dir)
        except Exception as e:
            report["hra_united_female"] = {"error": str(e)}
            _log(f"HRA ERROR: {e}")

    # Budget summary
    summary = {}
    bp = report.get("bodyparts3d") or {}
    if isinstance(bp, dict) and bp.get("skin") and bp["skin"].get("budget"):
        summary["bp3d_skin"] = bp["skin"]["budget"]
    hra = report.get("hra_united_female") or {}
    if isinstance(hra, dict) and hra.get("coverage_by_system"):
        summary["hra_by_system"] = {
            k: v["budget"] for k, v in hra["coverage_by_system"].items()
        }
    report["web_budget_summary"] = summary

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _log(f"Escrito {out_path} ({out_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
