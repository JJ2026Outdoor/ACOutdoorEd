#!/usr/bin/env python3
"""
check_manifest.py — Single source-of-truth check for ACOutdoorEd

Compares the three manifest files (files.json, btec.json, files3.json)
against what actually exists in the live GitHub repo, in both directions:

  1. UNDOCUMENTED: resource files that exist in the repo but aren't
     referenced by any unit in any manifest. (This is how RF42CY026 and
     HB12CY080 sat undiscovered for an unknown number of sessions.)

  2. BROKEN LINKS: files referenced by a manifest that don't actually
     exist in the repo — these 404 for a student the moment they click
     them. (This is how PS5TaskASourcePack.docx, PS9MapSkillsReference
     Sheet.docx, PS9RouteCardTemplate.docx and PS9NavigationPodcast.mp3
     were found broken.)

Zero third-party dependencies — uses only the Python standard library,
so it runs anywhere Python 3 is installed with no `pip install` needed.

USAGE
    python3 check_manifest.py

    Exit code 0  → everything is consistent
    Exit code 1  → at least one problem was found (undocumented files
                   and/or broken manifest links)

Run this at the start of any session, or any time after pushing new
files, to catch drift before a student does.
"""

import json
import re
import sys
import urllib.request
import urllib.error

REPO = "jj2026outdoor/ACOutdoorEd"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/main"
API_TREE_URL = f"https://api.github.com/repos/{REPO}/git/trees/main?recursive=1"

MANIFEST_FILES = ["files.json", "btec.json", "files3.json"]

# File types we expect to be referenced by a manifest. Anything matching
# this pattern that ISN'T in a manifest is a candidate "undocumented unit".
RESOURCE_PATTERN = re.compile(
    r"(Digital\.html|Workbook\.docx|Slides\.pptx|AnswerKey\.docx|Accessible\.docx)$"
)


def fetch_json(url):
    with urllib.request.urlopen(url, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_repo_tree():
    """Full recursive file listing of the repo's main branch via the GitHub API."""
    req = urllib.request.Request(
        API_TREE_URL, headers={"Accept": "application/vnd.github+json"}
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if "tree" not in data:
        raise RuntimeError(f"Unexpected GitHub API response: {data}")
    return {item["path"] for item in data["tree"] if item["type"] == "blob"}


def collect_manifest_files():
    """Returns (all_referenced_filenames, per_unit_map) across all three manifests."""
    referenced = set()
    unit_map = {}  # filename -> (manifest, unit_id, unit_title)
    for mf in MANIFEST_FILES:
        try:
            data = fetch_json(f"{RAW_BASE}/{mf}")
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            print(f"  ! Could not fetch {mf}: {e}")
            continue
        for unit in data.get("units", []):
            for f in unit.get("files", []):
                fname = f["filename"]
                referenced.add(fname)
                unit_map[fname] = (mf, unit.get("id", "?"), unit.get("title", "?"))
    return referenced, unit_map


def verify_live(filenames, sample_limit=None):
    """
    Double-checks a set of filenames actually return HTTP 200 from
    raw.githubusercontent.com — catches CDN/cache edge cases that a
    plain tree comparison could miss. Slower, so capped by sample_limit
    if given (None = check everything).
    """
    names = sorted(filenames)
    if sample_limit:
        names = names[:sample_limit]
    broken = []
    for name in names:
        url = f"{RAW_BASE}/{name}"
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status != 200:
                    broken.append((name, resp.status))
        except urllib.error.HTTPError as e:
            broken.append((name, e.code))
        except urllib.error.URLError as e:
            broken.append((name, str(e.reason)))
    return broken


def main():
    print(f"Checking {REPO} — manifests vs. live repo\n")

    print("Fetching manifests...")
    referenced, unit_map = collect_manifest_files()
    print(f"  {len(referenced)} unique files referenced across {len(MANIFEST_FILES)} manifests")

    print("Fetching live repo file tree...")
    try:
        repo_files = fetch_repo_tree()
    except Exception as e:
        print(f"  ! Could not fetch repo tree: {e}")
        sys.exit(2)
    print(f"  {len(repo_files)} files in repo")

    resource_files_on_repo = {f for f in repo_files if RESOURCE_PATTERN.search(f)}

    undocumented = sorted(resource_files_on_repo - referenced)
    broken_links = sorted(referenced - repo_files)

    problems_found = False

    print("\n" + "=" * 70)
    print("1. UNDOCUMENTED FILES (on repo, not referenced by any manifest)")
    print("=" * 70)
    if undocumented:
        problems_found = True
        for f in undocumented:
            print(f"  ! {f}")
        print(
            f"\n  {len(undocumented)} file(s) found. These may be complete units "
            "sitting live on the site with nobody tracking them (this is exactly "
            "how RF42CY026 and HB12CY080 were found)."
        )
    else:
        print("  None — every resource file on the repo is referenced by a manifest.")

    print("\n" + "=" * 70)
    print("2. BROKEN MANIFEST LINKS (referenced, but missing from repo)")
    print("=" * 70)
    if broken_links:
        problems_found = True
        for f in broken_links:
            manifest, unit_id, unit_title = unit_map.get(f, ("?", "?", "?"))
            print(f"  ! {f}")
            print(f"      referenced in {manifest} — unit {unit_id} ({unit_title})")
        print(
            f"\n  {len(broken_links)} file(s) found. These will 404 for a student "
            "who clicks them right now."
        )
    else:
        print("  None — every file referenced by a manifest exists on the repo.")

    print("\n" + "=" * 70)
    print("3. LIVE HTTP CHECK on manifest-referenced files (slower, thorough)")
    print("=" * 70)
    still_in_repo = referenced & repo_files
    print(f"  Checking {len(still_in_repo)} files via HTTP HEAD request...")
    http_broken = verify_live(still_in_repo)
    if http_broken:
        problems_found = True
        for name, status in http_broken:
            print(f"  ! {name} -> HTTP {status}")
    else:
        print("  All files returned HTTP 200.")

    print("\n" + "=" * 70)
    if problems_found:
        print("RESULT: Issues found — see above.")
        sys.exit(1)
    else:
        print("RESULT: Clean. Manifests and repo are fully consistent.")
        sys.exit(0)


if __name__ == "__main__":
    main()
