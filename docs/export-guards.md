# The five guarded export failure modes

Enforced by `bakekit` on every build - the build FAILS (`bakekit: FAILED -
<message>`, exit code 1) rather than shipping a violation. The discipline
generalizes SilentFuture's earlier per-project asset-converter contracts,
where each of these failure modes shipped at least once before it got a
guard. Tested headless via `python3 tools/build.py guards`
(`tests/run_guard_tests.py`).

## 1. Parent scale

**What it catches:** an export object parented to anything, or carrying a
non-identity scale after transforms are applied. A parented object inherits
its parent's transform at export time - the shipped mesh silently differs
from the authored one.

**Where:** `_enforce_contract` - rejects `obj.parent`, applies
rotation/scale per object, then asserts identity scale.
**Message:** `<name> has a parent (...)` / `<name> still carries scale ...`.
**Test:** `guard1_parented_object_fails`.

## 2. Black textures

**What it catches:** a bake that produced empty or uniformly black textures -
wrong bake pass, unlinked socket, dead UV area. Two halves: bake coverage is
measured per channel right after baking, and the WRITTEN glb's embedded
images are read back and checked again. The in-memory bake being right is
not evidence the file is right.

**Where:** `_bake` (coverage) and `_verify_glb` (file read-back).
**Message:** `bake of <x> is effectively empty (coverage ...)` /
`exported texture <x> is black - refusing to ship`.
**Tests:** `guard2_black_bake_fails` (negative),
`guard5_clean_build_exports_exact_selection` (positive half: embedded,
non-black images present).

## 3. The origin

**What it catches:** a prop whose base is not at z=0 or whose footprint is
not centred - it would sink into or hover over the ground at placement - and
a stated real-world dimension the built geometry misses beyond tolerance.

**Where:** `_enforce_contract` - measured on the assembled prop, never
assumed. `settle_on_origin(objects)` is the fix, not manual nudging.
**Message:** `prop base sits at z=..., not 0` / `... footprint is not
centred ...` / `stated dimension ... real-world scale is the contract`.
**Tests:** `guard3_floating_base_fails`, `contract_dimension_fails`; slot
order and object-set mismatches from the same contract check are covered by
`contract_slot_order_fails`.

## 4. Missing UVs

**What it catches:** an object leaving with baked textures but no UV layer -
the textures would sample garbage. `finish_build` unwraps every contract
object BEFORE saving the `.blend` and baking, so the guard holds by
construction; the clean-build test asserts the UV layer exists on the
exported object.

**Where:** `_unwrap` inside `finish_build`.
**Test:** positive assertion in `guard5_clean_build_exports_exact_selection`.

## 5. Selection leftovers

**What it catches:** exporting whatever happened to be selected. Saved-file
selection state is not a design decision - export deselects everything and
selects exactly the contract objects plus declared sockets.

**Where:** `finish_build` before `export_scene.gltf(use_selection=True)`.
**Test:** `guard5_clean_build_exports_exact_selection` - a decoy object in
the scene must not appear among the glb's nodes.
