#!/usr/bin/env python3
"""
GT School blog builder - turns each blog/<slug>.md into an AI-citable (GEO) HTML page
using blog/template.html.

Every article reuses the SAME template, so the whole library stays consistent and
technically citable (semantic HTML + JSON-LD + visible freshness dates + internal links).

Usage:
    pip install pyyaml markdown
    python3 blog/build.py            # builds every blog/*.md
    python3 blog/build.py <slug>     # builds one article

Output: blog/site/<slug>.html  (+ blog/site/index.html)
The generated pages are standalone (CSS inlined) and portable to any host/CMS.
Do not edit files in blog/site/ by hand - edit the .md or the template, then rebuild.

House rules enforced here:
  - Sources live in the bottom Sources list only; inline parenthesized citations in the body are
    stripped automatically (see convert_citations).
  - Competitors are never named or cited; the build fails if a competitor name appears (COMPETITORS).
"""
from __future__ import annotations

import html
import json
import re
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("Missing dependency: pip install pyyaml")
try:
    import markdown as md
except ImportError:
    sys.exit("Missing dependency: pip install markdown")

BLOG_DIR = Path(__file__).resolve().parent
OUT_DIR = BLOG_DIR / "site"
ASSETS_SRC = BLOG_DIR / "assets"
TEMPLATE = BLOG_DIR / "template.html"
SITE_URL = "https://www.gt.school"
# The library is hosted on Firebase for now, so the "Blog" breadcrumb points there.
# Swap to SITE_URL + "/blog" once the library moves onto the main gt.school site.
BLOG_INDEX_URL = "https://gt-school-blog.web.app/"
# Where the pages actually live right now (Firebase). Canonical URLs, OG URLs, the sitemap, and the
# JSON-LD page URLs all point here, so the LIVE pages are what Google indexes and AI engines cite.
# When the library moves onto gt.school, update this to the new home (and 301 the old URLs).
CANONICAL_BASE = "https://gt-school-blog.web.app"

FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.S)


def parse_article(path: Path) -> tuple[dict, str]:
    raw = path.read_text(encoding="utf-8")
    m = FM_RE.match(raw)
    if not m:
        raise ValueError(f"{path.name}: missing YAML front matter")
    front = yaml.safe_load(m.group(1)) or {}
    return front, m.group(2)


def to_date(v) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return datetime.strptime(str(v).strip(), "%Y-%m-%d").date()


def iso(v) -> str:
    return to_date(v).isoformat()


def human(v) -> str:
    d = to_date(v)
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def month_year(v) -> str:
    # Coarse "Month Year" shown to readers (freshness without exposing an exact same-day publish).
    d = to_date(v)
    return f"{d.strftime('%B')} {d.year}"


def strip_h1_and_dates(body: str) -> tuple[str, str]:
    """Return (h1_text_or_empty, body_without_h1_and_dates_line)."""
    h1 = ""
    m = re.search(r"^#\s+(.+?)\s*$", body, flags=re.M)
    if m:
        h1 = m.group(1).strip()
        body = body[: m.start()] + body[m.end():]
    body = re.sub(r"^\*Published.*\*\s*$", "", body, count=1, flags=re.M)
    return h1, body.strip()


def linkify_bare_urls(html_str: str) -> str:
    """Wrap bare http(s) URLs (e.g. in the Sources list) in anchors.
    Skips URLs already inside an attribute or anchor text (preceded by " or >)."""
    pattern = re.compile(r'(?<![">])(https?://[^\s<)]+)')
    return pattern.sub(lambda mo: f'<a href="{mo.group(1)}" rel="noopener">{mo.group(1)}</a>', html_str)


def wrap_tables(html_str: str) -> str:
    html_str = html_str.replace("<table>", '<div class="table-scroll"><table>')
    return html_str.replace("</table>", "</table></div>")


def class_answer_paragraph(html_str: str) -> str:
    return html_str.replace("<p>", '<p class="answer">', 1)


# Placeholder markers so we NEVER ship invented data.
# Block visual: a lone paragraph like [CHART: ...] / [VISUAL: ...] / [DATA: ...] -> dashed box.
# Inline stat: [STAT], [NUMBER], [%], [$] (optionally [STAT: note]) -> highlighted chip.
_PH_BLOCK = re.compile(
    r"<p>\s*\[(VISUAL|CHART|GRAPH|DATA|IMAGE|INFOGRAPHIC|TABLE)\s*:?\s*([^\]]*)\]\s*</p>",
    flags=re.I,
)
_PH_INLINE = re.compile(r"\[(STAT|NUMBER|PERCENT|%|\$)(?::[^\]]*)?\]", flags=re.I)


def process_placeholders(html_str: str) -> str:
    def block(m: re.Match) -> str:
        label = m.group(1).capitalize()
        desc = html.escape(m.group(2).strip())
        body = desc or f"Describe the {label.lower()} to insert here."
        return (
            f'<figure class="ph-visual" role="img" aria-label="Placeholder for {label}: {body}">'
            f'<div class="ph-visual-tag">{label} placeholder &middot; to add</div>'
            f'<div class="ph-visual-desc">{body}</div></figure>'
        )

    html_str = _PH_BLOCK.sub(block, html_str)
    html_str = _PH_INLINE.sub(
        lambda m: f'<mark class="ph-stat" title="Insert a primary-source-cited figure">{html.escape(m.group(0))}</mark>',
        html_str,
    )
    return html_str


