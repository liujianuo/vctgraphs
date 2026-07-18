#!/usr/bin/env python3
"""
vlr_utils.py

Small shared helpers for scraping vlr.gg: a common request header, an HTTP
client factory, a soup fetcher, and player/URL helpers. Kept separate so the
various scrapers (playerscraper, teammates, matches) can share one HTTP setup.

Uses httpx rather than requests: under sustained scraping vlr.gg intermittently
drops keep-alive connections, which surfaces as
``SSLError([SSL: UNEXPECTED_EOF_WHILE_READING])``. get_soup retries those
transient transport errors (and retryable HTTP statuses) with backoff, opening
a fresh connection each attempt.

Requires:
    pip install httpx beautifulsoup4
"""

import os
import re
import sys
import time
from typing import Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

# Read shared configuration from the repo-root scrape_defaults.py.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scrape_defaults import (  # noqa: E402
    BASE_URL,
    HEADERS,
    REQUEST_TIMEOUT_SECONDS,
    RETRY_ATTEMPTS,
    RETRY_BACKOFF,
    RETRY_STATUSES,
)

DEFAULT_TIMEOUT = httpx.Timeout(REQUEST_TIMEOUT_SECONDS)


def make_client(**kwargs) -> httpx.Client:
    """Create an httpx.Client configured for scraping vlr.gg (browser UA,
    generous timeout, redirects followed). Extra kwargs are passed through."""
    kwargs.setdefault("headers", HEADERS)
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    kwargs.setdefault("follow_redirects", True)
    return httpx.Client(**kwargs)


def get_soup(
    url: str,
    client: httpx.Client,
    retries: int = RETRY_ATTEMPTS,
    backoff: float = RETRY_BACKOFF,
) -> BeautifulSoup:
    """Fetch `url` and return parsed BeautifulSoup.

    Retries transient transport errors (connection resets / SSL EOF that vlr.gg
    throws when it drops a pooled connection) and retryable HTTP statuses, with
    exponential backoff. A fresh connection is used on each retry, so a stale
    keep-alive socket doesn't poison the whole run.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            resp = client.get(url)
        except httpx.TransportError as e:
            # Connection / SSL / read / timeout errors are transient here.
            last_exc = e
            if attempt < retries:
                time.sleep(backoff * (2 ** attempt))
                continue
            raise

        if resp.status_code in RETRY_STATUSES and attempt < retries:
            time.sleep(backoff * (2 ** attempt))
            continue

        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")

    # Only reached if every attempt hit a TransportError.
    raise last_exc  # type: ignore[misc]


def absolute(href: str) -> str:
    """Turn a site-relative href (e.g. '/team/2/sentinels') into a full URL."""
    return urljoin(BASE_URL, href)


def player_id(player_url: str) -> Optional[str]:
    """Extract the numeric player id from any vlr.gg player URL."""
    m = re.search(r"/player/(\d+)", player_url)
    return m.group(1) if m else None
