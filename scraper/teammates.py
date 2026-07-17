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
import time
from typing import Dict, List, Optional

import requests

from vlr_utils import get_soup, player_id as _player_id
from matches import iter_match_history, parse_scoreboard_teammates


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

    The player themselves is excluded from the result.
    """
    own_session = session is None
    session = session or requests.Session()
    me = _player_id(player_url)
    if not me:
        raise ValueError(f"Could not parse a player id from URL: {player_url}")

    try:
        # id -> ign, so the same person met across multiple matches counts once.
        teammates: Dict[str, str] = {}
        # id -> match count
        match_count: Dict[str, int] = {}

        # 1) Collect the VCT matches from the player's history, filtering on the
        #    event label shown in the history list (contains "VCT" for the whole
        #    VCT circuit — see the module docstring).
        vct_matches = [
            m for m in iter_match_history(player_url, session, delay=delay)
            if("vct"        in m["event_label"].lower() or
               "champions"  in m["event_label"].lower() or
               "masters"    in m["event_label"].lower() or
               "ewc"        in m["event_label"].lower()) and not (
               "showmatch"  in m["match_url"].lower() or
               "main-event" in m["match_url"].lower()
            )
            
        ]

        if verbose:
            print(f"Found {len(vct_matches)} VCT matches for {player_url}")

        # 2) For each VCT match, read the scoreboard and add teammates.
        for i, m in enumerate(vct_matches):
            if verbose:
                print(f"[{i + 1}/{len(vct_matches)}] "
                      f"{m['event_label']} — {m['match_url']}")
            try:
                soup = get_soup(m["match_url"], session)
            except requests.RequestException as e:
                print(f"    ! Failed to fetch {m['match_url']}: {e}",
                      file=sys.stderr)
                continue

            for p in parse_scoreboard_teammates(soup, me):
                id = p["id"]
                teammates.setdefault(id, p["ign"])
                if id in match_count:
                    match_count[id] = match_count[id] + 1
                else:
                    match_count[id] = 1

            if delay:
                time.sleep(delay)  # be polite to vlr.gg

        return sorted([teammates[k] for k in teammates.keys() if match_count[k] >= min_matches], key=str.lower) # check that each id has at least min_matches
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
        if isinstance(sys.argv[2], int):
            min_matches = sys.argv[2]
        else:
            print(f"Invalid minimum match count, using default: {min_matches}")
    names = get_past_teammates(player_url, min_matches, verbose=True)

    print(f"\n{len(names)} VCT teammates:")
    for name in names:
        print(f"  {name}")


if __name__ == "__main__":
    main()