# Keep sources on the page (AI + Google read the DOM; skeptical parents can verify)
# but collapsed behind a quiet toggle so the article reads clean. JSON-LD citations stay too.
_SOURCES_RE = re.compile(
    r"<h([23])[^>]*>\s*(?:Sources?|References?)(?:\s*&amp;\s*[Rr]eferences?)?\s*</h\1>\s*"
    r"(<(?:ul|ol|p)[^>]*>.*?</(?:ul|ol|p)>)",
    re.S | re.I,
)


def collapse_sources(html_str: str) -> str:
    return _SOURCES_RE.sub(
        lambda m: '<details class="references"><summary>Sources &amp; references</summary>'
        + m.group(2) + "</details>",
        html_str,
    )


# The FAQ archetype renders as warm Q/A cards (.qa-list), matching the redesign theme.
_FAQ_RE = re.compile(
    r"(<h2[^>]*>\s*(?:Frequently asked questions|Questions parents ask)\s*</h2>)"
    r"(.*?)(?=<hr\s*/?>|<h2|<details|$)",
    re.S | re.I,
)
_QA_PAIR_RE = re.compile(r"<h3[^>]*>(.*?)</h3>\s*<p>(.*?)</p>", re.S)


def convert_faq(html_str: str) -> str:
    def sub(m: "re.Match[str]") -> str:
        pairs = _QA_PAIR_RE.findall(m.group(2))
        if not pairs:
            return m.group(0)
        items = "".join(
            f'<div class="qa-item"><p class="q">{q.strip()}</p><p class="a">{a.strip()}</p></div>'
            for q, a in pairs
        )
        return f'{m.group(1)}<div class="qa-list">{items}</div>'

    return _FAQ_RE.sub(sub, html_str)


# The closing CTA paragraph becomes a dark .cta-card with buttons, per the redesign theme.
ANYWHERE_URL = "https://anywhere.gt.school/"
ACADEMICS_URL = "https://www.gt.school/academics"
# CTA = the paragraph right after the final <hr>, just before the references. Its first sentence
# becomes the card title. No reliance on bold, so article bodies can drop inline <strong> entirely.
_CTA_RE = re.compile(
    r'<hr\s*/?>\s*<p>(?P<body>(?:(?!</p>).)*?)</p>\s*(?=<details class="references">|$)',
    re.S,
)
_LINK_RE = re.compile(r'<a href="([^"]+)"[^>]*>(.*?)</a>', re.S)


def convert_cta(html_str: str) -> str:
    m = _CTA_RE.search(html_str)
    if not m:
        return html_str
    inner = re.sub(r"</?strong>", "", m.group("body")).strip()
    text = _LINK_RE.sub(lambda x: x.group(2), inner).strip()
    sm = re.match(r"(?s)(.+?[.!?])\s+(.*)$", text)
    hook, rest = (sm.group(1).strip(), sm.group(2).strip()) if sm else (text, "")
    # GT Anywhere (online) is the primary thing to promote; the model page is the secondary link.
    buttons = (f'<a class="btn btn-primary" href="{ANYWHERE_URL}">Explore GT Anywhere</a>'
               f'<a class="btn btn-ghost" href="{ACADEMICS_URL}">How the model works</a>')
    inner_html = f"<h3>{hook}</h3>" + (f"<p>{rest}</p>" if rest else "")
    card = ('<div class="cta-card"><p class="eyebrow">See it in action</p>'
            f'{inner_html}<div class="cta-actions">{buttons}</div></div>')
    return html_str[:m.start()] + card + html_str[m.end():]


# --- House style: attribution lives in the bottom Sources list, not inline footnotes. Every
# parenthesized link is stripped from the body; inline (navigation) links stay inline.
_SOURCES_BLOCK_RE = re.compile(
    r"<h([23])[^>]*>\s*(?:Sources?|References?)(?:\s*&amp;\s*[Rr]eferences?)?\s*</h\1>\s*"
    r"(?:<(?:ul|ol|p)[^>]*>.*?</(?:ul|ol|p)>)",
    re.S | re.I,
)
_CITE_RE = re.compile(r'\s*\(\s*<a href="(?P<href>[^"]+)"[^>]*>.*?</a>\s*\)', re.S)


def strip_sources_block(html_str: str) -> str:
    """Remove the in-body 'Sources' list; it's regenerated (numbered) at the very bottom."""
    return _SOURCES_BLOCK_RE.sub("", html_str)


def convert_citations(html_str: str, sources: list[dict]) -> tuple[str, list[str]]:
    """Strip every parenthesized link from the body; attribution lives in the bottom Sources list.
    Inline (non-parenthesized) navigation links are left untouched. Returns an empty order so the
    Sources list is built from the full front-matter source list."""
    return _CITE_RE.sub("", html_str), []


