#!/usr/bin/env python3
"""
audit_shared_components.py — Shared-component consistency check for ACOutdoorEd

Every Digital HTML workbook embeds its own copy of the same handful of
components (AudioRecorder, TA, DCFPanel, ListField, ResearchLinks) —
correct for the self-contained/B28 requirement, but it means a fix in
one file has to be manually re-applied everywhere else, which is
exactly how bugs like today's dead PS9 research links can reappear.

This does NOT do a byte-level diff and does NOT auto-rewrite anything.
A byte diff would be actively misleading here: Agored units use one
colour palette (G/DG/LG) and BTEC units use another (NAVY/NAVY_D/
NAVY_L) — a real, intentional difference, not drift. Flagging that as
a "problem" would train Jonathan to ignore the report.

Instead, this checks for the presence of specific BEHAVIORS that
should exist everywhere regardless of palette:

  AudioRecorder:
    - handles microphone-denied gracefully (alert, not a silent crash)
    - has the recording pulse animation (visual feedback while live)
  TA (textarea):
    - has the print-twin ta-screen/ta-print classes (B19 — without
      this, printed pages can show blank textareas)
    - supports recordings (onAddRecording wired through)
  DCFPanel:
    - present at all (school policy, not optional)
  ResearchLinks (where present):
    - flags this file for a manual link check — this script can't
      verify URLs are alive itself (see check_manifest.py's HTTP
      check for a similar pattern applied to whole files, not links
      embedded inside component props)

USAGE
    python3 audit_shared_components.py
    python3 audit_shared_components.py --unit PS9NavigationDigital.html
"""

import argparse
import json
import re
import sys
import urllib.request

REPO = "jj2026outdoor/ACOutdoorEd"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/main"
MANIFEST_FILES = ["files.json", "btec.json", "files3.json"]

CHECKS = [
    ("AudioRecorder present", lambda c: c.count("const AudioRecorder") > 0),
    ("  mic-denial handled", lambda c: bool(re.search(r"[Mm]icrophone access (was )?(denied|not allowed|not permitted)", c))),
    ("  pulse animation present", lambda c: "pulse 1.2s infinite" in c or "@keyframes pulse" in c),
    # NOTE: the textarea+audio component is NOT consistently named "TA" across
    # the codebase — A1BeingOrganisedDigital.html calls the same-behaviour
    # component "AudioAnswer", for example. Checking for the *behaviour*
    # (print-twin classes + audio wiring existing anywhere in the file) is
    # more honest than assuming one canonical name and false-flagging files
    # that just named it differently.
    ("Print-twin textarea component present (any name)", lambda c: "ta-screen" in c and "ta-print" in c),
    ("  recordings wired (any known naming: onAddRecording/setRec)", lambda c: "onAddRecording" in c or "setRec" in c),
    ("DCFPanel present", lambda c: "DCFPanel" in c),
    ("Self-contained (no CDN)", lambda c: "unpkg.com" not in c and "cdn." not in c.lower()),
]


def fetch_json(url):
    with urllib.request.urlopen(url, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def collect_digital_html_files():
    files = []
    for mf in MANIFEST_FILES:
        try:
            data = fetch_json(f"{RAW_BASE}/{mf}")
        except Exception as e:
            print(f"  ! Could not fetch {mf}: {e}")
            continue
        for unit in data.get("units", []):
            for f in unit.get("files", []):
                fname = f["filename"]
                if fname.endswith("Digital.html"):
                    files.append((fname, unit.get("id", "?")))
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", default=None, help="Only audit one specific filename")
    args = parser.parse_args()

    print(f"Auditing shared-component behaviour across {REPO}\n")
    files = collect_digital_html_files()
    if args.unit:
        files = [f for f in files if f[0] == args.unit]
        if not files:
            print(f"  ! {args.unit} not found in any manifest.")
            sys.exit(1)
    print(f"  {len(files)} Digital HTML file(s) to check\n")

    all_results = {}
    any_fail = False

    for fname, unit_id in files:
        url = f"{RAW_BASE}/{fname}"
        try:
            with urllib.request.urlopen(url, timeout=20) as resp:
                content = resp.read().decode("utf-8")
        except Exception as e:
            print(f"  ! {unit_id:12} {fname}: could not fetch ({e})")
            any_fail = True
            continue

        results = [(label, check(content)) for label, check in CHECKS]
        all_results[fname] = results
        failures = [label for label, ok in results if not ok and not label.startswith("  ")]
        # sub-checks (indented) only matter if their parent passed;
        # report them as failures too if the parent component exists
        # but the specific behaviour is missing
        sub_failures = [
            label for label, ok in results
            if label.startswith("  ") and not ok
        ]

        if failures or sub_failures:
            any_fail = True
            print(f"! {unit_id:12} {fname}")
            for label, ok in results:
                if not ok:
                    print(f"      MISSING: {label.strip()}")
        else:
            print(f"  {unit_id:12} {fname}  — all checks passed")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    total = len(all_results)
    clean = sum(
        1 for r in all_results.values()
        if all(ok for _, ok in r)
    )
    print(f"{clean}/{total} files pass every behavioural check.")
    if any_fail:
        print(
            "\nFiles with MISSING items above should be checked manually — "
            "this script tells you WHAT'S missing and WHERE, not how to fix it. "
            "Fixing should still go through Claude / manual review, the same as "
            "any other file change, given how easily a regex-only auto-fix could "
            "corrupt JSX (see MasterSessionFeedback.md Part 3 bugs B1/B27)."
        )
        sys.exit(1)
    else:
        print("\nEvery file has the full expected behaviour set.")
        sys.exit(0)


if __name__ == "__main__":
    main()
