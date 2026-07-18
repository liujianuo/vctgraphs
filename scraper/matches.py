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
    pip install httpx beautifulsoup4
"""

import re
import sys
import time
from typing import Iterator, List, Optional
import os
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup
import sqlite3

from vlr_utils import BASE_URL, absolute, get_soup, player_id as _player_id

# Event-label / URL rules for what counts as a "VCT circuit" match. Kept in one
# place so the CLI (teammates.py) and the analysis graph builder agree on which
# matches define a "previous teammate".
CIRCUIT_KEYWORDS = ("vct", "champions", "masters", "ewc")
EXCLUDE_URL_SUBSTRINGS = ("showmatch", "main-event")
PLAYER_META_TABLE_NAME = "players"
PLAYER_TEAMMATE_TABLE_NAME = "teammates"


def is_circuit_match(match: dict[str, str]) -> bool:
    """True if a match (as yielded by iter_match_history) belongs to the VCT
    circuit: its history-page event label contains one of CIRCUIT_KEYWORDS and
    its URL isn't an excluded showmatch/main-event."""
    label = (match.get("event_label") or "").lower()
    url = (match.get("match_url") or "").lower()
    if not any(kw in label for kw in CIRCUIT_KEYWORDS):
        return False
    return not any(bad in url for bad in EXCLUDE_URL_SUBSTRINGS)


def _cached_soup(
    url: str,
    session: httpx.Client,
    cache: Optional[dict[str, BeautifulSoup]] = None,
) -> BeautifulSoup:
    """get_soup with an optional in-memory cache keyed by URL, so a match page
    shared across several players is fetched only once."""
    if cache is not None and url in cache:
        return cache[url]
    soup = get_soup(url, session)
    if cache is not None:
        cache[url] = soup
    return soup


def _match_id(match_url: str) -> Optional[str]:
    """Extract the numeric match id from a match URL like '/660378/...'."""
    m = re.search(r"/(\d+)/", match_url if match_url.startswith("/")
                  else match_url.replace(BASE_URL, ""))
    return m.group(1) if m else None


def iter_match_history(
    player_url: str,
    session: httpx.Client,
    delay: float = 1.0,
) -> Iterator[dict[str, str]]:
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


def parse_scoreboard_players(soup: BeautifulSoup) -> List[dict[str, str]]:
    """Given a fetched match page, return [{id, ign, tag}] for every player on
    the scoreboard (both teams), de-duplicated by player id. `tag` is the team
    tag shown on each row (e.g. "MIBR"), which identifies the player's team in
    this match."""
    players: dict[str, dict[str, str]] = {}
    # Rows repeat per map (All maps + each map tab); dedupe by player id.
    for row in soup.select(".ovw-player"):
        link = row.select_one("a[href^='/player/']")
        if not link:
            continue
        m = re.search(r"/player/(\d+)", link["href"])
        if not m:
            continue
        pid = m.group(1)
        if pid in players:
            continue
        name_tag = row.select_one(".ovw-player-name")
        tag_tag = row.select_one(".ovw-player-tag")
        players[pid] = {
            "id": pid,
            "ign": name_tag.get_text(strip=True) if name_tag else "",
            "tag": tag_tag.get_text(strip=True) if tag_tag else "",
        }
    return list(players.values())


def parse_scoreboard_teammates(
    soup: BeautifulSoup,
    player_id: str,
) -> List[dict[str, str]]:
    """Given a fetched match page, return [{id, ign}] for the players on the
    same team as `player_id` (excluding the player themselves), read from the
    scoreboard. De-duplicated by player id across the match's maps.

    Returns an empty list if the player can't be located on the scoreboard.
    """
    rows = parse_scoreboard_players(soup)

    # Which team tag did the target player play under in this match?
    my_tags = {r["tag"] for r in rows if r["id"] == player_id and r["tag"]}
    if not my_tags:
        return []

    return [
        {"id": r["id"], "ign": r["ign"]}
        for r in rows
        if r["id"] != player_id and r["tag"] in my_tags and r["ign"]
    ]

def get_match_teammates(
    match_url: str,
    player_id: str,
    session: httpx.Client,
) -> List[dict[str, str]]:
    """Fetch a match page and return [{id, ign}] for the players on the same
    team as `player_id` (excluding the player themselves)."""
    soup = get_soup(match_url, session)
    return parse_scoreboard_teammates(soup, player_id)

def get_id_from_url(
    player_url: str
) -> int:
    path = urlsplit(player_url).path
    segments = [segment for segment in path.split('/') if segment]
    if len(segments) >= 2:
        return segments[-2]
    return None