def build_sources_details(order: list[str], sources: list[dict]) -> str:
    by_url = {s["url"]: s for s in sources if s.get("url")}
    urls = order + [u for u in by_url if u not in order]
    if not urls:
        return ""
    lis = []
    for i, u in enumerate(urls, start=1):
        s = by_url.get(u, {})
        label = html.escape(s.get("label", ""))
        acc = s.get("accessed", "")
        acc_s = f" (accessed {html.escape(str(acc))})" if acc else ""
        lis.append(f'<li id="src{i}">{label}. <a href="{u}" rel="noopener">{u}</a>{acc_s}</li>')
    return ('<details class="references"><summary>Sources</summary>'
            f'<ol>{"".join(lis)}</ol></details>')


def extract_steps(html_str: str) -> list[dict]:
    """Pull steps from the first <ol> for HowTo schema (keeps schema aligned to visible content)."""
    ol = re.search(r"<ol[^>]*>(.*?)</ol>", html_str, flags=re.S)
    if not ol:
        return []
    steps = []
    for i, li in enumerate(re.findall(r"<li[^>]*>(.*?)</li>", ol.group(1), flags=re.S), start=1):
        text = html.unescape(re.sub(r"<[^>]+>", "", li)).strip()
        text = re.sub(r"\s+", " ", text)
        if not text:
            continue
        name = re.split(r"(?<=[.!?])\s", text)[0][:110]
        steps.append({"@type": "HowToStep", "position": i, "name": name, "text": text})
    return steps


def build_jsonld(fm: dict, canonical: str, content_html: str) -> str:
    title = fm.get("title", "")
    desc = fm.get("description", "")
    graph = []

    blogposting = {
        "@type": "BlogPosting",
        "@id": canonical + "#article",
        "headline": title,
        "description": desc,
        "datePublished": iso(fm["date_published"]),
        "dateModified": iso(fm["date_modified"]),
        "inLanguage": "en",
        "author": {"@type": "Organization", "name": "GT School", "url": SITE_URL + "/"},
        "publisher": {
            "@type": "Organization",
            "name": "GT School",
            "url": SITE_URL + "/",
            "logo": {"@type": "ImageObject", "url": CANONICAL_BASE + "/assets/gt-icon.png"},
        },
        "mainEntityOfPage": {"@type": "WebPage", "@id": canonical},
        "url": canonical,
        "isAccessibleForFree": True,
        # Mark the answer-first parts so voice/AI answer engines know what to lift verbatim.
        "speakable": {"@type": "SpeakableSpecification", "cssSelector": ["h1", "p.answer"]},
    }
    if fm.get("target_queries"):
        blogposting["keywords"] = ", ".join(fm["target_queries"])
    if fm.get("primary_question"):
        # Reinforce that this page explores ONE specific question.
        blogposting["about"] = {"@type": "Thing", "name": fm["primary_question"]}
    if fm.get("image"):
        blogposting["image"] = {"@type": "ImageObject", "url": fm["image"]}
    if fm.get("sources"):
        blogposting["citation"] = [
            {"@type": "CreativeWork", "name": s.get("label", ""), "url": s.get("url", "")}
            for s in fm["sources"]
        ]
    graph.append(blogposting)

    if fm.get("faq"):
        graph.append({
            "@type": "FAQPage",
            "@id": canonical + "#faq",
            "mainEntity": [
                {"@type": "Question", "name": q["q"],
                 "acceptedAnswer": {"@type": "Answer", "text": q["a"]}}
                for q in fm["faq"]
            ],
        })

    if "HowTo" in (fm.get("schema_types") or []):
        steps = extract_steps(content_html)
        if steps:
            graph.append({
                "@type": "HowTo",
                "@id": canonical + "#howto",
                "name": title,
                "description": desc,
                "step": steps,
            })

    graph.append({
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": SITE_URL + "/"},
            {"@type": "ListItem", "position": 2, "name": "Blog", "item": BLOG_INDEX_URL},
            {"@type": "ListItem", "position": 3, "name": title, "item": canonical},
        ],
    })

    payload = {"@context": "https://schema.org", "@graph": graph}
    blob = json.dumps(payload, ensure_ascii=False, indent=2).replace("</", "<\\/")
    return f'<script type="application/ld+json">\n{blob}\n</script>'


def breadcrumb_html(title: str) -> str:
    return (
        '<nav class="crumbs" aria-label="Breadcrumb">'
        f'<a href="{SITE_URL}/">Home</a><span class="sep">/</span>'
        f'<a href="{BLOG_INDEX_URL}">Blog</a><span class="sep">/</span>'
        f'<span class="current">{html.escape(title)}</span></nav>'
    )


def related_html(fm: dict, titles: dict[str, str]) -> str:
    links = fm.get("internal_links") or []
    items = [(s, titles[s]) for s in links if s in titles]
    if not items:
        return ""
    lis = "".join(f'<li><a href="{s}.html">{html.escape(t)}</a></li>' for s, t in items)
    return f'<nav class="related" aria-label="Related articles"><h2>Related reading</h2><ul>{lis}</ul></nav>'


def build_toc(content_html: str) -> str:
    """Sticky 'In this guide' sidebar from the article's H2 section headings (uses the toc ids)."""
    heads = re.findall(r'<h2[^>]*\bid="([^"]+)"[^>]*>(.*?)</h2>', content_html, re.S)
    if len(heads) < 2:
        return ""
    items = "".join(
        f'<li><a href="#{hid}">{re.sub(r"<[^>]+>", "", txt).strip()}</a></li>'
        for hid, txt in heads
    )
    return (
        '<aside class="toc" aria-label="On this page">'
        '<p class="toc-title">In this guide</p>'
        f"<ul>{items}</ul></aside>"
    )


