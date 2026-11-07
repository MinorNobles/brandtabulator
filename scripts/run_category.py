#!/usr/bin/env python3
"""
Brandtabulator pipeline — one category per run.

Reads   categories/<slug>.json
Writes  data/<slug>/<YYYY-MM-DD>.csv, .json, latest.json, candidates.json
        categories/<slug>/index.md, index.html
        sitemap.xml (lastmod refresh)

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
    }
    m["ballast_pct"] = round(100 * refd / total, 1) if total else 0.0
    return m

def is_bot(rev):
    return bool(re.search(r"bot\b", rev.get("user", ""), re.I)) or any("bot" in t.lower() for t in rev.get("tags", []))

def wp_metrics(title, today):
    j = wp_api({"prop": "revisions|info", "rvlimit": "200", "rvprop": "timestamp|user|tags|size|comment", "titles": title})
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
COLS = ["label", "qid", "enwiki_title", "wp_last_substantive", "wp_last_50byte", "days_since_50byte", "rank_days_since_50byte", "wp_edits_90d", "wp_editors_90d", "wp_reverted_90d", "rank_wp_edits_90d", "wd_statements", "wd_referenced", "ballast_pct", "rank_ballast_pct", "key_props_present", "identity_links_out", "rank_identity_links_out", "n_inception", "wd_sitelinks", "wd_modified", "days_since_wd_edit", "wp_refs", "wp_words", "wp_refs_per_1000_words", "wp_newest_cite_year", "pv_user", "pv_spider", "pv_automated", "pv_all", "pv_bot_share", "rank_pv_user", "has_google_kg_id", "has_freebase_id", "has_official_name_history", "key_props_missing"]

def md_table(rows, cat):
    h = "| # stale | Brand | Last ≥50-byte edit | 90d edits/editors | Wikidata stmts (ref'd) | Ballast | Identity links out | Editions | Refs | Reader views | Bot share |\n|---|---|---|---|---|---|---|---|---|---|---|\n"
    for r in sorted(rows, key=lambda r: r.get("rank_days_since_50byte") or 999):
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
        if key == "wp_last_50byte": return (v or "")[:10], (v or "")[:10]
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
        hl = ' class="hl"' if r["qid"] in cat.get("highlight", []) else ""
        trs += f"<tr{hl}>{tds}</tr>"
    ths = "".join(f'<th data-kind="{k}" title="{H.escape(d)}" tabindex="0" role="button" aria-label="{H.escape(n)}: {H.escape(d)}. Click to sort.">{H.escape(n)}<span class="arr" aria-hidden="true"></span></th>' for (n, _, k, d) in COLDEFS)
    defs = "".join(f"<dt>{H.escape(n)}</dt><dd>{H.escape(d)}</dd>" for (n, _, _, d) in COLDEFS)
    ld = json.dumps({"@context":"https://schema.org","@type":"Dataset","name":f"Brandtabulator — {cat['name']} — {date}","description":"Public-record activity metrics for brands in this category, computed from Wikipedia and Wikidata.","dateModified":date,"license":"https://creativecommons.org/licenses/by-sa/4.0/","creator":{"@type":"Person","name":"Michael Quinn","url":"https://michaelquinn.ai"},"distribution":[{"@type":"DataDownload","encodingFormat":"text/csv","contentUrl":f"/data/{cat['slug']}/{date}.csv"},{"@type":"DataDownload","encodingFormat":"application/json","contentUrl":f"/data/{cat['slug']}/{date}.json"}]})
    n = len(rows); med_e = statistics.median([r.get("wp_edits_90d", 0) or 0 for r in rows]); med_b = statistics.median([r.get("ballast_pct", 0) for r in rows])
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
th{{font-weight:500;color:#555;text-align:left;font-size:12px;padding:10px 10px;border-bottom:1px solid #cfcdc5;white-space:nowrap;cursor:pointer;user-select:none;position:relative}}
th:hover,th:focus{{color:#1b1b1b;background:#f4f3ef;outline:none}}th .arr::after{{content:"";margin-left:6px;color:#999}}th.asc .arr::after{{content:"▲"}}th.desc .arr::after{{content:"▼"}}
th[title]:hover::before,th[title]:focus::before{{content:attr(title);position:absolute;left:0;top:100%;z-index:5;width:260px;white-space:normal;background:#1b1b1b;color:#f4f3ef;font-size:12px;line-height:1.4;padding:8px 10px;font-weight:400;cursor:default}}
td{{padding:11px 10px;border-bottom:1px solid #e3e1da;font-size:14px;vertical-align:top}}tr.hl td{{background:#fff8e6}}
.mono{{font-family:'IBM Plex Mono',ui-monospace,monospace}}.q{{font-size:12px;color:#555}}
dl{{display:grid;grid-template-columns:200px 1fr;gap:6px 16px;font-size:13px;margin:0}}dt{{font-weight:600}}dd{{margin:0;color:#444;line-height:1.45}}
.foot{{border-top:1px solid #cfcdc5;padding-top:20px;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:24px;font-size:13px;color:#444;line-height:1.5}}.foot b{{display:block;color:#1b1b1b;margin-bottom:4px;font-weight:600}}
details summary{{cursor:pointer;font-size:14px;font-weight:500}}
@media (max-width:760px){{main{{padding:24px 20px 48px;gap:22px}}h1{{font-size:30px}}.lead p{{font-size:17px}}.foot{{grid-template-columns:1fr}}dl{{grid-template-columns:1fr}}th[title]:hover::before{{display:none}}}}
</style></head>
<body>
<div class="mast"><div class="in"><div style="display:flex;gap:16px;align-items:baseline;flex-wrap:wrap"><a class="brand" href="/">Brandtabulator</a><span class="sub">working title · under the Brand AI Report</span></div><div class="sub" style="display:flex;gap:16px;flex-wrap:wrap"><a href="/categories/">Categories</a><a href="/methods/">Methods</a><a href="/data/">Data</a><span>Issue {date}</span></div></div></div>
<main>
<div style="display:flex;flex-direction:column;gap:10px"><div class="sub"><a href="/categories/">Categories</a> · {n} brands</div><h1>{H.escape(cat['name'])}</h1></div>
<div class="lead"><div class="sub" style="text-transform:uppercase;letter-spacing:.06em;font-size:12px;font-weight:500">This issue</div>
<p>Longest without a substantive edit: {H.escape(stale['label'])}, {stale.get('days_since_50byte')} days. Most recently worked on: {H.escape(fresh['label'])}. Category median is {med_e:g} edits per 90 days and {med_b:g}% of Wikidata statements referenced.</p>
<div class="sub">Every figure links to the Wikipedia article and Wikidata item it was computed from. Revision ids are in the <a href="/data/{cat['slug']}/{date}.json">JSON</a>.</div></div>
<div class="card">
<div style="display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px"><h2>The regatta</h2><span class="sub">Same wind for every boat. Click a heading to sort; hover for its definition. Default order: longest unupdated first.</span></div>
<div class="wrap"><table id="regatta"><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table></div>
<div class="sub">Edits: 90 days to {date}. Views: English Wikipedia, {pv_month}, by Wikimedia agent class. <a href="/data/{cat['slug']}/{date}.csv">CSV</a> · <a href="/data/{cat['slug']}/{date}.json">JSON</a> · <a href="/data/{cat['slug']}/candidates.json">Discovery candidates</a> · <a href="/methods/">Methods</a></div>
<details><summary>Column definitions</summary><div style="padding-top:12px"><dl>{defs}</dl></div></details>
</div>
<div class="foot">
<div><b>How this page is made</b>Computed from public Wikimedia data: Wikipedia revision history and pageviews, Wikidata items and statements. Membership of the category is editorial and listed in the repository. <a href="/methods/">Definitions</a>.</div>
<div><b>Agent classes</b>Reader = Wikimedia's "user" class, traffic that presents as a browser. Spider = declared crawlers. Automated = undeclared traffic flagged as bot-like. None measure AI retrieval through dumps or Enterprise feeds.</div>
<div><b>Author</b>Michael Quinn · <a href="https://michaelquinn.ai">michaelquinn.ai</a><br>Pages are regenerated weekly and never edited in place. Corrections are dated notes.</div>
</div>
</main>
<script>
(function(){{var t=document.getElementById('regatta');if(!t)return;var ths=t.tHead.rows[0].cells,tb=t.tBodies[0];
function sortBy(i,dir){{var k=ths[i].getAttribute('data-kind');var rows=Array.prototype.slice.call(tb.rows);
rows.sort(function(a,b){{var x=a.cells[i].getAttribute('data-v'),y=b.cells[i].getAttribute('data-v');
if(k==='num'){{x=parseFloat(x)||0;y=parseFloat(y)||0;return dir*(x-y);}}return dir*String(x).localeCompare(String(y));}});
rows.forEach(function(r){{tb.appendChild(r);}});
for(var j=0;j<ths.length;j++)ths[j].classList.remove('asc','desc');ths[i].classList.add(dir>0?'asc':'desc');}}
Array.prototype.forEach.call(ths,function(th,i){{var dir=1;function go(){{dir=th.classList.contains('asc')?-1:1;sortBy(i,dir);}}
th.addEventListener('click',go);th.addEventListener('keydown',function(e){{if(e.key==='Enter'||e.key===' '){{e.preventDefault();go();}}}});}});}})();
</script>
</body></html>"""