def get_last_match(
    player_url: str,
    db_path: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data/playerdata.db")
) -> str:
    last_match = None
    db = sqlite3.connect(db_path)
    cur = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (PLAYER_META_TABLE_NAME,)
    )
    if cur.fetchone() is not None:
        try:
            cur = db.execute(
                f"SELECT last_match_url FROM {PLAYER_META_TABLE_NAME} WHERE player_id = ?",
                (get_id_from_url(player_url),)
            )
            row = cur.fetchone()
            return row[0] if row else None
        except sqlite3.OperationalError:
            return None
    else:
        db.execute(
            f"CREATE TABLE {PLAYER_META_TABLE_NAME} ( player_id INT PRIMARY KEY, last_match_url VARCHAR(n) );"
        )
    return last_match

def append_saved_data(
    player_id: str,
    teammate_dict: dict[str, dict[str, object]],
    db_path: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data/playerdata.db")
) -> None:
    new_data = dict()
    db = sqlite3.connect(db_path)
    cursor = db.execute(
        f"SELECT teammate_id, teammate_ign, count FROM {PLAYER_TEAMMATE_TABLE_NAME} WHERE player_id = ?",
        (player_id,)
    )
    new_data = cursor.fetchall()
    db.close()
    
    for teammate, ign, extra in new_data:
        if teammate in teammate_dict:
            teammate_dict[teammate]["matches"] = teammate_dict[teammate]["matches"] + extra
        else:
            teammate_dict[teammate] = {"matches": extra, "ign": ign}
        teammate_dict[teammate]["matches"] = teammate_dict.get(teammate, dict()).get("matches", 0) + extra

def update_saved_data(
    player_id: str,
    teammate_dict: dict[str, dict[str, object]],
    last_match: str,
    db_path: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data/playerdata.db")
) -> None:
    db = sqlite3.connect(db_path)
    try:
        for teammate_id, data in teammate_dict.items():
            db.execute(
                f"INSERT OR REPLACE INTO {PLAYER_TEAMMATE_TABLE_NAME} (player_id, teammate_id, teammate_ign, count) VALUES (?, ?, ?, ?)",
                (player_id, teammate_id, data["ign"], data["matches"])
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
        
    try:
        db.execute(
            f"INSERT OR REPLACE INTO {PLAYER_META_TABLE_NAME} (player_id, last_match_url) VALUES (?, ?)",
            (player_id, last_match)
        )
        db.commit()
    except Exception:
        db.rollback()
        raise


def get_teammate_map(
    player_url: str,
    session: httpx.Client,
    delay: float = 0.2,
    cache: Optional[dict[str, BeautifulSoup]] = None,
    db_path: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data/playerdata.db"),
    verbose: bool = False,
) -> dict[str, dict[str, object]]:
    """Walk a player's entire match history and return every player who has
    been on the same team as them in a VCT-circuit match (see is_circuit_match),
    keyed by player id:

        {teammate_id: {"ign": str, "matches": int}}

    `matches` is how many circuit matches the two shared a team in. The target
    player is excluded. An optional `cache` (url -> soup) lets callers share
    fetched match pages across several players.
    """
    me = _player_id(player_url)
    if not me:
        raise ValueError(f"Could not parse a player id from URL: {player_url}")

    circuit_matches = [
        m for m in iter_match_history(player_url, session, delay=delay)
        if is_circuit_match(m)
    ]
    if verbose:
        print(f"Found {len(circuit_matches)} VCT matches for {player_url}")
    
    last_match = get_last_match(player_url, db_path)

    teammates: dict[str, dict[str, object]] = {}
    for i, m in enumerate(circuit_matches):
        if verbose:
            print(f"[{i + 1}/{len(circuit_matches)}] "
                  f"{m['event_label']} — {m['match_url']}")
        
        if last_match == m['match_url']:
            if verbose:
                print(    f"{m['match_url']} has been found in database.\n    Filling rest of data from database")
            append_saved_data(get_id_from_url(player_url), teammates, db_path)
            break

        try:
            soup = _cached_soup(m["match_url"], session, cache)
        except httpx.HTTPError as e:
            print(f"    ! Failed to fetch {m['match_url']}: {e}",
                  file=sys.stderr)
            continue

        for p in parse_scoreboard_teammates(soup, me):
            entry = teammates.setdefault(p["id"], {"ign": p["ign"], "matches": 0})
            entry["matches"] += 1

        if delay:
            time.sleep(delay)  # be polite to vlr.gg
    cur_last_match = circuit_matches[0]["match_url"]
    update_saved_data(get_id_from_url(player_url), teammates, cur_last_match, db_path)
    return teammates
