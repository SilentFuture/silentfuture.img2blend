#!/usr/bin/env python3
# img2blend review gate + provenance trail. Pure Python 3 stdlib,
# no Blender - this is the host-side state machine that makes the staged
# passes LOCKED and the gate trail the provenance.
#
# Methodology adapted from img2threejs
# (https://github.com/img2threejs/img2threejs, Apache License 2.0): the locked
# pass order, the one-action self-correction vocabulary and the bounded
# correction loop are their design, re-targeted at bpy-script emission. No
# source code was copied.
#
#   review.py init   --out valve.provenance.json --prop valve --script ... \
#                    --reference front=ref-front.jpg [--reference side=... ...] \
#                    --licence "CC0 ..." --source "..." \
#                    --dimension "handwheel diameter = 0.14 m (typical DN50)" \
#                    --seed 7 --limit "rear face mirrored from front" ...
#
# References are TAGGED WITH A VIEW (front|side|back|three-quarter|detail) so
# the gates can compare each fixed-camera render against ITS reference view.
# --licence/--source are given once (applies to every reference) or once per
# reference in the same order. Views no reference covers are the ONLY faces
# unseen-face inference may apply to - init records the evidenced/inferred
# coverage split so the provenance states it per face.
#   review.py status <provenance.json>
#   review.py record <provenance.json> --pass-id blockout --sheet <sheet.png> \
#                    --action continue|refine-script|refine-plan|request-input|stop \
#                    --changed "..." --still-off "..." --why "..." \
#                    [--renders a.png b.png c.png] [--invalidates <pass>]
#   review.py check  <provenance.json> --build-report <prop>-build.json
#
# Scripts enforce, the agent judges: nothing here scores an image. What it
# does enforce: pass order, one verdict vocabulary, evidence files that exist,
# a bounded number of attempts per pass (the img2threejs token-burn lesson -
# the loop must terminate in an escalation, never burn silently).

import argparse
import datetime
import json
import os
import sys

PASSES = ["blockout", "structure", "form", "material", "surface"]
ACTIONS = ["continue", "refine-script", "refine-plan", "request-input", "stop"]
VIEWS = ["front", "side", "back", "three-quarter", "detail"]
# The canonical faces a reference can evidence; "detail" evidences none.
COVERAGE_VIEWS = ["front", "side", "back", "three-quarter"]
MAX_ATTEMPTS = 5
SCHEMA = "img2blend/1"


def die(message):
    print(f"review: FAILED - {message}")
    sys.exit(1)


def load(path):
    if not os.path.exists(path):
        die(f"{path} does not exist - run init first")
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if data.get("schema") != SCHEMA:
        die(f"{path} is not an {SCHEMA} provenance file")
    return data


def save(path, data):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")


def pass_state(gates):
    """Replay the trail: which passes currently hold a continue verdict, and
    whether the run is halted. A refine-plan entry invalidates its own pass
    and every later one (the plan changed under them); --invalidates widens
    that back to an earlier pass."""
    passed = set()
    halted = None
    for entry in gates:
        idx = PASSES.index(entry["pass"])
        if entry["action"] == "continue":
            passed.add(entry["pass"])
        elif entry["action"] == "refine-plan":
            from_idx = PASSES.index(entry.get("invalidates") or entry["pass"])
            passed = {p for p in passed if PASSES.index(p) < min(idx, from_idx)}
        elif entry["action"] in ("request-input", "stop"):
            halted = entry["action"]
    current = next((p for p in PASSES if p not in passed), None)
    return passed, current, halted


def attempts_for(gates, pass_id):
    """Attempts since the pass last lost (or never had) its verdict."""
    count = 0
    for entry in gates:
        if entry["pass"] == pass_id:
            count += 1
        elif entry["action"] == "refine-plan":
            from_idx = PASSES.index(entry.get("invalidates") or entry["pass"])
            if PASSES.index(pass_id) >= from_idx:
                count = 0
    return count


