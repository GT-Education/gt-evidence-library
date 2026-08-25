#!/usr/bin/env python3
"""Report every open [NEEDS-FACT] in the library.

A [NEEDS-FACT: ...] marker is a question GT has not answered yet, written into a draft so the
article can be finished the moment the fact lands. This script is the to-do list: run it to see
exactly which facts are still outstanding and which articles are waiting on them.

    python3 check_gaps.py            # every open fact, grouped by article
    python3 check_gaps.py --slugs    # just the blocked slugs, one per line

Advisory only, so it never blocks a push. The real gate lives in check_style.py, which hard-fails
if a [NEEDS-FACT] survives into a `status: ready` article.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("Missing dependency: pip install pyyaml")

BLOG_DIR = Path(__file__).resolve().parent
FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.S)
NF_RE = re.compile(r"\[NEEDS-FACT\s*:?\s*([^\]]*)\]", re.I)


def main() -> int:
    slugs_only = "--slugs" in sys.argv
    blocked: list[tuple[str, str, list[str]]] = []

    for path in sorted(BLOG_DIR.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        m = FM_RE.match(path.read_text(encoding="utf-8"))
        if not m:
            continue
        fm = yaml.safe_load(m.group(1)) or {}
        facts = [f.strip() for f in NF_RE.findall(m.group(2))]
        if facts:
            blocked.append((fm.get("slug", path.stem), fm.get("title", path.stem), facts))

    if slugs_only:
        for slug, _t, _f in blocked:
            print(slug)
        return 0

    total = sum(len(f) for _s, _t, f in blocked)
    print(f"Open facts - {total} question(s) across {len(blocked)} article(s)\n")
    if not blocked:
        print("Nothing outstanding. Every article is fully sourced.")
        return 0

    for slug, title, facts in blocked:
        print(f"  {title}")
        print(f"  {slug}.md")
        for f in facts:
            print(f"    [ ] {f}")
        print()

    print("Fill the answer in the .md, delete the [NEEDS-FACT: ...] line, add the article to a")
    print("LIBRARY_GROUP in build.py, then rebuild. Until then it stays off the home page.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
