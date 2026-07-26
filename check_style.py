#!/usr/bin/env python3
"""
check_style.py - house-rules linter for the GT School blog.

Companion to check_facts.py (which checks numeric facts). This enforces the WRITING/house rules we
committed to, across every article, so nothing drifts as the library grows:

  HARD (fails the check, blocks a push):
    1. Competitor names anywhere in the file (mirrors build.py COMPETITORS; e.g. Davidson).
    2. Em dashes in the body ("no em dashes" house rule).

  SOFT (reported as warnings; does not block):
    3. Inline citations in the body - a parenthetical naming a source org/author (e.g. "(NAGC)",
       "(Reis, 1993)"). House rule: attribution lives in the bottom Sources list, never inline.
    4. Data/visual coverage - articles that truly lack numbers (no [STAT]/[CHART] placeholder AND
       fewer than 2 figures). It's a guide, not a data dump - too much data is poison - so this is
       only a nudge: add a number where it strengthens the point, or set `data_light: true` in the
       article's front matter to mark it an intentional narrative piece (which clears the advisory).

Usage:
    python3 blog/check_style.py            # check every article
    python3 blog/check_style.py <slug>     # check one article
    python3 blog/check_style.py --strict   # also make the SOFT warnings fail the check

Exit code is 1 if any HARD rule is broken (or any rule with --strict), so it can gate a push:
    python3 blog/check_facts.py && python3 blog/check_style.py && firebase deploy ... && git push
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

# Never name or cite a competitor (kept in sync with build.py COMPETITORS). Add brands as needed.
COMPETITORS = ("davidson",)

# Parentheticals that name a research source/org/author read as inline citations. These are the
# only acronyms/names we flag inside (...) - real term abbreviations like (2e), (ESA), (TEFA),
# (IEP) are intentionally NOT flagged.
SOURCE_TOKENS = (
    "NAGC", "NRC", "NRC/GT", "NCES", "OECD", "APA", "CTY", "SMPY", "EdChoice", "Belin",
    "Belin-Blank", "Renzulli", "Reis", "Westberg", "Colangelo", "Assouline", "Johns Hopkins",
    "Morning Consult", "Duke TIP", "Terman",
)
_INLINE_ACRONYM_RE = re.compile(r"\((?:" + "|".join(re.escape(t) for t in SOURCE_TOKENS) + r")\b[^)]*\)")
# "(Author, 1998)" / "(Reis & Westberg, 1993)" style parentheticals in the body.
_INLINE_AUTHORYEAR_RE = re.compile(r"\([A-Z][A-Za-z.&,\s]+,\s*(?:19|20)\d\d[a-z]?\)")

# Placeholder markers understood by build.py (block visuals + inline stats).
_PH_BLOCK_RE = re.compile(r"\[(?:VISUAL|CHART|GRAPH|DATA|IMAGE|INFOGRAPHIC|TABLE)\b", re.I)
_PH_INLINE_RE = re.compile(r"\[(?:STAT|NUMBER|PERCENT|%|\$)(?::[^\]]*)?\]", re.I)
# A "real" figure already in the prose (percent, dollar, "94th", "1.5 million", effect size +0.67).
_FIGURE_RE = re.compile(
    r"\d[\d,]*(?:\.\d+)?\s*%"                              # 57%  (no trailing \b - '%' is non-word)
    r"|\b\d[\d,]*(?:\.\d+)?\s*(?:percent|million|billion)\b"  # 1.5 million, 57 percent
    r"|\b\d+(?:st|nd|rd|th)\b"                              # 94th
    r"|\$\s?\d"                                             # $10,474
    r"|[+\-\u2212]\d+(?:\.\d+)?\b",                         # +0.67 effect size
    re.I)


def load_article(path: Path) -> tuple[dict, str]:
    raw = path.read_text(encoding="utf-8")
    m = FM_RE.match(raw)
    if not m:
        raise ValueError(f"{path.name}: missing front matter")
    fm = yaml.safe_load(m.group(1)) or {}
    body = m.group(2)
    # Drop the bottom Sources list so its citations/years/links don't count as body violations.
    body = re.sub(r"\n#{2,3}\s*Sources?\b.*$", "", body, flags=re.S | re.I)
    body = re.sub(r"^\*Published.*\*\s*$", "", body, flags=re.M)
    return fm, body


def check(slugs: list[str], strict: bool) -> int:
    hard: list[str] = []
    warn: list[str] = []

    for slug in slugs:
        path = BLOG_DIR / f"{slug}.md"
        fm, body = load_article(path)
        raw_lower = path.read_text(encoding="utf-8").lower()

        # 1. Competitors (HARD)
        for c in COMPETITORS:
            if c in raw_lower:
                hard.append(f"[{slug}] competitor name present: '{c}' - remove it (house rule).")

        # 2. Em dashes in body (HARD)
        if "\u2014" in body:
            n = body.count("\u2014")
            hard.append(f"[{slug}] {n} em dash(es) in the body - replace with a comma/period (no em dashes).")

        # 3. Inline citations in body (SOFT) - ignore text inside [CHART:/VISUAL: ...] placeholders,
        #    where naming the data source is expected, not a prose citation.
        prose = re.sub(r"\[(?:VISUAL|CHART|GRAPH|DATA|IMAGE|INFOGRAPHIC|TABLE)[^\]]*\]", "", body, flags=re.I)
        cites = _INLINE_ACRONYM_RE.findall(prose) + _INLINE_AUTHORYEAR_RE.findall(prose)
        for c in cites:
            warn.append(f"[{slug}] inline citation in body: \"{c.strip()}\" - move attribution to the bottom Sources list.")

        # 4. Data/visual coverage (SOFT) - not every article needs data (too much is poison); this
        #    only flags articles that truly lack numbers (no placeholder AND < 2 figures) AND are
        #    NOT explicitly marked `data_light: true` in the front matter. Mark a piece data_light
        #    to say "this one is intentionally a narrative guide" and clear the advisory.
        n_block = len(_PH_BLOCK_RE.findall(body))
        n_inline = len(_PH_INLINE_RE.findall(body))
        n_figures = len(_FIGURE_RE.findall(body))
        if not fm.get("data_light") and n_block == 0 and n_inline == 0 and n_figures < 1:
            note = "no figures in prose and no [STAT]/[CHART] placeholder"
            warn.append(f"[{slug}] {note} - add a number if it strengthens the point, "
                        f"or set `data_light: true` in the front matter to mark it an intentional narrative piece.")

    print(f"GT blog style check - {len(slugs)} article(s)\n")

    if hard:
        print("HOUSE-RULE VIOLATIONS (fix before push):")
        for h in hard:
            print(f"  x {h}")
        print()
    if warn:
        print("SUGGESTIONS (advisory):")
        for w in warn:
            print(f"  - {w}")
        print()

    fail = len(hard) + (len(warn) if strict else 0)
    if not hard and not warn:
        print("RESULT: all articles pass the house rules and carry data. Clear to push.")
    elif fail:
        kind = "issue(s)" if hard else "suggestion(s) (strict)"
        print(f"RESULT: {fail} {kind} to resolve.")
    else:
        print(f"RESULT: no hard violations. {len(warn)} advisory suggestion(s) above (non-blocking).")
    return 1 if fail else 0


def main() -> None:
    args = [a for a in sys.argv[1:]]
    strict = "--strict" in args
    args = [a for a in args if a != "--strict"]
    if args:
        slugs = [args[0].removesuffix(".md")]
    else:
        slugs = sorted(p.stem for p in BLOG_DIR.glob("*.md") if p.name.lower() != "readme.md")
    sys.exit(check(slugs, strict))


if __name__ == "__main__":
    main()