def render(fm: dict, body: str, titles: dict[str, str], template: str) -> str:
    slug = fm["slug"]
    canonical = f"{CANONICAL_BASE}/{slug}"
    h1_from_body, body_clean = strip_h1_and_dates(body)
    h1 = fm.get("title") or h1_from_body

    content = md.markdown(body_clean, extensions=["extra", "sane_lists", "toc"], output_format="html5")
    content = wrap_tables(content)
    content = linkify_bare_urls(content)
    content = class_answer_paragraph(content)
    content = process_placeholders(content)
    content = strip_sources_block(content)
    content = convert_faq(content)
    content = convert_cta(content)
    content, cited = convert_citations(content, fm.get("sources") or [])
    content += build_sources_details(cited, fm.get("sources") or [])

    words = len(re.findall(r"\w+", body_clean))
    reading = max(1, round(words / 200))

    og = f"{CANONICAL_BASE}/assets/og-default.png"
    og_img = (f'<meta property="og:image" content="{og}"/>'
              f'<meta property="og:image:width" content="1200"/>'
              f'<meta property="og:image:height" content="630"/>'
              f'<meta name="twitter:image" content="{og}"/>')

    repl = {
        "{{LANG}}": "en",
        "{{TITLE}}": html.escape(fm.get("title", h1)),
        "{{DESCRIPTION}}": html.escape(fm.get("description", "")),
        "{{CANONICAL}}": canonical,
        "{{SITE_URL}}": SITE_URL,
        "{{KEYWORDS}}": html.escape(", ".join(fm.get("target_queries") or [])),
        "{{CATEGORY}}": html.escape(SLUG_KICKER.get(slug, fm.get("category", "Gifted Education"))),
        "{{THEME}}": SLUG_THEME.get(slug, "#E48B53"),
        "{{DATE_PUBLISHED_ISO}}": iso(fm["date_published"]),
        "{{DATE_MODIFIED_ISO}}": iso(fm["date_modified"]),
        "{{DATE_PUBLISHED_HUMAN}}": human(fm["date_published"]),
        "{{DATE_MODIFIED_HUMAN}}": human(fm["date_modified"]),
        "{{DATE_MODIFIED_MONTHYEAR}}": month_year(fm["date_modified"]),
        "{{READING_TIME}}": str(reading),
        "{{OG_IMAGE_TAGS}}": og_img,
        "{{JSON_LD}}": build_jsonld(fm, canonical, content),
        "{{BREADCRUMB}}": breadcrumb_html(h1),
        "{{H1}}": html.escape(h1),
        "{{CONTENT}}": content,
        "{{TOC}}": build_toc(content),
        "{{RELATED}}": related_html(fm, titles),
        "{{YEAR}}": str(date.today().year),
    }
    out = template
    for k, v in repl.items():
        out = out.replace(k, v)
    return out


