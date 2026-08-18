# silentfuture.img2blend

Turn one or more licence-clean reference images of a hard-surface prop into
an engine-ready 3D asset: the pipeline emits a **deterministic Blender Python
build script** (the source of truth), runs it through headless Blender, and
gates the result with a staged vision-review loop
(`blockout -> structure -> form -> material -> surface`). Export is guarded
by an asset contract - the build fails rather than shipping a violation.

Ported from the `silentfuture.hive-engine` toolchain and decoupled from any
engine: the GLB output plus build report is generic; consumers document their
own import/acceptance step.

## Requirements

- Blender 4.2+ (the example prop builds verified end-to-end on 5.2 LTS:
  full build incl. bakes and guarded GLB export, review renders, provenance
  check). Discovery order: `SF_BLENDER` env var, the macOS app bundle
  (`/Applications/Blender.app`), `blender` on PATH.
- Python 3 for the runner and review tooling (`review.py` is pure stdlib;
  the bpy stages use Blender's bundled Python incl. numpy).

## Quick start

```bash
# provenance first (limits are mandatory - be honest)
python3 tools/review.py init --out work/<prop>.provenance.json \
    --prop <prop> --script work/build-<prop>.py \
    --reference front=<ref.jpg> --licence "..." --source "..." \
    --dimension "..." --seed 7 --limit "..."

# build (emits .blend, contract-guarded .glb, build report)
python3 tools/build.py build work/build-<prop>.py --out-dir work/out

# render the fixed review set + comparison sheet for the current pass
python3 tools/build.py review --blend work/out/<prop>.blend \
    --reference front=<ref.jpg> --out-dir work/review \
    --pass-id blockout --attempt 1

# record exactly one verdict per review; final gate:
python3 tools/review.py check work/<prop>.provenance.json \
    --build-report work/out/<prop>-build.json
```

Full contract and workflow: `tools/CONVENTIONS.md`, human manual in
`docs/manual.md`, agent skill in `.claude/skills/img2blend/`.

## Test gate

```bash
python3 tools/build.py guards   # headless export-guard tests (see docs/export-guards.md)
```

## Lineage and licence

Methodology adapted from
[img2threejs](https://github.com/img2threejs/img2threejs) (Apache License
2.0) - staged passes, review gates, self-correction vocabulary and honesty
rules; re-targeted to emit bpy build scripts. No source code was copied.
The export-guard discipline generalizes SilentFuture's earlier converter
contracts.

## Repo family conventions

Source of truth on Forgejo (`schemann/silentfuture.img2blend`, agent-primary)
with a GitHub twin (`SilentFuture/silentfuture.img2blend`) - push BOTH on
every commit. Work runs through orboto project `SFIB`.
