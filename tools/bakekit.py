# img2blend bakekit - the shared machinery every emitted build
# script imports. The script owns geometry and material AUTHORING; this module
# owns everything that must not vary between props: the seeded scene, the
# asset-contract enforcement, the bake to glTF-compatible textures, the guarded
# export and the build report.
#
# Runs INSIDE Blender (bpy). Invoked via tools/build.py, which puts
# this directory on sys.path and forces --factory-startup.
#
# Methodology adapted from img2threejs
# (https://github.com/img2threejs/img2threejs, Apache License 2.0) - staged
# generation with review gates; no source code copied. The export guards and
# the build-report habit generalize SilentFuture's earlier asset converters
# (lever-to-glb.py, gramophone-to-glb.py, build-gramophone.py): the five
# guarded export failure modes are theirs, verbatim in spirit.

import hashlib
import json
import math
import os

import bpy
from mathutils import Vector

# Set by reset_scene; consumed by the material helpers so every stochastic
# node input derives from the one declared SEED, in call order.
_SEED = 0
_NOISE_CALLS = 0

# material name -> (color socket, roughness socket, metallic socket), filled
# by finish() and consumed by the bake pass.
CHAN = {}


def fail(message):
    print(f"bakekit: FAILED - {message}")
    raise SystemExit(1)


# --------------------------------------------------------------------- scene


def reset_scene(seed):
    """Empty deterministic scene: metric, metres, CPU Cycles for the bake."""
    global _SEED, _NOISE_CALLS
    _SEED = int(seed)
    _NOISE_CALLS = 0
    CHAN.clear()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    return scene


def _seed_value(key):
    """Stable float in [0, 100) from the seed and a call key."""
    digest = hashlib.sha256(f"{_SEED}:{key}".encode()).digest()
    return int.from_bytes(digest[:4], "big") / 2**32 * 100.0


# ------------------------------------------------------------------ geometry


def new_obj(name, verts, faces, mat=None):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], faces)
    me.validate()
    me.update()
    ob = bpy.data.objects.new(name, me)
    if mat is not None:
        ob.data.materials.append(mat)
    bpy.context.collection.objects.link(ob)
    return ob


def revolve(profile, seg=64, axis="Z", close_start=False, close_end=False):
    """profile: list of (radius, height) revolved about the given axis."""
    verts, faces = [], []
    n = len(profile)
    for i in range(seg):
        a = 2.0 * math.pi * i / seg
        ca, sa = math.cos(a), math.sin(a)
        for r, h in profile:
            if axis == "Z":
                verts.append(Vector((r * ca, r * sa, h)))
            else:  # "Y"
                verts.append(Vector((r * ca, h, r * sa)))
    for i in range(seg):
        j = (i + 1) % seg
        for k in range(n - 1):
            faces.append((i * n + k, j * n + k, j * n + k + 1, i * n + k + 1))
    if close_start:
        c = len(verts)
        verts.append(Vector((0, 0, profile[0][1])) if axis == "Z" else Vector((0, profile[0][1], 0)))
        for i in range(seg):
            faces.append((i * n, c, ((i + 1) % seg) * n))
    if close_end:
        c = len(verts)
        verts.append(
            Vector((0, 0, profile[-1][1])) if axis == "Z" else Vector((0, profile[-1][1], 0))
        )
        for i in range(seg):
            faces.append((((i + 1) % seg) * n + n - 1, c, i * n + n - 1))
    return verts, faces


