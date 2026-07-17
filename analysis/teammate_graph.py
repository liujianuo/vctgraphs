#!/usr/bin/env python3
"""
teammate_graph.py

Build a player-connectivity graph for a vlr.gg event.

Given an event URL, this:
  1. reads every player who played in a match at the event,
  2. for each of those players, walks their entire VCT-circuit match history to
     find everyone they've ever been on a team with, and
  3. builds a networkx graph whose nodes are the event's players and whose edges
     connect two of them whenever they have been teammates — in this event or in
     any earlier VCT match. Edge weight is the number of matches they shared a
     team in.

Only players who appear in the event are nodes; a shared history with someone
who isn't in the event does not create a node or edge.

Usage:
    python teammate_graph.py https://www.vlr.gg/event/2860/vct-2026-americas-stage-1
    python teammate_graph.py <event_url> --out graph.graphml --draw graph.png
    python teammate_graph.py <event_url> --min-matches 2 --delay 0.3

Requires:
    pip install httpx beautifulsoup4 networkx
    # matplotlib is only needed for --draw
"""

import argparse
import os
import sys
from typing import Dict

import httpx
import networkx as nx

# Make the scraper package importable (matches.py, vlr_utils.py).
_SCRAPER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scraper")
if _SCRAPER_DIR not in sys.path:
    sys.path.insert(0, _SCRAPER_DIR)

from vlr_utils import BASE_URL, make_client  # noqa: E402
from matches import get_teammate_map  # noqa: E402
from vlr_event import get_event_players, parse_event  # noqa: E402


def build_teammate_graph(
    event_url: str,
    session: httpx.Client,
    min_matches: int = 1,
    delay: float = 0.2,
    verbose: bool = True,
) -> nx.Graph:
    """Build and return the event's teammate-connectivity graph (see module
    docstring). Nodes are player ids with `ign` / `label` attributes; edges
    carry a `weight` = number of shared VCT matches."""
    # A single soup cache shared across the whole build: match pages recur both
    # across the event's own matches and across players' histories, so caching
    # them saves a large number of requests.
    cache: Dict[str, object] = {}

    players = get_event_players(event_url, session, cache, delay=delay, verbose=verbose)
    if verbose:
        print(f"\n{len(players)} players played in this event.\n")

    graph = nx.Graph()
    for pid, ign in players.items():
        graph.add_node(pid, ign=ign, label=ign)

    player_ids = set(players)
    for i, (pid, ign) in enumerate(players.items(), start=1):
        if verbose:
            print(f"=== [{i}/{len(players)}] teammates of {ign} ({pid}) ===")
        player_url = f"{BASE_URL}/player/{pid}/{ign}"
        try:
            teammates = get_teammate_map(
                player_url, session, delay=delay, cache=cache, verbose=False
            )
        except (httpx.HTTPError, ValueError) as e:
            print(f"    ! Skipping {ign} ({pid}): {e}", file=sys.stderr)
            continue

        # Keep only teammates who are themselves in this event, meeting the
        # shared-match threshold.
        for other_id, info in teammates.items():
            if other_id == pid or other_id not in player_ids:
                continue
            if info["matches"] < min_matches:
                continue
            # add_edge is symmetric; if both directions are seen we keep the
            # larger shared-match count observed.
            w = int(info["matches"])
            if graph.has_edge(pid, other_id):
                w = max(w, graph[pid][other_id].get("weight", 0))
            graph.add_edge(pid, other_id, weight=w)

        if verbose:
            print(f"    degree so far: {graph.degree(pid)}")

    return graph


def draw_graph(graph: nx.Graph, path: str):
    """Render the graph to an image file with matplotlib (spring layout)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = {n: d.get("ign", n) for n, d in graph.nodes(data=True)}
    pos = nx.spring_layout(graph, k=0.5, seed=42)

    plt.figure(figsize=(16, 16))
    degrees = dict(graph.degree())
    node_sizes = [200 + 120 * degrees[n] for n in graph.nodes()]
    nx.draw_networkx_edges(graph, pos, alpha=0.25)
    nx.draw_networkx_nodes(graph, pos, node_size=node_sizes,
                           node_color="#4c78a8", alpha=0.9)
    nx.draw_networkx_labels(graph, pos, labels=labels, font_size=8)
    plt.axis("off")
    plt.tight_layout()
    plt.savefig(path, dpi=120, bbox_inches="tight")
    plt.close()


def print_summary(graph: nx.Graph):
    n, e = graph.number_of_nodes(), graph.number_of_edges()
    print("\n=== Graph summary ===")
    print(f"nodes (players): {n}")
    print(f"edges (teammate links): {e}")
    if n > 1:
        print(f"density: {nx.density(graph):.3f}")
    comps = list(nx.connected_components(graph))
    print(f"connected components: {len(comps)} "
          f"(largest: {max((len(c) for c in comps), default=0)})")
    top = sorted(graph.degree(), key=lambda kv: kv[1], reverse=True)[:10]
    if top:
        print("most-connected players:")
        for pid, deg in top:
            print(f"  {graph.nodes[pid].get('ign', pid):<16} {deg}")


def main():
    parser = argparse.ArgumentParser(
        description="Build a teammate-connectivity graph for a vlr.gg event.")
    parser.add_argument("event_url", help="vlr.gg event URL")
    parser.add_argument("--out", default=None,
                        help="Output GraphML path (default: analysis/output/"
                             "<event-slug>_teammates.graphml)")
    parser.add_argument("--draw", default=None,
                        help="Optional PNG path to render the graph (needs matplotlib)")
    parser.add_argument("--min-matches", type=int, default=1,
                        help="Minimum shared VCT matches for an edge (default: 1)")
    parser.add_argument("--delay", type=float, default=0.2,
                        help="Delay between requests in seconds (default: 0.2)")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output")
    args = parser.parse_args()

    _, slug = parse_event(args.event_url)
    out_path = args.out
    if out_path is None:
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{slug}_teammates.graphml")

    session = make_client()
    try:
        graph = build_teammate_graph(
            args.event_url, session,
            min_matches=args.min_matches,
            delay=args.delay,
            verbose=not args.quiet,
        )
    finally:
        session.close()

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    nx.write_graphml(graph, out_path)
    print(f"\nWrote graph to {out_path}")

    if args.draw:
        draw_graph(graph, args.draw)
        print(f"Wrote drawing to {args.draw}")

    print_summary(graph)


if __name__ == "__main__":
    main()
