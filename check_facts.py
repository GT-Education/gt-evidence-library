#!/usr/bin/env python3
"""
check_facts.py - pre-push content-integrity check for the GT School blog.

Catches CONFLICTING information before articles ship:
  1. A numeric fact stated differently from the vetted canonical value (from source-library.md).
  2. The same recurring fact stated inconsistently across two or more articles.
  3. Competitor names (mirrors the build.py COMPETITORS guard).

For every conflict it prints the vetted value, the source, and how to resolve it. This is the
automated "safety net": extend CANONICAL_FACTS as the library grows.

Usage:
    python3 blog/check_facts.py            # check every article
    python3 blog/check_facts.py <slug>     # check one article

Exit code is 1 if any conflict is found, so it can gate a deploy/push:
    python3 blog/check_facts.py && firebase deploy ... && git push ...
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

# Competitors that must never appear (kept in sync with build.py COMPETITORS).
COMPETITORS = ("davidson",)

# --- Canonical facts -------------------------------------------------------------------------------
# The vetted value for each recurring claim, its primary source, and how to resolve a conflict.
# A sentence is flagged as a CONFLICT when it (a) is about the fact's topic (matches a `trigger`),
# (b) states a value of the same kind (matches `present`), yet (c) does NOT state the correct value
# (`correct`). That catches both a single wrong article and two articles that disagree, because
# every article is measured against the same canonical value. Add new facts here as needed.
CANONICAL_FACTS = [
    {
        "id": "compacting_curriculum_pct",
        "topic": "Curriculum compacting: share of regular curriculum that can be eliminated",
        "triggers": [r"curriculum[^.]{0,80}(?:compact|eliminat|remov|cut)",
                     r"(?:compact|eliminat|remov|cut)\w*[^.]{0,80}curriculum"],
        "present": r"\d{1,3}\s*(?:%|percent)",
        "correct": r"40\s*(?:to|and|[-\u2013\u2014])\s*50\s*(?:%|percent)",
        "value": "40 to 50%",
        "source": "NRC/GT, The Curriculum Compacting Study (1993)",
    },
    {
        "id": "compacting_readers_pct",
        "topic": "Compacting: share of strong readers who passed pretests before instruction",
        "triggers": [r"before (?:those|the) skills (?:were|are)(?: ever)? taught",
                     r"passed (?:a |the )?(?:pre-?tests?|tests on skills)"],
        "present": r"\d{1,3}\s*(?:%|percent)",
        "correct": r"78\s*(?:to|and|[-\u2013\u2014])\s*88\s*(?:%|percent)",
        "value": "78 to 88%",
        "source": "NRC/GT, The Curriculum Compacting Study (1993)",
    },
    {
        "id": "acceleration_forms",
        "topic": "Number of recognized forms of acceleration",
        "triggers": [r"forms of acceleration", r"acceleration[^.]{0,40}\bforms\b",
                     r"\bforms\b[^.]{0,40}acceleration"],
        "present": r"\b(?:\d{1,3}|ten|twelve|fifteen|twenty|thirty|dozen)\b",
        "correct": r"\b(?:20|twenty)\b",
        "value": "about twenty",
        "source": "Belin-Blank Center, A Nation Empowered (2015)",
    },
    {
        "id": "tefa_award",
        "topic": "Texas Education Freedom Account (TEFA) 2026-27 award per student",
        # Only fire when the sentence actually asserts the award AMOUNT (a $ adjacent to "award"),
        # not when it merely mentions "the award" while quoting tuition.
        "triggers": [r"award\b[^.]{0,15}\$\s?\d", r"\$\s?[\d,]+[^.]{0,12}\baward\b",
                     r"award (?:is|of|amount|will be|=|:)"],
        "present": r"\$\s?\d[\d,]{2,}",
        "correct": r"\$?10,?474",
        "value": "$10,474 (2026-27)",
        "source": "Texas Education Freedom Account (official)",
    },
    {
        "id": "gt_anywhere_tuition",
        "topic": "GT Anywhere online tuition (GT-reported)",
        "triggers": [r"GT Anywhere[^.]{0,60}(?:tuition|\$|priced|10,?400)",
                     r"(?:tuition|priced)[^.]{0,40}GT Anywhere"],
        "present": r"\$\s?\d[\d,]{2,}",
        "correct": r"\$?10,?400",
        "value": "$10,400/yr",
        "source": "GT School / GT Anywhere (reported by GT)",
    },
    {
        "id": "gt_inperson_tuition",
        "topic": "GT School in-person day-school tuition (GT-reported)",
        "triggers": [r"in-person[^.]{0,50}(?:tuition|\$|25,?000)",
                     r"day school[^.]{0,40}\$", r"\$25,?000"],
        "present": r"\$\s?\d[\d,]{2,}",
        "correct": r"\$?25,?000",
        "value": "$25,000/yr",
        "source": "GT School (reported by GT)",
    },
    {
        "id": "worries_survey_n",
        "topic": "'What Worries Parents' survey sample size",
        "triggers": [r"survey of [\d,]+ parents", r"[\d,]+ parents of gifted"],
        "present": r"\b\d{2,4}\s+parents\b",
        "correct": r"\b847\s+parents\b",
        "value": "847 parents",
        "source": "Post & Fedor, What Worries Parents (Gifted Development Center)",
    },
    {
        "id": "edchoice_data_over_opinion",
        "topic": "Parents choosing hard data over a trusted person's negative opinion",
        "triggers": [r"trusted person", r"negative opinion", r"strong data even over"],
        "present": r"\d{1,3}\s*%",
        "correct": r"57\s*%",
        "value": "57%",
        "source": "EdChoice / Morning Consult (2024)",
    },
    {
        "id": "gt_national_percentiles",
        "topic": "GT-reported national percentile averages",
        "triggers": [r"national percentile"],
        "present": r"\d{1,3}(?:st|nd|rd|th)?\s*(?:to|[-\u2013\u2014])\s*\d{1,3}(?:st|nd|rd|th)?",
        "correct": r"94(?:th)?\s*(?:to|[-\u2013\u2014])\s*98(?:th)?",
        "value": "94th to 98th",
        "source": "GT School (reported by GT)",
    },
    {
        "id": "school_choice_students",
        "topic": "National private school-choice participation",
        "triggers": [r"school-choice", r"private (?:school[- ])?choice", r"choice programs"],
        "present": r"\b\d[\d.,]*\s*million\b",
        "correct": r"1\.5\s*million",
        "value": "more than 1.5 million students",
        "source": "EdChoice, The ABCs of School Choice (2026)",
    },
]


def load_article(path: Path) -> tuple[dict, str]:
    raw = path.read_text(encoding="utf-8")
    m = FM_RE.match(raw)
    if not m:
        raise ValueError(f"{path.name}: missing front matter")
    fm = yaml.safe_load(m.group(1)) or {}
    body = m.group(2)
    # Drop the end Sources list (citation years/pages would create false positives) and the
    # (stripped-at-build) *Published...* line; keep the visible prose + on-page FAQ.
    body = re.sub(r"\n#{2,3}\s*Sources?\b.*$", "", body, flags=re.S | re.I)
    body = re.sub(r"^\*Published.*\*\s*$", "", body, flags=re.M)
    return fm, body


def units(body: str):
    """Yield sentence-like chunks, one per line/bullet then split on sentence enders, so a claim in
    one bullet can't accidentally match a number in the next."""
    for line in body.split("\n"):
        line = line.strip().lstrip("-*# \t").strip()
        if not line:
            continue
        for s in re.split(r"(?<=[.!?:;])\s+", line):
            s = s.strip()
            if s:
                yield s