def tube(points, radii, seg=16, cap_start=True, cap_end=True):
    """Swept tube with parallel-transport frames so it never twists."""
    n = len(points)
    tangents = []
    for i in range(n):
        if i == 0:
            t = points[1] - points[0]
        elif i == n - 1:
            t = points[-1] - points[-2]
        else:
            t = points[i + 1] - points[i - 1]
        tangents.append(t.normalized())
    up = Vector((0, 0, 1))
    if abs(tangents[0].dot(up)) > 0.9:
        up = Vector((1, 0, 0))
    normal = (up - tangents[0] * up.dot(tangents[0])).normalized()
    verts, faces = [], []
    for i in range(n):
        if i > 0:
            normal = normal - tangents[i] * normal.dot(tangents[i])
            if normal.length < 1e-6:
                a = Vector((0, 0, 1))
                if abs(tangents[i].dot(a)) > 0.9:
                    a = Vector((1, 0, 0))
                normal = a - tangents[i] * a.dot(tangents[i])
            normal.normalize()
        binorm = tangents[i].cross(normal).normalized()
        for k in range(seg):
            a = 2.0 * math.pi * k / seg
            verts.append(points[i] + (normal * math.cos(a) + binorm * math.sin(a)) * radii[i])
    for i in range(n - 1):
        for k in range(seg):
            k2 = (k + 1) % seg
            faces.append((i * seg + k, i * seg + k2, (i + 1) * seg + k2, (i + 1) * seg + k))
    if cap_start:
        c = len(verts)
        verts.append(points[0])
        for k in range(seg):
            faces.append((k, c, (k + 1) % seg))
    if cap_end:
        c = len(verts)
        verts.append(points[-1])
        o = (n - 1) * seg
        for k in range(seg):
            faces.append((o + (k + 1) % seg, c, o + k))
    return verts, faces


def box(cx, cy, z0, z1, sx, sy):
    hx, hy = sx / 2.0, sy / 2.0
    v = [
        Vector((cx - hx, cy - hy, z0)),
        Vector((cx + hx, cy - hy, z0)),
        Vector((cx + hx, cy + hy, z0)),
        Vector((cx - hx, cy + hy, z0)),
        Vector((cx - hx, cy - hy, z1)),
        Vector((cx + hx, cy - hy, z1)),
        Vector((cx + hx, cy + hy, z1)),
        Vector((cx - hx, cy + hy, z1)),
    ]
    f = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    return v, f


def cyl(cx, cy, z0, z1, r, seg=48, taper=None):
    r1 = r if taper is None else taper
    v, f = revolve([(r, z0), (r1, z1)], seg=seg, close_start=True, close_end=True)
    off = Vector((cx, cy, 0))
    return [p + off for p in v], f


def join(objects, name):
    """Join static parts into one named object (contract rule 1)."""
    bpy.ops.object.select_all(action="DESELECT")
    for ob in objects:
        ob.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.convert(target="MESH")
    bpy.ops.object.join()
    joined = bpy.context.view_layer.objects.active
    joined.name = name
    return joined


def shade_smooth(obj, angle_deg=35):
    for p in obj.data.polygons:
        p.use_smooth = True
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    try:
        bpy.ops.object.shade_auto_smooth(angle=math.radians(angle_deg))
    except Exception:
        bpy.ops.object.shade_smooth()


def settle_on_origin(objects):
    """Shift the whole prop so its footprint centre is (0,0) and min z is 0.

    Relative placement between parts survives; only locations move, so a part
    whose origin is its hinge keeps the hinge as origin.
    """
    bpy.context.view_layer.update()
    pts = []
    for o in objects:
        pts.extend(o.matrix_world @ Vector(c) for c in o.bound_box)
    mn = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    mx = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    shift = Vector((-(mn.x + mx.x) / 2.0, -(mn.y + mx.y) / 2.0, -mn.z))
    for o in objects:
        o.location += shift
    bpy.context.view_layer.update()


def socket(name, location):
    """Attachment point: a named empty, exported with the prop."""
    if not name.startswith("socket_"):
        fail(f"socket name {name!r} must start with 'socket_'")
    empty = bpy.data.objects.new(name, None)
    empty.empty_display_size = 0.02
    empty.location = Vector(location)
    bpy.context.collection.objects.link(empty)
    return empty


# ----------------------------------------------------------------- materials


def base_material(name):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    texco = nt.nodes.new("ShaderNodeTexCoord")
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    return mat, nt, bsdf, out, texco, geo


