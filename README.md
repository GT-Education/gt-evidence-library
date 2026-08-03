# GT School Blog — draft library

> **Live site (view it now): https://gt-school-blog.web.app** — the full library is deployed here on Firebase Hosting.

This folder is where GT School blog / FAQ articles are **drafted** before they're transferred to the gt.school website. It's the "evidence library" / "Ceiling Report" from the Marketing-Direction BrainLift: a growing set of primary-source-cited pages that answer gifted parents' specific questions and get GT cited by AI answer engines.

## Why draft here (Markdown-first)
- **Portable & consistent:** plain Markdown + YAML front matter converts cleanly into any CMS (Webflow, WordPress, Framer, Ghost, a static site, etc.). Nothing is locked to a tool.
- **Version-controlled & reviewable:** every article is a text file you can diff, edit, and track.
- **GEO metadata travels:** each file's front matter carries the dates, FAQ pairs, schema types, and sources the site needs to emit **semantic HTML + JSON-LD** — the signals that drive AI citations. See the skill's `geo-checklist.md`.

## How to write a new article
Use the **`gt-school-blog` skill** (in `.cursor/skills/gt-school-blog/`). Just ask, e.g.:
> "Use the gt-school-blog skill to draft an article answering: *Can I use my Texas TEFA voucher for an online gifted school?*"

The skill loads the shared voice guide, archetypes, source library, and GEO checklist so every article comes out in the same voice and format. Copy `article-template.md` for the skeleton.

## Conventions
- **One file per article:** `blog/<slug>.md`, filename = the `slug` in front matter.
- **One question per article**, mapped to an archetype in the skill.
- **Front matter is required** (title, slug, description, both dates, `faq`, `sources`, `schema_types`). It's the spec for the site build.
- **Cite only primary sources** listed in the skill's `source-library.md`.

## Transfer to the website (handoff)
When an article is `status: ready`:
1. Convert the Markdown body to semantic HTML (H1 = title, `##` → `<h2>`, lists/tables preserved).
2. Emit JSON-LD from the front matter: `Article`/`BlogPosting` + `FAQPage` (+ `HowTo` where set) — templates in `geo-checklist.md`.
3. Show `date_published` and `date_modified` visibly on the page; keep `dateModified` fresh on edits.
4. Render the `sources` list as visible outbound links; set canonical URL to `https://www.gt.school/blog/<slug>`.
5. Add the internal links to related articles.

> Once you tell me the platform gt.school runs on, I can add an exact export step (or a small script) for that CMS.

## Build the AI-friendly HTML (template + generator)
Every article renders into a GEO-optimized page through **one shared template**, so the whole library stays consistent and citable by AI answer engines.
- **`template.html`** — the reusable page shell: semantic HTML, one `H1` = the question, visible published/updated `<time>` dates, an answer-first block, related-links nav, inline CSS, and a JSON-LD injection point. Edit this to change how *every* page looks.
- **`build.py`** — reads each `blog/<slug>.md` (front matter + body) and fills the template, writing `blog/site/<slug>.html` + `site/index.html`. It generates `BlogPosting` + `FAQPage` (+ `HowTo` where `schema_types` includes it) + `BreadcrumbList` JSON-LD straight from the front matter.

```
pip install pyyaml markdown
python3 blog/build.py            # build every article
python3 blog/build.py <slug>     # build one article
```

Generated pages are standalone (CSS inlined) and portable to any host/CMS. **Don't edit `blog/site/` by hand** — edit the `.md` or `template.html`, then rebuild. Platform-specific export (Webflow/WordPress/etc.) can be added once the gt.school platform is known.

## Content checks (run before pushing)
Two automated checkers guard the library; both are wired into the git **pre-push hook** (`hooks/pre-push`), so a push is blocked if either finds a hard problem. Bypass only in a true emergency with `git push --no-verify`.

**`check_facts.py`** — validates every article's recurring stats against the vetted canonical values in the skill's `source-library.md`, flags conflicts (a single wrong article, or two that disagree), and catches competitor names. Exits non-zero on a conflict.

**`check_style.py`** — enforces the writing house rules across every article:
- **Hard (blocks the push):** competitor names (e.g. Davidson), em dashes in the body.
- **Advisory (reported, non-blocking):** inline citations in the body (attribution belongs in the bottom Sources list), and thin data coverage — an article with no `[STAT]`/`[CHART]` placeholder and almost no figures ("it's a guide, but numbers back credibility"). Add `--strict` to make advisories fail too.

```
pip install pyyaml markdown
python3 blog/check_facts.py            # facts / canonical values
python3 blog/check_style.py            # house rules + data coverage
python3 blog/check_style.py <slug>     # one article
python3 blog/check_style.py --strict   # advisories also fail

# full gate (nothing ships unless both pass):
python3 blog/check_facts.py && python3 blog/check_style.py && python3 blog/build.py && <deploy> && git push
```

