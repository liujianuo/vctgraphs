#!/usr/bin/env python3
"""
scrape_defaults.py

Central configuration for the vlr.gg scrapers and analysis tools. Every tunable
constant — HTTP request settings, polite-delay defaults, match/roster
classification rules, database table names and paths, and default I/O
locations — lives here so the scraper (scraper/) and analysis (analysis/)
programs all share a single source of truth.

This module has no project dependencies, so any program can import it. It lives
at the repo root; modules in subpackages add the repo root to sys.path before
importing it (see how scraper/vlr_utils.py does it).
"""

import os

# Repo root — this file lives at the top level of the project.
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


# --- vlr.gg site / HTTP ------------------------------------------------------

BASE_URL = "https://www.vlr.gg"

# A normal browser UA is friendlier / less likely to be treated as a bot than a
# default library UA.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
HEADERS = {"User-Agent": USER_AGENT}

# Seconds before an HTTP request times out.
REQUEST_TIMEOUT_SECONDS = 30.0

# HTTP statuses worth retrying (rate limiting / transient server errors).
RETRY_STATUSES = {429, 500, 502, 503, 504}
# How many times to retry a failed request, and the base backoff in seconds;
# the wait between attempts grows as RETRY_BACKOFF * 2 ** attempt.
RETRY_ATTEMPTS = 3
RETRY_BACKOFF = 1.0

# Seconds to wait between requests, to be polite to vlr.gg.
QUERY_DELAY_DEFAULT = 0.5


# --- Match / roster classification ------------------------------------------

# Event-label / URL rules for what counts as a "VCT circuit" match. Kept in one
# place so the scraper and the analysis graph builder agree on which matches
# define a "previous teammate".
CIRCUIT_KEYWORDS = ("vct", "champions", "masters", "ewc")
EXCLUDE_URL_SUBSTRINGS = ("showmatch", "main-event")

# Keywords that mark a team-roster entry as staff rather than a player.
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

# Minimum number of shared matches for two players to count as teammates.
MINIMUM_MATCH_DEFAULT = 1


# --- Database ----------------------------------------------------------------

PLAYER_META_TABLE_NAME = "players"
PLAYER_TEAMMATE_TABLE_NAME = "teammates"
DEFAULT_DB_PATH = os.path.join(_REPO_ROOT, "data", "playerdata.db")


# --- Default I/O locations ---------------------------------------------------

DEFAULT_EVENT_URL = f"{BASE_URL}/event/2977/vct-2026-americas-stage-2"
DEFAULT_PLAYERS_CSV = os.path.join("data", "players.csv")


# --- Graph rendering ---------------------------------------------------------

# Node fill colour used when drawing the teammate graph.
GRAPH_NODE_COLOR = "#4c78a8"

# Edge line width (in points) scales with how many matches two players shared.
# The thinnest and thickest edges are clamped to these bounds so a single-match
# link stays visible and a heavily-shared link never overwhelms the drawing.
EDGE_WIDTH_MIN = 0.6
EDGE_WIDTH_MAX = 6.0
# Opacity of edges. Slightly translucent so overlapping links stay legible.
EDGE_ALPHA = 0.35
