# vctgraphs

Scrape [vlr.gg](https://www.vlr.gg) and build player-connectivity graphs for
VCT events — nodes are the players in an event, and an edge connects two of
them whenever they've been teammates in a VCT-circuit match (this event or any
earlier one). Edge weight is the number of matches they shared a team in.

The repo ships pre-built graphs and renders for several 2026 regions:
`vct_america`, `vct_emea`, `vct_pac`, and `vct_cn` (each as a `.graphml` plus a
`.png`).

## Install

Requires Python 3.10+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

`matplotlib` is only needed to render graphs to PNG (`--draw`); scraping and
graph-building work without it.

## Usage

### Build a teammate graph for an event

Point `teammate_graph.py` at a vlr.gg event URL. It reads every player in the
event, walks each one's full VCT match history, and builds the connectivity
graph.

```bash
python analysis/teammate_graph.py https://www.vlr.gg/event/2977/vct-2026-americas-stage-2
```

Options:

- `--out PATH` — GraphML output path (default:
  `analysis/output/<event-slug>_teammates.graphml`)
- `--draw PATH` — also render a PNG of the graph (needs matplotlib)
- `--min-matches N` — minimum shared VCT matches for an edge (default: 1)
- `--delay SECONDS` — delay between requests, to stay polite to vlr.gg
  (default: 0.5)
- `--quiet` — suppress progress output

### Scrape an event roster

`playerscraper.py` pulls the current roster (team, IGN, real name, role,
country) for every team in an event.

```bash
python scraper/playerscraper.py --url https://www.vlr.gg/event/2977/vct-2026-americas-stage-2 \
    --out data/players.csv --json data/players.json
```

## Layout

```
scrape_defaults.py     Shared config: HTTP settings, classification rules,
                       DB paths, graph-rendering constants (single source of truth)
scraper/               vlr.gg scraping
  playerscraper.py       event roster -> CSV/JSON
  matches.py             per-match scoreboards, teammate maps
  teammates.py           a player's past teammates across VCT matches
  vlr_utils.py           HTTP client with retries/backoff, soup fetching
analysis/              graph building
  teammate_graph.py      event -> networkx graph -> GraphML (+ optional PNG)
  vlr_event.py           parse an event page into its players
  output/                generated GraphML/PNG (gitignored)
data/                  playerdata.db (SQLite cache) and scraped CSVs
```

Modules in `scraper/` and `analysis/` add the repo root to `sys.path` so they
can import `scrape_defaults`.

## Notes

- Scraped data is cached in a local SQLite database (`data/playerdata.db`) so
  re-runs don't re-fetch everything from vlr.gg.
- "VCT circuit" matches are identified by keywords in the event label (VCT,
  Champions, Masters, EWC, VCL, Challengers, Evo/Evolution); see
  `CIRCUIT_KEYWORDS` in `scrape_defaults.py`.
- Please respect vlr.gg — keep the request delay reasonable.