def parse_references(args, base):
    """--reference view=path, repeated. Licence/source: one for all, or one
    per reference in order - anything else is refused, never guessed."""
    if not args.reference:
        die("at least one --reference view=path is required")
    for flag, values in (("--licence", args.licence), ("--source", args.source)):
        if len(values) not in (1, len(args.reference)):
            die(f"{flag} must be given once (for all references) or once per reference")
    refs = []
    for i, spec in enumerate(args.reference):
        view, sep, path = spec.partition("=")
        if not sep or view not in VIEWS:
            die(f"reference {spec!r} must be view=path with view one of {VIEWS}")
        if not os.path.exists(path):
            die(f"reference {path} does not exist")
        refs.append(
            {
                "path": os.path.relpath(os.path.abspath(path), base),
                "view": view,
                "licence": args.licence[i] if len(args.licence) > 1 else args.licence[0],
                "source": args.source[i] if len(args.source) > 1 else args.source[0],
            }
        )
    return refs


def cmd_init(args):
    if os.path.exists(args.out) and not args.force:
        die(f"{args.out} already exists - a provenance trail is never overwritten silently")
    if not args.limit:
        die("at least one --limit is required - even with full view coverage, scale and material response are inferred")
    base = os.path.dirname(os.path.abspath(args.out))
    references = parse_references(args, base)
    evidenced = sorted({r["view"] for r in references if r["view"] in COVERAGE_VIEWS})
    inferred = [v for v in COVERAGE_VIEWS if v not in evidenced]
    data = {
        "schema": SCHEMA,
        "prop": args.prop,
        "pipeline": "img2blend v1 (silentfuture.img2blend), methodology adapted from img2threejs (Apache-2.0)",
        "references": references,
        "coverage": {"evidenced_views": evidenced, "inferred_views": inferred},
        "stated_dimension": args.dimension,
        "seed": args.seed,
        "build_script": args.script,
        "limits": args.limit,
        "gates": [],
    }
    save(args.out, data)
    print(
        f"review: initialized {args.out} with {len(references)} reference(s); "
        f"evidenced views {evidenced or 'none'}, inferred views {inferred or 'none'}; "
        f"first pass is '{PASSES[0]}'"
    )


def cmd_status(args):
    data = load(args.provenance)
    passed, current, halted = pass_state(data["gates"])
    for p in PASSES:
        state = "passed" if p in passed else ("CURRENT" if p == current else "locked")
        print(f"  {p:10s} {state}  (attempts: {attempts_for(data['gates'], p)})")
    if halted:
        print(f"review: run is HALTED ({halted}) - operator input decides what happens next")
    elif current is None:
        print("review: all passes hold a continue verdict - run 'review.py check' for the final gate")
    else:
        print(f"review: current pass is '{current}'")