def search_any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


def check(slugs: list[str]) -> int:
    conflicts: list[dict] = []
    competitor_hits: list[tuple[str, str]] = []
    references: dict[str, set[str]] = {f["id"]: set() for f in CANONICAL_FACTS}

    for slug in slugs:
        path = BLOG_DIR / f"{slug}.md"
        fm, body = load_article(path)
        raw_lower = path.read_text(encoding="utf-8").lower()
        for c in COMPETITORS:
            if c in raw_lower:
                competitor_hits.append((slug, c))

        for sentence in units(body):
            for fact in CANONICAL_FACTS:
                if not search_any(fact["triggers"], sentence):
                    continue
                if re.search(fact["correct"], sentence, re.I):
                    references[fact["id"]].add(slug)
                elif re.search(fact["present"], sentence, re.I):
                    conflicts.append({"slug": slug, "fact": fact, "sentence": sentence})

    # --- Report ------------------------------------------------------------------------------------
    print(f"GT blog fact check - {len(slugs)} article(s)\n")

    if competitor_hits:
        print("COMPETITOR MENTIONS (remove before push):")
        for slug, c in competitor_hits:
            print(f"  x {slug}: '{c}'")
        print()

    if conflicts:
        print("CONFLICTS (a claim disagrees with the vetted value):")
        for c in conflicts:
            f = c["fact"]
            snippet = c["sentence"]
            snippet = (snippet[:150] + "...") if len(snippet) > 150 else snippet
            print(f"  x [{c['slug']}] {f['topic']}")
            print(f"      claim   : \"{snippet}\"")
            print(f"      vetted  : {f['value']}  ({f['source']})")
            print(f"      resolve : state it as \"{f['value']}\" per {f['source']}, "
                  f"or, if a newer credible source disagrees, update source-library.md and this fact.")
            print()

    used = {fid: sorted(s) for fid, s in references.items() if s}
    if used:
        print("Consistent facts across the library:")
        for f in CANONICAL_FACTS:
            slugs_used = used.get(f["id"])
            if slugs_used:
                print(f"  ok {f['value']:<26} {f['topic']}  ({len(slugs_used)} article(s))")
        print()

    total = len(conflicts) + len(competitor_hits)
    if total:
        print(f"RESULT: {total} issue(s) found. Resolve before pushing.")
        return 1
    print("RESULT: no conflicts found. Clear to push.")
    return 0


def main() -> None:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    if only:
        slugs = [only.removesuffix(".md")]
    else:
        slugs = sorted(p.stem for p in BLOG_DIR.glob("*.md") if p.name.lower() != "readme.md")
    sys.exit(check(slugs))


if __name__ == "__main__":
    main()
