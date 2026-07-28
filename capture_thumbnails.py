#!/usr/bin/env python3
"""
capture_thumbnails.py — Visual-regression thumbnail check for ACOutdoorEd

Renders the Cover section of every Digital HTML workbook on the live
repo in a real headless browser and saves a screenshot, so Jonathan can
scan a folder of images instead of opening 20+ files by hand.

This does NOT replace a proper visual QA pass (it only captures one
section — the Cover, which is what loads by default), but it catches
the class of bug that jsdom verification structurally cannot:
  - blank/broken renders that still "mount" (jsdom only checks that
    #root gets *some* children, not that the render is correct)
  - obviously wrong layout, missing images, broken logo embeds
  - CSS that fails outside jsdom's limited style engine

REQUIRES: Playwright with a Chromium binary installed.
    pip install playwright --break-system-packages
    playwright install chromium

USAGE
    python3 capture_thumbnails.py
    python3 capture_thumbnails.py --out ./thumbnails
    python3 capture_thumbnails.py --unit PS9NavigationDigital.html

Screenshots are saved as PNG, one per unit, named after the source
filename. Run it, then just open the output folder and scroll through
— far faster than opening each file individually.
"""

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

REPO = "jj2026outdoor/ACOutdoorEd"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/main"
PAGES_BASE = "https://jj2026outdoor.github.io/ACOutdoorEd"
MANIFEST_FILES = ["files.json", "btec.json", "files3.json"]


def fetch_json(url):
    with urllib.request.urlopen(url, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def collect_digital_html_files():
    """Every *Digital.html file referenced across all three manifests."""
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
                    files.append((fname, unit.get("id", "?"), unit.get("title", "?")))
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="./thumbnails", help="Output directory for screenshots")
    parser.add_argument("--unit", default=None, help="Only capture one specific filename")
    parser.add_argument("--width", type=int, default=1280, help="Viewport width")
    parser.add_argument("--height", type=int, default=900, help="Viewport height")
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is not installed. Run:")
        print("    pip install playwright --break-system-packages")
        print("    playwright install chromium")
        sys.exit(2)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Fetching manifests for the list of Digital HTML files...")
    files = collect_digital_html_files()
    if args.unit:
        files = [f for f in files if f[0] == args.unit]
        if not files:
            print(f"  ! {args.unit} not found in any manifest.")
            sys.exit(1)
    print(f"  {len(files)} Digital HTML file(s) to capture\n")

    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch()

        for fname, unit_id, unit_title in files:
            # A fresh page per file is deliberate, not incidental: each
            # workbook's compiled script declares top-level `const`s (NAVY,
            # G, DG, ...). Reusing one page across set_content() calls left
            # enough of the previous document's JS realm in place that the
            # second and subsequent files threw "already declared" errors
            # and silently failed to mount — caught during testing, when
            # every file failed except the first.
            page = browser.new_page(viewport={"width": args.width, "height": args.height})
            # raw.githubusercontent.com serves .html as text/plain (with
            # X-Content-Type-Options: nosniff), so a normal page.goto()
            # against it won't execute the scripts — the browser just shows
            # source text. And the real GitHub Pages domain may not be
            # reachable from every environment this script runs in. Fetching
            # the raw bytes ourselves and injecting via set_content() sidesteps
            # both problems: Playwright parses and executes the HTML/JS
            # regardless of what Content-Type the original request would have had.
            raw_url = f"{RAW_BASE}/{fname}"
            out_path = out_dir / fname.replace(".html", ".png")
            print(f"  {unit_id:12} {fname}")
            try:
                with urllib.request.urlopen(raw_url, timeout=20) as resp:
                    html_content = resp.read().decode("utf-8")
                page.set_content(html_content, wait_until="networkidle", timeout=30000)
                # Give React a moment to finish its render pass beyond "networkidle"
                page.wait_for_timeout(500)
                root_children = page.evaluate(
                    "document.getElementById('root') ? document.getElementById('root').children.length : -1"
                )
                page.screenshot(path=str(out_path))
                status = "OK" if root_children > 0 else "!! #root EMPTY — likely blank page"
                results.append((fname, unit_id, unit_title, status))
                print(f"      -> {out_path.name}  [{status}]")
            except Exception as e:
                results.append((fname, unit_id, unit_title, f"!! ERROR: {e}"))
                print(f"      -> FAILED: {e}")
            finally:
                page.close()

        browser.close()

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    problems = [r for r in results if not r[3] == "OK"]
    for fname, unit_id, unit_title, status in results:
        marker = "  " if status == "OK" else "! "
        print(f"{marker}{unit_id:12} {fname:45} {status}")

    print(f"\n{len(results) - len(problems)}/{len(results)} captured cleanly.")
    print(f"Screenshots saved to: {out_dir.resolve()}")
    if problems:
        print(f"\n{len(problems)} file(s) need attention — see markers above.")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
