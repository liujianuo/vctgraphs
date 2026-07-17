#!/usr/bin/env python3
"""
matches.py

Helpers for reading a vlr.gg player's match history and, for an individual
match, the scoreboard.

Two things are provided:

    iter_match_history(player_url, session)
        Yield every match in a player's history (paginated), as dicts with the
        match URL and the short event label shown on the history page.

    get_match_teammates(match_url, player_id, session)
        For a single match page, return the players who appeared on the same
        team as `player_id` in that match, read straight off the scoreboard.

The scoreboard is the source of truth for "who played together": every player
row carries a team tag (e.g. "MIBR"), so teammates are simply the other rows
sharing the target player's tag. Because the scoreboard only lists players who
actually played, benched/inactive roster members are naturally excluded.

Requires:
    pip install requests beautifulsoup4
"""

import re
import time
from typing import Dict, Iterator, List, Optional

import requests
from bs4 import BeautifulSoup

from vlr_utils import BASE_URL, absolute, get_soup, player_id as _player_id


def _match_id(match_url: str) -> Optional[str]:
    """Extract the numeric match id from a match URL like '/660378/...'."""
    m = re.search(r"/(\d+)/", match_url if match_url.startswith("/")
                  else match_url.replace(BASE_URL, ""))
    return m.group(1) if m else None


def iter_match_history(
    player_url: str,
    session: requests.Session,
    delay: float = 1.0,
) -> Iterator[Dict[str, str]]:
    """Yield {match_url, match_id, event_label} for every match in the
    player's history, walking the paginated /player/matches/ view until an
    empty page is reached."""
    pid = _player_id(player_url)
    if not pid:
        raise ValueError(f"Could not parse a player id from URL: {player_url}")

    # The history page slug doesn't matter to vlr.gg; the id is what counts.
    m = re.search(r"/player/\d+/([\w-]+)", player_url)
    slug = m.group(1) if m else pid
    base = f"{BASE_URL}/player/matches/{pid}/{slug}"

    seen_ids = set()
    page = 1
    while True:
        soup = get_soup(f"{base}?page={page}", session)
        cards = soup.select("a.wf-card.m-item")
        if not cards:
            break

        for card in cards:
            href = card.get("href", "")
            if not href:
                continue
            match_url = absolute(href)
            mid = _match_id(href)
            # Guard against duplicate/looping pages.
            if mid and mid in seen_ids:
                continue
            if mid:
                seen_ids.add(mid)

            event_label = ""
            event_tag = card.select_one(".m-item-event")
            if event_tag:
                # The first inner div is the event name; the rest is the
                # stage/series (e.g. "Playoffs · QF"). Take the first line.
                name_div = event_tag.find("div")
                event_label = (name_div.get_text(strip=True) if name_div
                               else event_tag.get_text(strip=True))

            yield {
                "match_url": match_url,
                "match_id": mid or "",
                "event_label": event_label,
            }

        page += 1
        if delay:
            time.sleep(delay)  # be polite to vlr.gg


def match_event_title(soup: BeautifulSoup) -> str:
    """The full event title shown in the match header, e.g.
    'VCT 2026: Americas Stage 1'."""
    header = soup.select_one("a.match-header-event")
    if not header:
        return ""
    name_div = header.select_one("div[style*='font-weight: 700']")
    if name_div:
        return name_div.get_text(strip=True)
    return header.get_text(" ", strip=True)


def parse_scoreboard_teammates(
    soup: BeautifulSoup,
    player_id: str,
) -> List[Dict[str, str]]:
    """Given a fetched match page, return [{id, ign}] for the players on the
    same team as `player_id` (excluding the player themselves), read from the
    scoreboard. De-duplicated by player id across the match's maps.

    Returns an empty list if the player can't be located on the scoreboard.
    """
    # Collect every scoreboard row: (player_id, ign, team_tag). Rows repeat
    # per map (All maps + each map tab); dedupe by player id.
    rows: List[Dict[str, str]] = []
    for row in soup.select(".ovw-player"):
        link = row.select_one("a[href^='/player/']")
        if not link:
            continue
        m = re.search(r"/player/(\d+)", link["href"])
        if not m:
            continue
        name_tag = row.select_one(".ovw-player-name")
        tag_tag = row.select_one(".ovw-player-tag")
        rows.append({
            "id": m.group(1),
            "ign": name_tag.get_text(strip=True) if name_tag else "",
            "tag": tag_tag.get_text(strip=True) if tag_tag else "",
        })

    # Which team tag did the target player play under in this match?
    my_tags = {r["tag"] for r in rows if r["id"] == player_id and r["tag"]}
    if not my_tags:
        return []

    teammates: Dict[str, str] = {}
    for r in rows:
        if r["id"] == player_id:
            continue
        if r["tag"] in my_tags and r["ign"]:
            teammates.setdefault(r["id"], r["ign"])

    return [{"id": pid, "ign": ign} for pid, ign in teammates.items()]


def get_match_teammates(
    match_url: str,
    player_id: str,
    session: requests.Session,
) -> List[Dict[str, str]]:
    """Fetch a match page and return [{id, ign}] for the players on the same
    team as `player_id` (excluding the player themselves)."""
    soup = get_soup(match_url, session)
    return parse_scoreboard_teammates(soup, player_id)
