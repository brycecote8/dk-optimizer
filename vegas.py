"""
vegas.py
--------
Turns Las Vegas betting lines into DraftKings fantasy projections, automatically.

The idea: a sportsbook's line for "Player X passing yards = 271.5" IS the
market's projection for that player. Bookmakers risk real money on these, so
they're the sharpest free numbers available. We pull those lines from a free
odds service (The Odds API), average them across all books, and convert them
into DraftKings points using DK's scoring rules.

You need a free API key from https://the-odds-api.com (2-minute signup).

The two halves of this file:
  - fetch_*()  : talk to the internet and get raw betting lines.
  - *_to_*()   : pure math that turns lines into fantasy points (no internet,
                 so it's easy to test).
"""

import json
import urllib.request
import urllib.error
from collections import defaultdict

API_BASE = "https://api.the-odds-api.com/v4"
SPORT = "americanfootball_nfl"

# The betting markets we pull. Each maps to a stat we score.
# (Fewer markets = fewer API credits used per refresh.)
OU_MARKETS = {
    "player_pass_yds": "pass_yds",
    "player_pass_tds": "pass_tds",
    "player_rush_yds": "rush_yds",
    "player_reception_yds": "rec_yds",
    "player_receptions": "receptions",
}
TD_MARKET = "player_anytime_td"
ALL_MARKETS = list(OU_MARKETS.keys()) + [TD_MARKET]


class VegasError(Exception):
    """Something went wrong talking to the odds service (bad key, etc.)."""


# ---------------------------------------------------------------------------
# Scoring math (no internet — pure and testable)
# ---------------------------------------------------------------------------
def american_to_prob(price):
    """Convert American odds (e.g. +150 or -200) into an implied probability."""
    price = float(price)
    if price > 0:
        return 100.0 / (price + 100.0)
    return -price / (-price + 100.0)


def collect_player_stats(events):
    """
    Walk the raw odds data and gather every stat line for every player,
    averaged across all bookmakers.

    `events` is a list of per-event odds objects (as returned by the API).
    Returns: dict  player_name -> { 'pass_yds': 271.5, 'receptions': 5.5, ... }
    """
    # ou[name][stat] = list of point values seen across books
    ou = defaultdict(lambda: defaultdict(list))
    # td[name] = list of touchdown probabilities across books
    td = defaultdict(list)

    for ev in events:
        for book in ev.get("bookmakers", []):
            for market in book.get("markets", []):
                key = market.get("key")
                outcomes = market.get("outcomes", [])

                if key in OU_MARKETS:
                    stat = OU_MARKETS[key]
                    for oc in outcomes:
                        name = oc.get("description")
                        point = oc.get("point")
                        if name and point is not None:
                            ou[name][stat].append(float(point))

                elif key == TD_MARKET:
                    # Gather Yes/No per player, then remove the book's "vig".
                    yes, no = {}, {}
                    for oc in outcomes:
                        name = oc.get("description")
                        side = (oc.get("name") or "").lower()
                        price = oc.get("price")
                        if not name or price is None:
                            continue
                        p = american_to_prob(price)
                        if side == "no":
                            no[name] = p
                        else:  # "yes" or a feed that just names the player
                            yes[name] = p
                    for name, p in yes.items():
                        q = no.get(name)
                        prob = p / (p + q) if q else p   # de-vig if we can
                        td[name].append(min(prob, 0.75))

    # Average everything into a single clean stat line per player.
    stats = {}
    for name, statmap in ou.items():
        stats[name] = {s: sum(v) / len(v) for s, v in statmap.items()}
    for name, probs in td.items():
        stats.setdefault(name, {})["td_prob"] = sum(probs) / len(probs)
    return stats


def stats_to_points(stats):
    """
    Apply DraftKings NFL scoring to one player's averaged stat line.
    Returns projected fantasy points (a number).
    """
    pass_yds = stats.get("pass_yds", 0.0)
    pass_tds = stats.get("pass_tds", 0.0)
    rush_yds = stats.get("rush_yds", 0.0)
    rec_yds = stats.get("rec_yds", 0.0)
    receptions = stats.get("receptions", 0.0)
    td_prob = stats.get("td_prob", 0.0)

    pts = 0.0
    pts += pass_yds * 0.04          # 1 pt per 25 passing yards
    pts += pass_tds * 4.0           # 4 pts per passing TD
    pts += rush_yds * 0.1           # 1 pt per 10 rushing yards
    pts += rec_yds * 0.1            # 1 pt per 10 receiving yards
    pts += receptions * 1.0         # PPR: 1 pt per catch
    pts += td_prob * 6.0            # expected rush/rec TD points

    # DraftKings milestone bonuses.
    if pass_yds >= 300:
        pts += 3.0
    if rush_yds >= 100:
        pts += 3.0
    if rec_yds >= 100:
        pts += 3.0
    return round(pts, 2)


