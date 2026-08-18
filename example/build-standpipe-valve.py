# build-standpipe-valve.py - emitted by the img2blend pipeline.
# THE SOURCE OF TRUTH for this prop; the .blend and .glb are artifacts of
# running it:
#
#   python3 tools/build.py build \
#       example/build-standpipe-valve.py \
#       --out-dir example/out
#
# Reference: a rusty cast-iron gate valve on a ~1 m rising main, CC0 1.0
# photo by Luc Coekaerts (Flickr, see standpipe-valve.provenance.json for the
# full source record). Front view evidenced; side/back/three-quarter inferred
# from gate-valve type knowledge - the provenance limits state how.
#
# Scale anchor: handwheel diameter 0.20 m; everything below derives from it.
# Part breakdown (bottom to top): tarred riser pipe -> bolted pipe flange ->
# oval gate body -> bonnet flange -> bonnet dome -> gland ring stack -> stem
# -> spoked handwheel (the articulated part: own object, origin ON the stem
# axis at hub height, rest pose = closed, throw = rotation about local +Z).

import math
import sys

import bakekit
import bpy
from mathutils import Vector

ARGS = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
OUT = ARGS[ARGS.index("--out-dir") + 1] if "--out-dir" in ARGS else "/tmp/img2blend-standpipe-valve"

SEED = 7

# ----------------------------------------------------------- the measurements
# Stated: handwheel diameter 0.20 m. Pixel ratios from the front reference.
# Blockout attempt 1 correction: the photo puts the valve head (pipe flange to
# wheel top) at ~33 percent of total height; the first constants spent 42
# percent on it. Pipe lengthened, head compressed, wheel dropped to the gland.
WHEEL_D = 0.20
WHEEL_RIM_R = 0.089  # rim centreline; rim tube 0.011 -> outer extent 0.200
WHEEL_TUBE_R = 0.011
PIPE_R = 0.057  # DN100 riser outer radius
Z_FLANGE = 0.665  # pipe runs from ground to the pipe flange
FLANGE_R = 0.105
FLANGE_T = 0.030
# Form attempt 1 correction: the reference's mass order from the pipe up is
# short drum body -> the WIDEST element, a double-disc bonnet flange -> the
# dominant dome (the bonnet) -> gland. The first form profiles had the bulge
# below the flange and a small cone above - inverted.
Z_BODY0 = Z_FLANGE + FLANGE_T
Z_BODY1 = 0.760  # short drum body between the flanges
BODY_R = 0.084
Z_BFLANGE1 = Z_BODY1 + 0.042  # double-disc bonnet flange, the widest element
BFLANGE_R = 0.098
Z_BONNET1 = 0.892  # the dominant bonnet dome, narrowing to the gland
BONNET_TOP_R = 0.036
Z_GLAND1 = 0.945  # packing gland ring stack
STEM_R = 0.009
Z_WHEEL = 0.985  # hub centre = the articulation point

CONTRACT = {
    "prop": "standpipe-valve",
    "objects": [
        {"name": "valve_body", "slots": ["valve_pipe", "valve_iron"], "origin": "base"},
        {
            "name": "valve_handwheel",
            "slots": ["valve_wheel"],
            "origin": "hinge",
            "axis": "Z",
            "rest": "closed",
        },
    ],
    "dimension": {
        "what": "handwheel diameter",
        "metres": 0.20,
        "measure": "extent_xy_max:valve_handwheel",
        "tolerance": 0.01,
    },
}

bakekit.reset_scene(SEED)

# ------------------------------------------------------------------ materials
# The reference's material story (material pass): everything is rusted cast
# iron, but in three registers. The pipe wears black bitumen wrap with rust
# breaking through in bands; the valve head is even mid-rust with darker
# cavities; the handwheel is the brightest orange (most handled, most
# weathered). Linear-space colours - they read far darker as numbers than
# they render.


