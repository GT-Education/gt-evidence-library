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

## Index
| Article | Archetype | Question | Status |
|---|---|---|---|
| `is-my-gifted-child-under-challenged.md` | diagnostic-checklist | Is my gifted child under-challenged? | draft |
| `does-grade-skipping-hurt-kids-socially.md` | myth-vs-evidence | Does grade-skipping hurt kids socially? | draft |
| `use-texas-tefa-voucher-online-gifted-school.md` | eligibility-howto | Can I use my Texas TEFA voucher for an online gifted school? | draft |
| `what-is-curriculum-compacting.md` | definition-explainer | What is curriculum compacting? | draft |
| `gifted-child-bored-what-are-my-options.md` | options-guide | My gifted child is bored — what are my options? | draft |
| `does-academic-acceleration-actually-work.md` | evidence-outcomes | Does academic acceleration actually work? | draft |
| `online-gifted-school-vs-homeschooling-gifted-child.md` | comparison | Online gifted school vs. homeschooling a gifted child | draft |
| `what-is-mastery-based-learning.md` | definition-explainer | What is a mastery-based (2-hour) learning model? | draft |

**Archetype coverage:** all 7 archetypes are now represented. Remaining priority questions to seed the library: twice-exceptional (2e) explainer, and an online-gifted-school-for-K–8 options guide.