When a fact genuinely changes (e.g. next year's TEFA award), update it in ONE place, `CANONICAL_FACTS` in `check_facts.py` and the matching entry in `source-library.md`, then rebuild; the checker reports every article that still states the old value. Genuinely contested facts stay a human call; the checker surfaces the disagreement, a reviewer decides, and the decision is recorded in the source library.

## Design system (colors + per-section theming)
`LIBRARY_GROUPS` in `build.py` is the **single source of truth** for the look. Each section defines a
`c` (theme color) and a short `label` (kicker), and everything else is derived, so **adding an article
to a group auto-themes it** (home marker, article header rule, Quick Answer bar, kicker).

- **Palette (locked, matches the GT results page):** background (cream) `#FAF7F2`, ink (GT navy) `#002A3A`, muted navy `#4a6572`, hairline border `#DDD6CD`, gold accent `#E48B53` (rules, list markers, focus states only — never fills or large areas), navy variants `#003B5C` / `#004F71`. `#b65e78` (accent rose) was removed — it is not in GT's palette.
- **Section color `c`** drives the home square marker + row arrow, AND each article's `--theme` (the thin rule on the article header + the Quick Answer bar), so a section reads as one coordinated color.
- **Section `label`** is the article kicker (e.g. `Acceleration`).
- **Background texture:** home page and articles draw the results-page graph-paper grid (`#ebba9b1f`, ~12% alpha, 24px) on the `body`. The grid runs **unbroken** under the whole page — no solid column fill on top; the column is defined by type alignment. Layout is hairline rules instead of cards — no gradients, no shadows, no rounded corners beyond 2px, no decorative illustration.
- **Two-tier width:** `--shell: 1140px` for the page shell (nav, indexes, question-group listings, footer) and `--measure: 700px` for long-form prose (article body copy). Both tokens live in `template.html` and `_LIB_CSS`.
- Add `(slug, title, blurb)` to a group to publish; an unlisted article still builds but gets the default orange theme + no home row (the build prints a warning).

## Index (live library, grouped by theme)
Five parent-question sections (same order on the site). Each shows its **kicker label** and **color**.

**Is my child actually gifted?** — kicker `Identifying Giftedness`, color `#e48b53` (orange)
- `signs-my-child-is-gifted.md` : How do I know if my child is gifted?
- `gifted-vs-high-achiever.md` : Gifted or just a high achiever?
- `what-iq-is-considered-gifted.md` : What IQ score is considered gifted?
- `what-is-twice-exceptional.md` : What does twice-exceptional (2e) mean?
- `how-are-gifted-children-tested.md` : How are children tested for giftedness?
- `signs-of-giftedness-in-toddlers-and-preschoolers.md` : Signs of giftedness in toddlers and preschoolers
- `giftedness-vs-adhd.md` : Is it giftedness or ADHD?

**Is my child bored or under-challenged?** — kicker `Staying Challenged`, color `#d0765a` (terracotta)
- `is-my-gifted-child-under-challenged.md` : Is my gifted child under-challenged?
- `gifted-child-bored-what-are-my-options.md` : My gifted child is bored, what are my options?
- `how-to-advocate-for-your-gifted-child-at-school.md` : How do I advocate for my gifted child at school?
- `why-is-my-gifted-child-getting-bad-grades.md` : Why is my gifted child getting bad grades?

**How is my child doing emotionally?** — kicker `Social & Emotional`, color `#d3897e` (coral rose)
- `why-is-my-gifted-child-so-intense.md` : Why is my gifted child so intense or emotional?
- `how-to-help-a-gifted-perfectionist.md` : How do I help a gifted perfectionist?

**Should we let them move ahead?** — kicker `Acceleration`, color `#c77a88` (dusty rose)
- `does-academic-acceleration-actually-work.md` : Does academic acceleration actually work?
- `does-grade-skipping-hurt-kids-socially.md` : Does grade-skipping hurt kids socially?
- `what-is-single-subject-acceleration.md` : What is single-subject acceleration?
- `is-my-child-ready-to-skip-a-grade.md` : Is my child ready to skip a grade?

**How do gifted kids learn best?** — kicker `Learning Models`, color `#003B5C` (mid navy)
- `what-is-mastery-based-learning.md` : What is a mastery-based (2-hour) learning model?
- `what-is-curriculum-compacting.md` : What is curriculum compacting?
- `enrichment-vs-acceleration.md` : Enrichment vs. acceleration
- `what-is-the-2-hour-school-day.md` : What is the 2-hour school day, and does it work?

**Where should they go to school?** — kicker `School Options`, color `#aa5570` (deep berry)
- `online-gifted-school-vs-homeschooling-gifted-child.md` : Online gifted school vs. homeschooling
- `use-texas-tefa-voucher-online-gifted-school.md` : Can I use my Texas TEFA voucher for an online gifted school?
- `what-is-the-texas-education-freedom-account.md` : What is the Texas Education Freedom Account (ESA)?
- `how-to-apply-for-the-texas-education-freedom-account.md` : How do I apply for the Texas ESA (eligibility + steps)?

**House rules (enforced):** sources live in front matter + the end Sources list only (no inline citations; the builder strips them). Never name or cite a competitor (the build fails if one appears). No em dashes.

25 articles across the 7 archetypes and 6 sections.