def _height_fac(nt, obj, z0, z1):
    """0 below z0, 1 above z1, from the object-space height - the surface
    pass uses it to concentrate rust where water sat (under the flange)."""
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(obj, sep.inputs["Vector"])
    return bakekit.ramp(
        nt, bakekit.mapf(nt, sep.outputs["Z"], 0.0, 1.0), [(z0, (0, 0, 0, 1)), (z1, (1, 1, 1, 1))]
    )


def mat_pipe():
    mat, nt, bsdf, out, texco, geo = bakekit.base_material("valve_pipe")
    obj = texco.outputs["Object"]
    bitumen = bakekit.rgb(nt, 0.0115, 0.0090, 0.0072)
    tar_sheen = bakekit.rgb(nt, 0.0220, 0.0185, 0.0150)
    rust_band = bakekit.rgb(nt, 0.0620, 0.0210, 0.0085)
    wrap_grey = bakekit.rgb(nt, 0.0480, 0.0430, 0.0360)
    # patchy tar base
    col = bakekit.mixrgb(
        nt, bakekit.mapf(nt, bakekit.noise(nt, obj, 14.0, 5.0), 0.0, 0.55), bitumen, tar_sheen
    )
    # rust breaking through in broad patches; heavier towards the flange,
    # where the reference shows the wrap failed first (surface pass)
    rust_mask = bakekit.ramp(
        nt,
        bakekit.noise(nt, obj, 5.5, 4.0),
        [(0.48, (0, 0, 0, 1)), (0.72, (1, 1, 1, 1))],
    )
    top_bias = _height_fac(nt, obj, 0.40, 0.62)
    boosted = nt.nodes.new("ShaderNodeMath")
    boosted.operation = "MAXIMUM"
    nt.links.new(rust_mask, boosted.inputs[0])
    band = nt.nodes.new("ShaderNodeMath")
    band.operation = "MULTIPLY"
    nt.links.new(top_bias, band.inputs[0])
    nt.links.new(bakekit.mapf(nt, bakekit.noise(nt, obj, 8.0, 3.0), 0.2, 0.9), band.inputs[1])
    nt.links.new(band.outputs[0], boosted.inputs[1])
    col = bakekit.mixrgb(nt, boosted.outputs[0], col, rust_band)
    # pale wrap remnants, sparse
    col = bakekit.mixrgb(
        nt,
        bakekit.ramp(
            nt,
            bakekit.noise(nt, obj, 9.0, 6.0),
            [(0.62, (0, 0, 0, 1)), (0.80, (1, 1, 1, 1))],
        ),
        col,
        wrap_grey,
    )
    rough = bakekit.mapf(nt, bakekit.noise(nt, obj, 30.0, 4.0), 0.48, 0.72)
    return bakekit.finish(mat, nt, bsdf, col, rough, bakekit.val(nt, 0.0))


