# Citizen Watch — first run, 7 November 2026

Category: watch manufacturers, Citizen's US mass/mid-market competitive set (14 brands). All data public Wikimedia data pulled 7 Nov 2026. Edits window: 90 days. Pageviews: October 2026, English Wikipedia, all access methods. Files: `watch_manufacturers_2026-11-07.csv` / `.json`.

## The regatta (activity rank, first-cut composite of edit velocity, ballast and recency)

| # | Brand | Last substantive edit | Last ≥50-byte edit | 90d edits / editors | Wikidata statements (referenced) | Ballast | Editions | Refs | Reader views Oct | Bot share |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Casio | 2026-11-07 | 2026-08-28 | 11 / 10 | 109 (43) | 39% | 56 | 60 | 18,070 | 22% |
| 2 | Orient | 2026-11-07 | 2026-11-07 | 6 / 6 | 25 (15) | 60% | 21 | 27 | 6,616 | 26% |
| 3 | Seiko | 2026-10-13 | 2026-09-20 | 7 / 5 | 66 (32) | 49% | 40 | 280 | 15,779 | 28% |
| 4 | Hamilton | 2026-10-23 | 2026-10-23 | 4 / 3 | 25 (15) | 60% | 16 | 35 | 8,971 | 20% |
| 5 | Tissot | 2026-09-20 | 2026-06-14 | 6 / 6 | 49 (27) | 55% | 38 | 34 | 7,637 | 27% |
| 6 | Longines | 2026-11-03 | 2026-09-16 | 5 / 5 | 44 (20) | 46% | 32 | 84 | 11,864 | 19% |
| **7** | **Citizen** | **2026-10-15** | **2026-08-25** | **3 / 3** | **49 (29)** | **59%** | **32** | **76** | **10,978** | **23%** |
| 8 | Bulova | 2026-10-17 | 2026-09-07 | 5 / 4 | 51 (15) | 29% | 22 | 54 | 8,732 | 23% |
| 9 | Rado | 2026-09-24 | 2026-09-24 | 1 / 1 | 32 (20) | 63% | 28 | 32 | 3,167 | 26% |
| 10 | Swatch | 2026-10-29 | 2025-10-28 | 7 / 5 | 44 (22) | 50% | 34 | 32 | 6,723 | 29% |
| 11 | Invicta | 2026-08-17 | 2026-06-26 | 2 / 2 | 14 (7) | 50% | 11 | 50 | 5,933 | 26% |
| 12 | Timex | 2026-09-01 | 2026-06-11 | 2 / 2 | 25 (13) | 52% | 16 | 80 | 9,704 | 23% |
| 13 | Fossil | 2026-10-08 | 2026-05-28 | 1 / 1 | 47 (15) | 32% | 14 | 28 | 7,254 | 29% |
| 14 | Movado | 2025-10-26 | 2024-04-17 | 0 / 0 | 33 (19) | 58% | 12 | 19 | 3,201 | 35% |

Category medians: 4.5 edits per 90 days; 51% of Wikidata statements referenced.

## Citizen: what the keel and sails actually show

**Two keels.** Wikidata has two "Citizen Watch" items. Q1368019 is the company (49 statements, 32 language editions, English article). Q14523570 is a second item typed as *trademark* (15 statements, founded 1918, site citizenwatch.com) and it is the one German and Spanish Wikipedia link to. It also holds the Google Knowledge Graph ID (/g/11cfty2wj). The company item holds only the older Freebase ID (/m/06y74g). Knowledge graphs see two Citizens.

**Four founding dates on one item.** Q1368019 carries inception = 1930 (as Citizen Watch Co.), 2007 (as Citizen Holdings), 2016 (renamed back) and 1918, all on the same property. Google's panel shows 1918. The English article leads with 1930.

**"Citizen Holdings" is an alias, not a former name.** No official-name property with start and end dates. Anything reading the item can't tell the name changed in 2007 and changed back in 2016.

**Ownership is one-way.** Bulova (owned by Citizen since 2008) and Frédérique Constant both point up to Citizen as parent. Citizen's item points down to none of them; its only listed subsidiary is Citizen Watch Manufacturing in Saitama. Alpina Watches has no link to Citizen at all and no English article. Arnold & Son has no Wikidata item.

**Citizen Watch America does not exist in the record.** No Wikipedia article, no Wikidata item, no search hit for the phrase on English Wikipedia. Seiko has a US item (thin, but present). The business the NY AI Summit guest runs is invisible to any system that resolves entities.

**The brand's own site declares nothing.** citizenwatch.com/us/en/ has no JSON-LD, no schema.org markup, no sameAs, no reference to Wikidata or Wikipedia. Nothing bolts the site to the keel.

**The sails are mid-fleet.** English article: 2,506 words, 76 references, newest source 2026, last substantive edit 15 Oct, last ≥50-byte change 25 Aug. Three edits by three editors in 90 days against a category median of 4.5. Reader views 10,978 in October, down 7% from September (11,810). Seventh of fourteen on activity. Not neglected, not maintained.

**Category findings worth a line each.** Seiko and the Swatch brand are not classified as watch companies in Wikidata (no industry/product statements), so no structured query finds them; they were added by hand. The structured query for watch manufacturers with English articles returns 143 items and includes Armani, Mango and Moschino. Movado's article has had no edit in over a year and no substantive change since April 2024. Bulova and Fossil have the lowest ballast (29%, 32%). Bot share of pageviews runs 19–35% across the set; Movado's is highest.

## Method notes for this run
- Brand list: Wikidata SPARQL (industry = horology or watchmaking, or product = watch, or instance of watch manufacturing company) with an English sitelink; competitive set then chosen by hand. Seiko (Q322601) and Swatch (Q573422) added manually.
- "Last substantive edit" = most recent edit not by a bot account and not tagged as reverted. "Last ≥50-byte edit" = same, with a size change of at least 50 bytes.
- Ballast = share of Wikidata statements carrying at least one reference.
- Pageviews: Wikimedia REST API, monthly, October 2026. Bot share = (all-agents − user) / all-agents. Spider and automated split available for Citizen, Seiko, Casio only this run.
- Activity score (first cut, to be replaced): 50 × velocity vs. median + 50 × ballast vs. median − 0.2 × days since last ≥50-byte edit.
- Pulled through the desktop browser pane because both shells are proxied off Wikimedia. Rate-limited twice at the pageview API; a proper run needs a User-Agent with contact info and spacing between calls.
