---
name: img2blend
description: Turn one or more licence-clean reference images of a hard-surface prop (device, furniture, fixture, hardware) into an engine-ready asset by emitting a deterministic bpy build script, gated by staged vision review of headless Blender renders. Each reference is tagged with a view (front/side/back/three-quarter/detail); more views means less inference. Use when asked to generate a 3D prop from a photo or reference image. Characters and creatures are out of scope - escalate, do not stylize.
---

# img2blend - reference image to Blender asset

Read `tools/CONVENTIONS.md` first - it is the binding contract this
workflow executes. Methodology adapted from img2threejs (Apache-2.0);
re-targeted to emit a bpy build script as the source of truth.

## Preconditions - refuse early, not late

1. **References**: one or more licence-clean images (own photo, own render,
   or verified CC0/permissive with URL). No licence, no build. Tag EVERY
   image with its view: `front|side|back|three-quarter|detail`. More tagged
   views shrink the inference surface - ask the operator for more angles when
   an identity-defining face is uncovered.
2. **Subject**: hard-surface only. A character/creature request gets
   `request-input` recorded and an honest "out of scope" answer.
3. **Scale**: state ONE real-world dimension and its justification before any
   geometry ("handwheel diameter 0.14 m, typical DN50 valve").
4. **Look at every image first** with your own vision, before any code, and
   merge what they show into ONE part breakdown: what moves, what is fixed,
   materials in PBR terms, the identity-defining features per view, where the
   views disagree (note it - photos lie about different things), and which
   faces NO view covers - those are your inference list.

## The loop

Work from the repo root. Blender runs headless and SERIALLY - never render in
parallel, this machine is shared.

```bash
# 1. start the provenance trail (limits are mandatory - be honest; --reference
#    repeats, one view tag each; --licence/--source once for all or one each)
python3 tools/review.py init --out <dir>/<prop>.provenance.json \
    --prop <prop> --script <dir>/build-<prop>.py \
    --reference front=<ref1> --reference side=<ref2> \
    --licence "..." --source "..." --dimension "..." --seed <n> \
    --limit "rear face mirrored from the front view (no back reference)" \
    --limit "all dimensions estimated from the stated one"

# 2. emit/edit the build script (see CONVENTIONS.md section 2 for the
#    contract, the example prop for the shape), then build
python3 tools/build.py build <dir>/build-<prop>.py --out-dir <dir>/out

# 3. render the fixed review set + comparison sheet for the CURRENT pass
#    (review.py status tells you which; a back camera renders only when a
#    back reference exists)
python3 tools/build.py review --blend <dir>/out/<prop>.blend \
    --reference front=<ref1> --reference side=<ref2> \
    --out-dir <dir>/review --pass-id <pass> --attempt <n>

# 4. LOOK at the sheet (two rows: references over renders, one column per
#    view, grey where uncovered) and judge THIS PASS's criteria only - each
#    column against ITS OWN reference - then record exactly one verdict
python3 tools/review.py record <dir>/<prop>.provenance.json \
    --pass-id <pass> --sheet <sheet.png> --action <verdict> \
    --changed "..." --still-off "..." --why "..."

# 5. repeat until all five passes hold continue, then the final gate
python3 tools/review.py check <dir>/<prop>.provenance.json \
    --build-report <dir>/out/<prop>-build.json
```

Passes in order: `blockout -> structure -> form -> material -> surface`. What
each pass must achieve and what its gate judges: CONVENTIONS.md section 4.
The build script grows through the passes - the same file, refined; earlier
passes' geometry is never thrown away, only corrected.

## Judging a sheet - the rules that survive contact

- Judge the pass against its OWN criteria, not overall prettiness. A blockout
  is allowed to be grey boxes; it is not allowed to be the wrong proportions.
- **The three-quarter view is the truth serum**: silhouette matches are blind
  to flatness, edge character and material response. If front/side look right
  but three-quarter reads as a toy, the pass FAILS.
- Structural evidence beats texture confidence: a good material on a wrong
  shape is a `structure`/`form` failure, never a `continue`.
- Framing, background and lighting differ from the photo BY DESIGN - never
  fail a pass for those. Compare shape, proportion, part placement, palette,
  material class.
- A column with no reference (grey top cell) is judged for SELF-CONSISTENCY
  only - does the inferred face follow plausibly from the evidenced ones. It
  is never failed against a photo that does not show it, and never used as
  positive evidence of fidelity.
- Verdict vocabulary: `continue` (criteria met), `refine-script` (script does
  not achieve the pass - fix code), `refine-plan` (part breakdown or stated
  dimension wrong - invalidates the named pass and everything after),
  `request-input` (image cannot answer - ask the operator), `stop`.
- Every verdict records what changed, what is still off, and why the action.
  Never claim "done" for "improved". Attempt cap is 5 per pass; the cap
  forces escalation, not silent iteration.

## Finishing

- `review.py check` green is the pipeline's own gate. Engine/consumer
  acceptance is separate: import the glb the way the consuming project
  documents (its importer, its validation step), place it, look at it.
- Deliverables per prop: `build-<prop>.py` (source of truth),
  `<prop>.provenance.json` (gate trail), the reference, the final sheet;
  `.blend`/`.glb`/textures are build artifacts, reproducible from the script.
- The manual for humans: `docs/manual.md`.
