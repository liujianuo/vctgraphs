#!/usr/bin/env python3
"""
teammates.py

Given a vlr.gg player URL, walk the player's *entire match history* and
collect every player who has appeared on the same team as them in a match,
restricted to matches played at a VCT event.

"VCT event" here means the event label vlr.gg shows in the player's
match-history list contains "VCT" (case-insensitive). vlr.gg prefixes the
whole VCT circuit this way, so this includes the league stages (e.g.
"VCT 26: AMER Stage 1") as well as Champions, Masters, Challengers, and
LOCK//IN. Note that this is broader than matching the full official event
title, many of which are branded "Champions Tour ..." / "Valorant Champions
..." without the "VCT" acronym.

Unlike a roster snapshot, this reflects who actually played alongside the
player over time: for each qualifying match, the match scoreboard is read and
the other players sharing the target player's team (in that match) are counted
as teammates.

Usage (as a library):
    from teammates import get_past_teammates
    names = get_past_teammates("https://www.vlr.gg/player/8480/aspas")

Usage (as a script):
    python teammates.py https://www.vlr.gg/player/8480/aspas

Requires:
    pip install requests beautifulsoup4
"""

import sys
from typing import List, Optional

import requests

from matches import get_teammate_map


def get_past_teammates(
    player_url: str,
    min_matches: int,
    session: Optional[requests.Session] = None,
    delay: float = 0.2,
    verbose: bool = False,
) -> List[str]:
    """Return a de-duplicated, sorted list of the IGNs of every player who has
    played on the same team as the given player, across all of that player's
    matches at VCT events (the match-history event label contains "VCT",
    case-insensitive; see the module docstring for what that covers).

    Only teammates the player shared at least `min_matches` matches with are
    included. The player themselves is excluded from the result.
    """
    own_session = session is None
    session = session or requests.Session()
    try:
        teammates = get_teammate_map(
            player_url, session, delay=delay, verbose=verbose
        )
        return sorted(
            (entry["ign"] for entry in teammates.values()
             if entry["matches"] >= min_matches),
            key=str.lower,
        )
    finally:
        if own_session:
            session.close()


def main():
    if len(sys.argv) < 2:
        print("Usage: python teammates.py <player_url>", file=sys.stderr)
        sys.exit(1)

    player_url = sys.argv[1]
    min_matches = 1
    if len(sys.argv) > 2:
        try:
            min_matches = int(sys.argv[2])
        except ValueError:
            print(f"Invalid minimum match count, using default: {min_matches}")
    names = get_past_teammates(player_url, min_matches, verbose=True)

    print(f"\n{len(names)} VCT teammates:")
    for name in names:
        print(f"  {name}")


if __name__ == "__main__":
    main()
