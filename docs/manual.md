# 39 - img2blend: props from reference images

Turn one or more reference images of a hard-surface prop into an engine-ready
asset:
a deterministic Blender Python build script (the source of truth), a `.blend`
the operator can keep editing, a guarded `.glb` for `assets/models/`, and a
provenance file whose gate trail shows how the result was reached - including
where it corrected itself.

The tooling lives in [`tools/`](../tools/CONVENTIONS.md).
Agents get the same workflow as a repo skill (`.claude/skills/img2blend/`).
The methodology is adapted from
[img2threejs](https://github.com/img2threejs/img2threejs) (Apache-2.0):
staged passes, vision review gates, honest self-correction - re-targeted to
emit bpy scripts instead of Three.js factories.

## What you need

| Input | Rule |
|---|---|
| Reference images | One or more, licence-clean: your own photos, your own renders, or verified CC0/permissive sources. Each is TAGGED with a view - `front`, `side`, `back`, `three-quarter`, or `detail` - and each view's render is judged against its own reference. More views mean less inference; faces no reference covers are the only place unseen-face inference is allowed, and the provenance records the evidenced/inferred split. Licence and source are recorded per image - no licence, no build. |
| A stated dimension | One real-world measurement with a justification ("handwheel diameter 0.14 m, typical DN50 valve"). Everything else derives from it; the build fails if it misses it. |
| Blender | 4.2+ on the machine, found via `$SF_BLENDER`, the macOS app bundle, or `PATH`. Runs headless; nothing opens. |
| Subject scope | Hard-surface: devices, furniture, fixtures, hardware. Characters and creatures are out of scope in v1 - the pipeline refuses honestly instead of stylizing (see the conventions doc for the recorded trigger to lift this). |

## The pipeline in five commands

```bash
cd <engine checkout>

# 1. start the provenance trail (the limits flags are mandatory honesty;
#    --reference repeats, one view tag each)
python3 tools/review.py init --out work/valve.provenance.json \
    --prop valve --script work/build-valve.py \
    --reference front=work/ref-front.jpg --reference side=work/ref-side.jpg \
    --licence "CC0 1.0" --source "https://..." \
    --dimension "handwheel diameter = 0.14 m (typical DN50 gate valve)" \
    --seed 7 --limit "rear face inferred by symmetry (no back reference)"

# 2. write/refine the build script, then build (headless Blender)
python3 tools/build.py build work/build-valve.py --out-dir work/out

# 3. render the fixed review set (front, side, three-quarter - plus back if a
#    back reference exists) and composite one comparison sheet
python3 tools/build.py review --blend work/out/valve.blend \
    --reference front=work/ref-front.jpg --reference side=work/ref-side.jpg \
    --out-dir work/review --pass-id blockout --attempt 1

# 4. judge the sheet, record exactly one verdict
python3 tools/review.py record work/valve.provenance.json \
    --pass-id blockout --sheet work/review/blockout-a1-sheet.png \
    --action continue --changed "..." --still-off "..." --why "..."

# 5. after all five passes: the final gate
python3 tools/review.py check work/valve.provenance.json \
    --build-report work/out/valve-build.json
```

The build script is a normal Python file that imports `bakekit` (geometry and
material helpers, the deterministic bake, the guarded export). The worked
example lives at `example/` - copy its shape.

## The staged passes

`blockout -> structure -> form -> material -> surface`, locked in order:
`review.py` refuses a verdict for a pass whose predecessor has not passed. Each
review renders the same fixed camera set and composites one sheet - a two-row
grid, references on top (neutral grey where no reference covers a view),
renders below, one column per view, `detail` references as reference-only
trailing columns - judged by eye (agent vision or yours), never by a pixel
score. Each column is compared against its own reference; uncovered columns
are checked for self-consistency only. The three-quarter view is mandatory
because silhouette comparisons cannot see flatness: a model can match the
front view perfectly and still read as a cardboard cutout at 40 degrees.

Verdicts: `continue`, `refine-script` (the script does not achieve the pass),
`refine-plan` (the part breakdown or stated dimension was wrong - invalidates
that pass and everything after it), `request-input` (the image cannot answer),
`stop`. Five attempts per pass, then the tool forces an escalation - the loop
terminates by construction.

## What comes out

| Artifact | What it is |
|---|---|
| `build-<prop>.py` | The source of truth. Diffable, re-runnable, deterministic (one `SEED`). |
| `<prop>.blend` | The operator's editing surface: separate named parts, procedural node-tree materials, real modifiers - saved BEFORE the bake flattens anything. |
| `<prop>.glb` | Engine-ready: baked basecolor/roughness/metallic, named material slots in contract order, articulation parts as named nodes with origins at their pivots. Drop into `assets/models/` ([05-assets.md](05-assets.md)). |
| `<prop>-build.json` | The build report: measured dimensions, triangle counts, slot order, bake coverage - facts recorded, never retyped. |
| `<prop>.provenance.json` | Every reference with view tag + licence, the evidenced/inferred view split, seed, limits, and the full gate trail: every verdict with its evidence sheet, what changed, what still differed, why. |

The export guards (see docs/export-guards.md) fail the build on
the five classic silent Blender export corruptions: inherited parent scale,
black/unpacked textures, wrong origins, missing UVs, and stale-selection
leftovers. The written glb's embedded images are read back and verified -
in-memory correctness is not evidence.

## The asset contract, in one paragraph

Named objects; anything that moves is its own object with its origin exactly
at the articulation point, its axis named, its rest pose baked into the mesh;
material slots are named and their order is index-aligned with the engine's
Material component of the consuming engine; scale is real-world metres derived from the
stated dimension; standing props are base-at-origin; attachment points are
`socket_*` empties. The full contract with rationale:
[`tools/CONVENTIONS.md`](../tools/CONVENTIONS.md).

## Honesty rules

Photographs cannot show absolute scale or unlit material response, and the
faces no reference covers are inferred, not observed. The provenance records
which views are evidenced and which are inferred, and its `limits` list states
how the inferred ones were filled; `review.py init` refuses to start without
at least one entry (scale and material inference remain even with full view
coverage). "This cannot reach the requested fidelity from these images" is a
valid, recordable result - preferred over a confident guess.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `review: FAILED - current pass is 'X'` | Passes are locked in order; run `review.py status` to see the trail state. |
| Build fails on the stated dimension | The script's constants drifted from the declared real-world size. Fix the constants (or, if the statement was wrong, record `refine-plan`). |
| `refusing to ship - texture is black` | The bake wrote nothing (usually missing UVs or an unregistered material). The guard caught what would have shipped as a black prop. |
| glb looks right in Blender, wrong in the engine | Check the build report's slot order against the scene's Material wiring - order is the contract. |
