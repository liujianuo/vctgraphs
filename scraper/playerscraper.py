#!/usr/bin/env python3
"""
vlr_scraper.py

Scrapes a VLR.gg event page (e.g. VCT 2026: Americas Stage 2), finds every
participating team, then visits each team's page to pull the current roster
of players.

Usage:
    python vlr_scraper.py
    python vlr_scraper.py --url https://www.vlr.gg/event/2977/vct-2026-americas-stage-2
    python vlr_scraper.py --out players.csv --json players.json

Output:
    - Prints a summary to the console
    - Writes a CSV (team, player, real_name, role, country, player_url)
    - Optionally writes a JSON file with the same data

Requires:
    pip install requests beautifulsoup4
"""

import argparse
import csv
import json
import re
import sys
import time
from dataclasses import dataclass, asdict
from typing import List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.vlr.gg"
DEFAULT_EVENT_URL = "https://www.vlr.gg/event/2977/vct-2026-americas-stage-2"

HEADERS = {
    # vlr.gg will happily serve a default python-requests UA, but a normal
    # browser UA is friendlier / less likely to be treated as a bot.
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

# Keywords that mark a roster entry as staff rather than a player.
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
)


@dataclass
class Player:
    team: str
    team_url: str
    ign: str
    real_name: str
    role: str
    country: str
    player_url: str


def get_soup(url: str, session: requests.Session) -> BeautifulSoup:
    resp = session.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def get_teams(event_url: str, session: requests.Session) -> List[dict]:
    """Return a de-duplicated list of {name, url} for every team linked
    from the event page."""
    soup = get_soup(event_url, session)
    teams = {}

    # Every team link on the event page (standings table + "Participating
    # Teams" section) points at /team/<id>/<slug>. Collect them all and
    # dedupe by team id. This is more robust than relying on one specific
    # container class, since vlr.gg's markup shifts between event types.
    for a in soup.find_all("a", href=re.compile(r"^/team/\d+/")):
        href = a["href"]
        m = re.match(r"^/team/(\d+)/([\w-]+)", href)
        if not m:
            continue
        team_id, slug = m.group(1), m.group(2)
        team_url = urljoin(BASE_URL, f"/team/{team_id}/{slug}")

        name = a.get_text(strip=True)
        # Some links (e.g. in the standings table) wrap the logo image and
        # extra "Spoiler hidden" text; prefer a clean, non-empty name.
        if not name:
            continue
        # Skip obvious non-name junk sometimes picked up (e.g. "Spoiler hidden")
        if name.lower() in ("spoiler hidden",):
            continue

        if team_id not in teams:
            teams[team_id] = {"id": team_id, "name": name, "url": team_url}

    return list(teams.values())


def classify_role(role_text: str) -> str:
    role_text = (role_text or "").strip()
    return role_text


def is_staff(role_text: str) -> bool:
    role_lower = (role_text or "").lower()
    return any(kw in role_lower for kw in STAFF_KEYWORDS)