def finish(mat, nt, bsdf, col_sock, rough_sock, metal_sock):
    """Wire the three channels and register them for the bake pass."""
    nt.links.new(col_sock, bsdf.inputs["Base Color"])
    nt.links.new(rough_sock, bsdf.inputs["Roughness"])
    nt.links.new(metal_sock, bsdf.inputs["Metallic"])
    CHAN[mat.name] = (col_sock, rough_sock, metal_sock)
    return mat


def val(nt, v):
    n = nt.nodes.new("ShaderNodeValue")
    n.outputs[0].default_value = v
    return n.outputs[0]


def rgb(nt, r, g, b):
    n = nt.nodes.new("ShaderNodeRGB")
    n.outputs[0].default_value = (r, g, b, 1.0)
    return n.outputs[0]


def ramp(nt, sock, stops):
    n = nt.nodes.new("ShaderNodeValToRGB")
    nt.links.new(sock, n.inputs["Fac"])
    el = n.color_ramp.elements
    while len(el) > 1:
        el.remove(el[-1])
    el[0].position, el[0].color = stops[0][0], stops[0][1]
    for pos, colr in stops[1:]:
        e = el.new(pos)
        e.color = colr
    return n.outputs["Color"]


def noise(nt, coord, scale, detail=6.0, rough=0.5):
    """4D noise whose W derives from the declared SEED, in call order - the
    one place stochastic variation enters, so two runs are identical and a
    different seed moves every wear patch at once."""
    global _NOISE_CALLS
    _NOISE_CALLS += 1
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.noise_dimensions = "4D"
    n.inputs["Scale"].default_value = scale
    n.inputs["Detail"].default_value = detail
    n.inputs["Roughness"].default_value = rough
    n.inputs["W"].default_value = _seed_value(f"noise:{_NOISE_CALLS}")
    nt.links.new(coord, n.inputs["Vector"])
    return n.outputs["Fac"]


def mixrgb(nt, fac, a, b):
    n = nt.nodes.new("ShaderNodeMix")
    n.data_type = "RGBA"
    n.blend_type = "MIX"
    if isinstance(fac, (int, float)):
        n.inputs["Factor"].default_value = fac
    else:
        nt.links.new(fac, n.inputs["Factor"])
    nt.links.new(a, n.inputs[6])
    nt.links.new(b, n.inputs[7])
    return n.outputs[2]


def mapf(nt, sock, lo, hi):
    n = nt.nodes.new("ShaderNodeMapRange")
    nt.links.new(sock, n.inputs["Value"])
    n.inputs["To Min"].default_value = lo
    n.inputs["To Max"].default_value = hi
    return n.outputs["Result"]


def pointiness(nt, geo, lo, hi):
    """Convex edges -> hi, everything else -> lo. The lower ramp stop sits at
    0.5 deliberately: Pointiness reads exactly 0.5 on a flat face, so a ramp
    opening below that would wear every surface at once. Only genuinely convex
    geometry should wear."""
    return mapf(
        nt,
        ramp(nt, geo.outputs["Pointiness"], [(0.50, (0, 0, 0, 1)), (0.66, (1, 1, 1, 1))]),
        lo,
        hi,
    )


# ---------------------------------------------------- contract + bake + export


def _measure(objects, spec):
    """Resolve a stated-dimension measure like 'extent_xy_max:valve_handwheel'."""
    kind, _, obj_name = spec.partition(":")
    targets = [o for o in objects if not obj_name or o.name == obj_name]
    if not targets:
        fail(f"dimension measure {spec!r} names no built object")
    pts = []
    for o in targets:
        pts.extend(o.matrix_world @ Vector(c) for c in o.bound_box)
    ext = {
        "extent_x": max(p.x for p in pts) - min(p.x for p in pts),
        "extent_y": max(p.y for p in pts) - min(p.y for p in pts),
        "extent_z": max(p.z for p in pts) - min(p.z for p in pts),
    }
    ext["extent_xy_max"] = max(ext["extent_x"], ext["extent_y"])
    if kind not in ext:
        fail(f"unknown dimension measure kind {kind!r}")
    return ext[kind]


