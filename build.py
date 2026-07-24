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
TEMPLATE = BLOG_DIR / "template.html"
SITE_URL = "https://www.gt.school"
# The library is hosted on Firebase for now, so the "Blog" breadcrumb points there.
# Swap to SITE_URL + "/blog" once the library moves onto the main gt.school site.
BLOG_INDEX_URL = "https://gt-school-blog.web.app/"

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
            "logo": {"@type": "ImageObject", "url": SITE_URL + "/logo.png"},
        },
        "mainEntityOfPage": {"@type": "WebPage", "@id": canonical},
        "url": canonical,
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
    canonical = f"{SITE_URL}/blog/{slug}"
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

    # The hero is a generated ombre panel (not a photo), so there is no og:image.
    og_img = ""

    repl = {
        "{{LANG}}": "en",
        "{{TITLE}}": html.escape(fm.get("title", h1)),
        "{{DESCRIPTION}}": html.escape(fm.get("description", "")),
        "{{CANONICAL}}": canonical,
        "{{SITE_URL}}": SITE_URL,
        "{{KEYWORDS}}": html.escape(", ".join(fm.get("target_queries") or [])),
        "{{CATEGORY}}": html.escape(fm.get("category", "Gifted Education")),
        "{{HUE}}": str(SLUG_HUE.get(slug, 45)),
        "{{DATE_PUBLISHED_ISO}}": iso(fm["date_published"]),
        "{{DATE_MODIFIED_ISO}}": iso(fm["date_modified"]),
        "{{DATE_PUBLISHED_HUMAN}}": human(fm["date_published"]),
        "{{DATE_MODIFIED_HUMAN}}": human(fm["date_modified"]),
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


# --- Library (index) configuration -------------------------------------------------
# One warm-guide page: reassuring intro + "reviewed by" + full-width search + a "start here"
# path, then articles grouped by the parent's real worry. Each group carries a soft pastel
# hue for its Q markers (peach -> pink -> orchid -> green; no yellow). Edit here to curate.
LIBRARY_INTRO = {
    "kicker": "Evidence Library",
    "h1": "Feeling lost with your gifted kid?<br>Let\u2019s figure it out together.",
    "sub": "Calm, clear answers to the questions gifted parents ask, grounded in real research.",
    "reviewed": "Written &amp; reviewed by GT School\u2019s gifted-education team",
}
LIBRARY_START_HERE = [
    ("Is my child gifted?", "signs-my-child-is-gifted"),
    ("Under-challenged?", "is-my-gifted-child-under-challenged"),
    ("Does acceleration work?", "does-academic-acceleration-actually-work"),
]
LIBRARY_GROUPS = [
    {"q": "Is my child actually gifted?", "h": 14, "items": [
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
    ]},
    {"q": "Is my child bored or under-challenged?", "h": 28, "items": [
        ("is-my-gifted-child-under-challenged", "Is my gifted child under-challenged?",
         "The signs a gifted child isn\u2019t being stretched, and what to do."),
        ("gifted-child-bored-what-are-my-options", "My gifted child is bored, what are my options?",
         "The real options when a bright kid is coasting, and how to choose."),
        ("how-to-advocate-for-your-gifted-child-at-school", "How do I advocate for my child at school?",
         "What to ask for, the evidence to bring, and what to do if they say no."),
    ]},
    {"q": "Should we let them move ahead?", "h": 50, "items": [
        ("does-academic-acceleration-actually-work", "Does academic acceleration actually work?",
         "Decades of research on whether moving faster actually helps."),
        ("does-grade-skipping-hurt-kids-socially", "Does grade-skipping hurt kids socially?",
         "What the research says about the social worry every parent has."),
        ("what-is-single-subject-acceleration", "What is single-subject acceleration?",
         "Move a child up in one subject while they stay with age peers."),
    ]},
    {"q": "How do gifted kids learn best?", "h": 80, "items": [
        ("what-is-mastery-based-learning", "What is a mastery-based (2-hour) model?",
         "Advance by mastery, not age or seat-time."),
        ("what-is-curriculum-compacting", "What is curriculum compacting?",
         "Skip what\u2019s already mastered so class time buys something new."),
        ("enrichment-vs-acceleration", "Enrichment vs. acceleration",
         "Deeper at grade level, or further ahead? When to use each."),
    ]},
    {"q": "Where should they go to school?", "h": 96, "items": [
        ("online-gifted-school-vs-homeschooling-gifted-child", "Online gifted school vs. homeschooling",
         "A neutral guide to pace, parent time, cost, and funding."),
        ("use-texas-tefa-voucher-online-gifted-school", "Can I use my Texas TEFA voucher online?",
         "How an approved Texas ESA can fund an accredited online school."),
        ("what-is-the-texas-education-freedom-account", "What is the Texas Education Freedom Account?",
         "What the Texas ESA is, how much it\u2019s worth, and who may qualify."),
    ]},
]

# Map each article slug to its theme hue (drives the per-article ombre hero + library markers).
SLUG_HUE = {slug: g["h"] for g in LIBRARY_GROUPS for (slug, _t, _b) in g["items"]}

_LIB_CSS = """<style>
  :root{--cream:oklch(97.5% 0.014 75);--paper:oklch(99.2% 0.006 85);--ink:oklch(24% 0.025 45);--muted:oklch(46% 0.03 45);--faint:oklch(63% 0.025 50);--line:oklch(89% 0.02 60);
    --accent:oklch(68% 0.15 45);--deep:oklch(52% 0.14 38);--soft:oklch(94% 0.045 55);
    --serif:"Fraunces",Georgia,serif;--sans:"IBM Plex Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;--mono:"IBM Plex Mono",ui-monospace,monospace}
  *{box-sizing:border-box}
  body{margin:0;background:var(--cream);color:var(--ink);font-family:var(--sans);-webkit-font-smoothing:antialiased}
  /* 888 = article reading width (840) + wrap padding (2x24), so the content column
     lines up exactly with the article pages (border-box includes the 24px padding). */
  .page{max-width:888px;margin:0 auto;padding:56px 24px 96px}
  a{color:inherit}
  /* richer multi-hue ombre hero */
  .top{position:relative;overflow:hidden;border:1px solid oklch(90% .04 55);border-radius:16px;padding:30px 30px 26px;margin-bottom:24px;
    background:
      radial-gradient(62% 95% at 6% 6%, oklch(90% .09 22/.92), transparent 72%),
      radial-gradient(58% 90% at 40% -12%, oklch(92% .078 55/.88), transparent 72%),
      radial-gradient(60% 92% at 84% 4%, oklch(92% .085 90/.88), transparent 72%),
      radial-gradient(64% 94% at 108% 55%, oklch(92% .072 150/.6), transparent 72%),
      radial-gradient(42% 64% at 100% 96%, oklch(89% .04 240/.28), transparent 70%),
      radial-gradient(60% 90% at 48% 132%, oklch(91% .07 330/.5), transparent 70%),
      linear-gradient(120deg, oklch(96.5% .035 55), oklch(98.6% .015 80));}
  /* matches the article "kicker" eyebrow (mono 12px, 0.08em tracking, 10px rounded rectangle) */
  .kick{display:inline-flex;align-items:center;gap:7px;font-family:var(--mono);font-size:12px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--deep);background:var(--paper);padding:7px 14px 7px 12px;border-radius:10px;margin:0 0 18px}
  .kick::before{content:"";width:6px;height:6px;border-radius:50%;background:var(--accent)}
  .h1{font-family:var(--serif);font-weight:600;font-size:30px;line-height:1.16;letter-spacing:-.01em;margin:0 0 8px;text-wrap:balance}
  .sub{font-family:var(--serif);color:var(--muted);font-size:16px;margin:0 0 16px;max-width:none}
  .rev{display:inline-flex;align-items:center;gap:7px;font-size:12.5px;color:var(--muted);margin:0 0 18px}
  .rev svg{width:15px;height:15px;flex:none}
  .rev svg .s{fill:none;stroke:var(--deep);stroke-width:2.4;stroke-linecap:round;stroke-linejoin:round}
  .search{display:flex;align-items:center;gap:10px;width:100%;background:var(--paper);border:1px solid oklch(88% .03 55);border-radius:12px;padding:13px 16px;margin:0 0 16px}
  .search svg{width:16px;height:16px;flex:none;stroke:var(--faint);fill:none;stroke-width:2}
  .search input{border:none;background:transparent;outline:none;width:100%;font-family:var(--sans);font-size:14px;color:var(--ink)}
  .search input::placeholder{color:var(--faint)}
  .starthere{display:flex;flex-wrap:wrap;align-items:center;gap:9px}
  .starthere .lbl{font-family:var(--mono);font-size:12.5px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:var(--deep)}
  .pill{font-family:var(--sans);font-size:13px;color:var(--ink);background:var(--paper);border:1px solid oklch(87% .04 50);border-radius:9px;padding:7px 14px;text-decoration:none}
  .pill:hover{border-color:var(--accent);color:var(--deep)}
  .sec{margin:26px 0 0}
  .qh{font-family:var(--serif);font-weight:600;font-size:19px;line-height:1.3;letter-spacing:-.01em;margin:0 0 6px;color:var(--ink)}
  .row{display:flex;gap:15px;padding:13px 12px;border-radius:12px;text-decoration:none;color:inherit;transition:background .13s ease}
  .row:hover{background:oklch(97.5% .022 var(--h))}
  .row .mark{font-family:var(--serif);font-weight:700;font-size:18px;line-height:1.35;color:oklch(72% .11 var(--h));flex:none;width:18px;text-align:center}
  .row .tx{flex:1;min-width:0}
  .row h4{font-family:var(--serif);font-weight:600;font-size:17px;line-height:1.25;margin:0 0 3px}
  .row:hover h4{color:oklch(54% .12 var(--h))}
  .row p{font-size:13.5px;line-height:1.5;color:var(--muted);margin:0}
  .row .ar{color:oklch(72% .11 var(--h));flex:none;align-self:center;font-size:15px}
  .noresults{font-family:var(--serif);color:var(--muted);font-size:16px;padding:20px 12px;display:none}
  footer.site{margin-top:44px;padding-top:24px;border-top:1px solid var(--line);font-family:var(--sans);font-size:13px;color:var(--faint)}
  @media (max-width:640px){.page{padding:40px 20px 80px}.h1{font-size:26px}.top{padding:24px 22px 22px}}
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


def build_index(articles: list[dict]) -> str:
    secs = []
    for g in LIBRARY_GROUPS:
        rows = []
        for slug, title, blurb in g["items"]:
            rows.append(
                f'<a class="row" href="{slug}.html"><span class="mark">Q</span>'
                f'<div class="tx"><h4>{html.escape(title)}</h4><p>{html.escape(blurb)}</p></div>'
                f'<span class="ar">\u2192</span></a>'
            )
        secs.append(
            f'<div class="sec" style="--h:{g["h"]}"><h3 class="qh">{html.escape(g["q"])}</h3>'
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
        f'<link rel="canonical" href="{SITE_URL}/blog"/>\n'
        '<link rel="preconnect" href="https://fonts.googleapis.com"/>\n'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>\n'
        '<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400..700;1,9..144,400..600&family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@500;600&display=swap" rel="stylesheet"/>\n'
        + _LIB_CSS + '\n</head>\n<body>\n<div class="page">\n'
        '  <div class="top">\n'
        f'    <p class="kick">{LIBRARY_INTRO["kicker"]}</p>\n'
        f'    <h1 class="h1">{LIBRARY_INTRO["h1"]}</h1>\n'
        f'    <p class="sub">{LIBRARY_INTRO["sub"]}</p>\n'
        '    <p class="rev"><svg viewBox="0 0 24 24"><path class="s" d="M12 3l7 3v5c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z"/><path class="s" d="M9 12l2 2 4-4"/></svg> '
        f'{LIBRARY_INTRO["reviewed"]}</p>\n'
        '    <div class="search"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><line x1="16.5" y1="16.5" x2="21" y2="21"/></svg>'
        '<input id="lib-search" type="search" placeholder="Search the library&hellip;" aria-label="Search the library"/></div>\n'
        f'    <div class="starthere"><span class="lbl">New here? Start with</span>{pills}</div>\n'
        '  </div>\n'
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


def main() -> None:
    if not TEMPLATE.exists():
        sys.exit(f"Template not found: {TEMPLATE}")
    template = TEMPLATE.read_text(encoding="utf-8")
    OUT_DIR.mkdir(exist_ok=True)

    paths = [p for p in BLOG_DIR.glob("*.md") if p.name.lower() != "readme.md"]
    check_no_competitors(paths)
    articles = []
    titles: dict[str, str] = {}
    for p in paths:
        fm, body = parse_article(p)
        fm["_body"] = body
        articles.append(fm)
        titles[fm["slug"]] = fm.get("title", fm["slug"])

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

    print(f"Done. {built} article page(s) -> {OUT_DIR}")


if __name__ == "__main__":
    main()