def get_roster(team: dict, session: requests.Session) -> List[Player]:
    soup = get_soup(team["url"], session)
    players: List[Player] = []

    # Country, shown near the top of the team page as a plain text line.
    country = ""
    country_tag = soup.select_one(".team-header-country")
    if country_tag:
        country = country_tag.get_text(strip=True)

    roster_items = soup.select(".team-roster-item")

    if roster_items:
        for item in roster_items:
            alias_tag = item.select_one(".team-roster-item-name-alias")
            real_tag = item.select_one(".team-roster-item-name-real")
            role_tag = item.select_one(".team-roster-item-name-role")
            link_tag = item.select_one("a[href^='/player/']")

            ign = alias_tag.get_text(strip=True) if alias_tag else (
                link_tag.get_text(strip=True) if link_tag else ""
            )
            if not ign:
                continue

            real_name = real_tag.get_text(strip=True) if real_tag else ""
            role_text = role_tag.get_text(strip=True) if role_tag else ""
            player_url = urljoin(BASE_URL, link_tag["href"]) if link_tag else ""

            if is_staff(role_text):
                continue

            players.append(
                Player(
                    team=team["name"],
                    team_url=team["url"],
                    ign=ign,
                    real_name=real_name,
                    role=classify_role(role_text),
                    country=country,
                    player_url=player_url,
                )
            )
    else:
        # Fallback: older/alternate markup. Look for the "Current Roster"
        # heading, then walk player links until a "staff" divider.
        roster_header = None
        for h in soup.find_all(["h2", "h1"]):
            if "roster" in h.get_text(strip=True).lower():
                roster_header = h
                break

        if roster_header:
            container = roster_header.find_parent(
                "div", class_=re.compile("wf-card|module")
            ) or roster_header.parent

            in_staff_section = False
            for el in container.find_all(["div", "a", "h3", "h4"]):
                text = el.get_text(strip=True).lower()
                if el.name in ("h3", "h4") and text == "staff":
                    in_staff_section = True
                    continue
                if el.name == "a" and el.get("href", "").startswith("/player/"):
                    if in_staff_section:
                        continue
                    full_text = el.get_text(" ", strip=True)
                    if not full_text:
                        continue
                    parts = full_text.split(" ", 1)
                    ign = parts[0]
                    real_name = parts[1] if len(parts) > 1 else ""
                    players.append(
                        Player(
                            team=team["name"],
                            team_url=team["url"],
                            ign=ign,
                            real_name=real_name,
                            role="",
                            country=country,
                            player_url=urljoin(BASE_URL, el["href"]),
                        )
                    )

    return players


def scrape(event_url: str, delay: float = 1.0, verbose: bool = True) -> List[Player]:
    session = requests.Session()
    teams = get_teams(event_url, session)

    if not teams:
        print(
            "No teams found on the event page. VLR.gg may have changed its "
            "markup, or the page didn't load as expected.",
            file=sys.stderr,
        )
        return []

    if verbose:
        print(f"Found {len(teams)} teams:")
        for t in teams:
            print(f"  - {t['name']} ({t['url']})")
        print()

    all_players: List[Player] = []
    for i, team in enumerate(teams):
        if verbose:
            print(f"[{i + 1}/{len(teams)}] Fetching roster for {team['name']}...")
        try:
            roster = get_roster(team, session)
        except requests.RequestException as e:
            print(f"    ! Failed to fetch {team['url']}: {e}", file=sys.stderr)
            roster = []

        if verbose:
            for p in roster:
                extra = f" ({p.real_name})" if p.real_name else ""
                print(f"    - {p.ign}{extra}")

        all_players.extend(roster)
        time.sleep(delay)  # be polite

    return all_players


def write_csv(players: List[Player], path: str):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["team", "ign", "real_name", "role", "country", "player_url", "team_url"],
        )
        writer.writeheader()
        for p in players:
            writer.writerow(
                {
                    "team": p.team,
                    "ign": p.ign,
                    "real_name": p.real_name,
                    "role": p.role,
                    "country": p.country,
                    "player_url": p.player_url,
                    "team_url": p.team_url,
                }
            )


def write_json(players: List[Player], path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(p) for p in players], f, indent=2, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser(description="Scrape all player rosters from a VLR.gg event.")
    parser.add_argument("--url", default=DEFAULT_EVENT_URL, help="VLR.gg event URL")
    parser.add_argument("--out", default="data/players.csv", help="Output CSV path")
    parser.add_argument("--json", default=None, help="Optional output JSON path")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between requests (seconds)")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output")
    args = parser.parse_args()

    players = scrape(args.url, delay=args.delay, verbose=not args.quiet)

    write_csv(players, args.out)
    print(f"\nWrote {len(players)} players to {args.out}")

    if args.json:
        write_json(players, args.json)
        print(f"Wrote {len(players)} players to {args.json}")

    if not args.quiet:
        print("\n=== Summary ===")
        by_team = {}
        for p in players:
            by_team.setdefault(p.team, []).append(p.ign)
        for team, igns in by_team.items():
            print(f"{team}: {', '.join(igns)}")


if __name__ == "__main__":
    main()