# --- Library (index) + COLOR SYSTEM (single source of truth) ------------------------
# The whole visual system derives from LIBRARY_GROUPS below. Each group has:
#   "q"     : the parent-worry question shown as the section heading on the home page.
#   "c"     : the section THEME COLOR. It drives BOTH the home markers (square marker + row
#             arrow) AND every article in the group: via SLUG_THEME -> {{THEME}} -> the article's
#             --theme, which colors the thin rule on the article header + the Quick Answer bar.
#             So a section's header rule, its Quick Answer bar, and its home markers all read as
#             ONE coordinated color.
#   "label" : the short 1-2 word section name shown as the article KICKER (SLUG_KICKER ->
#             {{CATEGORY}}), e.g. "Acceleration". Falls back to the .md `category` if unset.
#   "items" : (slug, title, blurb) rows, in display order.
#
# Restrained "results page" look: no ombre, no gradients. --theme colors only the thin rule on
# the article header + the Quick Answer bar (see template.html), and the home section markers.
#
# LOCKED PALETTE - GT brand portal (see "GT Brand/Colors/gt-brand-colors.md"). Do not invent colors.
#   Gold #e48b53 (brand calls gold "the single accent") | Gold Dark #ab683e | Blue #004f71
#   Blue Dark #003b5c | Navy #002a3a | Dark Navy #001117 | Off White #fcf4ef (bg) | Grey #cac6c4
#   There is NO pink, rose, berry, coral or terracotta in the GT palette. Earlier versions of this
#   file used #d3897e, #c77a88, #aa5570, #b65e78 and #d0765a; all five were off-brand and are gone.
#   Section colors descend gold -> blue -> navy, one official value per section. Navy (#002a3a) and
#   Dark Navy (#001117) are close as small markers; they sit on the last two sections deliberately.
# TO ADD AN ARTICLE: write blog/<slug>.md, then add (slug, title, blurb) to the right group here;
# it auto-inherits the section color, kicker, home row, header rule tint, and Quick Answer color.
# An unlisted .md still builds (default orange theme, no home row) and the build prints a warning.
LIBRARY_INTRO = {
    "kicker": "Evidence Library",
    "h1": "The questions gifted parents ask, answered.",
    "sub": "Assessment, acceleration, curriculum, and choosing a school.",
    "reviewed": "Written &amp; reviewed by GT School\u2019s gifted-education team",
}
LIBRARY_START_HERE = [
    ("Is my child gifted?", "signs-my-child-is-gifted"),
    ("Under-challenged?", "is-my-gifted-child-under-challenged"),
    ("Does acceleration work?", "does-academic-acceleration-actually-work"),
]
LIBRARY_GROUPS = [
    {"q": "Is my child actually gifted?", "c": "#e48b53", "label": "Identifying Giftedness", "items": [
        ("signs-my-child-is-gifted", "How do I know if my child is gifted?",
         "The traits that actually signal giftedness, and when to seek an evaluation."),
        ("gifted-vs-high-achiever", "Gifted or just a high achiever?",
         "Why a straight-A kid and a gifted kid are not always the same thing."),
        ("what-iq-is-considered-gifted", "What IQ score is considered gifted?",
         "There is no single cutoff. Here is what the numbers really mean."),
        ("what-is-twice-exceptional", "What does twice-exceptional (2e) mean?",
         "When a child is gifted and has a learning difference at the same time."),
        ("how-are-gifted-children-tested", "How are children tested for giftedness?",
         "What an evaluation involves, the tests used, and what the scores mean."),
        ("signs-of-giftedness-in-toddlers-and-preschoolers", "Signs of giftedness in toddlers and preschoolers",
         "The early signs that show up before school, and what they do and don\u2019t mean."),
        ("giftedness-vs-adhd", "Is it giftedness or ADHD?",
         "Why the two can look alike, when it\u2019s both (2e), and how to get clarity."),
    ]},
    {"q": "Is my child bored or under-challenged?", "c": "#ab683e", "label": "Staying Challenged", "items": [
        ("is-my-gifted-child-under-challenged", "Is my gifted child under-challenged?",
         "The signs a gifted child isn\u2019t being stretched, and what to do."),
        ("gifted-child-bored-what-are-my-options", "My gifted child is bored, what are my options?",
         "The real options when a bright kid is coasting, and how to choose."),
        ("how-to-advocate-for-your-gifted-child-at-school", "How do I advocate for my child at school?",
         "What to ask for, the evidence to bring, and what to do if they say no."),
        ("why-is-my-gifted-child-getting-bad-grades", "Why is my gifted child getting bad grades?",
         "How a capable kid ends up with average grades, and what actually helps."),
    ]},
    {"q": "How is my child doing emotionally?", "c": "#004f71", "label": "Social & Emotional", "items": [
        ("why-is-my-gifted-child-so-intense", "Why is my gifted child so intense or emotional?",
         "Big feelings are common in gifted kids. What\u2019s normal, and how to help."),
        ("how-to-help-a-gifted-perfectionist", "How do I help a gifted perfectionist?",
         "Turning fear of failure into healthy striving, at home and at school."),
    ]},
    {"q": "Should we let them move ahead?", "c": "#003b5c", "label": "Acceleration", "items": [
        ("does-academic-acceleration-actually-work", "Does academic acceleration actually work?",
         "Decades of research on whether moving faster actually helps."),
        ("does-grade-skipping-hurt-kids-socially", "Does grade-skipping hurt kids socially?",
         "What the research says about the social worry every parent has."),
        ("what-is-single-subject-acceleration", "What is single-subject acceleration?",
         "Move a child up in one subject while they stay with age peers."),
        ("is-my-child-ready-to-skip-a-grade", "Is my child ready to skip a grade?",
         "A whole-child way to decide, and what the research says about the risk."),
    ]},
    {"q": "How do gifted kids learn best?", "c": "#002a3a", "label": "Learning Models", "items": [
        ("what-is-mastery-based-learning", "What is a mastery-based (2-hour) model?",
         "Advance by mastery, not age or seat-time."),
        ("what-is-curriculum-compacting", "What is curriculum compacting?",
         "Skip what\u2019s already mastered so class time buys something new."),
        ("enrichment-vs-acceleration", "Enrichment vs. acceleration",
         "Deeper at grade level, or further ahead? When to use each."),
        ("what-is-the-2-hour-school-day", "What is the 2-hour school day?",
         "How a focused, mastery-based block covers more in less time, and whether it works."),
    ]},
    {"q": "Where should they go to school?", "c": "#001117", "label": "School Options", "items": [
        ("online-gifted-school-vs-homeschooling-gifted-child", "Online gifted school vs. homeschooling",
         "A neutral guide to pace, parent time, cost, and funding."),
        ("use-texas-tefa-voucher-online-gifted-school", "Can I use my Texas TEFA voucher online?",
         "How an approved Texas ESA can fund an accredited online school."),
        ("what-is-the-texas-education-freedom-account", "What is the Texas Education Freedom Account?",
         "What the Texas ESA is, how much it\u2019s worth, and who may qualify."),
        ("how-to-apply-for-the-texas-education-freedom-account", "How do I apply for the Texas ESA?",
         "Who qualifies, what it covers, and the steps to apply for 2026-27."),
    ]},
]

