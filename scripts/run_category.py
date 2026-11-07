#!/usr/bin/env python3
"""
Brandtabulator pipeline — one category per run.

Reads   categories/<slug>.json
Writes  data/<slug>/<YYYY-MM-DD>.csv, .json, latest.json, candidates.json
        categories/<slug>/index.md, index.html
        index.html, categories/, data/, methods/ pages, llms.txt, robots.txt, sitemap.xml

All data is public Wikimedia data. Every request carries a contact-tagged
User-Agent and is paced; 429s back off and retry.

Usage:  python3 scripts/run_category.py watch-manufacturers [--date YYYY-MM-DD]
"""
import argparse, csv, datetime as dt, json, os, re, statistics, sys, time, urllib.parse
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTACT = os.environ.get("BT_CONTACT", "https://github.com/MinorNobles/brandtabulator")
UA = f"Brandtabulator/0.1 ({CONTACT})"
PACE = float(os.environ.get("BT_PACE_SECONDS", "1.2"))
S = requests.Session(); S.headers["User-Agent"] = UA
# The site's public address. Change this one value (or set BT_SITE_URL) when the site moves to its own domain.
SITE_URL = os.environ.get("BT_SITE_URL", "https://minornobles.github.io/brandtabulator").rstrip("/")
BASE = urllib.parse.urlparse(SITE_URL).path.rstrip("/")   # "/brandtabulator" today, "" on a custom domain

def fix_links(text):
    """Turn site-root links ("/methods/") into links that work under BASE."""
    return text.replace('href="/', f'href="{BASE}/').replace('](/', f']({BASE}/')

KEY_PROPS = {"P452": "industry", "P1056": "product", "P749": "parent", "P355": "subsidiary", "P1830": "owner of", "P2671": "Google KG id"}
IDENTITY_PROPS = ["P1056", "P1716", "P355", "P1830", "P800", "P495", "P1451", "P166", "P793", "P112", "P169"]

# ---------- HTTP ----------
def get(url, params=None, tries=6):
    for i in range(tries):
        r = S.get(url, params=params, timeout=60)
        if r.status_code == 429 or r.status_code >= 500:
            wait = min(60, 5 * (2 ** i)); print(f"  {r.status_code} on {url[:80]} — waiting {wait}s", flush=True); time.sleep(wait); continue
        r.raise_for_status(); time.sleep(PACE); return r
    raise RuntimeError(f"gave up on {url}")

def sparql(query):
    r = get("https://query.wikidata.org/sparql", {"format": "json", "query": query})
    return r.json()["results"]["bindings"]

def wd_entities(ids):
    out = {}
    for i in range(0, len(ids), 50):
        chunk = ids[i:i+50]
        j = get("https://www.wikidata.org/w/api.php", {"action": "wbgetentities", "format": "json", "props": "claims|sitelinks|info|labels|descriptions|aliases", "languages": "en", "ids": "|".join(chunk)}).json()
        out.update(j.get("entities", {}))
    return out

def wp_api(params):
    params = dict(params, action="query", format="json", formatversion="2")
    return get("https://en.wikipedia.org/w/api.php", params).json()

def pageviews(title, agent, start, end):
    t = urllib.parse.quote(title.replace(" ", "_"), safe="")
    url = f"https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/{agent}/{t}/monthly/{start}/{end}"
    r = S.get(url, timeout=60)
    if r.status_code == 404: time.sleep(PACE); return 0
    if r.status_code == 429:
        time.sleep(30); r = S.get(url, timeout=60)
    time.sleep(PACE)
    if not r.ok: return None
    return sum(i["views"] for i in r.json().get("items", []))

# ---------- metrics ----------
def wd_metrics(e):
    c = e.get("claims", {})
    total = sum(len(v) for v in c.values())
    refd = sum(1 for v in c.values() for s in v if s.get("references"))
    sl = e.get("sitelinks", {})
    inc = c.get("P571", [])
    m = {
        "wd_statements": total, "wd_referenced": refd, "wd_props": len(c), "wd_sitelinks": len(sl),
        "wd_modified": e.get("modified"), "wd_desc": (e.get("descriptions", {}).get("en") or {}).get("value"),
        "enwiki_title": (sl.get("enwiki") or {}).get("title"),
        "n_inception": len(inc),
        "key_props_present": sum(1 for p in KEY_PROPS if p in c),
        "key_props_missing": [KEY_PROPS[p] for p in KEY_PROPS if p not in c],
        "identity_links_out": sum(len(c[p]) for p in IDENTITY_PROPS if p in c),
        "has_freebase_id": "P646" in c, "has_google_kg_id": "P2671" in c,
        "has_official_name_history": "P1448" in c,
        "wd_lastrevid": e.get("lastrevid"),
    }
    m["ballast_pct"] = round(100 * refd / total, 1) if total else 0.0
    return m

def is_bot(rev):
    return bool(re.search(r"bot\b", rev.get("user", ""), re.I)) or any("bot" in t.lower() for t in rev.get("tags", []))

def wp_metrics(title, today):
    j = wp_api({"prop": "revisions|info", "rvlimit": "200", "rvprop": "ids|timestamp|user|tags|size|comment", "titles": title})
    page = j["query"]["pages"][0]
    if page.get("missing"): return {"wp_missing": True}
    revs = page.get("revisions", [])
    since = (today - dt.timedelta(days=90)).isoformat() + "T00:00:00Z"
    r90 = [r for r in revs if r["timestamp"] >= since]
    reverted = lambda r: "mw-reverted" in r.get("tags", [])
    sub = next((r for r in revs if not is_bot(r) and not reverted(r)), None)
    big = next((r for i, r in enumerate(revs) if not is_bot(r) and not reverted(r) and i < len(revs) - 1 and abs(r["size"] - revs[i+1]["size"]) >= 50), None)
    m = {
        "wp_length": page.get("length"), "wp_touched": page.get("touched"),
        "wp_edits_90d": len(r90), "wp_editors_90d": len({r["user"] for r in r90}),
        "wp_reverted_90d": sum(1 for r in r90 if reverted(r)), "wp_bot_90d": sum(1 for r in r90 if is_bot(r)),
        "wp_last_any": revs[0]["timestamp"] if revs else None,
        "wp_last_substantive": sub["timestamp"] if sub else None,
        "wp_last_50byte": big["timestamp"] if big else None,
        "wp_current_revid": revs[0]["revid"] if revs else None,
        "wp_last_substantive_revid": sub["revid"] if sub else None,
        "wp_last_substantive_parentid": sub.get("parentid") if sub else None,
        "wp_last_50byte_revid": big["revid"] if big else None,
        "wp_last_50byte_parentid": big.get("parentid") if big else None,
        "wp_revisions_examined": len(revs),
    }
    w = wp_api({"prop": "revisions", "rvprop": "content", "rvslots": "main", "titles": title})
    txt = w["query"]["pages"][0]["revisions"][0]["slots"]["main"]["content"]
    m["wp_refs"] = len(re.findall(r"<ref[ >]", txt))
    m["wp_words"] = len(re.sub(r"<[^>]+>|\{\{[^}]*\}\}|\[\[|\]\]", "", txt).split())
    yrs = [int(y) for y in re.findall(r"\|\s*(?:access-date|accessdate|date)\s*=\s*[^|}]*?(20\d\d)", txt)]
    m["wp_newest_cite_year"] = max(yrs) if yrs else None
    m["wp_refs_per_1000_words"] = round(1000 * m["wp_refs"] / m["wp_words"], 1) if m["wp_words"] else 0
    return m

