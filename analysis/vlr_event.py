#!/usr/bin/env python3
"""
vlr_event.py

Helpers for reading a vlr.gg *event* (as opposed to a single player). Given an
event URL, enumerate its matches and collect every player who actually played
in one of them.

These build on the scraper package (scraper/matches.py, scraper/vlr_utils.py),
which is added to sys.path below so this module works whether it's imported
from the repo root or run directly from analysis/.

Requires:
    pip install requests beautifulsoup4
"""

import os
import re
import sys
import time
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

# Make the scraper package importable.
_SCRAPER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scraper")
if _SCRAPER_DIR not in sys.path:
    sys.path.insert(0, _SCRAPER_DIR)

from vlr_utils import BASE_URL, absolute, get_soup  # noqa: E402
from matches import parse_scoreboard_players  # noqa: E402


def parse_event(event_url: str):
    """Return (event_id, slug) parsed from any vlr.gg event URL, e.g.
    'https://www.vlr.gg/event/2860/vct-2026-americas-stage-1' or its
    '/event/matches/2860/...' variant."""
    m = re.search(r"/event/(?:matches/)?(\d+)/([\w-]+)", event_url)
    if not m:
        raise ValueError(f"Could not parse an event id from URL: {event_url}")
    return m.group(1), m.group(2)


def get_event_match_urls(
    event_url: str,
    session: requests.Session,
    cache: Optional[Dict[str, BeautifulSoup]] = None,
) -> List[str]:
    """Return the full URLs of every match listed on an event's matches page."""
    event_id, slug = parse_event(event_url)
    matches_url = f"{BASE_URL}/event/matches/{event_id}/{slug}/?series_id=all"
    soup = get_soup(matches_url, session)
    if cache is not None:
        cache[matches_url] = soup

    urls: List[str] = []
    seen = set()
    for a in soup.select("a.wf-module-item.match-item"):
        href = a.get("href", "")
        m = re.match(r"^/(\d+)/", href)
        if not m:
            continue
        mid = m.group(1)
        if mid in seen:
            continue
        seen.add(mid)
        urls.append(absolute(href))
    return urls


def get_event_players(
    event_url: str,
    session: requests.Session,
    cache: Optional[Dict[str, BeautifulSoup]] = None,
    delay: float = 0.2,
    verbose: bool = False,
) -> Dict[str, str]:
    """Return {player_id: ign} for every player who appeared on a scoreboard in
    any match of the event. IGNs are taken from the event's own scoreboards, so
    they reflect the name the player used during this event.
    """
    match_urls = get_event_match_urls(event_url, session, cache)
    if verbose:
        print(f"Event has {len(match_urls)} matches")

    players: Dict[str, str] = {}
    for i, url in enumerate(match_urls):
        if verbose:
            print(f"[{i + 1}/{len(match_urls)}] players from {url}")
        try:
            if cache is not None and url in cache:
                soup = cache[url]
            else:
                soup = get_soup(url, session)
                if cache is not None:
                    cache[url] = soup
        except requests.RequestException as e:
            print(f"    ! Failed to fetch {url}: {e}", file=sys.stderr)
            continue

        for p in parse_scoreboard_players(soup):
            if p["ign"]:
                players.setdefault(p["id"], p["ign"])

        if delay:
            time.sleep(delay)  # be polite to vlr.gg

    return players