# Map each article slug to its theme color (drives the per-article header rule + library markers).
SLUG_THEME = {slug: g["c"] for g in LIBRARY_GROUPS for (slug, _t, _b) in g["items"]}
# Map each article slug to its section label (shown as the article kicker, e.g. "Acceleration").
SLUG_KICKER = {slug: g["label"] for g in LIBRARY_GROUPS for (slug, _t, _b) in g["items"]}

_LIB_CSS = """<style>
  :root{--bg:#fcf4ef;--ink:#002A3A;--muted:#4a6572;--faint:#7d8f98;--line:#DDD6CD;
    --accent:#E48B53;
    --shell:1140px;   /* page shell: nav, indexes, question-group listings, footer */
    --measure:700px;  /* long-form prose reading measure (articles; index subhead) */
    --serif:"Literata",Georgia,serif;--sans:"Inter Tight",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;--mono:"Inconsolata",ui-monospace,monospace}
  *{box-sizing:border-box}
  /* Graph-paper grid (from the results page) runs UNBROKEN under the whole page - no solid
     column fill (a fill makes a hard edge where the grid stops). The column is defined by type
     alignment; the grid stays faint (~12% alpha) so text reads cleanly over it. */
  body{margin:0;background-color:var(--bg);color:var(--ink);font-family:var(--sans);-webkit-font-smoothing:antialiased;
    background-image:linear-gradient(#ebba9b1f 1px, transparent 1px),linear-gradient(90deg, #ebba9b1f 1px, transparent 1px);
    background-size:24px 24px}
  a{color:inherit}
  a:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
  /* Shell matches the article pages' --shell + 24px padding, so columns line up across pages. */
  .page{max-width:var(--shell);margin:0 auto;padding:40px 24px 88px;position:relative}
  .hero{padding:0 0 16px}
  .lib-header{margin:0 0 22px}
  .lib-header .brand{height:30px;width:auto;display:block}
  /* section eyebrow: plain uppercase mono text, muted navy */
  .kick{display:block;font-family:var(--mono);font-size:12px;font-weight:600;letter-spacing:.16em;text-transform:uppercase;color:var(--muted);margin:0}
  .h1{font-family:var(--serif);font-weight:400;font-size:36px;line-height:1.14;letter-spacing:-.03em;margin:12px 0 14px;text-wrap:balance}
  .sub{font-family:var(--serif);color:var(--muted);font-size:16.5px;line-height:1.5;margin:0 0 14px;max-width:var(--measure)}
  .rev{display:block;font-family:var(--mono);font-size:12.5px;letter-spacing:.02em;color:var(--muted);margin:0 0 20px}
  .search{display:flex;align-items:center;gap:10px;width:100%;max-width:var(--measure);background:transparent;border:1px solid var(--line);border-radius:2px;padding:12px 15px;margin:0 0 16px}
  .search svg{width:16px;height:16px;flex:none;stroke:var(--faint);fill:none;stroke-width:2}
  .search input{border:none;background:transparent;outline:none;width:100%;font-family:var(--sans);font-size:14px;color:var(--ink)}
  .search input::placeholder{color:var(--faint)}
  .starthere{display:flex;flex-wrap:wrap;align-items:center;gap:9px}
  .starthere .lbl{font-family:var(--mono);font-size:12px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
  .pill{font-family:var(--mono);font-size:12px;font-weight:500;letter-spacing:.04em;text-transform:uppercase;color:var(--ink);background:transparent;border:1px solid var(--line);border-radius:2px;padding:8px 13px;text-decoration:none;transition:border-color .15s ease}
  .pill:hover{border-color:var(--ink)}
  /* single gold hairline under the masthead (gold = rules only, never fills) */
  .hrule{height:1px;border:0;margin:22px 0 2px;background:var(--accent)}
  /* groups: small section-color marker + serif question at regular weight, then arrow rows.
     Dividers appear only BETWEEN sections. */
  .sec{padding:26px 0 12px}
  .sec + .sec{border-top:1px solid var(--line)}
  .gh{display:flex;align-items:baseline;gap:12px;margin:0 0 6px}
  .ring{width:10px;height:10px;border-radius:1px;background:var(--c);flex:none;align-self:center}
  .qcol{display:inline-block}
  .qh{display:block;font-family:var(--serif);font-weight:400;font-size:21px;line-height:1.3;letter-spacing:-.02em;margin:0;color:var(--ink)}
  .row{display:flex;gap:14px;align-items:flex-start;padding:13px 8px 13px 22px;border-radius:2px;text-decoration:none;color:inherit;transition:background .13s ease}
  .row:hover{background:color-mix(in srgb, var(--c) 7%, transparent)}
  .row .tx{flex:1;min-width:0}
  .row h4{font-family:var(--serif);font-weight:500;font-size:16.5px;line-height:1.28;margin:0 0 3px;color:var(--ink)}
  .row p{font-size:13.5px;line-height:1.5;color:var(--muted);margin:0}
  .row .ar{color:var(--c);flex:none;align-self:center;font-size:16px}
  .noresults{font-family:var(--serif);color:var(--muted);font-size:16px;padding:20px 12px;display:none}
  footer.site{margin-top:44px;padding-top:24px;border-top:1px solid var(--line);font-family:var(--mono);font-size:12.5px;letter-spacing:.02em;color:var(--faint)}
  @media (max-width:640px){.page{padding:28px 16px 64px}.hero{padding:0 0 12px}.h1{font-size:28px}}
</style>"""