def days_since(ts, today):
    return (today - dt.date.fromisoformat(ts[:10])).days if ts else None

def percentiles(rows, key, lower_is_better=False):
    vals = [r[key] for r in rows if r.get(key) is not None]
    n = len(vals)
    for r in rows:
        v = r.get(key)
        if v is None or n < 2: r["pct_" + key] = None; continue
        below = sum(1 for x in vals if x < v); equal = sum(1 for x in vals if x == v)
        p = 100 * (below + (equal - 1) / 2) / (n - 1)
        r["pct_" + key] = round(100 - p if lower_is_better else p, 1)

def rank(rows, key, reverse=True):
    s = sorted([r for r in rows if r.get(key) is not None], key=lambda r: r[key], reverse=reverse)
    for i, r in enumerate(s): r["rank_" + key] = i + 1

# ---------- output ----------
COLS = ["label", "qid", "in_set", "highlight", "dissolved", "manual_addition", "enwiki_title", "wp_current_revid", "wd_lastrevid", "wp_last_substantive", "wp_last_substantive_revid", "wp_last_50byte", "wp_last_50byte_revid", "days_since_50byte", "rank_days_since_50byte", "wp_edits_90d", "wp_editors_90d", "wp_reverted_90d", "rank_wp_edits_90d", "wd_statements", "wd_referenced", "ballast_pct", "rank_ballast_pct", "key_props_present", "identity_links_out", "rank_identity_links_out", "n_inception", "wd_sitelinks", "wd_modified", "days_since_wd_edit", "wp_refs", "wp_words", "wp_refs_per_1000_words", "wp_newest_cite_year", "pv_user", "pv_spider", "pv_automated", "pv_all", "pv_bot_share", "rank_pv_user", "has_google_kg_id", "has_freebase_id", "has_official_name_history", "key_props_missing"]

def md_table(rows, cat):
    h = "| # stale | Brand | Last ≥50-byte edit | 90d edits/editors | Wikidata stmts (ref'd) | Ballast | Identity links out | Editions | Refs | Reader views | Bot share |\n|---|---|---|---|---|---|---|---|---|---|---|\n"
    for r in sorted(rows, key=lambda r: r.get("rank_days_since_50byte") or 999):
        tag = (" · set" if r.get("in_set") else "") + (" · dissolved" if r.get("dissolved") else "")
        h += f"| {r.get('rank_days_since_50byte','')} | [{r['label']}](https://en.wikipedia.org/wiki/{urllib.parse.quote((r.get('enwiki_title') or '').replace(' ','_'))}) ([{r['qid']}](https://www.wikidata.org/wiki/{r['qid']})) | {(r.get('wp_last_50byte') or '')[:10]} | {r.get('wp_edits_90d','')} / {r.get('wp_editors_90d','')} | {r.get('wd_statements','')} ({r.get('wd_referenced','')}) | {r.get('ballast_pct','')}% | {r.get('identity_links_out','')} | {r.get('wd_sitelinks','')} | {r.get('wp_refs','')} | {r.get('pv_user','')} | {r.get('pv_bot_share','')}% |\n"
    return h

COLDEFS = [
    ("#", "rank_days_since_50byte", "num", "Rank by staleness within this category. 1 = longest without a substantive edit."),
    ("Brand", "label", "str", "English Wikipedia article and Wikidata item (Q-id). Click either to see the source."),
    ("Last substantive edit", "wp_last_50byte", "date", "Most recent English Wikipedia edit of 50 bytes or more by a non-bot account that was not later reverted."),
    ("90d edits / editors", "wp_edits_90d", "num", "Edits to the English article in the 90 days to the issue date, and how many distinct accounts made them."),
    ("Reverted", "wp_reverted_90d", "num", "Of those 90-day edits, how many were reverted. A measure of contestation."),
    ("Statements (referenced)", "wd_statements", "num", "Number of statements on the Wikidata item, and how many carry at least one reference."),
    ("Ballast", "ballast_pct", "num", "Share of Wikidata statements that carry a reference. Sourced, complete Wikidata is what lets the record hold up."),
    ("Identity links out", "identity_links_out", "num", "Statements on the item that point to the brand's own products, brands, subsidiaries, holdings, founders, origin, motto, awards or executives. What the item says the brand is."),
    ("Key props", "key_props_present", "num", "Of six properties a brand item should carry: industry, product, parent, subsidiaries, owner-of, Google Knowledge Graph id."),
    ("Editions", "wd_sitelinks", "num", "Language Wikipedias (and sister projects) with a page linked to this item. Sail area."),
    ("Refs", "wp_refs", "num", "Reference tags in the English article."),
    ("Words", "wp_words", "num", "Approximate word count of the English article."),
    ("Reader views", "pv_user", "num", "English Wikipedia views in the stated month from Wikimedia's \"user\" agent class: traffic that presents as a browser. Not a guarantee of a human."),
    ("Spider", "pv_spider", "num", "Views from declared crawlers such as Googlebot."),
    ("Automated", "pv_automated", "num", "Views from undeclared traffic that Wikimedia's heuristics flag as bot-like. The scraper signal."),
]