def events_to_projections(events):
    """
    Full conversion: raw odds data -> list of {Name, ProjectedPoints}.
    This is the pure, internet-free core (easy to test with sample data).
    """
    stats = collect_player_stats(events)
    rows = []
    for name, s in stats.items():
        rows.append({"Name": name, "ProjectedPoints": stats_to_points(s)})
    rows.sort(key=lambda r: r["ProjectedPoints"], reverse=True)
    return rows


# ---------------------------------------------------------------------------
# The internet half (fetching)
# ---------------------------------------------------------------------------
def _get(url):
    """Do one HTTP GET, returning (parsed_json, response_headers)."""
    try:
        with urllib.request.urlopen(url, timeout=25) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data, resp.headers
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise VegasError("Your API key was rejected (401). Double-check it.")
        if e.code == 429:
            raise VegasError("Out of API requests for now (429). Try later.")
        body = e.read().decode("utf-8", "ignore")
        raise VegasError(f"Odds service error {e.code}: {body[:200]}")
    except urllib.error.URLError as e:
        raise VegasError(f"Couldn't reach the odds service: {e.reason}")


def fetch_events(api_key):
    """List the upcoming NFL games. Returns a list of event dicts."""
    url = f"{API_BASE}/sports/{SPORT}/events?apiKey={api_key}"
    data, _ = _get(url)
    return data


def fetch_event_odds(api_key, event_id, markets=None):
    """Get all player-prop odds for a single game."""
    markets = markets or ALL_MARKETS
    url = (f"{API_BASE}/sports/{SPORT}/events/{event_id}/odds"
           f"?apiKey={api_key}&regions=us&oddsFormat=american"
           f"&markets={','.join(markets)}")
    data, headers = _get(url)
    remaining = headers.get("x-requests-remaining")
    return data, remaining


def filter_upcoming(events, days=7, now=None):
    """
    Keep only games kicking off within the next `days` days.

    This matters a lot: the odds service lists the WHOLE season (270+ games).
    Fetching props for all of them would burn your entire monthly API budget in
    one click. A DraftKings slate is a single week, so 7 days is the right
    window.
    """
    from datetime import datetime, timezone, timedelta

    now = now or datetime.now(timezone.utc)
    cutoff = now + timedelta(days=days)
    kept = []
    for ev in events:
        raw = ev.get("commence_time")
        if not raw:
            continue
        try:
            when = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if now <= when <= cutoff:
            kept.append(ev)
    return kept


def estimate_cost(num_games, markets=None):
    """
    How many API credits a fetch will cost.
    The service charges [number of markets] credits per game.
    """
    markets = markets or ALL_MARKETS
    return num_games * len(markets)


def fetch_projections(api_key, markets=None, days=7, max_games=24):
    """
    The one call the app uses. Fetches this week's games only, pulls their
    player props, and converts them to projections.

    Returns (rows, meta) where rows is a list of {Name, ProjectedPoints} and
    meta describes what happened (games used, players found, credits left).
    """
    events = fetch_events(api_key)
    if not events:
        raise VegasError(
            "No NFL games found. Props may not be posted yet — "
            "try again closer to game day."
        )

    upcoming = filter_upcoming(events, days=days)
    if not upcoming:
        raise VegasError(
            f"Found {len(events)} NFL games, but none in the next {days} days. "
            "Props are usually posted a few days before kickoff."
        )

    # Hard safety cap so a bad window can never drain the API budget.
    truncated = False
    if max_games and len(upcoming) > max_games:
        upcoming = upcoming[:max_games]
        truncated = True

    all_odds = []
    remaining = None
    for ev in upcoming:
        odds, remaining = fetch_event_odds(api_key, ev["id"], markets)
        all_odds.append(odds)

    rows = events_to_projections(all_odds)
    meta = {
        "games": len(upcoming),
        "players": len(rows),
        "credits_remaining": remaining,
        "credits_used": estimate_cost(len(upcoming), markets),
        "truncated": truncated,
    }
    return rows, meta