_LIB_SEARCH_JS = """<script>
(function(){
  var q=document.getElementById('lib-search');
  if(!q) return;
  var rows=[].slice.call(document.querySelectorAll('.row'));
  var secs=[].slice.call(document.querySelectorAll('.sec'));
  var none=document.getElementById('noresults');
  q.addEventListener('input',function(){
    var t=q.value.trim().toLowerCase(); var hits=0;
    rows.forEach(function(r){var m=r.textContent.toLowerCase().indexOf(t)>-1; r.style.display=m?'':'none'; if(m)hits++;});
    secs.forEach(function(s){var vis=[].slice.call(s.querySelectorAll('.row')).some(function(r){return r.style.display!=='none';}); s.style.display=vis?'':'none';});
    if(none) none.style.display=hits?'none':'block';
  });
})();
</script>"""


def build_index_jsonld(articles: list[dict]) -> str:
    """WebSite + CollectionPage/ItemList + BreadcrumbList for the library hub, so search + AI
    engines understand the hub page and every article it links to."""
    url = CANONICAL_BASE + "/"
    items = []
    pos = 1
    for g in LIBRARY_GROUPS:
        for slug, title, _blurb in g["items"]:
            items.append({"@type": "ListItem", "position": pos,
                          "url": f"{CANONICAL_BASE}/{slug}", "name": title})
            pos += 1
    graph = [
        {"@type": "WebSite", "@id": url + "#website", "url": url,
         "name": "GT School Evidence Library",
         "description": "Primary-source answers to the questions parents of gifted and "
                        "twice-exceptional K-8 students ask.",
         "inLanguage": "en",
         "publisher": {"@type": "Organization", "name": "GT School", "url": SITE_URL + "/"}},
        {"@type": "CollectionPage", "@id": url + "#library", "url": url,
         "name": "GT School: Gifted Education Evidence Library",
         "isPartOf": {"@id": url + "#website"},
         "mainEntity": {"@type": "ItemList", "itemListElement": items}},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": SITE_URL + "/"},
            {"@type": "ListItem", "position": 2, "name": "Blog", "item": url}]},
    ]
    payload = {"@context": "https://schema.org", "@graph": graph}
    blob = json.dumps(payload, ensure_ascii=False, indent=2).replace("</", "<\\/")
    return f'<script type="application/ld+json">\n{blob}\n</script>'


def build_index(articles: list[dict]) -> str:
    secs = []
    for g in LIBRARY_GROUPS:
        rows = []
        for slug, title, blurb in g["items"]:
            rows.append(
                f'<a class="row" href="{slug}.html">'
                f'<div class="tx"><h4>{html.escape(title)}</h4><p>{html.escape(blurb)}</p></div>'
                f'<span class="ar">\u2192</span></a>'
            )
        secs.append(
            f'<div class="sec" style="--c:{g["c"]}">'
            f'<div class="gh"><span class="ring"></span>'
            f'<span class="qcol"><h3 class="qh">{html.escape(g["q"])}</h3></span></div>'
            + "".join(rows) + "</div>"
        )
    sections_html = "\n".join(secs)
    pills = "".join(
        f'<a class="pill" href="{slug}.html">{html.escape(label)}</a>'
        for label, slug in LIBRARY_START_HERE
    )
    return (
        '<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8"/>\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1"/>\n'
        '<title>GT School: Gifted Education Evidence Library</title>\n'
        '<meta name="description" content="Calm, clear, primary-source answers to the questions parents of gifted and twice-exceptional K-8 students actually ask."/>\n'
        '<meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1"/>\n'
        f'<link rel="canonical" href="{CANONICAL_BASE}/"/>\n'
        '<meta property="og:type" content="website"/>\n'
        '<meta property="og:site_name" content="GT School"/>\n'
        '<meta property="og:title" content="GT School: Gifted Education Evidence Library"/>\n'
        '<meta property="og:description" content="Primary-source answers to the questions parents of gifted and twice-exceptional K-8 students ask."/>\n'
        f'<meta property="og:url" content="{CANONICAL_BASE}/"/>\n'
        f'<meta property="og:image" content="{CANONICAL_BASE}/assets/og-default.png"/>\n'
        '<meta name="twitter:card" content="summary_large_image"/>\n'
        f'<meta name="twitter:image" content="{CANONICAL_BASE}/assets/og-default.png"/>\n'
        '<link rel="icon" type="image/png" href="assets/gt-icon.png"/>\n'
        '<link rel="apple-touch-icon" href="assets/gt-icon.png"/>\n'
        + build_index_jsonld(articles) + '\n'
        '<link rel="preconnect" href="https://fonts.googleapis.com"/>\n'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>\n'
        '<link href="https://fonts.googleapis.com/css2?family=Literata:ital,opsz,wght@0,7..72,300..700;1,7..72,300..600&family=Inter+Tight:wght@400;500;600;700&family=Inconsolata:wght@500;600;700&display=swap" rel="stylesheet"/>\n'
        + _LIB_CSS + '\n</head>\n<body>\n<div class="page">\n'
        '  <div class="hero">\n'
        '  <header class="lib-header"><a href="index.html" aria-label="GT School home"><img class="brand" src="assets/gt-school-logo.png" alt="GT School" height="30"/></a></header>\n'
        f'  <p class="kick">{LIBRARY_INTRO["kicker"]}</p>\n'
        f'  <h1 class="h1">{LIBRARY_INTRO["h1"]}</h1>\n'
        f'  <p class="sub">{LIBRARY_INTRO["sub"]}</p>\n'
        f'  <p class="rev">{LIBRARY_INTRO["reviewed"]}</p>\n'
        '  <div class="search"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><line x1="16.5" y1="16.5" x2="21" y2="21"/></svg>'
        '<input id="lib-search" type="search" placeholder="Search the library&hellip;" aria-label="Search the library"/></div>\n'
        f'  <div class="starthere"><span class="lbl">New here? Start with</span>{pills}</div>\n'
        '  </div>\n'
        '  <hr class="hrule"/>\n'
        + sections_html + '\n'
        '  <p class="noresults" id="noresults">No guides match that yet. Try a different word.</p>\n'
        f'  <footer class="site">Published by GT School, the gifted academy of the Alpha School family. &copy; {date.today().year} GT School.</footer>\n'
        '</div>\n' + _LIB_SEARCH_JS + '\n</body>\n</html>'
    )