def _rust(name, base, dark, bright, edge):
    """Shared rust recipe: patch noise between base and dark, cavities hold
    the dark, convex edges rub toward the bright tone."""
    mat, nt, bsdf, out, texco, geo = bakekit.base_material(name)
    obj = texco.outputs["Object"]
    base_c = bakekit.rgb(nt, *base)
    dark_c = bakekit.rgb(nt, *dark)
    bright_c = bakekit.rgb(nt, *bright)
    col = bakekit.mixrgb(
        nt, bakekit.mapf(nt, bakekit.noise(nt, obj, 24.0, 6.0), 0.1, 0.9), base_c, dark_c
    )
    # broad weather stains (surface pass: the head is mottled at arm's length,
    # not evenly brown)
    col = bakekit.mixrgb(
        nt,
        bakekit.ramp(
            nt,
            bakekit.noise(nt, obj, 3.2, 3.0),
            [(0.42, (0, 0, 0, 1)), (0.70, (0.55, 0.55, 0.55, 1))],
        ),
        col,
        dark_c,
    )
    # fine speckle of scale
    col = bakekit.mixrgb(
        nt,
        bakekit.ramp(
            nt,
            bakekit.noise(nt, obj, 180.0, 2.0),
            [(0.60, (0, 0, 0, 1)), (0.85, (1, 1, 1, 1))],
        ),
        col,
        dark_c,
    )
    # convex edges rub brighter (handled, weathered high points)
    col = bakekit.mixrgb(nt, bakekit.pointiness(nt, geo, 0.0, edge), col, bright_c)
    rough = bakekit.mapf(nt, bakekit.noise(nt, obj, 60.0, 4.0), 0.58, 0.80)
    rough = bakekit.mixrgb(nt, bakekit.pointiness(nt, geo, 0.0, 0.5), rough, bakekit.val(nt, 0.52))
    metal = bakekit.mixrgb(nt, bakekit.pointiness(nt, geo, 0.0, 0.6), bakekit.val(nt, 0.04), bakekit.val(nt, 0.22))
    return bakekit.finish(mat, nt, bsdf, col, rough, metal)


def mat_iron():
    return _rust(
        "valve_iron",
        base=(0.1050, 0.0330, 0.0125),
        dark=(0.0330, 0.0125, 0.0062),
        bright=(0.2000, 0.0700, 0.0230),
        edge=0.45,
    )


def mat_wheel():
    return _rust(
        "valve_wheel",
        base=(0.1500, 0.0480, 0.0160),
        dark=(0.0480, 0.0165, 0.0075),
        bright=(0.2700, 0.0980, 0.0300),
        edge=0.60,
    )


PIPE = mat_pipe()
IRON = mat_iron()
WHEEL = mat_wheel()

# ------------------------------------------------------------------ the body
parts = []

# riser pipe, ground to flange
v, f = bakekit.cyl(0, 0, 0.0, Z_FLANGE, PIPE_R, seg=48)
parts.append(bakekit.new_obj("pipe", v, f, PIPE))

# pipe flange, with the bolt ring the reference shows (8 studs)
v, f = bakekit.cyl(0, 0, Z_FLANGE, Z_BODY0, FLANGE_R, seg=48)
parts.append(bakekit.new_obj("flange", v, f, IRON))
BOLT_RING_R = FLANGE_R - 0.018
for i in range(8):
    a = 2.0 * math.pi * (i + 0.5) / 8
    bx, by = BOLT_RING_R * math.cos(a), BOLT_RING_R * math.sin(a)
    v, f = bakekit.cyl(bx, by, Z_FLANGE - 0.008, Z_BODY0 + 0.008, 0.011, seg=6)
    parts.append(bakekit.new_obj(f"bolt_{i}", v, f, IRON))

# gate body: a short slightly waisted drum between the two flanges
BH = Z_BODY1 - Z_BODY0
v, f = bakekit.revolve(
    [
        (BODY_R * 0.98, Z_BODY0),
        (BODY_R * 0.92, Z_BODY0 + BH * 0.5),
        (BODY_R * 0.98, Z_BODY1),
    ],
    seg=48,
    close_start=True,
    close_end=True,
)
parts.append(bakekit.new_obj("body", v, f, IRON))

# bonnet flange: the widest element of the head, read as TWO stacked discs
# (flange + counter-flange) with a shadow gap between them
BF_T = (Z_BFLANGE1 - Z_BODY1 - 0.004) / 2.0
for i, (r, z0) in enumerate(
    [(BFLANGE_R, Z_BODY1), (BFLANGE_R * 0.965, Z_BODY1 + BF_T + 0.004)]
):
    v, f = bakekit.revolve(
        [
            (r - 0.005, z0),
            (r, z0 + 0.005),
            (r, z0 + BF_T - 0.005),
            (r - 0.005, z0 + BF_T),
        ],
        seg=48,
        close_start=True,
        close_end=True,
    )
    parts.append(bakekit.new_obj(f"bflange_{i}", v, f, IRON))

