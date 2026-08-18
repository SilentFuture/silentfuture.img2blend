#!/usr/bin/env python3
# img2blend runner. Drives the two bpy stages headless with this
# directory on sys.path (so emitted scripts can `import bakekit`) and
# --factory-startup (so user preferences can never make a build
# irreproducible).
#
#   python3 tools/build.py build <prop-script.py> --out-dir <dir>
#   python3 tools/build.py review --blend <prop.blend> \
#       --reference <ref.img> --out-dir <dir> --pass-id <pass> --attempt <n>
#
# Blender discovery: $SF_BLENDER, then the macOS app bundle, then PATH.
# Builds and renders run SERIALLY by design - this machine is shared.

import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def find_blender():
    candidates = [
        os.environ.get("SF_BLENDER"),
        "/Applications/Blender.app/Contents/MacOS/Blender",
        shutil.which("blender"),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    sys.exit("img2blend: no Blender found - set SF_BLENDER or install Blender")


def run_bpy(script, script_args):
    # Blender ignores PYTHONPATH unless --python-use-system-env is set; a
    # sys.path bootstrap keeps the build isolated from user site-packages
    # instead. Expressions and scripts execute in argument order.
    bootstrap = f"import sys; sys.path.insert(0, {HERE!r})"
    cmd = [
        find_blender(),
        "--background",
        "--factory-startup",
        "--python-exit-code",
        "1",
        "--python-expr",
        bootstrap,
        "--python",
        script,
        "--",
        *script_args,
    ]
    return subprocess.run(cmd).returncode


def main():
    parser = argparse.ArgumentParser(description="img2blend headless runner")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("build", help="run an emitted prop build script (the source of truth)")
    p.add_argument("script")
    p.add_argument("--out-dir", required=True, help="artifact directory (.blend, .glb, report)")

    sub.add_parser("guards", help="run the headless export-guard tests (docs/export-guards.md)")

    p = sub.add_parser("review", help="render the fixed camera set + comparison sheet")
    p.add_argument("--blend", required=True)
    p.add_argument(
        "--reference",
        action="append",
        default=[],
        metavar="VIEW=PATH",
        help="repeatable; view is front|side|back|three-quarter|detail",
    )
    p.add_argument("--out-dir", required=True)
    p.add_argument("--pass-id", required=True)
    p.add_argument("--attempt", type=int, required=True)

    args = parser.parse_args()
    if args.cmd == "guards":
        code = run_bpy(
            os.path.join(os.path.dirname(HERE), "tests", "run_guard_tests.py"), []
        )
    elif args.cmd == "build":
        if not os.path.exists(args.script):
            sys.exit(f"img2blend: {args.script} does not exist")
        code = run_bpy(
            os.path.abspath(args.script), ["--out-dir", os.path.abspath(args.out_dir)]
        )
    else:
        if not args.reference:
            sys.exit("img2blend: at least one --reference view=path is required")
        ref_args = []
        for spec in args.reference:
            view, sep, path = spec.partition("=")
            if not sep:
                sys.exit(f"img2blend: reference {spec!r} must be view=path")
            ref_args += ["--reference", f"{view}={os.path.abspath(path)}"]
        code = run_bpy(
            os.path.join(HERE, "render_review.py"),
            [
                "--blend",
                os.path.abspath(args.blend),
                *ref_args,
                "--out-dir",
                os.path.abspath(args.out_dir),
                "--pass-id",
                args.pass_id,
                "--attempt",
                str(args.attempt),
            ],
        )
    sys.exit(code)


if __name__ == "__main__":
    main()
