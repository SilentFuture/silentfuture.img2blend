# img2blend review renderer. Renders a built prop .blend with a
# FIXED, deterministic camera set under a fixed neutral studio light, then
# composites ONE comparison sheet as a two-row grid:
#
#     top row     reference for that view (neutral grey where uncovered)
#     bottom row  the render
#     columns     front | side | three-quarter [| back] [| detail ...]
#
# References are tagged with a view, so each render column is judged against
# ITS OWN reference. The back camera only exists when a back reference does -
# an uncovered back face is inference territory and gets no fake evidence
# column. Detail references appear as extra reference-only columns (grey
# below): they inform material/surface judgment, they match no fixed camera.
#
# The agent's vision judges the sheet; this script never scores anything
# (img2threejs's rule: scripts enforce, the model judges). Runs inside
# Blender, invoked through tools/build.py:
#
#   build.py review --blend out/valve.blend --reference front=ref.jpg \
#       [--reference side=... --reference detail=...] \
#       --out-dir out/review --pass-id blockout --attempt 1
#
# Camera set (azimuth measured from -Y, the "front"; elevation from
# horizontal): front 0/10, side 90/10, three-quarter 40/22, back 180/10.
# Framing derives only from the prop's world bounds, so two renders of the
# same build are identical and renders across passes stay comparable.

import argparse
import math
import os
import sys

import bpy
from mathutils import Vector

CAMERAS = {
    "front": (0.0, 10.0),
    "side": (90.0, 10.0),
    "three-quarter": (40.0, 22.0),
    "back": (180.0, 10.0),
}
BASE_VIEWS = ["front", "side", "three-quarter"]
REF_VIEWS = ["front", "side", "back", "three-quarter", "detail"]
RES = 900
SAMPLES = 48
SHEET_H = 512
GUTTER = 8
PLACEHOLDER = (0.13, 0.13, 0.14, 1.0)


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--blend", required=True)
    parser.add_argument("--reference", action="append", default=[], metavar="VIEW=PATH")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--pass-id", required=True)
    parser.add_argument("--attempt", type=int, required=True)
    return parser.parse_args(argv)


def parse_references(specs):
    refs = []
    for spec in specs:
        view, sep, path = spec.partition("=")
        if not sep or view not in REF_VIEWS:
            print(f"render_review: FAILED - reference {spec!r} must be view=path, view in {REF_VIEWS}")
            raise SystemExit(1)
        if not os.path.exists(path):
            print(f"render_review: FAILED - reference {path} does not exist")
            raise SystemExit(1)
        refs.append((view, path))
    if not refs:
        print("render_review: FAILED - at least one --reference view=path is required")
        raise SystemExit(1)
    return refs


def scene_bounds():
    pts = []
    for o in bpy.context.scene.objects:
        if o.type == "MESH" and o.visible_get():
            pts.extend(o.matrix_world @ Vector(c) for c in o.bound_box)
    if not pts:
        print("render_review: FAILED - the blend contains no visible mesh")
        raise SystemExit(1)
    mn = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    mx = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return mn, mx


def light(name, loc, target, energy, size, color):
    data = bpy.data.lights.new(name, "AREA")
    data.energy = energy
    data.size = size
    data.color = color
    obj = bpy.data.objects.new(name, data)
    obj.location = loc
    direction = (Vector(target) - Vector(loc)).normalized()
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    bpy.context.collection.objects.link(obj)


def setup_stage(mn, mx):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = SAMPLES
    scene.cycles.use_denoising = True
    scene.cycles.seed = 0
    scene.render.resolution_x = RES
    scene.render.resolution_y = RES
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"

    ctr = (mn + mx) / 2.0
    size = max(mx - mn)

    world = bpy.data.worlds.new("review")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.045, 0.046, 0.050, 1)
    bg.inputs["Strength"].default_value = 1.0

    bpy.ops.mesh.primitive_plane_add(size=size * 30, location=(ctr.x, ctr.y, mn.z - 0.0006))
    floor = bpy.context.active_object
    mat = bpy.data.materials.new("review_floor")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.09, 0.09, 0.092, 1)
    bsdf.inputs["Roughness"].default_value = 0.8
    floor.data.materials.append(mat)

    key_h = ctr.z + size * 1.5
    light("key", (ctr.x - size * 0.9, ctr.y - size * 1.2, key_h), ctr, size * size * 240, size * 1.1, (1.0, 0.94, 0.86))
    light("fill", (ctr.x + size * 1.6, ctr.y - size * 0.7, ctr.z + size * 0.4), ctr, size * size * 60, size * 1.6, (0.85, 0.89, 1.0))
    light("rim", (ctr.x + size * 0.5, ctr.y + size * 1.7, ctr.z + size * 1.1), ctr, size * size * 100, size * 0.9, (1.0, 0.97, 0.92))

    camera_data = bpy.data.cameras.new("review_cam")
    camera_data.lens = 60
    camera = bpy.data.objects.new("review_cam", camera_data)
    bpy.context.collection.objects.link(camera)
    scene.camera = camera
    return camera, ctr, size


