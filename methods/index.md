# Methods

Pre-launch draft. The full methods page is at https://minornobles.github.io/brandtabulator/methods/

## Definitions

- **#**: Rank by staleness within this category. 1 = longest without a substantive edit.
- **Brand**: English Wikipedia article and Wikidata item (Q-id). Click either to see the source.
- **Last substantive edit**: Most recent English Wikipedia edit of 50 bytes or more by a non-bot account that was not later reverted.
- **90d edits / editors**: Edits to the English article in the 90 days to the issue date, and how many distinct accounts made them.
- **Reverted**: Of those 90-day edits, how many were reverted. A measure of contestation.
- **Statements (referenced)**: Number of statements on the Wikidata item, and how many carry at least one reference.
- **Ballast**: Share of Wikidata statements that carry a reference. Sourced, complete Wikidata is what lets the record hold up.
- **Identity links out**: Statements on the item that point to the brand's own products, brands, subsidiaries, holdings, founders, origin, motto, awards or executives. What the item says the brand is.
- **Key props**: Of six properties a brand item should carry: industry, product, parent, subsidiaries, owner-of, Google Knowledge Graph id.
- **Editions**: Language Wikipedias (and sister projects) with a page linked to this item. Sail area.
- **Refs**: Reference tags in the English article.
- **Words**: Approximate word count of the English article.
- **Reader views**: English Wikipedia views in the stated month from Wikimedia's "user" agent class: traffic that presents as a browser. Not a guarantee of a human.
- **Spider**: Views from declared crawlers such as Googlebot.
- **Automated**: Views from undeclared traffic that Wikimedia's heuristics flag as bot-like. The scraper signal.

## Key properties checked

industry (P452), product (P1056), parent (P749), subsidiary (P355), owner of (P1830), Google KG id (P2671)

## Identity links counted

product or material produced (P1056), brand (P1716), subsidiary (P355), owner of (P1830), notable work (P800), country of origin (P495), motto (P1451), award received (P166), significant event (P793), founded by (P112), chief executive officer (P169)

## Watch manufacturers

Full category query:

```sparql
SELECT DISTINCT ?item ?itemLabel ?sitelinks WHERE { { ?item wdt:P452 wd:Q41767 . } UNION { ?item wdt:P452 wd:Q63346664 . } UNION { ?item wdt:P1056 wd:Q178794 . } UNION { ?item wdt:P31 wd:Q136094627 . } ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> . ?item wikibase:sitelinks ?sitelinks . SERVICE wikibase:label { bd:serviceParam wikibase:language "en". } } ORDER BY DESC(?sitelinks) LIMIT 400
```

Added by hand: Seiko (Q322601): Not classified as a watch company in Wikidata (no industry/product statement); obviously belongs., Swatch (Q573422): Same..

Removed by hand: none.

Competitive set: none yet. One will be added only when it rests on a stated, sourced rule.