def _enforce_contract(contract, objects, empties):
    """The asset contract, asserted rather than assumed. Returns report facts."""
    by_name = {o.name: o for o in objects}
    declared = [entry["name"] for entry in contract["objects"]]
    if sorted(by_name) != sorted(declared):
        fail(f"built objects {sorted(by_name)} do not match contract objects {sorted(declared)}")

    slot_names = []
    facts = []
    for entry in contract["objects"]:
        obj = by_name[entry["name"]]
        # Guard 1: parent scale. Rest pose is baked here too: rotation and
        # scale are applied, location (the assembled mount position) survives.
        if obj.parent is not None:
            fail(f"{obj.name} has a parent ({obj.parent.name}) - its scale would ride along")
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        if any(abs(s - 1.0) > 1e-5 for s in obj.scale):
            fail(f"{obj.name} still carries scale {tuple(obj.scale)} after applying transforms")

        slots = [s.material.name if s.material else None for s in obj.material_slots]
        if slots != entry["slots"]:
            fail(
                f"{obj.name} exports material slots {slots}, contract says {entry['slots']} - "
                "slot order is the contract consumers index-align against - a re-order paints the wrong part"
            )
        for s in slots:
            if s in slot_names:
                fail(f"material slot {s!r} appears on two objects - slot names must be unique")
            slot_names.append(s)

        mesh = obj.data
        local = [Vector(c) for c in obj.bound_box]
        facts.append(
            {
                "object": obj.name,
                "origin": entry.get("origin", "assembled"),
                "axis": entry.get("axis"),
                "rest": entry.get("rest"),
                "location": [round(v, 4) for v in obj.location],
                "triangles": sum(max(len(p.vertices) - 2, 0) for p in mesh.polygons),
                "vertices": len(mesh.vertices),
                "material_slots": slots,
                "local_bounds_min": [round(min(c[i] for c in local), 4) for i in range(3)],
                "local_bounds_max": [round(max(c[i] for c in local), 4) for i in range(3)],
            }
        )

    # Guard 3: the placement origin, measured on the assembled prop.
    bpy.context.view_layer.update()
    pts = []
    for o in objects:
        pts.extend(o.matrix_world @ Vector(c) for c in o.bound_box)
    mn = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    mx = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    size = max(mx - mn)
    if abs(mn.z) > 0.001:
        fail(f"prop base sits at z={mn.z:.4f}, not 0 - run settle_on_origin(objects)")
    if abs((mn.x + mx.x) / 2.0) > 0.005 or abs((mn.y + mx.y) / 2.0) > 0.005:
        fail("prop footprint is not centred on the origin - run settle_on_origin(objects)")

    dim = contract["dimension"]
    measured = _measure(objects, dim["measure"])
    tol = dim.get("tolerance", 0.01)
    if abs(measured - dim["metres"]) > tol:
        fail(
            f"stated dimension '{dim['what']}' is {dim['metres']} m but the build measures "
            f"{measured:.4f} m (tolerance {tol}) - real-world scale is the contract"
        )

    for empty in empties:
        if not empty.name.startswith("socket_"):
            fail(f"exported empty {empty.name!r} is not a socket_* attachment point")

    return facts, {
        "dimensions_m": [round(v, 4) for v in (mx - mn)],
        "stated_dimension": {**dim, "measured_m": round(measured, 4)},
        "size_m": round(size, 4),
    }


def _unwrap(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.004)
    bpy.ops.object.mode_set(mode="OBJECT")