def html_page(cat, rows, date, pv_month):
    import html as H
    def cell(r, key):
        v = r.get(key)
        if key == "label":
            t = (r.get("enwiki_title") or "").replace(" ", "_")
            return f'<a href="https://en.wikipedia.org/wiki/{H.escape(urllib.parse.quote(t))}">{H.escape(r["label"])}</a> <span class="q"><a href="https://www.wikidata.org/wiki/{r["qid"]}">{r["qid"]}</a></span>', r["label"]
        if key == "wp_last_50byte":
            d = (v or "")[:10]; rid = r.get("wp_last_50byte_revid")
            if rid:
                href = f"https://en.wikipedia.org/w/index.php?diff={rid}" + (f"&oldid={r['wp_last_50byte_parentid']}" if r.get("wp_last_50byte_parentid") else "")
                return f'<a href="{href}" title="Open this edit on Wikipedia">{d}</a>', d
            return d, d
        if key == "wp_edits_90d": return f'{r.get("wp_edits_90d","")} / {r.get("wp_editors_90d","")}', r.get("wp_edits_90d") or 0
        if key == "wd_statements": return f'{r.get("wd_statements","")} <span class="q">({r.get("wd_referenced","")})</span>', r.get("wd_statements") or 0
        if key == "ballast_pct": return f'{v}%', v or 0
        if key in ("pv_user", "pv_spider", "pv_automated"): return (f'{v:,}' if isinstance(v, int) else ""), v or 0
        return ("" if v is None else str(v)), (v if v is not None else 0)
    trs = ""
    for r in sorted(rows, key=lambda r: r.get("rank_days_since_50byte") or 999):
        tds = ""
        for (_, key, kind, _) in COLDEFS:
            txt, val = cell(r, key)
            cls = ' class="mono"' if kind != "str" else ""
            tds += f'<td{cls} data-v="{H.escape(str(val))}">{txt}</td>'
        cls = ("hl " if (r.get("in_set") or r.get("highlight")) else "") + ("dis" if r.get("dissolved") else "")
        trs += f'<tr class="{cls.strip()}" data-set="{1 if r.get("in_set") else 0}">{tds}</tr>'
    ths = "".join(f'<th data-kind="{k}"><span class="hd" tabindex="0" role="button" data-tip="{H.escape(d)}" aria-label="Sort by {H.escape(n)}">{H.escape(n)}<span class="arr" aria-hidden="true"></span></span><button type="button" class="i" data-def="def-{i}" aria-label="Definition of {H.escape(n)}">i</button></th>' for i, (n, _, k, d) in enumerate(COLDEFS))
    defs = "".join(f'<dt id="def-{i}">{H.escape(n)}</dt><dd>{H.escape(d)}</dd>' for i, (n, _, _, d) in enumerate(COLDEFS))
    ld = json.dumps({"@context":"https://schema.org","@type":"Dataset","name":f"Brandtabulator — {cat['name']} — {date}","description":"Public-record activity metrics for brands in this category, computed from Wikipedia and Wikidata.","dateModified":date,"license":"https://creativecommons.org/licenses/by-sa/4.0/","url":f"{SITE_URL}/categories/{cat['slug']}/","creator":{"@type":"Person","name":"Michael Quinn","url":"https://michaelquinn.ai"},"distribution":[{"@type":"DataDownload","encodingFormat":"text/csv","contentUrl":f"{SITE_URL}/data/{cat['slug']}/{date}.csv"},{"@type":"DataDownload","encodingFormat":"application/json","contentUrl":f"{SITE_URL}/data/{cat['slug']}/{date}.json"}]})
    cs = cat.get("competitive_set") or {}; n_set = sum(1 for r in rows if r.get("in_set")); n_dis = sum(1 for r in rows if r.get("dissolved"))
    adds = ", ".join(H.escape(x.get("label", x["qid"])) for x in cat.get("manual_additions", []))
    n = len(rows); med_e = statistics.median([r.get("wp_edits_90d", 0) or 0 for r in rows]); med_b = statistics.median([r.get("ballast_pct", 0) for r in rows])
    has_rev = any(r.get("wp_current_revid") for r in rows)
    prov = ("Edit dates link to the edit itself. The JSON records the exact Wikipedia and Wikidata revisions each figure was computed from."
            if has_rev else "Each brand links to its Wikipedia article and Wikidata item.")
    ex = cat.get("exclude", {}) or {}
    if isinstance(ex, list): ex = {q: "" for q in ex}
    removed = ("Removed by hand, with reasons: " + "; ".join(f"{H.escape(q)} ({H.escape(why)})" for q, why in ex.items()) + ".") if ex else "Nothing removed by hand."
    if cs.get("members"):
        seg_html = f'<div class="seg" role="group" aria-label="Which brands to show"><button type="button" class="on" data-view="all">Full category <span class="n">{n}</span></button><button type="button" data-view="set">{H.escape(cs.get("name","Competitive set"))} <span class="n">{n_set}</span></button></div>'
        set_note = f'<span data-for="set" hidden><b>{H.escape(cs.get("name","Competitive set"))}:</b> {H.escape(cs.get("basis",""))} Chosen by {H.escape(cs.get("chosen_by","the author"))}; the list is in the <a href="https://github.com/MinorNobles/brandtabulator/blob/main/categories/{cat["slug"]}.json">category file</a>.</span>'
    else:
        seg_html = ""
        hl = ", ".join(H.escape(r["label"]) for r in rows if r.get("highlight"))
        set_note = ""
    stale = max(rows, key=lambda r: r.get("days_since_50byte") or 0); fresh = min(rows, key=lambda r: r.get("days_since_50byte") if r.get("days_since_50byte") is not None else 9999)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{H.escape(cat['name'])} — Brandtabulator</title>
