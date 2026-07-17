#!/usr/bin/env python3
"""
vlr_utils.py

Small shared helpers for scraping vlr.gg: a common request header, a soup
fetcher, and player/URL helpers. Kept separate so the various scrapers
(playerscraper, teammates, matches) can share one HTTP setup.

Requires:
    pip install requests beautifulsoup4
"""

import re
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.vlr.gg"

HEADERS = {
    # A normal browser UA is friendlier / less likely to be treated as a bot
    # than the default python-requests UA.
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


def get_soup(url: str, session: requests.Session) -> BeautifulSoup:
    """Fetch `url` with the shared headers and return a parsed BeautifulSoup."""
    resp = session.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def absolute(href: str) -> str:
    """Turn a site-relative href (e.g. '/team/2/sentinels') into a full URL."""
    return urljoin(BASE_URL, href)


def player_id(player_url: str) -> Optional[str]:
    """Extract the numeric player id from any vlr.gg player URL."""
    m = re.search(r"/player/(\d+)", player_url)
    return m.group(1) if m else None