def _bake(objects, prop, bake_res, out_dir):
    """Bake each registered material's three channels to its own texture set,
    then swap every slot to a baked principled material KEEPING THE SLOT NAME.

    Ordering is load-bearing (learned in build-gramophone.py): the final
    materials that use the baked images are created BEFORE baking, so each
    image keeps a real user for the rest of the run - otherwise Blender may
    release the buffer and every later save exports a black map while the
    in-memory pixels still read correct.
    """
    import numpy as np

    scene = bpy.context.scene
    scene.cycles.samples = 1
    scene.cycles.use_denoising = False
    scene.render.bake.use_pass_direct = False
    scene.render.bake.use_pass_indirect = False
    scene.render.bake.margin = 12
    scene.render.bake.use_clear = True

    channels = [("basecolor", 0, "sRGB"), ("roughness", 1, "Non-Color"), ("metallic", 2, "Non-Color")]
    source_mats = {}
    for obj in objects:
        for slot in obj.material_slots:
            if slot.material.name not in CHAN:
                fail(f"material {slot.material.name} was not registered via bakekit.finish()")
            source_mats.setdefault(slot.material.name, slot.material)

    images = {}
    baked = {}
    for name in source_mats:
        final = bpy.data.materials.new(name + ".baked")
        final.use_nodes = True
        nt = final.node_tree
        for n in list(nt.nodes):
            nt.nodes.remove(n)
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.inputs["IOR"].default_value = 1.5
        nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
        for cname, _idx, cs in channels:
            img = bpy.data.images.new(
                f"{prop}_{name}_{cname}", bake_res, bake_res, alpha=False, is_data=(cs != "sRGB")
            )
            img.colorspace_settings.name = cs
            images[(name, cname)] = img
            t = nt.nodes.new("ShaderNodeTexImage")
            t.image = img
            target = {"basecolor": "Base Color", "roughness": "Roughness", "metallic": "Metallic"}[
                cname
            ]
            nt.links.new(t.outputs["Color"], bsdf.inputs[target])
        baked[name] = final

    coverage = {}
    for cname, idx, _cs in channels:
        bake_nodes = []
        for name, mat in source_mats.items():
            nt = mat.node_tree
            src = CHAN[name][idx]
            em = nt.nodes.new("ShaderNodeEmission")
            em.inputs["Strength"].default_value = 1.0
            nt.links.new(src, em.inputs["Color"])
            out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
            prev = out.inputs["Surface"].links[0].from_socket
            nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
            tex = nt.nodes.new("ShaderNodeTexImage")
            tex.image = images[(name, cname)]
            for n in nt.nodes:
                n.select = False
            tex.select = True
            nt.nodes.active = tex
            bake_nodes.append((nt, em, tex, out, prev))
        for obj in objects:
            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            # A second object writing into an already-baked image must not
            # clear it; slot names are unique per object, so images never
            # collide, but use_clear stays off after the first object anyway.
            scene.render.bake.use_clear = obj is objects[0]
            res = bpy.ops.object.bake(type="EMIT")
            if "FINISHED" not in res:
                fail(f"bake of {cname} on {obj.name} returned {res}")
        for nt, em, tex, out, prev in bake_nodes:
            nt.links.new(prev, out.inputs["Surface"])
            nt.nodes.remove(em)
            nt.nodes.remove(tex)
        # Guard 2, first half: a black bake means the pass silently did
        # nothing. Never ship that.
        for name in source_mats:
            img = images[(name, cname)]
            buf = np.empty(bake_res * bake_res * 4, dtype=np.float32)
            img.pixels.foreach_get(buf)
            rgb_max = float(buf.reshape(-1, 4)[:, :3].max())
            cov = float((buf.reshape(-1, 4)[:, :3].max(axis=1) > 0.002).sum()) / (
                bake_res * bake_res
            )
            coverage[f"{name}/{cname}"] = {"max": round(rgb_max, 4), "coverage": round(cov, 4)}
            if cname == "basecolor" and cov < 0.02:
                fail(f"bake of {name}/{cname} is effectively empty (coverage {cov * 100:.2f}%)")

    for obj in objects:
        for slot in obj.material_slots:
            source_name = slot.material.name
            slot.material = baked[source_name]
    # The exported materials carry the CONTRACT slot names.
    for name, mat in baked.items():
        source_mats[name].name = name + ".procedural"
        mat.name = name
    return coverage