def cmd_record(args):
    data = load(args.provenance)
    passed, current, halted = pass_state(data["gates"])
    if halted:
        die(f"run is halted ({halted}) - a halted trail takes no further verdicts")
    if current is None:
        die("all passes already hold a continue verdict - nothing left to record")
    if args.pass_id != current:
        die(f"current pass is '{current}', not '{args.pass_id}' - passes are locked in order")
    if args.action not in ACTIONS:
        die(f"action must be one of {ACTIONS}")
    if not os.path.exists(args.sheet):
        die(f"comparison sheet {args.sheet} does not exist - no sheet, no verdict")
    for render in args.renders or []:
        if not os.path.exists(render):
            die(f"render {render} does not exist")
    if args.invalidates and args.invalidates not in PASSES:
        die(f"--invalidates must name one of {PASSES}")
    if args.invalidates and args.action != "refine-plan":
        die("--invalidates only makes sense with action refine-plan")

    attempt = attempts_for(data["gates"], args.pass_id) + 1
    if attempt > MAX_ATTEMPTS and args.action not in ("request-input", "stop"):
        die(
            f"pass '{args.pass_id}' is at attempt {attempt} (cap {MAX_ATTEMPTS}) - the loop must "
            "terminate: escalate with request-input or stop instead of iterating blind"
        )

    base = os.path.dirname(os.path.abspath(args.provenance))
    entry = {
        "pass": args.pass_id,
        "attempt": attempt,
        "action": args.action,
        "sheet": os.path.relpath(os.path.abspath(args.sheet), base),
        "renders": [os.path.relpath(os.path.abspath(r), base) for r in args.renders or []],
        "changed": args.changed,
        "still_off": args.still_off,
        "why": args.why,
        "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    }
    if args.invalidates:
        entry["invalidates"] = args.invalidates
    data["gates"].append(entry)
    save(args.provenance, data)
    passed, current, halted = pass_state(data["gates"])
    nxt = f"next pass '{current}'" if current else "all passes passed"
    print(f"review: recorded {args.pass_id} attempt {attempt} -> {args.action}; {nxt}")


def cmd_check(args):
    data = load(args.provenance)
    passed, current, halted = pass_state(data["gates"])
    problems = []
    if halted:
        problems.append(f"run is halted ({halted})")
    if current is not None:
        problems.append(f"pass '{current}' has no continue verdict")
    if not data.get("limits"):
        problems.append("limits list is empty - reconstruction honesty is mandatory")
    base_dir = os.path.dirname(os.path.abspath(args.provenance))
    for ref in data["references"]:
        if not ref.get("licence"):
            problems.append(f"reference {ref['path']} has no licence recorded")
        if not os.path.exists(os.path.join(base_dir, ref["path"])):
            problems.append(f"reference {ref['path']} is missing on disk")
    # The sheet is the JUDGED evidence and must survive; the per-view renders
    # are working copies (the sheet embeds them) and may be cleaned up.
    warnings = []
    for entry in data["gates"]:
        if not os.path.exists(os.path.join(base_dir, entry["sheet"])):
            problems.append(f"gate evidence {entry['sheet']} is missing on disk")
        for path in entry["renders"]:
            if not os.path.exists(os.path.join(base_dir, path)):
                warnings.append(f"per-view render {path} is not on disk (sheet evidence intact)")
    if not os.path.exists(args.build_report):
        problems.append(f"build report {args.build_report} does not exist - has the final build run?")
    else:
        with open(args.build_report, encoding="utf-8") as handle:
            report = json.load(handle)
        if report.get("prop") != data["prop"]:
            problems.append("build report prop does not match the provenance")
        if report.get("seed") != data["seed"]:
            problems.append(
                f"build report seed {report.get('seed')} differs from provenance seed {data['seed']}"
            )
    for w in warnings:
        print(f"review: warning - {w}")
    if problems:
        for p in problems:
            print(f"review: FAIL - {p}")
        sys.exit(1)
    corrections = sum(1 for e in data["gates"] if e["action"] != "continue")
    print(
        f"review: PASS - {len(data['gates'])} gate verdicts, {corrections} self-correction(s), "
        f"all {len(PASSES)} passes hold continue, evidence on disk, build report consistent"
    )


def main():
    parser = argparse.ArgumentParser(description="img2blend gate trail")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init")
    p.add_argument("--out", required=True)
    p.add_argument("--prop", required=True)
    p.add_argument("--script", required=True)
    p.add_argument("--reference", action="append", default=[], metavar="VIEW=PATH")
    p.add_argument("--licence", action="append", default=[], required=True)
    p.add_argument("--source", action="append", default=[], required=True)
    p.add_argument("--dimension", required=True)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--limit", action="append", default=[])
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("status")
    p.add_argument("provenance")

    p = sub.add_parser("record")
    p.add_argument("provenance")
    p.add_argument("--pass-id", required=True, choices=PASSES)
    p.add_argument("--sheet", required=True)
    p.add_argument("--action", required=True, choices=ACTIONS)
    p.add_argument("--changed", required=True)
    p.add_argument("--still-off", required=True)
    p.add_argument("--why", required=True)
    p.add_argument("--renders", nargs="*")
    p.add_argument("--invalidates")

    p = sub.add_parser("check")
    p.add_argument("provenance")
    p.add_argument("--build-report", required=True)

    args = parser.parse_args()
    {"init": cmd_init, "status": cmd_status, "record": cmd_record, "check": cmd_check}[args.cmd](args)


if __name__ == "__main__":
    main()
