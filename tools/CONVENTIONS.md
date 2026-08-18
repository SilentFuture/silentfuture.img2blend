# img2blend - conventions

Turn one or more reference images into an engine-ready prop by emitting a
deterministic Blender Python build script, gated by vision review against
headless renders. Every reference is tagged with a view
(`front|side|back|three-quarter|detail`); more tagged views means less
inference, and the provenance states per face which of the two it got.

Methodology adapted from img2threejs
(https://github.com/img2threejs/img2threejs, Apache License 2.0) - the staged
passes, the review gates, the self-correction vocabulary and the honesty rules
are theirs, re-targeted from "emit a Three.js factory" to "emit a bpy build
script". No source code was copied. The converter discipline (the five guarded
export failure modes, named slots, hinge origins, the build report) generalizes
SilentFuture's earlier per-project asset-converter contracts.

## 1. The bpy script is the source of truth

The pipeline's output is a **Python build script**, not a mesh file. The
`.blend` and the `.glb` are artifacts of running it. This is the same rule the
schemann.dev converters live by: deterministic, diffable, re-runnable - an
operator edit is a script edit, and re-running reproduces the asset bit-for-bit
at the geometry level.

- Everything derives from named constants in metres at the top of the script.
- One `SEED` constant; every stochastic choice (noise offsets, wear patches)
  derives from it. Two runs of the same script produce the same asset.
- The script builds, bakes, verifies and exports in one headless run through
  `tools/build.py`. It imports `bakekit` for the shared machinery;
  the geometry and material authoring stays in the script, because that is the
  part an operator will want to edit in place.
- No network, no timestamps in the artifact, no dependence on user preferences
  (`--factory-startup` is forced by the runner).

## 2. The asset contract (what "interaction-ready" means)

Generalized from SilentFuture's earlier lever and gramophone converter contracts. Every emitted
script declares a `CONTRACT` dict and `bakekit` enforces it at export - the
build FAILS rather than shipping a violation.

1. **Named objects.** Every exported object has a deliberate name
   (`valve_body`, `valve_handwheel`), never `Cube.003`. One object per
   independently moving part; everything static joins into the body object.
2. **Articulation points are origins.** A part that hinges, spins or slides is
   its OWN object with its origin exactly at the articulation point, its
   axis named in the contract (`"axis": "Z"`), and its **rest pose baked into
   the mesh**. The runtime rotates from zero about the part's local axis;
   nothing in code knows the rest angle, so the two cannot drift apart.
3. **Named material slots, order is a contract.** Consuming engines
   index-align their material bindings with the mesh's distinct embedded
   materials in DFS order. The contract lists slot names per object in order;
   bakekit asserts the export matches. A swappable surface (a label, a painted
   panel) gets its own named slot.
