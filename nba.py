"""
nba.py
------
Everything NBA-specific: DraftKings NBA scoring, turning NBA betting lines
into projections, which roster slots each player can fill, and the NBA
Classic optimizer.

DraftKings NBA Classic roster (8 players, $50,000 cap):
    PG, SG, SF, PF, C, G (any PG/SG), F (any SF/PF), UTIL (anyone)
    - Players must come from at least 2 different games.

NBA Showdown uses the same Captain format as NFL (1 Captain at 1.5x points
and salary, 5 others, both teams), so it reuses optimizer.optimize_showdown.
"""

import csv
import io
import math
from collections import defaultdict

import pulp

from optimizer import InfeasibleError

SPORT_KEY = "basketball_nba"
SALARY_CAP = 50000
SLOTS = ["PG", "SG", "SF", "PF", "C", "G", "F", "UTIL"]
ROSTER_SIZE = len(SLOTS)

# The betting markets we buy, 1 credit per game each. Points, rebounds,
# assists and threes are posted for nearly every rotation player. Steals and
# blocks are posted for only a handful, so they aren't worth the credits.
MARKETS = {
    "player_points": "pts",
    "player_rebounds": "reb",
    "player_assists": "ast",
    "player_threes": "threes",
}

# DraftKings NBA Classic scoring.
POINT, THREE, REBOUND, ASSIST = 1.0, 0.5, 1.25, 1.5
STEAL, BLOCK, TURNOVER = 2.0, 2.0, -0.5
DOUBLE_DOUBLE, TRIPLE_DOUBLE = 1.5, 3.0

# Typical steals, blocks and turnovers for a full-minutes player. ESTIMATES,
# scaled down for lower-usage players below. Together they're worth only
# about 2 DraftKings points a night, which is why we don't buy those lines.
STEALS_FULL, BLOCKS_FULL, TURNOVERS_FULL = 0.85, 0.55, 1.6


def _prob_at_least(line, threshold, spread, min_sd):
    """Chance a stat reaches `threshold` when its betting line (the median) is `line`."""
    if line <= 0:
        return 0.0
    sd = max(spread * line, min_sd)
    z = (threshold - line) / sd
    return 0.5 * (1.0 - math.erf(z / math.sqrt(2.0)))


def collect_player_stats(events):
    """Average each player's lines across all sportsbooks."""
    lines = defaultdict(lambda: defaultdict(list))
    for ev in events:
        for book in ev.get("bookmakers", []):
            for market in book.get("markets", []):
                stat = MARKETS.get(market.get("key"))
                if not stat:
                    continue
                for oc in market.get("outcomes", []):
                    name, point = oc.get("description"), oc.get("point")
                    if name and point is not None:
                        lines[name][stat].append(float(point))
    return {name: {s: sum(v) / len(v) for s, v in stats.items()}
            for name, stats in lines.items()}


def stats_to_range(stats):
    """(floor, mean, ceiling) DraftKings points for one player's stat lines."""
    pts = stats.get("pts", 0.0)
    reb = stats.get("reb", 0.0)
    ast = stats.get("ast", 0.0)
    threes = stats.get("threes", 0.0)

    # Bench players get fewer steals and blocks than starters. Points +
    # rebounds + assists is a decent stand-in for how much someone plays.
    usage = min(1.3, max(0.3, (pts + reb + ast) / 25.0))

    # Double-double / triple-double bonuses, by the chance each category
    # reaches 10 (treated as independent — a simplification).
    p_pts = _prob_at_least(pts, 10, 0.30, 4.0)
    p_reb = _prob_at_least(reb, 10, 0.38, 2.5)
    p_ast = _prob_at_least(ast, 10, 0.42, 2.0)
    p_dd = (p_pts * p_reb + p_pts * p_ast + p_reb * p_ast
            - 2 * p_pts * p_reb * p_ast)
    p_td = p_pts * p_reb * p_ast

    mean = (pts * POINT + threes * THREE + reb * REBOUND + ast * ASSIST
            + STEALS_FULL * usage * STEAL + BLOCKS_FULL * usage * BLOCK
            + TURNOVERS_FULL * usage * TURNOVER
            + DOUBLE_DOUBLE * p_dd + TRIPLE_DOUBLE * p_td)

    return range_from_mean(mean)


# How much a player's night-to-night score swings. Counting stats (points,
# rebounds, assists) spread out with the SQUARE ROOT of the average, not in
# proportion to it: a 50-point star typically lands 40-60, while a 15-point
# bench player can score 5 or 30. So cheaper, lower-minute players carry more
# upside (and more risk) relative to their projection. The 1.35 scale is an
# estimate that puts a 50-point star's typical swing near 10 points.
SWING = 1.35


def range_from_mean(mean):
    """(floor, mean, ceiling): roughly a bad night, typical, and a 1-in-10 night."""
    sd = SWING * math.sqrt(max(mean, 0.0))
    return (round(max(0.0, mean - sd), 2), round(mean, 2),
            round(mean + 1.28 * sd, 2))


