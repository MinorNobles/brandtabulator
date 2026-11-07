# Pipeline

`run_category.py <slug>` reads `categories/<slug>.json`, pulls public Wikimedia data for each member brand, and writes the issue files (CSV, JSON, Markdown, HTML) plus a refreshed sitemap. It runs weekly on GitHub Actions (`.github/workflows/weekly.yml`), Mondays 06:17 UTC, and can be run by hand from the Actions tab.

Requests carry a User-Agent of `Brandtabulator/0.1 (<contact>)`. Set a repository variable `BT_CONTACT` (Settings → Secrets and variables → Actions → Variables) to a URL or mailbox Wikimedia can reach you at; it defaults to this repository's URL. Calls are paced at 1.2 s and back off on 429.

Metrics are defined on the methods page. Category membership is editorial: `members` is the ranked set; `discovery_sparql` only produces `candidates.json` for review.

## To do
- Sanity check before commit: compare each week's counts with the previous issue and refuse to publish on wild swings (tag renames, article renames, Wikidata merges should fail loudly). Add after two or three clean weekly runs.
- Pin `actions/checkout` and `actions/setup-python` to Node 24-compatible majors when GitHub finishes the Node 20 deprecation.
