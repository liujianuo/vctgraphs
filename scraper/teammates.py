#!/usr/bin/env python3
"""
teammates.py

Given a VLR.gg player URL, scrape every team that player has been part of
(the "Current Teams" and "Past Teams" sections on their player page), then
visit each team page and collect the players on its roster. The union of
those players — minus the player themselves — is returned as a list of
teammate names.

Note on scope:
    VLR.gg team pages only expose a team's *current* roster (there is no
    "former players" section in the markup). This means the teammates found
    for a given team are that team's roster as it stands now, not a perfect
    historical snapshot of who overlapped with the player. It is, however,
    the connectivity information VLR.gg makes readily available, and is a
    reasonable approximation for building a player-connectivity graph.

Usage (as a library):
    from teammates import get_past_teammates
    names = get_past_teammates("https://www.vlr.gg/player/8480/aspas")

Usage (as a script):
    python teammates.py https://www.vlr.gg/player/8480/aspas

Requires:
    pip install requests beautifulsoup4
"""

import re
import sys
import time
from typing import List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.vlr.gg"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

# Roster entries whose role matches one of these are staff, not teammates.
STAFF_KEYWORDS = (
    "manager",
    "head coach",
    "assistant coach",
    "coach",
    "analyst",
    "owner",
    "director",
    "csm",
    "content",
    "founder",
    "staff",
)

# Team-history section headings on a player page.
TEAM_SECTION_LABELS = ("current teams", "past teams")


def _get_soup(url: str, session: requests.Session) -> BeautifulSoup:
    resp = session.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def _player_id(player_url: str) -> Optional[str]:
    m = re.search(r"/player/(\d+)", player_url)
    return m.group(1) if m else None


def _is_staff(role_text: str) -> bool:
    role_lower = (role_text or "").lower()
    return any(kw in role_lower for kw in STAFF_KEYWORDS)


def get_team_history(player_url: str, session: requests.Session) -> List[dict]:
    """Return [{id, name, url}] for every team in the player's
    'Current Teams' and 'Past Teams' sections (deduped by team id)."""
    soup = _get_soup(player_url, session)
    teams: dict = {}

    for label in soup.find_all("h2", class_="wf-label"):
        if label.get_text(strip=True).lower() not in TEAM_SECTION_LABELS:
            continue
        # The roster/team links live in the wf-card that follows the heading.
        card = label.find_next_sibling("div", class_="wf-card")
        if not card:
            continue
        for a in card.find_all("a", href=re.compile(r"^/team/\d+/")):
            href = a["href"]
            m = re.match(r"^/team/(\d+)/([\w-]+)", href)
            if not m:
                continue
            team_id, slug = m.group(1), m.group(2)
            name = a.get_text(strip=True)
            if team_id not in teams:
                teams[team_id] = {
                    "id": team_id,
                    "name": name,
                    "url": urljoin(BASE_URL, f"/team/{team_id}/{slug}"),
                }

    return list(teams.values())


def get_roster(team_url: str, session: requests.Session) -> List[dict]:
    """Return [{id, ign}] for the players on a team's current roster,
    excluding staff."""
    soup = _get_soup(team_url, session)
    roster: List[dict] = []

    for item in soup.select(".team-roster-item"):
        link = item.select_one("a[href^='/player/']")
        if not link:
            continue
        m = re.search(r"/player/(\d+)", link["href"])
        if not m:
            continue
        player_id = m.group(1)

        role_tag = item.select_one(".team-roster-item-name-role")
        if _is_staff(role_tag.get_text(strip=True) if role_tag else ""):
            continue

        alias_tag = item.select_one(".team-roster-item-name-alias")
        ign = (alias_tag.get_text(strip=True) if alias_tag
               else link.get_text(strip=True))
        if not ign:
            continue

        roster.append({"id": player_id, "ign": ign})

    return roster


def get_past_teammates(
    player_url: str,
    session: Optional[requests.Session] = None,
    delay: float = 1.0,
    verbose: bool = False,
) -> List[str]:
    """Scrape VLR.gg for every teammate the given player has had across all
    of their teams, and return a de-duplicated, sorted list of teammate IGNs.

    The player themselves is excluded from the result.
    """
    own_session = session is None
    session = session or requests.Session()
    me = _player_id(player_url)

    teams = get_team_history(player_url, session)
    if verbose:
        print(f"Found {len(teams)} teams for player {player_url}:")
        for t in teams:
            print(f"  - {t['name']} ({t['url']})")

    # id -> ign, so the same person on multiple shared teams counts once.
    teammates: dict = {}
    for i, team in enumerate(teams):
        if verbose:
            print(f"[{i + 1}/{len(teams)}] Roster for {team['name']}...")
        try:
            roster = get_roster(team["url"], session)
        except requests.RequestException as e:
            print(f"    ! Failed to fetch {team['url']}: {e}", file=sys.stderr)
            roster = []

        for p in roster:
            if me and p["id"] == me:
                continue  # skip the player themselves
            teammates.setdefault(p["id"], p["ign"])

        if delay:
            time.sleep(delay)  # be polite to vlr.gg

    if own_session:
        session.close()

    return sorted(teammates.values(), key=str.lower)


def main():
    if len(sys.argv) < 2:
        print("Usage: python teammates.py <player_url>", file=sys.stderr)
        sys.exit(1)

    player_url = sys.argv[1]
    names = get_past_teammates(player_url, verbose=True)

    print(f"\n{len(names)} past teammates:")
    for name in names:
        print(f"  {name}")


if __name__ == "__main__":
    main()