# House rule: never name or cite a competitor. Attribution is bottom-list only (inline citations are
# stripped automatically by convert_citations), but competitor *names* can't be auto-removed safely,
# so the build hard-fails if one appears. Add new competitor names here as needed.
COMPETITORS = ("davidson",)


def check_no_competitors(paths: list[Path]) -> None:
    offenders = []
    for p in paths:
        low = p.read_text(encoding="utf-8").lower()
        found = sorted({c for c in COMPETITORS if c in low})
        if found:
            offenders.append(f"  - {p.name}: {', '.join(found)}")
    if offenders:
        sys.exit(
            "BUILD FAILED - competitor name(s) found in article source.\n"
            "House rule (see source-library.md): never name or cite a competitor; "
            "keep comparisons to general categories.\n" + "\n".join(offenders)
        )


def copy_assets() -> None:
    """Copy brand assets (logos, favicon, OG image) into site/assets/ so they deploy + serve."""
    if not ASSETS_SRC.exists():
        return
    dst = OUT_DIR / "assets"
    dst.mkdir(parents=True, exist_ok=True)
    for f in ASSETS_SRC.iterdir():
        if f.is_file():
            shutil.copy2(f, dst / f.name)


def write_sitemap(articles: list[dict]) -> None:
    urls = [(CANONICAL_BASE + "/", date.today().isoformat())]
    for fm in articles:
        urls.append((f"{CANONICAL_BASE}/{fm['slug']}", iso(fm["date_modified"])))
    body = "".join(
        f"  <url>\n    <loc>{u}</loc>\n    <lastmod>{lm}</lastmod>\n  </url>\n" for u, lm in urls
    )
    (OUT_DIR / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + body + "</urlset>\n",
        encoding="utf-8",
    )


def write_robots() -> None:
    (OUT_DIR / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\n\nSitemap: {CANONICAL_BASE}/sitemap.xml\n", encoding="utf-8"
    )


def main() -> None:
    if not TEMPLATE.exists():
        sys.exit(f"Template not found: {TEMPLATE}")
    template = TEMPLATE.read_text(encoding="utf-8")
    OUT_DIR.mkdir(exist_ok=True)
    copy_assets()

    paths = [p for p in BLOG_DIR.glob("*.md") if p.name.lower() != "readme.md"]
    check_no_competitors(paths)
    articles = []
    titles: dict[str, str] = {}
    for p in paths:
        fm, body = parse_article(p)
        fm["_body"] = body
        articles.append(fm)
        titles[fm["slug"]] = fm.get("title", fm["slug"])

    # Guardrail for "building more": any article not wired into a LIBRARY_GROUP still builds, but it
    # gets the default orange theme, a generic kicker, and no row on the home page. Warn so it's
    # obvious the article needs to be added to a section (see LIBRARY_GROUPS) to get its colors.
    orphans = sorted(s for s in titles if s not in SLUG_THEME)
    if orphans:
        print("  WARNING: these articles aren't in any LIBRARY_GROUP, so they get the default "
              "orange theme + no home row:")
        for s in orphans:
            print(f"    - {s}  (add it to a group in build.py to give it a section color + kicker)")

    only = sys.argv[1] if len(sys.argv) > 1 else None
    built = 0
    for fm in articles:
        if only and fm["slug"] != only:
            continue
        page = render(fm, fm["_body"], titles, template)
        (OUT_DIR / f"{fm['slug']}.html").write_text(page, encoding="utf-8")
        built += 1
        print(f"  built site/{fm['slug']}.html")

    if not only:
        (OUT_DIR / "index.html").write_text(build_index(articles), encoding="utf-8")
        print("  built site/index.html")
        write_sitemap(articles)
        write_robots()
        print("  built site/sitemap.xml + site/robots.txt")

    print(f"Done. {built} article page(s) -> {OUT_DIR}")


if __name__ == "__main__":
    main()