# bonnet: the dominant dome, shouldering from nearly flange width into the
# gland neck
DH = Z_BONNET1 - Z_BFLANGE1
v, f = bakekit.revolve(
    [
        (BODY_R * 0.95, Z_BFLANGE1),
        (BODY_R * 0.93, Z_BFLANGE1 + DH * 0.22),
        (BODY_R * 0.82, Z_BFLANGE1 + DH * 0.45),
        (BODY_R * 0.62, Z_BFLANGE1 + DH * 0.68),
        (BODY_R * 0.44, Z_BFLANGE1 + DH * 0.86),
        (BONNET_TOP_R, Z_BONNET1),
    ],
    seg=48,
    close_start=True,
    close_end=True,
)
parts.append(bakekit.new_obj("bonnet", v, f, IRON))

# gland ring stack: packing gland and yoke sleeve read as alternating discs
# in the reference (structure pass)
GLAND_RINGS = [
    (0.040, 0.016),
    (0.030, 0.012),
    (0.043, 0.014),
    (0.028, 0.010),
    (0.036, 0.008),
]
z = Z_BONNET1
for i, (r, t) in enumerate(GLAND_RINGS):
    v, f = bakekit.cyl(0, 0, z, z + t, r, seg=32)
    parts.append(bakekit.new_obj(f"gland_ring_{i}", v, f, IRON))
    z += t

# stem up into the wheel hub
v, f = bakekit.cyl(0, 0, Z_GLAND1, Z_WHEEL + 0.022, STEM_R, seg=16)
parts.append(bakekit.new_obj("stem", v, f, IRON))

body = bakekit.join(parts, "valve_body")
bakekit.shade_smooth(body, angle_deg=38)

# ------------------------------------------------- the handwheel (own object,
# origin on the stem axis at hub height - the articulation point). Structure:
# rim ring + 5 spokes + hub, authored about the origin so the runtime's
# rotation about local +Z spins it in place.
wheel_parts = []
# rim: round in section (an octagonal approximation of the torus tube)
rim_profile = []
for i in range(9):
    a = 2.0 * math.pi * i / 8
    rim_profile.append(
        (WHEEL_RIM_R + WHEEL_TUBE_R * math.cos(a), WHEEL_TUBE_R * math.sin(a))
    )
v, f = bakekit.revolve(rim_profile, seg=48)
wheel_parts.append(bakekit.new_obj("wheel_rim", v, f, WHEEL))
# 5 spokes, hub to rim
for i in range(5):
    a = 2.0 * math.pi * i / 5
    p0 = Vector((0.012 * math.cos(a), 0.012 * math.sin(a), 0.0))
    p1 = Vector((WHEEL_RIM_R * math.cos(a), WHEEL_RIM_R * math.sin(a), 0.0))
    v, f = bakekit.tube([p0, p0.lerp(p1, 0.5), p1], [0.0085, 0.0075, 0.0068], seg=10)
    wheel_parts.append(bakekit.new_obj(f"wheel_spoke_{i}", v, f, WHEEL))
# hub with the stem nut on top
v, f = bakekit.cyl(0, 0, -0.016, 0.018, 0.020, seg=24)
wheel_parts.append(bakekit.new_obj("wheel_hub", v, f, WHEEL))
v, f = bakekit.cyl(0, 0, 0.018, 0.032, 0.011, seg=6)
wheel_parts.append(bakekit.new_obj("wheel_nut", v, f, WHEEL))
wheel = bakekit.join(wheel_parts, "valve_handwheel")
bakekit.shade_smooth(wheel, angle_deg=38)
wheel.location = Vector((0, 0, Z_WHEEL))

objects = [body, wheel]
bakekit.settle_on_origin(objects)

bakekit.finish_build(CONTRACT, OUT, SEED, bake_res=1024)