def _verify_glb(path):
    """Guard 2, second half: read the shipped file's embedded images back and
    prove they carry an image. In-memory correctness is not evidence."""
    import struct
    import tempfile

    import numpy as np

    data = open(path, "rb").read()
    total = struct.unpack("<III", data[:12])[2]
    off, js, binbuf = 12, None, None
    while off < total:
        clen, ctype = struct.unpack("<II", data[off : off + 8])
        off += 8
        chunk = data[off : off + clen]
        off += clen
        if ctype == 0x4E4F534A:
            js = json.loads(chunk)
        elif ctype == 0x004E4942:
            binbuf = chunk
    if not js or not js.get("images"):
        fail("exported glb carries no images")
    for i, im in enumerate(js["images"]):
        bv = js["bufferViews"][im["bufferView"]]
        o = bv.get("byteOffset", 0)
        tmp = os.path.join(tempfile.gettempdir(), f"img2blend_glbchk_{i}.bin")
        open(tmp, "wb").write(binbuf[o : o + bv["byteLength"]])
        chk = bpy.data.images.load(tmp)
        buf = np.empty(chk.size[0] * chk.size[1] * 4, dtype=np.float32)
        chk.pixels.foreach_get(buf)
        mx = float(buf.reshape(-1, 4)[:, :3].max())
        bpy.data.images.remove(chk)
        os.remove(tmp)
        if mx < 0.02:
            fail(f"exported texture {im.get('name', i)!r} is black - refusing to ship")
    return len(js["images"])


def finish_build(contract, out_dir, seed, bake_res=1024, sockets=()):
    """Contract check -> save the editable .blend -> unwrap -> bake -> export
    the guarded glb -> verify it -> write the build report. One call, so no
    emitted script can reorder the guards away."""
    prop = contract["prop"]
    objects = [bpy.data.objects[e["name"]] for e in contract["objects"]]
    empties = list(sockets)
    os.makedirs(out_dir, exist_ok=True)

    facts, measures = _enforce_contract(contract, objects, empties)

    # The .blend the operator opens is the PROCEDURAL authoring: node-tree
    # materials, separate parts, real modifiers. Saved before the bake
    # flattens anything.
    for obj in objects:
        _unwrap(obj)  # Guard 4: UVs exist in the saved file and for the bake.
    blend_path = os.path.join(out_dir, f"{prop}.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)

    coverage = _bake(objects, prop, bake_res, out_dir)

    # Guard 5: export exactly what the contract names, nothing else.
    bpy.ops.object.select_all(action="DESELECT")
    for target in objects + empties:
        target.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    glb_path = os.path.join(out_dir, f"{prop}.glb")
    bpy.ops.export_scene.gltf(
        filepath=glb_path,
        export_format="GLB",
        use_selection=True,
        export_apply=True,
        export_yup=True,
        export_materials="EXPORT",
        export_image_format="JPEG",
        export_jpeg_quality=90,
        export_normals=True,
        export_tangents=False,
        export_texcoords=True,
        export_cameras=False,
        export_lights=False,
        export_extras=False,
    )
    embedded = _verify_glb(glb_path)

    report = {
        "prop": prop,
        "seed": seed,
        "blender": bpy.app.version_string,
        "contract": contract,
        "objects": facts,
        "measures": measures,
        "bake": {"resolution": bake_res, "coverage": coverage},
        "sockets": [e.name for e in empties],
        "outputs": {
            "blend": os.path.basename(blend_path),
            "glb": os.path.basename(glb_path),
            "glb_bytes": os.path.getsize(glb_path),
            "glb_embedded_images": embedded,
        },
    }
    report_path = os.path.join(out_dir, f"{prop}-build.json")
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    print(
        f"bakekit: {prop} -> {os.path.basename(glb_path)} "
        f"({report['outputs']['glb_bytes'] / 1024:.0f} KB, "
        f"{sum(f['triangles'] for f in facts)} tris, "
        f"{measures['dimensions_m']} m), report {os.path.basename(report_path)}"
    )
    return report
