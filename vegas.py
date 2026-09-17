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
import math
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

    # DraftKings milestone bonuses (+3 each), weighted by how LIKELY the
    # player is to reach them. A betting line is a median, not a guarantee: a
    # receiver set at 92.5 yards still clears 100 fairly often, and one set at
    # 101.5 misses about half the time. A hard cutoff at the line created a
    # 3-point cliff between near-identical players.
    pts += 3.0 * _prob_at_least(pass_yds, 300, spread=0.25)
    pts += 3.0 * _prob_at_least(rush_yds, 100, spread=0.50)
    pts += 3.0 * _prob_at_least(rec_yds, 100, spread=0.55)
    return round(pts, 2)


def _prob_at_least(line, threshold, spread):
    """
    Chance a stat reaches `threshold` when the betting line (the median) is
    `line`. Game-to-game swings scale with the line itself, so the standard
    deviation is `spread` times the line, with a small floor.
    """
    if line <= 0:
        return 0.0
    sd = max(spread * line, 12.0)
    z = (threshold - line) / sd
    return 0.5 * (1.0 - math.erf(z / math.sqrt(2.0)))


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


def group_by_gameday(events, now=None):
    """
    Group upcoming games by their Eastern-time calendar date — which is how
    DraftKings slates actually work ("Sunday main slate", "Thursday night").

    A plain "next N days" window is unreliable: run it Wednesday and "2 days"
    misses Sunday entirely. Picking the real game day is unambiguous.

    Returns a list of (label, date_key, [events]) sorted by date, e.g.
        ("Sun Sep 13 — 13 games", "2026-09-13", [...])
    """
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    eastern = ZoneInfo("America/New_York")
    now = now or datetime.now(timezone.utc)

    buckets = {}
    for ev in events:
        raw = ev.get("commence_time")
        if not raw:
            continue
        try:
            when = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if when < now:
            continue                      # already kicked off
        local = when.astimezone(eastern)
        key = local.strftime("%Y-%m-%d")
        buckets.setdefault(key, {"label_dt": local, "events": []})
        buckets[key]["events"].append(ev)

    out = []
    for key in sorted(buckets):
        b = buckets[key]
        n = len(b["events"])
        label = (f"{b['label_dt'].strftime('%a %b %d')} — "
                 f"{n} game{'s' if n != 1 else ''}")
        out.append((label, key, b["events"]))
    return out


def fetch_projections_for(api_key, events, markets=None):
    """
    Fetch props for an EXACT list of games (from group_by_gameday) and convert
    them to projections. This is what the app uses once you've picked a slate,
    so you only ever pay for the games you're actually playing.
    """
    if not events:
        raise VegasError("No games selected.")

    all_odds = []
    remaining = None
    for ev in events:
        odds, remaining = fetch_event_odds(api_key, ev["id"], markets)
        all_odds.append(odds)

    rows = events_to_projections(all_odds)
    meta = {
        "games": len(events),
        "players": len(rows),
        "credits_remaining": remaining,
        "credits_used": estimate_cost(len(events), markets),
        "truncated": False,
    }
    return rows, meta


# ---------------------------------------------------------------------------
# Game lines -> team totals -> defense projections
# ---------------------------------------------------------------------------
TEAM_ABBR = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL",
    "Baltimore Ravens": "BAL", "Buffalo Bills": "BUF",
    "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE",
    "Dallas Cowboys": "DAL", "Denver Broncos": "DEN",
    "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND",
    "Jacksonville Jaguars": "JAX", "Kansas City Chiefs": "KC",
    "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LAR", "Miami Dolphins": "MIA",
    "Minnesota Vikings": "MIN", "New England Patriots": "NE",
    "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI",
    "Pittsburgh Steelers": "PIT", "San Francisco 49ers": "SF",
    "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}
# DraftKings has used a few alternate abbreviations over the years.
ABBR_ALIASES = {"JAC": "JAX", "LA": "LAR", "WSH": "WAS"}


def fetch_game_lines(api_key):
    """
    Spreads and totals for every upcoming game in ONE call (2 credits total,
    not per game). Returns {team_abbr: {"implied": pts, "opp_implied": pts}}
    for each team's next game, averaged across sportsbooks.
    """
    url = (f"{API_BASE}/sports/{SPORT}/odds?apiKey={api_key}"
           "&regions=us&markets=spreads,totals&oddsFormat=american")
    games, _ = _get(url)
    return game_lines_from(games)


def game_lines_from(games):
    """Pure half of fetch_game_lines: raw odds JSON -> implied team totals."""
    lines = {}
    for g in sorted(games, key=lambda g: g.get("commence_time", "")):
        home = TEAM_ABBR.get(g.get("home_team"))
        away = TEAM_ABBR.get(g.get("away_team"))
        if not home or not away or home in lines or away in lines:
            continue  # unknown team, or we already have its nearest game

        totals, home_spreads = [], []
        for book in g.get("bookmakers", []):
            for m in book.get("markets", []):
                for oc in m.get("outcomes", []):
                    if oc.get("point") is None:
                        continue
                    if m["key"] == "totals" and oc.get("name") == "Over":
                        totals.append(float(oc["point"]))
                    elif m["key"] == "spreads" and oc.get("name") == g["home_team"]:
                        home_spreads.append(float(oc["point"]))
        if not totals or not home_spreads:
            continue

        total = sum(totals) / len(totals)
        spread = sum(home_spreads) / len(home_spreads)   # negative = favored
        home_pts = (total - spread) / 2.0
        away_pts = total - home_pts
        lines[home] = {"implied": home_pts, "opp_implied": away_pts}
        lines[away] = {"implied": away_pts, "opp_implied": home_pts}
    return lines


# DraftKings points-allowed tiers: (lowest score in tier, fantasy points).
_PA_TIERS = [(0, 10), (1, 7), (7, 4), (14, 1), (21, 0), (28, -1), (35, -4)]


def dst_projection(opp_implied):
    """
    Expected DraftKings points for a defense, given how many points Vegas
    expects its OPPONENT to score.

    Points allowed are treated as a bell curve around that expectation, and
    each DraftKings tier is weighted by its probability. Sacks, takeaways and
    defensive scores are added on top, slightly higher against weak offenses.
    """
    sd = 9.5

    def cdf(x):
        return 0.5 * (1.0 + math.erf((x - opp_implied) / (sd * math.sqrt(2.0))))

    expected_tier = 0.0
    for n, (low, pts) in enumerate(_PA_TIERS):
        lo = -math.inf if n == 0 else low - 0.5
        hi = math.inf if n + 1 == len(_PA_TIERS) else _PA_TIERS[n + 1][0] - 0.5
        expected_tier += pts * (cdf(hi) - cdf(lo))

    events = 4.0 + 0.12 * (24.0 - opp_implied)
    return round(expected_tier + max(events, 1.5), 2)


def apply_dst_projections(df, lines):
    """
    Replace each defense's projection with one based on its opponent's
    Vegas team total. Defenses have no player props, so without this they
    fall back to last season's average and ignore the matchup entirely.
    """
    if not lines or "Position" not in df.columns:
        return df
    df = df.copy()
    for i in df.index[df["Position"] == "DST"]:
        abbr = str(df.at[i, "TeamAbbrev"]).upper()
        info = lines.get(ABBR_ALIASES.get(abbr, abbr))
        if info:
            df.at[i, "Projection"] = dst_projection(info["opp_implied"])
            df.at[i, "ProjectionSource"] = "Vegas game line (DST)"
    return df