def update_sitemap(date, cat_slug):
    p = os.path.join(ROOT, "sitemap.xml")
    urls = {"/": date, "/methods/": date, "/categories/": date, "/data/": date, f"/categories/{cat_slug}/": date}
    if os.path.exists(p):
        for loc, lm in re.findall(r"<loc>([^<]+)</loc><lastmod>([^<]+)</lastmod>", open(p).read()):
            urls.setdefault(loc, lm)
    body = "".join(f"  <url><loc>{u}</loc><lastmod>{d}</lastmod></url>\n" for u, d in sorted(urls.items()))
    open(p, "w").write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + body + "</urlset>\n")

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
        open(os.path.join(pagedir, "index.md"), "w").write(f"# {cat['name']}\n\nIssue {date}. {len(rows)} brands. Ranked by staleness (longest unupdated first). Views: {pv_month}.\n\n" + md_table(rows, cat) + f"\nData: [CSV](/data/{a.slug}/{date}.csv) · [JSON](/data/{a.slug}/{date}.json) · [Methods](/methods/)\n")
        open(os.path.join(pagedir, "index.html"), "w").write(html_page(cat, rows, date, pv_month)); print("rendered from latest.json"); return

    if not a.skip_discovery and cat.get("discovery_sparql"):
        print("discovery query…", flush=True)
        try:
            cands = [{"qid": b["item"]["value"].rsplit("/", 1)[1], "label": b.get("itemLabel", {}).get("value"), "sitelinks": int(b.get("sitelinks", {}).get("value", 0))} for b in sparql(cat["discovery_sparql"])]
            json.dump({"computed_at": today.isoformat(), "query": cat["discovery_sparql"], "candidates": cands}, open(os.path.join(outdir, "candidates.json"), "w"), indent=1)
            print(f"  {len(cands)} candidates saved", flush=True)
        except Exception as ex:
            print("  discovery failed:", ex, flush=True)

    members = cat["members"]; ids = [m["qid"] for m in members]
    print(f"fetching {len(ids)} Wikidata items…", flush=True)
    ents = wd_entities(ids)
    rows = []
    for m in members:
        e = ents.get(m["qid"]); row = {"qid": m["qid"], "label": m.get("label") or e["labels"]["en"]["value"]}
        row.update(wd_metrics(e))
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
    open(os.path.join(pagedir, "index.md"), "w").write(f"# {cat['name']}\n\nIssue {date}. {len(rows)} brands. Ranked by staleness (longest unupdated first). Views: {pv_month}.\n\n" + md_table(rows, cat) + f"\nData: [CSV](/data/{a.slug}/{date}.csv) · [JSON](/data/{a.slug}/{date}.json) · [Methods](/methods/)\n")
    open(os.path.join(pagedir, "index.html"), "w").write(html_page(cat, rows, date, pv_month))
    update_sitemap(date, a.slug)
    print("done:", date, flush=True)

if __name__ == "__main__":
    main()