<meta name="description" content="Weekly ranking of {H.escape(cat['name'].lower())} by how actively their public record on Wikipedia and Wikidata is maintained.">
<link rel="alternate" type="application/json" href="/data/{cat['slug']}/latest.json">
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<script type="application/ld+json">{ld}</script>
<style>
body{{margin:0;background:#f4f3ef;color:#1b1b1b;font-family:'IBM Plex Sans',system-ui,sans-serif;-webkit-font-smoothing:antialiased}}
a{{color:#0b4f8a;text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:3px}}a:hover{{color:#063a66}}
.mast{{border-bottom:1px solid #cfcdc5;background:#fbfaf7}}.mast .in{{max-width:1180px;margin:0 auto;padding:18px 32px;display:flex;justify-content:space-between;align-items:baseline;gap:24px;flex-wrap:wrap}}
.brand{{font-size:20px;font-weight:600;letter-spacing:-.01em;text-decoration:none;color:#1b1b1b}}.sub{{font-size:13px;color:#555}}
main{{max-width:1180px;margin:0 auto;padding:40px 32px 64px;display:flex;flex-direction:column;gap:32px}}
h1{{margin:0;font-size:40px;line-height:1.1;font-weight:600;letter-spacing:-.02em}}
.lead{{background:#fff;border:1px solid #cfcdc5;padding:24px 28px;display:flex;flex-direction:column;gap:8px}}.lead p{{margin:0;font-size:20px;line-height:1.4;font-weight:500}}
.card{{background:#fff;border:1px solid #cfcdc5;padding:22px 26px;display:flex;flex-direction:column;gap:14px}}
.card h2{{margin:0;font-size:18px;font-weight:600}}
.wrap{{overflow-x:auto}}table{{border-collapse:collapse;width:100%}}
th{{font-weight:500;color:#555;text-align:left;font-size:12px;padding:8px 10px;border-bottom:1px solid #cfcdc5;white-space:nowrap;user-select:none;position:relative}}
th .hd{{cursor:pointer;display:inline-block;padding:4px 0}}th .hd:hover,th .hd:focus-visible{{color:#1b1b1b;outline:none}}th .arr::after{{content:"";margin-left:6px;color:#999}}th.asc .arr::after{{content:"▲"}}th.desc .arr::after{{content:"▼"}}
th .i{{margin-left:6px;width:18px;height:18px;border:1px solid #cfcdc5;border-radius:50%;background:#fff;color:#555;font:inherit;font-size:11px;line-height:1;cursor:pointer;vertical-align:middle;padding:0}}th .i:hover,th .i:focus-visible{{border-color:#1b1b1b;color:#1b1b1b;outline:none}}
@media (hover:hover){{th .hd:hover::after{{content:attr(data-tip);position:absolute;left:0;top:100%;z-index:5;width:260px;white-space:normal;background:#1b1b1b;color:#f4f3ef;font-size:12px;line-height:1.4;padding:8px 10px;font-weight:400;pointer-events:none}}}}
dt.flash{{background:#fff8e6;outline:2px solid #e3d9b0}}
td{{padding:11px 10px;border-bottom:1px solid #e3e1da;font-size:14px;vertical-align:top}}tr.hl td{{background:#fff8e6}}tr.dis td{{color:#888}}tr.dis td a{{color:#6b7d8f}}tr.hidden{{display:none}}
.seg{{display:inline-flex;border:1px solid #cfcdc5;border-radius:4px;overflow:hidden}}.seg button{{font:inherit;font-size:13px;padding:10px 14px;min-height:44px;border:0;background:#fff;color:#1b1b1b;cursor:pointer}}.seg button+button{{border-left:1px solid #cfcdc5}}.seg button.on{{background:#1b1b1b;color:#f4f3ef}}.seg .n{{opacity:.7;margin-left:6px;font-family:'IBM Plex Mono',monospace;font-size:12px}}
.mono{{font-family:'IBM Plex Mono',ui-monospace,monospace}}.q{{font-size:12px;color:#555}}
dl{{display:grid;grid-template-columns:200px 1fr;gap:6px 16px;font-size:13px;margin:0}}dt{{font-weight:600}}dd{{margin:0;color:#444;line-height:1.45}}
.foot{{border-top:1px solid #cfcdc5;padding-top:20px;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:24px;font-size:13px;color:#444;line-height:1.5}}.foot b{{display:block;color:#1b1b1b;margin-bottom:4px;font-weight:600}}
details summary{{cursor:pointer;font-size:14px;font-weight:500}}
@media (max-width:760px){{main{{padding:24px 20px 48px;gap:22px}}h1{{font-size:30px}}.lead p{{font-size:17px}}.foot{{grid-template-columns:1fr}}dl{{grid-template-columns:1fr}}}}
</style></head>
<body>
<div class="mast"><div class="in"><div style="display:flex;gap:16px;align-items:baseline;flex-wrap:wrap"><a class="brand" href="/">Brandtabulator</a><span class="sub">working title · under the Brand AI Report</span></div><div class="sub" style="display:flex;gap:16px;flex-wrap:wrap"><a href="/categories/">Categories</a><a href="/methods/">Methods</a><a href="/data/">Data</a><span>Issue {date}</span></div></div></div>
<main>
<div style="display:flex;flex-direction:column;gap:10px"><div class="sub"><a href="/categories/">Categories</a> · {n} brands</div><h1>{H.escape(cat['name'])}</h1></div>
<div class="lead"><div class="sub" style="text-transform:uppercase;letter-spacing:.06em;font-size:12px;font-weight:500">This issue</div>
<p>Longest without a substantive edit: {H.escape(stale['label'])}, {stale.get('days_since_50byte')} days. Most recently worked on: {H.escape(fresh['label'])}. Category median is {med_e:g} edits per 90 days and {med_b:g}% of Wikidata statements referenced.</p>
<div class="sub">{prov} <a href="/data/{cat['slug']}/{date}.json">JSON</a> · <a href="/methods/">How this is measured</a></div></div>
<div class="card">
<div style="display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px"><h2>The regatta</h2><span class="sub">Same wind for every boat. Click a heading to sort; hover or tap ⓘ for its definition. Default order: longest unupdated first.</span></div>
{seg_html}
<div class="sub" id="viewnote"><span data-for="all"><b>Full category:</b> every Wikidata item that is classified as a watch company (industry horology or watchmaking, product watch, or instance of watch manufacturing company) and has an English Wikipedia article, as returned by <a href="/data/{cat['slug']}/candidates.json">this query</a>.</span>{set_note}</div>
<div class="sub">Click any column heading to sort by it. Click the <b>i</b> next to a heading to see what it measures. Questions: <a href="mailto:Michael@MichaelQuinn.ai">Michael@MichaelQuinn.ai</a></div>
<div class="wrap"><table id="regatta"><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table></div>
<div class="sub">Edits: 90 days to {date}. Views: English Wikipedia, {pv_month}, by Wikimedia agent class. <a href="/data/{cat['slug']}/{date}.csv">CSV</a> · <a href="/data/{cat['slug']}/{date}.json">JSON</a> · <a href="/data/{cat['slug']}/candidates.json">Discovery candidates</a> · <a href="/methods/">Methods</a></div>
<details><summary>Column definitions</summary><div style="padding-top:12px"><dl>{defs}</dl></div></details>
</div>
<div class="foot">
<div><b>How this page is made</b>Computed from public Wikimedia data: Wikipedia revision history and pageviews, Wikidata items and statements. Which brands appear follows a published query, with any hand additions named on this page. <a href="/methods/">Methods</a>.</div>
<div><b>Agent classes</b>Reader = Wikimedia's "user" class, traffic that presents as a browser. Spider = declared crawlers. Automated = undeclared traffic flagged as bot-like. None measure AI retrieval through dumps or Enterprise feeds.</div>
<div><b>Author</b>Michael Quinn · <a href="https://michaelquinn.ai">michaelquinn.ai</a><br>The page is regenerated each week; each week's data files are kept under their date. Corrections are dated notes. Pre-launch: issues before the first public one may be regenerated.</div>
</div>
</main>
<script>
(function(){{var t=document.getElementById('regatta');if(!t)return;var ths=t.tHead.rows[0].cells,tb=t.tBodies[0];
function sortBy(i,dir){{var k=ths[i].getAttribute('data-kind');var rows=Array.prototype.slice.call(tb.rows);
rows.sort(function(a,b){{var x=a.cells[i].getAttribute('data-v'),y=b.cells[i].getAttribute('data-v');
if(k==='num'){{x=parseFloat(x)||0;y=parseFloat(y)||0;return dir*(x-y);}}return dir*String(x).localeCompare(String(y));}});
rows.forEach(function(r){{tb.appendChild(r);}});
for(var j=0;j<ths.length;j++)ths[j].classList.remove('asc','desc');ths[i].classList.add(dir>0?'asc':'desc');}}
var seg=document.querySelector('.seg');if(seg){{seg.addEventListener('click',function(e){{var b=e.target.closest('button');if(!b)return;var v=b.getAttribute('data-view');
Array.prototype.forEach.call(seg.querySelectorAll('button'),function(x){{x.classList.toggle('on',x===b);}});
Array.prototype.forEach.call(tb.rows,function(r){{r.classList.toggle('hidden',v==='set'&&r.getAttribute('data-set')!=='1');}});
Array.prototype.forEach.call(document.querySelectorAll('#viewnote [data-for]'),function(x){{x.hidden=x.getAttribute('data-for')!==v;}});}});}}
Array.prototype.forEach.call(ths,function(th,i){{var hd=th.querySelector('.hd'),ib=th.querySelector('.i');
function go(){{sortBy(i,th.classList.contains('asc')?-1:1);hd.blur();}}
hd.addEventListener('click',go);hd.addEventListener('keydown',function(e){{if(e.key==='Enter'||e.key===' '){{e.preventDefault();go();}}}});
ib.addEventListener('click',function(e){{e.stopPropagation();var d=document.getElementById(ib.getAttribute('data-def'));var det=d&&d.closest('details');if(det)det.open=true;
if(d){{d.scrollIntoView({{behavior:'smooth',block:'center'}});d.classList.add('flash');setTimeout(function(){{d.classList.remove('flash');}},2500);}}}});}});}})();
</script>
</body></html>"""

IDENTITY_LABELS = {"P1056": "product or material produced", "P1716": "brand", "P355": "subsidiary", "P1830": "owner of", "P800": "notable work",
                   "P495": "country of origin", "P1451": "motto", "P166": "award received", "P793": "significant event", "P112": "founded by", "P169": "chief executive officer"}

SHELL_CSS = """body{margin:0;background:#f4f3ef;color:#1b1b1b;font-family:'IBM Plex Sans',system-ui,sans-serif;-webkit-font-smoothing:antialiased;line-height:1.5}
a{color:#0b4f8a;text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:3px}a:hover{color:#063a66}
.mast{border-bottom:1px solid #cfcdc5;background:#fbfaf7}.mast .in{max-width:900px;margin:0 auto;padding:18px 32px;display:flex;justify-content:space-between;align-items:baseline;gap:24px;flex-wrap:wrap}
.brand{font-size:20px;font-weight:600;text-decoration:none;color:#1b1b1b}.sub{font-size:13px;color:#555}
main{max-width:900px;margin:0 auto;padding:40px 32px 64px}
h1{margin:0 0 16px;font-size:36px;line-height:1.15;font-weight:600;letter-spacing:-.02em}h2{font-size:20px;margin:36px 0 10px;font-weight:600}h3{font-size:16px;margin:22px 0 6px}
p,li{font-size:16px}code,.mono{font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:13px}
pre{background:#fff;border:1px solid #cfcdc5;padding:12px 14px;overflow-x:auto;font-size:12px;white-space:pre-wrap}
dl{display:grid;grid-template-columns:220px 1fr;gap:8px 18px;margin:0}dt{font-weight:600}dd{margin:0;color:#333}
table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:9px 10px;border-bottom:1px solid #e3e1da;font-size:14px;vertical-align:top}th{font-weight:500;color:#555;font-size:12px}
.note{background:#fff;border:1px solid #cfcdc5;padding:14px 18px;margin:16px 0}
.foot{border-top:1px solid #cfcdc5;margin-top:48px;padding-top:16px;font-size:13px;color:#555}
@media (max-width:760px){main{padding:24px 20px 48px}h1{font-size:28px}dl{grid-template-columns:1fr}}"""

def shell(title, desc, body):
    import html as H
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{H.escape(title)}</title><meta name="description" content="{H.escape(desc)}">
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>{SHELL_CSS}</style></head><body>
<div class="mast"><div class="in"><div style="display:flex;gap:16px;align-items:baseline;flex-wrap:wrap"><a class="brand" href="/">Brandtabulator</a><span class="sub">working title · under the Brand AI Report</span></div><div class="sub" style="display:flex;gap:16px;flex-wrap:wrap"><a href="/categories/">Categories</a><a href="/methods/">Methods</a><a href="/data/">Data</a></div></div></div>
<main>{body}
<div class="foot">Michael Quinn · <a href="https://michaelquinn.ai">michaelquinn.ai</a> · Pre-launch draft. Computed from public Wikimedia data. Code: <a href="https://github.com/MinorNobles/brandtabulator">github.com/MinorNobles/brandtabulator</a></div>
</main></body></html>"""

def load_categories():
    cats = []
    for fn in sorted(os.listdir(os.path.join(ROOT, "categories"))):
        if not fn.endswith(".json"): continue
        c = json.load(open(os.path.join(ROOT, "categories", fn)))
        lp = os.path.join(ROOT, "data", c["slug"], "latest.json")
        c["_latest"] = json.load(open(lp)) if os.path.exists(lp) else None
        cats.append(c)
    return cats

def methods_body(cats):
    import html as H
    coldefs = "".join(f"<dt>{H.escape(n)}</dt><dd>{H.escape(d)}</dd>" for (n, _, _, d) in COLDEFS)
    keyp = ", ".join(f"{H.escape(v)} ({k})" for k, v in KEY_PROPS.items())
    idp = ", ".join(f"{H.escape(IDENTITY_LABELS.get(k, k))} ({k})" for k in IDENTITY_PROPS)
    percat = ""
    for c in cats:
        cs = c.get("competitive_set") or {}
        ex = c.get("exclude", {}) or {}
        if isinstance(ex, list): ex = {q: "" for q in ex}
        adds = "".join(f"<li>{H.escape(a.get('label', a['qid']))} ({a['qid']}): {H.escape(a.get('reason',''))}</li>" for a in c.get("manual_additions", [])) or "<li>None.</li>"
        exs = "".join(f"<li>{H.escape(q)}: {H.escape(why)}</li>" for q, why in ex.items()) or "<li>None. If any brand is ever removed by hand, it will be listed here with the reason.</li>"
        percat += f"""<h3>{H.escape(c['name'])}</h3>
<p><b>Full category.</b> Every Wikidata item returned by the query below that has an English Wikipedia article. Companies that Wikidata records as dissolved are kept and shown greyed.</p>
<pre>{H.escape(c.get('discovery_sparql',''))}</pre>
<p><b>Added by hand</b> (the query does not find them):</p><ul>{adds}</ul>
<p><b>Removed by hand:</b></p><ul>{exs}</ul>
{(f"<p><b>{H.escape(cs.get('name','Competitive set'))}.</b> {H.escape(cs.get('basis',''))} Chosen by: {H.escape(cs.get('chosen_by',''))}.</p>" if cs.get('members') else "<p><b>Competitive set.</b> None yet. One will be added only when it rests on a stated, sourced rule.</p>")}"""
    return f"""<h1>Methods</h1>
<div class="note"><b>Status.</b> Pre-launch draft, working title. Issues dated before the first public issue may be regenerated. From the first public issue on, each week's data files are kept unchanged under their date.</div>

<h2>What this measures</h2>
<p>When people ask AI assistants about products, the answers lean on the public record. This site looks at two parts of that record for each brand, and compares brands within a category.</p>
<p><b>The keel: facts.</b> The brand's entry in Wikidata, a free database of facts that search engines and other knowledge graphs reuse. How many of its facts carry a source, whether the basics are filled in, and whether it points to the brand's own products and companies.</p>
<p><b>The sails: descriptions.</b> The brand's English Wikipedia article. How many references it has, how many languages it exists in, how often it is edited, and when someone last made a real change to it.</p>
<p>It also counts how often machines load the article. It does not rank brands as products, and it does not say which brands are best.</p>

<h2>Which brands are included</h2>
<p>Each category has two lists. The <b>full category</b> comes from a published query, so anyone can reproduce it. A <b>competitive set</b> is a smaller list chosen by a person, and the page says who chose it and why.</p>
{percat}

<h2>Definitions</h2>
<dl>{coldefs}</dl>
<h3>Details behind the definitions</h3>
<ul>
<li><b>Bot edits</b> are edits by an account whose name ends in "bot", or edits tagged as bot edits. They are left out of "last substantive edit".</li>
<li><b>Reverted edits</b> are edits Wikipedia itself tags as reverted. They are left out of "last substantive edit".</li>
<li><b>Last substantive edit</b> looks at the article's most recent 200 revisions. If none of them qualifies, the field is blank.</li>
<li><b>Statements</b> counts every statement on the Wikidata item, including identifiers such as stock tickers and database IDs.</li>
<li><b>Key properties</b> checked: {keyp}.</li>
<li><b>Identity links</b> counted: {idp}.</li>
<li><b>Editions</b> counts every Wikimedia site linked to the item, including Wikimedia Commons, not only language Wikipedias.</li>
<li><b>References</b> counts &lt;ref&gt; tags in the article's source, so a reference used twice counts twice. Word counts are approximate.</li>
</ul>

<h2>Views and machine visits</h2>
<p>Views come from Wikimedia's public pageview service, for English Wikipedia, for the previous full calendar month. Wikimedia sorts traffic into three classes. <b>Reader</b> ("user"): traffic that looks like a person using a browser. Some automated traffic that disguises itself ends up here. <b>Spider</b>: crawlers that identify themselves, such as Googlebot. <b>Automated</b>: traffic Wikimedia's own checks flag as automated.</p>
<p>These counts cannot see the bulk copies of Wikipedia that search and AI companies take directly, through downloads and Wikimedia's paid feed. No one outside those companies can see that. Machine visits here are a floor, the same floor for every brand.</p>

<h2>Rankings</h2>
<p>The default order is by staleness: the brand that has gone longest without a substantive edit comes first. Any column can be used to sort. There is no combined score yet.</p>

<h2>How the numbers are checked</h2>
<p>All figures are fetched from Wikimedia's public services by a published script, which runs every Monday on GitHub. Each request identifies the project, and requests are spaced out as Wikimedia asks. The first run was compared figure by figure with a separate hand pull, and they matched. Each brand's record in the JSON carries the revision ids it was computed from, so any figure can be traced to the exact version of the article or item.</p>
<p>Planned, not yet in place: an automatic week-on-week check that stops publication if numbers jump implausibly, and a check of any written summary against the edits it describes. Until then the author reviews each issue.</p>

<h2>If your brand is listed</h2>
<p>Anyone can correct facts in Wikidata, including people who work for the brand. Wikimedia's Terms of Use require anyone who is paid to edit, such as staff or an agency, to disclose that on their account. English Wikipedia also asks people with a conflict of interest not to edit the article directly, and to suggest changes on the article's talk page instead.</p>

<h2>Corrections</h2>
<p>Report an error on <a href="https://github.com/MinorNobles/brandtabulator/issues">GitHub</a> or through <a href="https://michaelquinn.ai">michaelquinn.ai</a>. Corrections are published as dated notes.</p>

<h2>Data and licence</h2>
<p>Wikipedia text is licensed CC BY-SA; Wikidata is CC0. The data files here are published under CC BY-SA 4.0. Weekly CSV and JSON files are on the <a href="/data/">data page</a>.</p>

<h2>Related work</h2>
<ul>
<li><b>QRank</b>: a ranking of Wikidata items by pageviews across Wikimedia sites, published on Wikimedia's cloud.</li>
<li><b>Recoin</b>: a Wikidata tool that shows which properties an item is missing compared with similar items.</li>
<li><b>Wiki3DRank</b> (Universidad de Murcia): a model that ranks topics by Wikidata statements, language editions and article length.</li>
<li><b>Dror Poleg's Wikipedia Power Ranking</b>: a weekly ranking of people by edits to their Wikipedia biographies.</li>
</ul>"""

def methods_md(cats):
    out = "# Methods\n\nPre-launch draft. The full methods page is at " + SITE_URL + "/methods/\n\n## Definitions\n\n"
    out += "".join(f"- **{n}**: {d}\n" for (n, _, _, d) in COLDEFS)
    out += "\n## Key properties checked\n\n" + ", ".join(f"{v} ({k})" for k, v in KEY_PROPS.items())
    out += "\n\n## Identity links counted\n\n" + ", ".join(f"{IDENTITY_LABELS.get(k,k)} ({k})" for k in IDENTITY_PROPS) + "\n"
    for c in cats:
        cs = c.get("competitive_set") or {}
        out += f"\n## {c['name']}\n\nFull category query:\n\n```sparql\n{c.get('discovery_sparql','')}\n```\n\nAdded by hand: " + (", ".join(f"{a.get('label')} ({a['qid']}): {a.get('reason','')}" for a in c.get('manual_additions', [])) or "none") + ".\n\nRemoved by hand: " + (", ".join(f"{q}: {w}" for q, w in (c.get('exclude') or {}).items()) or "none") + (f".\n\n{cs.get('name','Competitive set')}: {cs.get('basis','')} Chosen by: {cs.get('chosen_by','')}.\n" if cs.get('members') else ".\n\nCompetitive set: none yet. One will be added only when it rests on a stated, sourced rule.\n")
    return out

def build_site():
    """Home, categories, data and methods pages; llms.txt, robots.txt, sitemap.xml. All links built from SITE_URL."""
    import html as H
    cats = load_categories()
    def w(rel, text):
        path = os.path.join(ROOT, rel); os.makedirs(os.path.dirname(path), exist_ok=True); open(path, "w").write(fix_links(text))
    rows = ""; mdrows = ""
    for c in cats:
        L = c["_latest"]
        if not L: continue
        n = len(L["brands"]); d = L["computed_at"]
        rows += f'<tr><td><a href="/categories/{c["slug"]}/">{H.escape(c["name"])}</a></td><td class="mono">{n}</td><td class="mono">{d}</td><td>{H.escape(L.get("pageview_month",""))}</td></tr>'
        mdrows += f"| [{c['name']}](/categories/{c['slug']}/) | {n} | {d} |\n"
    cat_table = f'<table><thead><tr><th>Category</th><th>Brands</th><th>Issue</th><th>Views month</th></tr></thead><tbody>{rows}</tbody></table>'
    w("index.html", shell("Brandtabulator", "Weekly rankings of brands by how well their public record on Wikipedia and Wikidata is kept.",
        f"""<h1>Brandtabulator</h1>
<div style="background:#fff;border:1px solid #cfcdc5;padding:18px 22px;margin:8px 0 4px"><p style="margin:0 0 8px;font-weight:600">Why this matters to a marketing team</p><p style="margin:0 0 8px">When a customer asks AI about a brand or category, the AI leans heavily on Wikipedia and the facts behind it in Wikidata. When a brand's pages are thin, out of date, or contradictory, AI can describe the brand incorrectly or mix it up with another company.</p><p style="margin:0">Your team can't see this from inside the company. Brandtabulator shows where your brand stands against everyone else in its category, week by week, and what is missing.</p></div>
<h2>Categories</h2>{cat_table}
<p><a href="/methods/">How this is measured</a> · <a href="/data/">Data files</a></p>"""))
    w("categories/index.html", shell("Categories — Brandtabulator", "Brand categories covered by Brandtabulator.", f"<h1>Categories</h1>{cat_table}"))
    w("categories/index.md", "# Categories\n\n| Category | Brands | Issue |\n|---|---|---|\n" + mdrows)
    drows = ""; dmd = ""
    for c in cats:
        dd = os.path.join(ROOT, "data", c["slug"])
        if not os.path.isdir(dd): continue
        files = sorted([f for f in os.listdir(dd) if f.endswith((".csv", ".json"))], reverse=True)
        def label(f):
            if f == "latest.json": return "Latest issue (JSON)"
            if f == "candidates.json": return "Full-category query results"
            return ("Issue " + f.rsplit(".", 1)[0] + (" (CSV)" if f.endswith(".csv") else " (JSON)"))
        items = "".join(f'<li><a href="/data/{c["slug"]}/{f}">{label(f)}</a></li>' for f in files)
        drows += f"<h2>{H.escape(c['name'])}</h2><ul>{items}</ul>"
        dmd += f"\n## {c['name']}\n\n" + "".join(f"- [{label(f)}](/data/{c['slug']}/{f})\n" for f in files)
    w("data/index.html", shell("Data — Brandtabulator", "Weekly data files.", f"<h1>Data</h1><p>Each week's figures, as CSV and JSON. Each brand's JSON record includes the Wikipedia and Wikidata revision ids the figures came from. Licence: CC BY-SA 4.0.</p>{drows}"))
    w("data/index.md", "# Data\n" + dmd)
    w("methods/index.html", shell("Methods — Brandtabulator", "How Brandtabulator measures brands' public records.", methods_body(cats)))
    w("methods/index.md", methods_md(cats))
    catlines = "".join(f"- {c['name']}: {SITE_URL}/categories/{c['slug']}/ (Markdown: {SITE_URL}/categories/{c['slug']}/index.md; data: {SITE_URL}/data/{c['slug']}/latest.json)\n" for c in cats if c["_latest"])
    open(os.path.join(ROOT, "llms.txt"), "w").write(f"""# Brandtabulator

> Weekly rankings of brands, by category, by how complete and current their public record on Wikipedia and Wikidata is, and how often machines read it. Author: Michael Quinn (michaelquinn.ai). Part of the Brand AI Report. Pre-launch draft.

## Categories

{catlines}
## Reference

- Methods: {SITE_URL}/methods/ (Markdown: {SITE_URL}/methods/index.md)
- Data files: {SITE_URL}/data/
- Source code: https://github.com/MinorNobles/brandtabulator

## Conventions

- Each brand's JSON record carries the Wikipedia and Wikidata revision ids its figures were computed from.
- Category pages and the methods page have Markdown versions at index.md in the same folder.
- Reader views are Wikimedia's "user" agent class; spider and automated classes are reported separately. None measure AI companies' bulk use of Wikipedia.
""")
    open(os.path.join(ROOT, "robots.txt"), "w").write(f"User-agent: *\nAllow: /\n\nSitemap: {SITE_URL}/sitemap.xml\n")
    today = dt.date.today().isoformat()
    urls = [("/", today), ("/methods/", today), ("/categories/", today), ("/data/", today)] + [(f"/categories/{c['slug']}/", c["_latest"]["computed_at"]) for c in cats if c["_latest"]]
    body = "".join(f"  <url><loc>{SITE_URL}{u}</loc><lastmod>{d}</lastmod></url>\n" for u, d in urls)
    open(os.path.join(ROOT, "sitemap.xml"), "w").write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + body + "</urlset>\n")

# ---------- main ----------
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("slug"); ap.add_argument("--date"); ap.add_argument("--skip-discovery", action="store_true"); ap.add_argument("--render-only", action="store_true", help="rebuild pages from data/<slug>/latest.json without fetching")
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
    cat = json.load(open(os.path.join(ROOT, "categories", a.slug + ".json")))
    outdir = os.path.join(ROOT, "data", a.slug); os.makedirs(outdir, exist_ok=True)
    pagedir = os.path.join(ROOT, "categories", a.slug); os.makedirs(pagedir, exist_ok=True)

    # previous full month for pageviews
    first = today.replace(day=1); last_prev = first - dt.timedelta(days=1); start = last_prev.replace(day=1)
    pv_start, pv_end = start.strftime("%Y%m%d"), last_prev.strftime("%Y%m%d"); pv_month = start.strftime("%B %Y")

    if a.render_only:
        meta = json.load(open(os.path.join(outdir, "latest.json"))); rows = meta["brands"]; date = meta["computed_at"]; pv_month = meta["pageview_month"]
        set_q = set((cat.get("competitive_set") or {}).get("members", [])); hl_q = set((cat.get("highlight") or {}).get("members", []))
        for r in rows: r["in_set"] = r["qid"] in set_q; r["highlight"] = r["qid"] in hl_q
        open(os.path.join(pagedir, "index.md"), "w").write(fix_links(f"# {cat['name']}\n\nIssue {date}. {len(rows)} brands. Ranked by staleness (longest unupdated first). Views: {pv_month}.\n\n" + md_table(rows, cat) + f"\nData: [CSV](/data/{a.slug}/{date}.csv) · [JSON](/data/{a.slug}/{date}.json) · [Methods](/methods/)\n"))
        open(os.path.join(pagedir, "index.html"), "w").write(fix_links(html_page(cat, rows, date, pv_month))); build_site(); print("rendered from latest.json"); return

    if not a.skip_discovery and cat.get("discovery_sparql"):
        print("discovery query…", flush=True)
        try:
            cands = [{"qid": b["item"]["value"].rsplit("/", 1)[1], "label": b.get("itemLabel", {}).get("value"), "sitelinks": int(b.get("sitelinks", {}).get("value", 0))} for b in sparql(cat["discovery_sparql"])]
            json.dump({"computed_at": today.isoformat(), "query": cat["discovery_sparql"], "candidates": cands}, open(os.path.join(outdir, "candidates.json"), "w"), indent=1)
            print(f"  {len(cands)} candidates saved", flush=True)
        except Exception as ex:
            print("  discovery failed:", ex, flush=True)

    members = list(cat.get("members", [])) + list(cat.get("manual_additions", []))
    if cat.get("members_from_discovery"):
        cpath = os.path.join(outdir, "candidates.json")
        cands = json.load(open(cpath))["candidates"] if os.path.exists(cpath) else []
        have = {m["qid"] for m in members}
        ex = cat.get("exclude", {}); excl = set(ex.keys() if isinstance(ex, dict) else ex)   # only if Michael lists them, with reasons
        for c in cands:
            if c["qid"] not in have and c["qid"] not in excl:
                members.append({"qid": c["qid"], "label": c.get("label")}); have.add(c["qid"])
    ids = [m["qid"] for m in members]
    print(f"fetching {len(ids)} Wikidata items…", flush=True)
    ents = wd_entities(ids)
    members = [m for m in members if ents.get(m["qid"])]
    seen = set(); members = [m for m in members if not (m["qid"] in seen or seen.add(m["qid"]))]
    rows = []
    for m in members:
        e = ents.get(m["qid"]); row = {"qid": m["qid"], "label": m.get("label") or (e.get("labels", {}).get("en") or {}).get("value") or m["qid"]}
        row.update(wd_metrics(e))
        row["dissolved"] = "P576" in e.get("claims", {})
        row["in_set"] = m["qid"] in set((cat.get("competitive_set") or {}).get("members", []))
        row["highlight"] = m["qid"] in set((cat.get("highlight") or {}).get("members", []))
        row["manual_addition"] = m["qid"] in {x["qid"] for x in cat.get("manual_additions", [])}
        title = m.get("enwiki") or row.get("enwiki_title")
        if title:
            print(f"  {row['label']}: Wikipedia…", flush=True)
            row.update(wp_metrics(title, today))
            row.update({f"pv_{ag}": pageviews(title, ag, pv_start, pv_end) for ag in ("user", "spider", "automated")})
            row["pv_all"] = sum(v for v in (row["pv_user"], row["pv_spider"], row["pv_automated"]) if v)
            row["pv_bot_share"] = round(100 * (row["pv_all"] - (row["pv_user"] or 0)) / row["pv_all"], 1) if row["pv_all"] else None
        row["days_since_50byte"] = days_since(row.get("wp_last_50byte"), today)
        row["days_since_substantive"] = days_since(row.get("wp_last_substantive"), today)
        row["days_since_wd_edit"] = days_since(row.get("wd_modified"), today)
        rows.append(row)

    for key, lower in [("days_since_50byte", True), ("ballast_pct", False), ("wp_edits_90d", False), ("pv_user", False), ("identity_links_out", False), ("wd_statements", False), ("wd_sitelinks", False), ("wp_refs_per_1000_words", False), ("pv_bot_share", True)]:
        percentiles(rows, key, lower); rank(rows, key, reverse=(key != "pv_bot_share"))  # staleness rank: longest unupdated = 1

    date = today.isoformat()
    with open(os.path.join(outdir, f"{date}.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
    meta = {"category": cat["name"], "slug": a.slug, "computed_at": date, "edit_window_days": 90, "pageview_month": pv_month, "pageview_range": [pv_start, pv_end],
            "median_edits_90d": statistics.median([r.get("wp_edits_90d", 0) or 0 for r in rows]), "median_ballast_pct": statistics.median([r.get("ballast_pct", 0) for r in rows]),
            "user_agent": UA, "brands": rows}
    json.dump(meta, open(os.path.join(outdir, f"{date}.json"), "w"), indent=1)
    json.dump(meta, open(os.path.join(outdir, "latest.json"), "w"), indent=1)
    open(os.path.join(pagedir, "index.md"), "w").write(fix_links(f"# {cat['name']}\n\nIssue {date}. {len(rows)} brands. Ranked by staleness (longest unupdated first). Views: {pv_month}.\n\n" + md_table(rows, cat) + f"\nData: [CSV](/data/{a.slug}/{date}.csv) · [JSON](/data/{a.slug}/{date}.json) · [Methods](/methods/)\n"))
    open(os.path.join(pagedir, "index.html"), "w").write(fix_links(html_page(cat, rows, date, pv_month)))
    build_site()
    print("done:", date, flush=True)

if __name__ == "__main__":
    main()
