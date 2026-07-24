# GT School Blog — draft library

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

## Index (live library, grouped by theme)
The live library groups articles into five parent-question themes (same order on the site).

**Is my child actually gifted?**
- `signs-my-child-is-gifted.md` : How do I know if my child is gifted?
- `gifted-vs-high-achiever.md` : Gifted or just a high achiever?
- `what-iq-is-considered-gifted.md` : What IQ score is considered gifted?
- `what-is-twice-exceptional.md` : What does twice-exceptional (2e) mean?
- `how-are-gifted-children-tested.md` : How are children tested for giftedness?

**Is my child bored or under-challenged?**
- `is-my-gifted-child-under-challenged.md` : Is my gifted child under-challenged?
- `gifted-child-bored-what-are-my-options.md` : My gifted child is bored, what are my options?
- `how-to-advocate-for-your-gifted-child-at-school.md` : How do I advocate for my gifted child at school?

**Should we let them move ahead?**
- `does-academic-acceleration-actually-work.md` : Does academic acceleration actually work?
- `does-grade-skipping-hurt-kids-socially.md` : Does grade-skipping hurt kids socially?
- `what-is-single-subject-acceleration.md` : What is single-subject acceleration?

**How do gifted kids learn best?**
- `what-is-mastery-based-learning.md` : What is a mastery-based (2-hour) learning model?
- `what-is-curriculum-compacting.md` : What is curriculum compacting?
- `enrichment-vs-acceleration.md` : Enrichment vs. acceleration

**Where should they go to school?**
- `online-gifted-school-vs-homeschooling-gifted-child.md` : Online gifted school vs. homeschooling
- `use-texas-tefa-voucher-online-gifted-school.md` : Can I use my Texas TEFA voucher for an online gifted school?
- `what-is-the-texas-education-freedom-account.md` : What is the Texas Education Freedom Account (ESA)?

**House rules (enforced):** sources live in front matter + the end Sources list only (no inline citations; the builder strips them). Never name or cite a competitor (the build fails if one appears). No em dashes.

17 articles across all 7 archetypes.
