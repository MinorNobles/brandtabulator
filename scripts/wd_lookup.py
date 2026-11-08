#!/usr/bin/env python3
"""
Wikidata lookups for drafting new categories. Run on GitHub (Actions → "Lookup"), because
the Claude workspaces cannot reach Wikidata.

Reads review/lookup_request.json:
  {"search": ["Coach handbags", ...],            # text searches: top hits with descriptions
   "items": ["Q123", ...],                       # items to describe: instance of, industry, products, parent
   "sparql": {"name": "SELECT ...", ...}}        # queries to run (count and first rows)
Writes review/lookup_result.json.
"""
import json, os, sys, time, requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = "BrandTabulator/0.1 (https://brandtabulator.michaelquinn.ai)"
S = requests.Session(); S.headers["User-Agent"] = UA
API = "https://www.wikidata.org/w/api.php"

def get(url, params):
    for i in range(6):
        r = S.get(url, params=params, timeout=90)
        if r.status_code == 429 or r.status_code >= 500: time.sleep(5 * 2 ** i); continue
        r.raise_for_status(); time.sleep(1.2); return r.json()
    raise RuntimeError("gave up")

def labels(ids):
    out = {}
    ids = [i for i in ids if i]
    for k in range(0, len(ids), 50):
        j = get(API, {"action": "wbgetentities", "ids": "|".join(ids[k:k+50]), "props": "labels|descriptions", "languages": "en", "format": "json"})
        for q, e in j.get("entities", {}).items():
            out[q] = ((e.get("labels") or {}).get("en", {}).get("value"), (e.get("descriptions") or {}).get("en", {}).get("value"))
    return out

def claim_ids(e, p):
    return [c["mainsnak"]["datavalue"]["value"]["id"] for c in e.get("claims", {}).get(p, []) if c["mainsnak"].get("datavalue")]

def main():
    req = json.load(open(os.path.join(ROOT, "review", "lookup_request.json")))
    res = {"search": {}, "items": {}, "sparql": {}}
    for term in req.get("search", []):
        j = get(API, {"action": "wbsearchentities", "search": term, "language": "en", "limit": 6, "format": "json"})
        res["search"][term] = [{"qid": h["id"], "label": h.get("label"), "description": h.get("description")} for h in j.get("search", [])]
    ids = req.get("items", [])
    for k in range(0, len(ids), 50):
        j = get(API, {"action": "wbgetentities", "ids": "|".join(ids[k:k+50]), "props": "labels|descriptions|claims|sitelinks", "languages": "en", "format": "json"})
        for q, e in j.get("entities", {}).items():
            props = {p: claim_ids(e, p) for p in ("P31", "P452", "P1056", "P749", "P127", "P355", "P1830", "P17")}
            names = labels(sorted({x for v in props.values() for x in v}))
            res["items"][q] = {"label": (e.get("labels") or {}).get("en", {}).get("value"),
                               "description": (e.get("descriptions") or {}).get("en", {}).get("value"),
                               "enwiki": (e.get("sitelinks") or {}).get("enwiki", {}).get("title"),
                               **{p: [[x, names.get(x, (None,))[0]] for x in v] for p, v in props.items()}}
    for name, q in (req.get("sparql") or {}).items():
        try:
            r = S.get("https://query.wikidata.org/sparql", params={"query": q, "format": "json"}, timeout=120); time.sleep(2)
            r.raise_for_status()
            rows = r.json()["results"]["bindings"]
            res["sparql"][name] = {"count": len(rows), "rows": [{k: v["value"].rsplit("/", 1)[-1] if v["type"] == "uri" else v["value"] for k, v in b.items()} for b in rows[:400]]}
        except Exception as ex:
            res["sparql"][name] = {"error": str(ex)[:300]}
    res["urls"] = {}
    for name, u in (req.get("urls") or {}).items():
        try:
            r = S.get(u, timeout=60); time.sleep(1.2)
            res["urls"][name] = r.json() if r.ok else {"status": r.status_code}
        except Exception as ex:
            res["urls"][name] = {"error": str(ex)[:200]}
    json.dump(res, open(os.path.join(ROOT, "review", "lookup_result.json"), "w"), indent=1, ensure_ascii=False)
    print("done")

if __name__ == "__main__":
    main()