def aim(camera, ctr, mn, mx, size, azimuth_deg, elevation_deg):
    az = math.radians(azimuth_deg - 90.0)  # -Y is the front
    el = math.radians(elevation_deg)
    target = Vector((ctr.x, ctr.y, mn.z + (mx.z - mn.z) * 0.5))
    camera.location = target + Vector(
        (math.cos(az) * math.cos(el), math.sin(az) * math.cos(el), math.sin(el))
    ) * (size * 2.6)
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()


def load_pixels(path):
    import numpy as np

    img = bpy.data.images.load(path)
    w, h = img.size
    buf = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    bpy.data.images.remove(img)
    return buf.reshape(h, w, 4)


def scale_to_height(pix, target_h):
    import numpy as np

    h, w, _ = pix.shape
    target_w = max(1, round(w * target_h / h))
    ys = (np.arange(target_h) * h / target_h).astype(int).clip(0, h - 1)
    xs = (np.arange(target_w) * w / target_w).astype(int).clip(0, w - 1)
    return pix[ys][:, xs]


def pad_to_width(cell, width):
    import numpy as np

    h, w, _ = cell.shape
    if w >= width:
        return cell
    left = (width - w) // 2
    right = width - w - left
    filler = np.array(PLACEHOLDER, dtype=np.float32)
    pad_l = np.broadcast_to(filler, (h, left, 4)).copy()
    pad_r = np.broadcast_to(filler, (h, right, 4)).copy()
    return np.concatenate([pad_l, cell, pad_r], axis=1)


def composite_sheet(columns, out_path):
    """columns: list of (reference pixels or None, render pixels or None).
    Everything is scaled to a common height; a missing cell becomes a neutral
    grey placeholder so column positions stay meaningful."""
    import numpy as np

    filler = np.array(PLACEHOLDER, dtype=np.float32)
    scaled = []
    for ref, render in columns:
        ref_cell = scale_to_height(ref, SHEET_H) if ref is not None else None
        render_cell = scale_to_height(render, SHEET_H) if render is not None else None
        width = max(c.shape[1] for c in (ref_cell, render_cell) if c is not None)
        if ref_cell is None:
            ref_cell = np.broadcast_to(filler, (SHEET_H, width, 4)).copy()
        if render_cell is None:
            render_cell = np.broadcast_to(filler, (SHEET_H, width, 4)).copy()
        scaled.append((pad_to_width(ref_cell, width), pad_to_width(render_cell, width)))

    gutter_v = np.ones((SHEET_H, GUTTER, 4), dtype=np.float32)

    def build_row(cells):
        row = []
        for i, cell in enumerate(cells):
            if i:
                row.append(gutter_v)
            row.append(cell)
        return np.concatenate(row, axis=1)

    top = build_row([ref for ref, _ in scaled])
    bottom = build_row([render for _, render in scaled])
    gutter_h = np.ones((GUTTER, top.shape[1], 4), dtype=np.float32)
    # Image rows run bottom-up in Blender buffers, so "top row on top" means
    # concatenating reference row LAST.
    sheet = np.concatenate([bottom, gutter_h, top], axis=0)
    h, w, _ = sheet.shape
    out = bpy.data.images.new("sheet", w, h, alpha=True)
    out.pixels.foreach_set(sheet.ravel())
    out.filepath_raw = out_path
    out.file_format = "PNG"
    out.save()
    bpy.data.images.remove(out)


def main():
    args = parse_args()
    references = parse_references(args.reference)
    if not os.path.exists(args.blend):
        print(f"render_review: FAILED - {args.blend} does not exist")
        raise SystemExit(1)
    os.makedirs(args.out_dir, exist_ok=True)

    ref_by_view = {}
    details = []
    for view, path in references:
        if view == "detail":
            details.append(path)
        elif view in ref_by_view:
            print(f"render_review: FAILED - two references tagged {view!r}; tag one 'detail'")
            raise SystemExit(1)
        else:
            ref_by_view[view] = path

    views = list(BASE_VIEWS)
    if "back" in ref_by_view:
        views.append("back")

    bpy.ops.wm.open_mainfile(filepath=args.blend)
    mn, mx = scene_bounds()
    camera, ctr, size = setup_stage(mn, mx)

    stem = f"{args.pass_id}-a{args.attempt}"
    render_paths = {}
    scene = bpy.context.scene
    for name in views:
        azimuth, elevation = CAMERAS[name]
        aim(camera, ctr, mn, mx, size, azimuth, elevation)
        path = os.path.join(args.out_dir, f"{stem}-{name}.png")
        scene.render.filepath = path
        scene.render.image_settings.file_format = "PNG"
        bpy.ops.render.render(write_still=True)
        render_paths[name] = path
        print(f"render_review: {name} -> {path}")

    columns = []
    for name in views:
        ref = ref_by_view.get(name)
        columns.append((load_pixels(ref) if ref else None, load_pixels(render_paths[name])))
    for path in details:
        columns.append((load_pixels(path), None))

    sheet = os.path.join(args.out_dir, f"{stem}-sheet.png")
    composite_sheet(columns, sheet)
    covered = sorted(ref_by_view)
    print(
        f"render_review: sheet -> {sheet} (columns {views + ['detail'] * len(details)}, "
        f"reference-covered views {covered}, top row = reference, bottom row = render)"
    )


main()
