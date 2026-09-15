"""Construye superficie de piel BodyParts3D alineada a Z-Anatomy (SKIN-01).

Uso:
  /Applications/Blender.app/Contents/MacOS/Blender -b -P pipeline/build-skin-surface.py -- \\
    [--out dist/raw/skin-surface.glb] [--meta dist/raw/skin-surface.meta.json]

Pasos: isla externa FJ2810 → limpieza → LS (escala + Rx−90° + T) con ≥6 huesos →
validación de envoltura vs muscles → decimate ≤60k → export Skin.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXTERNAL = REPO_ROOT / "source" / "external"
EXTRACTED = EXTERNAL / "extracted"
ZIP_PATH = EXTERNAL / "isa_BP3D_4.0_obj_99.zip"
ELEMENT_PARTS = EXTERNAL / "isa_element_parts.txt"
SKELETON_GLB = REPO_ROOT / "dist" / "raw" / "skeleton.glb"
MUSCLES_GLB = REPO_ROOT / "dist" / "raw" / "muscles.glb"
DEFAULT_OUT = REPO_ROOT / "dist" / "raw" / "skin-surface.glb"
DEFAULT_META = REPO_ROOT / "dist" / "raw" / "skin-surface.meta.json"

# FMA → (ZA name hints, role label)
BONE_TARGETS: list[dict] = [
    {
        "role": "femur_r",
        "fma": "FMA24474",
        "za_hints": ("Femur.r", "Femur.R"),
    },
    {
        "role": "femur_l",
        "fma": "FMA24475",
        "za_hints": ("Femur.l", "Femur.L"),
    },
    {
        "role": "hip_r",
        "fma": "FMA16586",
        "za_hints": ("Hip bone.r", "Hip bone.R"),
    },
    {
        "role": "hip_l",
        "fma": "FMA16587",
        "za_hints": ("Hip bone.l", "Hip bone.L"),
    },
    {
        "role": "humerus_r",
        "fma": "FMA23130",
        "za_hints": ("Humerus.r", "Humerus.R"),
    },
    {
        "role": "humerus_l",
        "fma": "FMA23131",
        "za_hints": ("Humerus.l", "Humerus.L"),
    },
    {
        "role": "frontal",
        "fma": "FMA52734",
        "za_hints": ("Frontal bone", "Frontal"),
    },
    {
        "role": "sacrum",
        "fma": "FMA16202",
        "za_hints": ("Sacrum",),
    },
]

SKIN_OBJ = EXTRACTED / "FJ2810.obj"
TARGET_TRIS = 60_000
REMOVE_DOUBLES_MM = 0.01  # mm in native BP3D units
FILL_HOLE_MAX_SIDES = 30
MUSCLE_SAMPLE = 5_000
MEDIAN_OK_MM = 8.0
MEDIAN_STOP_MM = 12.0
OUTSIDE_OK_PCT = 3.0
OUTSIDE_STOP_PCT = 6.0


def _argv_after_double_dash(argv: list[str]) -> list[str]:
    if "--" in argv:
        return argv[argv.index("--") + 1 :]
    return argv[1:]


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SKIN-01 superficie BodyParts3D")
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument("--meta", default=str(DEFAULT_META))
    p.add_argument("--skin-obj", default=str(SKIN_OBJ))
    p.add_argument("--skeleton-glb", default=str(SKELETON_GLB))
    p.add_argument("--muscles-glb", default=str(MUSCLES_GLB))
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args(argv)


def _log(msg: str) -> None:
    print(f"[build-skin-surface] {msg}", flush=True)


def _clear_scene() -> None:
    import bpy

    bpy.ops.wm.read_factory_settings(use_empty=True)


def _load_element_parts(path: Path) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    if not path.exists():
        return mapping
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        concept, _en, fj = parts[0], parts[1], parts[2]
        mapping.setdefault(concept, []).append(fj)
    return mapping


def _ensure_obj(fma: str, elements: dict[str, list[str]]) -> Path | None:
    EXTRACTED.mkdir(parents=True, exist_ok=True)
    for fj in elements.get(fma, []):
        out = EXTRACTED / f"{fj}.obj"
        if out.exists():
            return out
        member = f"isa_BP3D_4.0_obj_99/{fj}.obj"
        if not ZIP_PATH.exists():
            return None
        with zipfile.ZipFile(ZIP_PATH) as zf:
            names = {Path(n).name.lower(): n for n in zf.namelist()}
            key = f"{fj}.obj".lower()
            if key not in names:
                continue
            with zf.open(names[key]) as src, out.open("wb") as dst:
                dst.write(src.read())
            return out
    return None


def _import_obj(path: Path):
    import bpy

    before = {o.name for o in bpy.data.objects}
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


def _bbox_center_world(obj) -> tuple[float, float, float]:
    import mathutils

    corners = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
    cx = sum(v.x for v in corners) / 8.0
    cy = sum(v.y for v in corners) / 8.0
    cz = sum(v.z for v in corners) / 8.0
    return (float(cx), float(cy), float(cz))


def _bbox_size_world(obj) -> tuple[float, float, float]:
    import mathutils

    corners = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
    xs = [v.x for v in corners]
    ys = [v.y for v in corners]
    zs = [v.z for v in corners]
    return (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))


def _find_za_mesh(objects, hints: tuple[str, ...]):
    meshes = [o for o in objects if o.type == "MESH"]
    by_lower = {o.name.lower(): o for o in meshes}
    for h in hints:
        if h.lower() in by_lower:
            return by_lower[h.lower()]
    for h in hints:
        hl = h.lower()
        for o in meshes:
            if o.name.lower().startswith(hl):
                return o
    for h in hints:
        hl = h.lower()
        for o in meshes:
            if hl in o.name.lower():
                return o
    return None


def _separate_external_island(obj) -> dict:
    """Conserva la isla de mayor área que envuelve el bbox; borra el resto."""
    import bmesh
    import bpy

    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    visited = set()
    islands = []
    for v in bm.verts:
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
        faces = {f for vv in comps for f in vv.link_faces}
        area = sum(f.calc_area() for f in faces) if faces else 0.0
        if comps:
            coords = [vv.co for vv in comps]
            mn = [min(c[i] for c in coords) for i in range(3)]
            mx = [max(c[i] for c in coords) for i in range(3)]
            size = [mx[i] - mn[i] for i in range(3)]
        else:
            mn = mx = size = [0.0, 0.0, 0.0]
        islands.append(
            {
                "verts": comps,
                "faces": faces,
                "area": float(area),
                "bbox_size": size,
                "n_verts": len(comps),
                "n_faces": len(faces),
            }
        )

    if not islands:
        bpy.ops.object.mode_set(mode="OBJECT")
        raise SystemExit("Piel sin islas")

    # Heurística externa: mayor área × wrap del bbox global
    gsize = [0.0, 0.0, 0.0]
    for isl in islands:
        for i in range(3):
            gsize[i] = max(gsize[i], isl["bbox_size"][i])
    best_i = 0
    best_score = -1.0
    for i, isl in enumerate(islands):
        ratios = []
        for a, b in zip(isl["bbox_size"], gsize):
            if b <= 1e-9:
                continue
            ratios.append(min(a / b, 1.0))
        wrap = (sum(ratios) / len(ratios)) if ratios else 0.0
        score = wrap * 0.5 + (isl["area"] / max(islands[0]["area"], 1e-9)) * 0.5
        # Prefer larger area as primary sort already; recompute vs max area
        max_area = max(x["area"] for x in islands)
        score = wrap * 0.5 + (isl["area"] / max(max_area, 1e-9)) * 0.5
        if score > best_score:
            best_score = score
            best_i = i

    keep = islands[best_i]
    keep_verts = set(v.index for v in keep["verts"])
    # Delete other verts
    to_delete = [v for v in bm.verts if v.index not in keep_verts]
    bmesh.ops.delete(bm, geom=to_delete, context="VERTS")
    bmesh.update_edit_mesh(obj.data)
    bpy.ops.object.mode_set(mode="OBJECT")

    return {
        "island_count_total": len(islands),
        "kept_faces": keep["n_faces"],
        "kept_verts": keep["n_verts"],
        "kept_area": round(keep["area"], 4),
        "kept_bbox_size_mm": [round(s, 4) for s in keep["bbox_size"]],
        "external_score": round(best_score, 4),
        "deleted_islands": len(islands) - 1,
    }


def _clean_mesh(obj) -> dict:
    import bmesh
    import bpy

    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bm = bmesh.from_edit_mesh(obj.data)
    # remove doubles (0.01 mm in native mm units)
    dist = REMOVE_DOUBLES_MM
    merged = bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=dist)
    # fill small holes
    bmesh.ops.holes_fill(bm, edges=list(bm.edges), sides=FILL_HOLE_MAX_SIDES)
    # normals out
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.edges.ensure_lookup_table()
    non_manifold = sum(1 for e in bm.edges if not e.is_manifold)
    bmesh.update_edit_mesh(obj.data)
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.data.calc_loop_triangles()
    return {
        "remove_doubles_dist_mm": dist,
        "non_manifold_edges_after": non_manifold,
        "triangles_after_clean": len(obj.data.loop_triangles),
        "vertices_after_clean": len(obj.data.vertices),
    }


def _apply_matrix(obj, M) -> None:
    import bpy

    obj.matrix_world = M @ obj.matrix_world
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    # Normales hacia afuera tras la transform (Rx puede invertir winding)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")


def _kabsch_translation_scale(
    src_pts: list[tuple[float, float, float]],
    dst_pts: list[tuple[float, float, float]],
    anisotropic: bool = False,
) -> tuple:
    """Escala (uni o aniso) + Rx−90° fija + traslación LS.

    BP3D OBJ en Blender: altura en −Y (mm). GLB importado: altura en +Z (m).
    Rx−90° mapea (x,y,z)_bp → (x,z,−y) hacia el espacio Blender del esqueleto.
    """
    from mathutils import Matrix, Vector

    R = Matrix.Rotation(math.radians(-90.0), 4, "X")
    src_r = [R @ Vector(p) for p in src_pts]
    dst_v = [Vector(p) for p in dst_pts]
    n = len(src_r)

    mean_r = sum(src_r, Vector((0, 0, 0))) / n
    mean_d = sum(dst_v, Vector((0, 0, 0))) / n
    src_c = [s - mean_r for s in src_r]
    dst_c = [d - mean_d for d in dst_v]

    if anisotropic:
        def axis_scale(i: int) -> float:
            num = sum(src_c[k][i] * dst_c[k][i] for k in range(n))
            den = sum(src_c[k][i] ** 2 for k in range(n))
            if den < 1e-9:
                return 0.001
            s = num / den
            if not (0.0003 < s < 0.003):
                _log(f"aviso escala aniso eje {i}={s:.6f}; usa 0.001")
                return 0.001
            return float(s)

        sx, sy, sz = axis_scale(0), axis_scale(1), axis_scale(2)
        S = Matrix.Diagonal((sx, sy, sz, 1.0))
        scale_info = {"mode": "anisotropic", "sx": sx, "sy": sy, "sz": sz}
    else:
        num = sum(src_c[k].dot(dst_c[k]) for k in range(n))
        den = sum(src_c[k].length_squared for k in range(n))
        measured = float(num / den) if den > 1e-9 else 0.001
        if 0.0005 < measured < 0.002:
            s = 0.001
            note = "canonical mm→m (0.001)"
        else:
            s = measured
            note = f"LS ratio {measured:.6f}"
        S = Matrix.Scale(s, 4)
        scale_info = {"mode": "uniform", "s": s, "measured": measured, "note": note}

    src_sr = [S @ v for v in src_r]
    mean_sr = sum(src_sr, Vector((0, 0, 0))) / n
    T = Matrix.Translation(mean_d - mean_sr)
    M = T @ S @ R

    residuals_mm = []
    for p_src, p_dst in zip(src_pts, dst_pts):
        mapped = M @ Vector(p_src)
        err = (mapped - Vector(p_dst)).length * 1000.0
        residuals_mm.append(float(err))

    return M, scale_info, residuals_mm


def _sample_muscle_verts_in_scene(
    muscles_glb: Path, n: int, seed: int
) -> tuple[list[tuple[float, float, float]], list]:
    """Importa muscles en la escena actual; no borra objetos previos.

    Returns (puntos, objetos_musculo_a_borrar).
    """
    objs = _import_glb(muscles_glb)
    meshes = [o for o in objs if o.type == "MESH"]
    rng = random.Random(seed)
    reservoir: list[tuple[float, float, float]] = []
    seen = 0
    for obj in meshes:
        mw = obj.matrix_world
        for v in obj.data.vertices:
            seen += 1
            co = mw @ v.co
            pt = (float(co.x), float(co.y), float(co.z))
            if len(reservoir) < n:
                reservoir.append(pt)
            else:
                j = rng.randint(0, seen - 1)
                if j < n:
                    reservoir[j] = pt
    return reservoir, objs


def _count_outside(skin_obj, points: list[tuple[float, float, float]]) -> dict:
    """Punto fuera si el vector al hit más cercano apunta en el sentido de la normal."""
    import bpy
    import bmesh
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree

    deps = bpy.context.evaluated_depsgraph_get()
    eval_obj = skin_obj.evaluated_get(deps)
    mesh = eval_obj.to_mesh()
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.transform(eval_obj.matrix_world)
    bm.normal_update()
    bvh = BVHTree.FromBMesh(bm, epsilon=1e-5)

    outside = 0
    zone_hits: dict[str, int] = {}
    for pt in points:
        origin = Vector(pt)
        hit = bvh.find_nearest(origin)
        if hit[0] is None:
            outside += 1
            zone = "unknown"
        else:
            loc, normal, _idx, _dist = hit
            # Normal hacia afuera: (p - surface) · n > 0 → fuera
            if (origin - loc).dot(normal) > 0:
                outside += 1
                # En Blender post-import GLB, altura = Z
                z = pt[2]
                if z > 1.2:
                    zone = "head_torso"
                elif z < 0.5:
                    zone = "legs"
                else:
                    zone = "trunk"
            else:
                zone = None
        if zone:
            zone_hits[zone] = zone_hits.get(zone, 0) + 1

    eval_obj.to_mesh_clear()
    bm.free()
    total = len(points) or 1
    pct = 100.0 * outside / total
    return {
        "sampled": total,
        "outside": outside,
        "outside_pct": round(pct, 3),
        "zones_outside": zone_hits,
        "method": "bvh_nearest_normal",
    }


def _decimate(obj, target_tris: int) -> dict:
    import bpy

    obj.data.calc_loop_triangles()
    before = len(obj.data.loop_triangles)
    if before <= target_tris:
        return {"before": before, "after": before, "ratio": 1.0, "skipped": True}
    ratio = max(0.01, min(1.0, target_tris / before))
    mod = obj.modifiers.new(name="DecimateSkin", type="DECIMATE")
    mod.decimate_type = "COLLAPSE"
    mod.ratio = ratio
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.modifier_apply(modifier=mod.name)
    obj.data.calc_loop_triangles()
    after = len(obj.data.loop_triangles)
    # If still over, second pass
    if after > target_tris * 1.05:
        ratio2 = max(0.01, target_tris / after)
        mod2 = obj.modifiers.new(name="DecimateSkin2", type="DECIMATE")
        mod2.decimate_type = "COLLAPSE"
        mod2.ratio = ratio2
        bpy.ops.object.modifier_apply(modifier=mod2.name)
        obj.data.calc_loop_triangles()
        after = len(obj.data.loop_triangles)
    return {"before": before, "after": after, "ratio": ratio, "skipped": False}


def run(args: argparse.Namespace) -> int:
    elements = _load_element_parts(ELEMENT_PARTS)
    skin_path = Path(args.skin_obj)
    if not skin_path.exists():
        p = _ensure_obj("FMA7163", elements)
        if p is None:
            raise SystemExit(f"No está la piel: {skin_path}")
        skin_path = p

    _log(f"Importando piel {skin_path}…")
    _clear_scene()
    skins = _import_obj(skin_path)
    if not skins:
        raise SystemExit("Import piel = 0 mallas")
    skin = skins[0]
    if len(skins) > 1:
        import bpy

        bpy.context.view_layer.objects.active = skin
        for o in skins:
            o.select_set(True)
        bpy.ops.object.join()
        skin = bpy.context.view_layer.objects.active

    island_info = _separate_external_island(skin)
    _log(f"Isla externa: {json.dumps(island_info)}")
    clean_info = _clean_mesh(skin)
    _log(f"Limpieza: {json.dumps(clean_info)}")

    bone_pairs = []
    for target in BONE_TARGETS:
        bp_path = _ensure_obj(target["fma"], elements)
        if bp_path is None:
            _log(f"  skip {target['role']}: sin OBJ {target['fma']}")
            continue
        bone_pairs.append({**target, "bp_path": bp_path})
    if len(bone_pairs) < 6:
        raise SystemExit(f"Solo {len(bone_pairs)} huesos BP3D; ≥6 requeridos")

    za_objs = _import_glb(Path(args.skeleton_glb))
    src_pts: list[tuple[float, float, float]] = []
    dst_pts: list[tuple[float, float, float]] = []
    pair_rows: list[dict] = []
    import bpy

    for row in bone_pairs:
        bp_objs = _import_obj(row["bp_path"])
        if not bp_objs:
            continue
        bp = bp_objs[0]
        za = _find_za_mesh(za_objs, row["za_hints"])
        if za is None:
            _log(f"  skip {row['role']}: ZA no encontrada")
            bpy.data.objects.remove(bp, do_unlink=True)
            continue
        c_bp = _bbox_center_world(bp)
        c_za = _bbox_center_world(za)
        src_pts.append(c_bp)
        dst_pts.append(c_za)
        pair_rows.append(
            {
                "role": row["role"],
                "fma": row["fma"],
                "bp_obj": bp.name,
                "za_obj": za.name,
                "bp_center_mm": [round(x, 4) for x in c_bp],
                "za_center_m": [round(x, 6) for x in c_za],
            }
        )
        bpy.data.objects.remove(bp, do_unlink=True)

    if len(src_pts) < 6:
        raise SystemExit(f"Solo {len(src_pts)} pares; ≥6 requeridos")

    M, scale_info, residuals = _kabsch_translation_scale(src_pts, dst_pts, False)
    median_mm = float(statistics.median(residuals))
    alignment_mode = "uniform"
    _log(f"Uniforme mediana={median_mm:.3f} mm scale={scale_info}")
    for row, r in zip(pair_rows, residuals):
        row["residuo_mm"] = round(r, 3)
        _log(f"  {row['role']}: {row['residuo_mm']} mm → {row['za_obj']}")

    if median_mm > MEDIAN_OK_MM:
        M2, scale_info2, residuals2 = _kabsch_translation_scale(src_pts, dst_pts, True)
        median2 = float(statistics.median(residuals2))
        _log(f"Aniso mediana={median2:.3f} mm scale={scale_info2}")
        if median2 < median_mm:
            M, scale_info, residuals, median_mm = M2, scale_info2, residuals2, median2
            alignment_mode = "anisotropic"
            for row, r in zip(pair_rows, residuals):
                row["residuo_mm"] = round(r, 3)

    meta_base = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": {
            "fma": "FMA7163",
            "element": "FJ2810",
            "license": "CC BY-SA 2.1 JP",
            "dataset": "BodyParts3D 4.0 (DBCLS)",
        },
        "island": island_info,
        "clean": clean_info,
        "alignment_mode": alignment_mode,
        "scale": scale_info,
        "pairs": pair_rows,
        "median_residuo_mm": round(median_mm, 3),
        "mean_residuo_mm": round(float(statistics.mean(residuals)), 3),
    }

    if median_mm > MEDIAN_STOP_MM:
        meta_base["ok"] = False
        meta_base["abort_reason"] = (
            f"mediana residuo {median_mm:.3f} mm > {MEDIAN_STOP_MM} mm"
        )
        Path(args.meta).parent.mkdir(parents=True, exist_ok=True)
        Path(args.meta).write_text(
            json.dumps(meta_base, ensure_ascii=False, indent=2) + "\n"
        )
        _log(f"ABORT alineación: {meta_base['abort_reason']}")
        return 2

    # Isolate skin and apply transform
    for o in list(bpy.data.objects):
        if o != skin:
            bpy.data.objects.remove(o, do_unlink=True)
    _apply_matrix(skin, M)
    skin.name = "Skin"
    if skin.data:
        skin.data.name = "Skin"

    _log(f"Muestreando {MUSCLE_SAMPLE} vértices musculares (misma escena)…")
    muscle_pts, muscle_objs = _sample_muscle_verts_in_scene(
        Path(args.muscles_glb), MUSCLE_SAMPLE, args.seed
    )
    _log(f"  muestra={len(muscle_pts)}")
    envelope = _count_outside(skin, muscle_pts)
    _log(f"Envoltura: {json.dumps(envelope)}")
    meta_base["envelope"] = envelope
    for o in muscle_objs:
        try:
            bpy.data.objects.remove(o, do_unlink=True)
        except ReferenceError:
            pass

    if envelope["outside_pct"] > OUTSIDE_STOP_PCT:
        meta_base["ok"] = False
        meta_base["abort_reason"] = (
            f"fuera {envelope['outside_pct']}% > {OUTSIDE_STOP_PCT}%"
        )
        Path(args.meta).write_text(
            json.dumps(meta_base, ensure_ascii=False, indent=2) + "\n"
        )
        _log(f"ABORT envoltura: {meta_base['abort_reason']}")
        return 3

    # Decimate
    dec = _decimate(skin, TARGET_TRIS)
    _log(f"Decimate: {json.dumps(dec)}")
    meta_base["decimate"] = dec
    skin.name = "Skin"
    if skin.data:
        skin.data.name = "Skin"

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    skin.select_set(True)
    bpy.context.view_layer.objects.active = skin
    # Y-up como el resto de sistemas Z-Anatomy (export convierte Z-up Blender → Y-up glTF)
    bpy.ops.export_scene.gltf(
        filepath=str(out),
        export_format="GLB",
        use_selection=True,
        export_apply=True,
        export_yup=True,
        export_normals=True,
        export_materials="EXPORT",
    )
    skin.data.calc_loop_triangles()
    meta_base["ok"] = True
    meta_base["out"] = str(out)
    meta_base["triangles"] = len(skin.data.loop_triangles)
    meta_base["bytes"] = out.stat().st_size if out.exists() else None
    meta_base["warnings"] = []
    if envelope["outside_pct"] > OUTSIDE_OK_PCT:
        meta_base["warnings"].append(
            f"fuera {envelope['outside_pct']}% > objetivo {OUTSIDE_OK_PCT}% (≤ stop)"
        )
    if median_mm > MEDIAN_OK_MM:
        meta_base["warnings"].append(
            f"mediana {median_mm:.3f} mm > objetivo {MEDIAN_OK_MM} mm (≤ stop)"
        )

    Path(args.meta).write_text(
        json.dumps(meta_base, ensure_ascii=False, indent=2) + "\n"
    )
    _log(f"OK → {out} tris={meta_base['triangles']} bytes={meta_base['bytes']}")
    return 0


if __name__ == "__main__":
    args = _parse_args(_argv_after_double_dash(sys.argv))
    raise SystemExit(run(args))
