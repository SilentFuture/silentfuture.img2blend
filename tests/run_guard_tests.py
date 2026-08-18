# img2blend export-guard tests. Runs INSIDE Blender (bpy), invoked headless:
#
#   python3 tools/build.py guards
#
# Each case builds a MINIMAL scene and asserts that the guard path fails (or
# passes) as specified in docs/export-guards.md. bakekit.fail is patched to
# raise instead of exiting so one run covers every case.

import json
import os
import struct
import sys
import tempfile
import traceback

import bpy

import bakekit


class GuardFailure(Exception):
    pass


def _raise_fail(message):
    raise GuardFailure(message)


bakekit.fail = _raise_fail


def minimal_prop(shade=0.35):
    """One box object with one registered material, settled on the origin.
    Returns (body, contract). shade=0.0 produces the black-texture case."""
    bakekit.reset_scene(7)
    mat, nt, bsdf, out, texco, geo = bakekit.base_material("prop_skin")
    bakekit.finish(
        mat, nt, bsdf,
        bakekit.rgb(nt, shade, shade * 0.8, shade * 0.6),
        bakekit.val(nt, 0.5),
        bakekit.val(nt, 0.0),
    )
    verts, faces = bakekit.box(0.0, 0.0, 0.0, 0.2, 0.2, 0.2)
    body = bakekit.new_obj("prop_body", verts, faces, mat)
    bakekit.settle_on_origin([body])

    contract = {
        "prop": "guard-test",
        "objects": [{"name": "prop_body", "slots": ["prop_skin"], "origin": "base"}],
        "dimension": {
            "what": "body width",
            "metres": round(bakekit._measure([body], "extent_xy_max:prop_body"), 4),
            "measure": "extent_xy_max:prop_body",
            "tolerance": 0.01,
        },
    }
    return body, contract


def expect_failure(fn, *fragments):
    try:
        fn()
    except GuardFailure as failure:
        message = str(failure)
        if any(f in message for f in fragments):
            return
        raise AssertionError(f"guard failed with {message!r}, expected one of {fragments}")
    raise AssertionError(f"expected a guard failure containing {fragments}, but the call passed")


def read_glb_node_names(path):
    data = open(path, "rb").read()
    total = struct.unpack("<III", data[:12])[2]
    off = 12
    while off < total:
        clen, ctype = struct.unpack("<II", data[off:off + 8])
        off += 8
        chunk = data[off:off + clen]
        off += clen
        if ctype == 0x4E4F534A:
            js = json.loads(chunk)
            return sorted(n.get("name") for n in js.get("nodes", []))
    raise AssertionError(f"{path} carries no JSON chunk")


# ------------------------------------------------------------------- cases


def clean_contract_passes():
    body, contract = minimal_prop()
    facts, measures = bakekit._enforce_contract(contract, [body], [])
    assert facts[0]["object"] == "prop_body", facts
    assert measures["stated_dimension"]["measured_m"] > 0.0


def guard1_parented_object_fails():
    body, contract = minimal_prop()
    parent = bakekit.new_obj("rig_parent", *bakekit.box(0.5, 0.5, 0.0, 0.1, 0.05, 0.05))
    body.parent = parent
    expect_failure(
        lambda: bakekit._enforce_contract(contract, [body], []),
        "has a parent",
    )


def guard3_floating_base_fails():
    body, contract = minimal_prop()
    body.location.z += 0.05
    expect_failure(
        lambda: bakekit._enforce_contract(contract, [body], []),
        "base sits at z=",
    )


def contract_slot_order_fails():
    body, contract = minimal_prop()
    contract["objects"][0]["slots"] = ["some_other_slot"]
    expect_failure(
        lambda: bakekit._enforce_contract(contract, [body], []),
        "slot order is the contract",
    )


def contract_dimension_fails():
    body, contract = minimal_prop()
    contract["dimension"]["metres"] *= 2.0
    expect_failure(
        lambda: bakekit._enforce_contract(contract, [body], []),
        "real-world scale is the contract",
    )


def guard2_black_bake_fails():
    body, contract = minimal_prop(shade=0.0)
    out_dir = tempfile.mkdtemp(prefix="img2blend-guards-")
    expect_failure(
        lambda: bakekit.finish_build(contract, out_dir, seed=7, bake_res=64),
        "effectively empty",
        "is black",
    )


def guard5_clean_build_exports_exact_selection():
    body, contract = minimal_prop()
    bakekit.new_obj("decoy_helper", *bakekit.box(1.0, 1.0, 0.0, 0.1, 0.05, 0.05))
    out_dir = tempfile.mkdtemp(prefix="img2blend-guards-")
    report = bakekit.finish_build(contract, out_dir, seed=7, bake_res=64)

    # Guard 5: the decoy in the scene must not leak into the export.
    names = read_glb_node_names(os.path.join(out_dir, "guard-test.glb"))
    assert names == ["prop_body"], f"exported nodes {names}, expected only prop_body"
    # Guard 4 (positive half): the exported object carries a UV layer.
    assert len(bpy.data.objects["prop_body"].data.uv_layers) > 0, "no UV layer after finish_build"
    # Guard 2 (positive half): embedded images exist and are non-black.
    assert report["outputs"]["glb_embedded_images"] > 0
    assert os.path.exists(os.path.join(out_dir, "guard-test-build.json"))


CASES = [
    clean_contract_passes,
    guard1_parented_object_fails,
    guard3_floating_base_fails,
    contract_slot_order_fails,
    contract_dimension_fails,
    guard2_black_bake_fails,
    guard5_clean_build_exports_exact_selection,
]


def main():
    failed = 0
    for fn in CASES:
        try:
            fn()
            print(f"guards: PASS - {fn.__name__}")
        except Exception:
            failed += 1
            print(f"guards: FAIL - {fn.__name__}")
            traceback.print_exc()
    print(f"guards: {len(CASES) - failed}/{len(CASES)} passed")
    if failed:
        sys.exit(1)


main()