def is_nba_position(position):
    return all(p in ("PG", "SG", "SF", "PF", "C")
               for p in str(position).upper().split("/"))


def events_to_projections(events):
    """Raw NBA odds data -> list of {Name, ProjectedPoints, Floor, Ceiling}."""
    rows = []
    for name, s in collect_player_stats(events).items():
        if "pts" not in s:
            continue  # no points line means not a real part of the rotation
        floor, mean, ceiling = stats_to_range(s)
        rows.append({"Name": name, "ProjectedPoints": mean,
                     "Floor": floor, "Ceiling": ceiling})
    rows.sort(key=lambda r: r["ProjectedPoints"], reverse=True)
    return rows


def eligible_slots(position):
    """
    Which Classic slots a player can fill. DraftKings lists dual positions as
    "PG/SG"; every player can play UTIL, guards can play G, forwards F.
    """
    slots = {"UTIL"}
    for p in str(position).upper().split("/"):
        p = p.strip()
        if p in ("PG", "SG", "SF", "PF", "C"):
            slots.add(p)
        if p in ("PG", "SG"):
            slots.add("G")
        if p in ("SF", "PF"):
            slots.add("F")
    return slots


def optimize_classic(df, num_lineups=5, max_shared=6, max_exposure_pct=1.0,
                     objective="ceiling", leverage_budget=0.0, verbose=False):
    """
    Build NBA Classic lineups. Each lineup is returned as a list of 8 row
    indexes in slot order: PG, SG, SF, PF, C, G, F, UTIL.

    Same ideas as the NFL optimizer: maximise the chosen score, then (if
    leverage_budget > 0) take the least-popular lineup within that many points.
    """
    players = list(df.index)
    elig = {i: eligible_slots(df.at[i, "Position"]) for i in players}
    for s in SLOTS:
        if not any(s in elig[i] for i in players):
            raise InfeasibleError(f"No player in the pool can play {s}.")

    score_col = {"ceiling": "Ceiling", "floor": "Floor"}.get(objective, "Projection")
    score = df[score_col].to_dict()
    salary = df["Salary"].to_dict()
    game = df["GameInfo"].to_dict()
    own = (df["Ownership"].to_dict() if leverage_budget > 0 and "Ownership" in df.columns
           else {i: 0.0 for i in players})
    games = sorted(set(game.values()))
    if len(games) < 2:
        raise InfeasibleError("NBA Classic needs at least 2 games on the slate. "
                              "For a single game, use Showdown.")

    max_appearances = max(1, math.floor(max_exposure_pct * num_lineups))
    usage = {i: 0 for i in players}
    lineups = []

    def build(name, sense):
        prob = pulp.LpProblem(name, sense)
        y = {(i, s): pulp.LpVariable(f"y_{i}_{s}", cat="Binary")
             for i in players for s in elig[i]}
        used = {i: pulp.lpSum(y[i, s] for s in elig[i]) for i in players}

        for s in SLOTS:                               # every slot filled once
            prob += pulp.lpSum(y[i, s] for i in players if s in elig[i]) == 1
        for i in players:                             # nobody in two slots
            prob += used[i] <= 1
        prob += pulp.lpSum(salary[i] * used[i] for i in players) <= SALARY_CAP
        for g in games:                               # at least 2 games
            prob += pulp.lpSum(used[i] for i in players if game[i] == g) <= ROSTER_SIZE - 1
        for i in players:
            if usage[i] >= max_appearances:
                prob += used[i] == 0
        for prev in lineups:
            prob += pulp.lpSum(used[i] for i in prev) <= max_shared
        return prob, y, used

    solver = pulp.PULP_CBC_CMD(msg=False)
    for k in range(num_lineups):
        prob, y, used = build(f"nba_{k}", pulp.LpMaximize)
        prob += pulp.lpSum(score[i] * used[i] for i in players)
        if pulp.LpStatus[prob.solve(solver)] != "Optimal":
            if verbose:
                print(f"  Stopped after {len(lineups)} lineup(s).")
            break

        if leverage_budget > 0:
            best = sum(score[i] for i in players if used[i].value() > 0.5)
            prob2, y2, used2 = build(f"nba_lev_{k}", pulp.LpMinimize)
            prob2 += pulp.lpSum(score[i] * used2[i] for i in players) >= best - leverage_budget
            prob2 += pulp.lpSum((own[i] - 0.001 * score[i]) * used2[i] for i in players)
            if pulp.LpStatus[prob2.solve(solver)] == "Optimal":
                y = y2

        ordered = [next(i for i in players if s in elig[i] and y[i, s].value() > 0.5)
                   for s in SLOTS]
        lineups.append(ordered)
        for i in ordered:
            usage[i] += 1
    return lineups


def lineups_to_csv_string(lineups, df):
    """NBA Classic lineups in DraftKings upload format."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(SLOTS)
    for lu in lineups:
        writer.writerow([f"{df.at[i, 'Name']} ({df.at[i, 'ID']})" for i in lu])
    return buffer.getvalue()
