# Methods

Stub. To be completed before the first issue.

## Sources
All data is public Wikimedia data: Wikipedia revision history and pageviews (by agent class), Wikidata items and statements, and QRank. Brand lists come from Wikidata SPARQL queries published alongside each category.

## Metrics (definitions to be finalised)
- Last substantive edit: most recent edit excluding bot accounts and reverted edits.
- 90-day edit velocity: edits in the last 90 days divided by the category median.
- Ballast: share of Wikidata statements carrying at least one reference; presence of key properties (industry, CEO, inception, official website, parent organization, subsidiaries).
- Editions: number of language Wikipedias with an article (sitelinks).
- Reader / spider / automated views: Wikimedia pageview agent classes, last 30 days.
- sameAs: whether the brand's official website declares its Wikidata item or Wikipedia article in schema.org markup.

## Verification
1. Deterministic checks: every link resolves, every revision id matches the data, every sentence carries a claim record, timestamps fall inside the issue window.
2. A second model, of a different family, checks each sentence against the linked record and logs the result. The log is published with the page.
3. A person reads every page before publication.

## Prior work
QRank (Wikimedia), Recoin (Wikidata gadget), Wiki3DRank (Universidad de Murcia), XTools, ORES, Dror Poleg's Wikipedia Power Ranking.

## Corrections
Pages are never edited in place. Corrections are dated notes linked from the page.