4. **Real-world scale, in metres, from a stated reference dimension.** A
   single image has no absolute scale. The contract states ONE dimension and
   where it comes from ("handwheel diameter 0.14 m, typical DN50 cast-iron
   gate valve") and every other constant derives from it. bakekit measures the
   built object and fails if it misses the stated dimension by more than the
   declared tolerance.
5. **Placement origin.** A prop that stands gets its origin at the centre of
   its footprint, base at z=0. A prop that mounts declares its mount face in
   the contract notes.
6. **Sockets are named empties.** Attachment points for other props or effects
   are empties named `socket_<role>`, exported with the object.
7. **Operator post-editing is a first-class outcome.** Real geometry, real
   modifiers where sensible, materials as node trees in the saved `.blend` -
   the bake to textures happens after the `.blend` is saved, so what the
   operator opens is editable authoring, not a flattened husk.

## 3. The five guarded export failure modes

Enforced by `bakekit.export_glb` on every build (spec and headless tests:
`docs/export-guards.md`):

1. **Parent scale** - transforms are applied per object and every exported
   object is checked for identity scale afterwards; a parented export object
   is an error.
2. **Black textures** - every baked or linked image is checked for pixel data
   that is neither empty nor uniformly black before export, and the written
   GLB's embedded images are read back and checked again. The in-memory bake
   being right is not evidence the file is right.
3. **The origin** - contract origins (hinge, base) are asserted against the
   measured mesh, not assumed.
4. **Missing UVs** - an object leaving with baked textures and no UV layer is
   an error, not a warning.
5. **Selection leftovers** - export selects exactly the objects the contract
   names. Saved-file selection state is not a design decision.

Every build writes a **build report** (`<prop>-build.json`): Blender version,
measured dimensions, triangle counts, slot order per object, bake coverage per
channel, the contract as enforced. Facts are recorded, never retyped.

## 4. The staged passes

Five passes, in order, each gated. A pass may not begin until the previous one
has a `continue` verdict in the gate trail (`review.py` enforces this).

| Pass | What the script must achieve | What the gate judges |
|---|---|---|
| `blockout` | Primary masses at correct real-world scale and position | Silhouette and proportions vs reference in all three views |
| `structure` | Every contract part exists as its own named object; articulation origins placed | Part presence and placement; nothing floating, nothing fused |
| `form` | Profiles, tapers, bevels, curvature - the shapes read as the object | Three-quarter view reads as the object, not a toy of it |
| `material` | Material slots assigned, base colours and PBR classes right | Palette and material class (metal/paint/wood) per part |
| `surface` | Wear, dirt, edge highlights, micro detail - the register of the reference | Believability of the surface story; nothing washed out or flat |

2D gates are blind to 3D realism (the img2threejs Bowie-knife lesson): a
matching silhouette can still read as a flat toy. That is why the three-quarter
render is mandatory in every review and why `form` is judged primarily there.
Structural evidence beats texture confidence: a pass with a convincing material
on a wrong shape FAILS `structure` retroactively - record `refine-script`, do
not paper over geometry with texture.

## 5. The review gate

`render_review.py` renders the built `.blend` with a FIXED camera set - front,
side, three-quarter, plus back when (and only when) a back reference exists -
deterministically framed from the object bounds, under a fixed neutral studio
light, and composites one comparison sheet as a two-row grid: top row the
reference for each view (neutral grey where no reference covers it), bottom
row the render, one column per view, detail references as reference-only
trailing columns.

Each render column is judged against ITS OWN reference view. A column with no
reference is judged for self-consistency only (does the inferred face follow
plausibly from the evidenced ones) - never "failed" against a photo that does
not show it. Detail references inform the `material` and `surface` passes.

The agent's vision judges the sheet - scripts never score visuals. Exactly one
verdict per review, recorded via `review.py record` into the provenance file:

- `continue` - the pass meets its criteria; the next pass unlocks.
- `refine-script` - the build script does not achieve what this pass requires;
  edit it, rebuild, re-render, re-review. (img2threejs's `refine-code`.)
- `refine-plan` - the part breakdown or a stated dimension was wrong; fix the
  contract/constants, which may invalidate earlier passes - say so in the
  notes. (Their `refine-spec`.)
- `request-input` - the image cannot answer the question (hidden geometry,
  ambiguous material). Escalate to the operator instead of inventing.
- `stop` - target fidelity reached early, or unreachable from this image.

Every verdict carries the sheet path, what changed since the last attempt,
what still does not match, and why the action was chosen. **The gate trail is
the provenance** - a reader must be able to trace which decision produced
which geometry. Attempts per pass are bounded (default 5); the cap forces
`request-input` or `stop`, never a silent infinite loop.

## 6. Provenance and honesty

`review.py init` creates `<prop>.provenance.json`; every gate verdict appends
to it. It records: every reference image with its view tag, licence and
source, the computed coverage split (`evidenced_views` vs `inferred_views`),
the stated reference dimension, pipeline version, seed, the build script path,
the full gate trail, and a `limits` list that MUST be honest:

- unseen-face inference applies ONLY to views no reference covers - the
  coverage split says which, the limits say how they were inferred (mirrored,
  type knowledge);
- all dimensions are estimated from one stated dimension - name it;
- materials are inferred from lit pixels, not measured - inference, not
  inverse rendering. This one stands even with full view coverage.

Never claim a feature is "done" when it is "improved". "This cannot reach the
requested fidelity from this image" is a valid, recordable result.

The reference image must be licence-clean: your own photograph, your own
render, or a verifiable CC0/permissive source - recorded with URL and licence
in the provenance. No reference, no build.

## 7. Scope of v1: hard-surface only

Devices, furniture, fixtures, hardware - the actual prop demand. **Characters
(and creatures) are explicitly out of scope.** Recorded trigger for lifting
the exclusion: a real character/creature asset demand lands AND the pipeline
grows an anatomy track (proportion systems, landmark placement, topology fit
for deformation - the img2threejs character track shows the required shape).
Until then a character request gets `request-input`, not a stylized guess.

Out of scope is not "will not work"; it is "will not be pretended to work".
