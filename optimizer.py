"""
optimizer.py
------------
The "brain". Given a table of players (with a Projection column), it builds
lineups that score as high as possible while obeying all DraftKings rules.

We use "PuLP", a library that solves this kind of "pick the best combination
under these constraints" problem exactly (not by guessing).

DraftKings NFL Classic roster (9 players):
    1 QB, 2 RB, 3 WR, 1 TE, 1 FLEX (RB/WR/TE), 1 DST
    - Salary cap: $50,000
    - Max 8 players from the same team
    - Players from at least 2 different games

Diversity across the set of lineups:
    - No two lineups share more than MAX_SHARED players (default 6)
    - No single player appears in more than MAX_EXPOSURE of lineups (default 60%)
"""

import math
import pulp

# The exact roster slots DraftKings requires.
ROSTER_SIZE = 9
SALARY_CAP = 50000

# Position rules. FLEX means "one extra RB, WR, or TE".
# We express this as min/max counts per position:
#   RB: at least 2, at most 3 (2 required + possible flex)
#   WR: at least 3, at most 4
#   TE: at least 1, at most 2
POSITION_LIMITS = {
    "QB": (1, 1),
    "RB": (2, 3),
    "WR": (3, 4),
    "TE": (1, 2),
    "DST": (1, 1),
}


class InfeasibleError(Exception):
    """Raised when no valid lineup can be built (e.g. pool too small)."""


def _build_opponent_map(df):
    """
    Work out who each team plays, from the GameInfo column.
    DraftKings writes it like 'BUF@KC 09/08/2024 ...', meaning BUF plays KC.
    Returns a dict: team -> opponent team.
    """
    opponents = {}
    for gi in df["GameInfo"].unique():
        matchup = str(gi).split(" ")[0]          # e.g. "BUF@KC"
        if "@" in matchup:
            away, home = matchup.split("@")[:2]
            away, home = away.strip().upper(), home.strip().upper()
            opponents[away] = home
            opponents[home] = away
    return opponents


def _validate_pool(df):
    """Make sure the player pool can even form one legal lineup."""
    problems = []
    for pos, (need_min, _) in POSITION_LIMITS.items():
        have = (df["Position"] == pos).sum()
        if have < need_min:
            problems.append(f"need at least {need_min} {pos}, but only {have} in pool")
    if problems:
        raise InfeasibleError(
            "The player pool is too small to build a lineup: "
            + "; ".join(problems)
        )


def optimize(df, num_lineups=20, max_shared=6, max_exposure_pct=0.60,
             objective="mean", leverage_weight=0.0,
             stack_size=0, bring_back=0, verbose=True,
             leverage_budget=0.0, max_per_game=8, no_dst_conflict=False):
    """
    Build up to `num_lineups` lineups.

    New tournament options:
      objective        - "mean" (average points, good for cash games) or
                         "ceiling" (upside, good for tournaments).
      leverage_weight  - how hard to fade popular players. 0 = ignore ownership.
                         Higher = subtract more points for high ownership.
      stack_size       - require the QB to be paired with at least this many of
                         his OWN team's WR/TE (0 = no stack).
      bring_back       - require this many players from the QB's OPPONENT
                         (0 = no bring-back).
      leverage_budget  - how many projected points you'll give up to be
                         different. The optimizer finds the best lineup, then
                         the LEAST-OWNED lineup within this many points of it.
                         0 = just take the best lineup. Unlike leverage_weight,
                         every step of this has a predictable effect.
      max_per_game     - most players allowed from any single game. DraftKings
                         allows 8; lower spreads your risk across games. Never
                         set below what your stack needs (QB + stack + bring-back).
      no_dst_conflict  - never roster offensive players facing your own
                         defense, since the two root against each other.

    Returns a list of lineups. Each lineup is a list of row-index numbers that
    point back into the `df` table (so you can look up name, salary, etc).
    """
    _validate_pool(df)

    players = list(df.index)                 # the pool, by row number
    salary = df["Salary"].to_dict()          # row number -> salary
    pos = df["Position"].to_dict()           # row number -> position
    team = df["TeamAbbrev"].to_dict()        # row number -> team
    game = df["GameInfo"].to_dict()          # row number -> game

    # Pick which number we're maximizing: average points or ceiling (upside).
    score_col = {"ceiling": "Ceiling", "floor": "Floor"}.get(
        objective, "Projection")
    if score_col not in df.columns:
        raise ValueError(f"Need a '{score_col}' column for objective={objective!r}.")
    score = df[score_col].to_dict()

    # Ownership is only needed if we're applying leverage.
    if leverage_weight > 0 or leverage_budget > 0:
        if "Ownership" not in df.columns:
            raise ValueError("Need an 'Ownership' column to apply leverage.")
        own = df["Ownership"].to_dict()
    else:
        own = {i: 0.0 for i in players}

    teams = sorted(set(team.values()))
    games = sorted(set(game.values()))
    opponents = _build_opponent_map(df)

    # A player may appear in at most this many lineups (the 60% exposure cap).
    max_appearances = math.floor(max_exposure_pct * num_lineups)
    if max_appearances < 1:
        max_appearances = 1

    # A game cap below what the stack requires would make every QB unusable.
    game_cap = min(8, max(int(max_per_game), 1 + stack_size + bring_back))

    lineups = []
    usage = {i: 0 for i in players}          # how many lineups each player is in

    def build(name, sense):
        """A problem with every roster rule in place, but no objective yet."""
        prob = pulp.LpProblem(name, sense)
        x = {i: pulp.LpVariable(f"x_{i}", cat="Binary") for i in players}

        # Exactly 9 players.
        prob += pulp.lpSum(x[i] for i in players) == ROSTER_SIZE

        # Position minimums and maximums (this is what creates the FLEX).
        for p, (pmin, pmax) in POSITION_LIMITS.items():
            group = [x[i] for i in players if pos[i] == p]
            prob += pulp.lpSum(group) >= pmin
            prob += pulp.lpSum(group) <= pmax

        # Salary cap.
        prob += pulp.lpSum(salary[i] * x[i] for i in players) <= SALARY_CAP

        # Max 8 players from any one team.
        for t in teams:
            prob += pulp.lpSum(x[i] for i in players if team[i] == t) <= 8

        # At least 2 different games (DraftKings caps a game at 8), and your
        # own tighter limit on how much rides on any one game.
        for g in games:
            prob += pulp.lpSum(x[i] for i in players if game[i] == g) <= game_cap

        # Defense vs. your own offense: if a team's defense is in the lineup,
        # nobody from the offense it's facing can be.
        if no_dst_conflict:
            for d in players:
                if pos[d] != "DST":
                    continue
                opp = opponents.get(team[d])
                facing = [x[i] for i in players
                          if team[i] == opp and pos[i] in ("QB", "RB", "WR", "TE")]
                if facing:
                    prob += pulp.lpSum(facing) <= ROSTER_SIZE * (1 - x[d])

        # Stacking: if we pick a team's QB, force at least `stack_size` of that
        # same team's WR/TE into the lineup (QB + his pass-catchers).
        if stack_size > 0:
            for t in teams:
                qb_here = [x[i] for i in players if team[i] == t and pos[i] == "QB"]
                if not qb_here:
                    continue
                catchers = [x[i] for i in players
                            if team[i] == t and pos[i] in ("WR", "TE")]
                prob += pulp.lpSum(catchers) >= stack_size * pulp.lpSum(qb_here)

        # Bring-back: if we pick a team's QB, force `bring_back` offensive
        # players from the OPPONENT's team.
        if bring_back > 0:
            for t in teams:
                qb_here = [x[i] for i in players if team[i] == t and pos[i] == "QB"]
                opp = opponents.get(t)
                if not qb_here or opp is None:
                    continue
                opp_players = [x[i] for i in players
                               if team[i] == opp and pos[i] in ("RB", "WR", "TE")]
                prob += pulp.lpSum(opp_players) >= bring_back * pulp.lpSum(qb_here)

        # Exposure cap: if a player already hit the appearance limit, forbid it.
        for i in players:
            if usage[i] >= max_appearances:
                prob += x[i] == 0

        # Diversity: overlap with each previous lineup must be <= max_shared.
        for prev in lineups:
            prob += pulp.lpSum(x[i] for i in prev) <= max_shared

        return prob, x

    solver = pulp.PULP_CBC_CMD(msg=False)

    for k in range(num_lineups):
        # Stage 1: the best lineup available under every rule.
        prob, x = build(f"best_{k}", pulp.LpMaximize)
        prob += pulp.lpSum(
            (score[i] - leverage_weight * own[i]) * x[i] for i in players
        )
        status = prob.solve(solver)
        if pulp.LpStatus[status] != "Optimal":
            if verbose:
                print(f"  Stopped after {len(lineups)} lineup(s): no more "
                      f"lineups satisfy all the diversity rules.")
            break
        chosen = [i for i in players if x[i].value() > 0.5]

        # Stage 2 (leverage): the least-owned lineup that stays within
        # `leverage_budget` points of that best one.
        if leverage_budget > 0:
            best = sum(score[i] for i in chosen)
            prob2, y = build(f"lev_{k}", pulp.LpMinimize)
            prob2 += (pulp.lpSum(score[i] * y[i] for i in players)
                      >= best - leverage_budget)
            # Tiny tie-breaker so equal-ownership options prefer more points.
            prob2 += pulp.lpSum((own[i] - 0.001 * score[i]) * y[i]
                                for i in players)
            if pulp.LpStatus[prob2.solve(solver)] == "Optimal":
                chosen = [i for i in players if y[i].value() > 0.5]

        lineups.append(chosen)
        for i in chosen:
            usage[i] += 1

    return lineups


# ---------------------------------------------------------------------------
# Showdown / Captain Mode (single-game contests)
# ---------------------------------------------------------------------------
SHOWDOWN_ROSTER_SIZE = 6
CAPTAIN_MULTIPLIER = 1.5


def optimize_showdown(df, num_lineups=20, max_shared=4, max_exposure_pct=0.60,
                      objective="mean", leverage_weight=0.0, verbose=True,
                      leverage_budget=0.0):
    """
    Build lineups for a DraftKings Showdown (single-game) contest.

    Completely different rules from Classic:
      - 6 players, not 9.
      - Exactly 1 CAPTAIN, who scores 1.5x points but also COSTS 1.5x salary.
      - The other 5 are FLEX and can be ANY position (QB/RB/WR/TE/K/DST).
      - $50,000 cap.
      - Must use players from BOTH teams.

    Because the Captain both scores and costs 1.5x, choosing him is a real
    trade-off — that's why this needs its own model rather than a tweak to the
    Classic one.

    Expects `df` to have a CptSalary column (see loader.prepare_showdown).
    Returns a list of dicts: {"captain": idx, "flex": [idx, ...]}.
    """
    if "CptSalary" not in df.columns:
        raise ValueError("Showdown needs a 'CptSalary' column "
                         "(run loader.prepare_showdown first).")

    players = list(df.index)
    if len(players) < SHOWDOWN_ROSTER_SIZE:
        raise InfeasibleError(
            f"Need at least {SHOWDOWN_ROSTER_SIZE} players, got {len(players)}.")

    salary = df["Salary"].to_dict()
    cpt_salary = df["CptSalary"].to_dict()
    team = df["TeamAbbrev"].to_dict()

    score_col = {"ceiling": "Ceiling", "floor": "Floor"}.get(
        objective, "Projection")
    if score_col not in df.columns:
        raise ValueError(f"Need a '{score_col}' column for objective={objective!r}.")
    score = df[score_col].to_dict()

    if leverage_weight > 0 or leverage_budget > 0:
        if "Ownership" not in df.columns:
            raise ValueError("Need an 'Ownership' column to apply leverage.")
        own = df["Ownership"].to_dict()
    else:
        own = {i: 0.0 for i in players}

    teams = sorted(set(team.values()))
    if len(teams) < 2:
        raise InfeasibleError(
            "Showdown needs players from both teams, but this file only has "
            f"one team ({teams[0] if teams else 'none'}).")

    max_appearances = max(1, math.floor(max_exposure_pct * num_lineups))

    lineups = []
    usage = {i: 0 for i in players}

    def build(name, sense):
        """Every Showdown rule in place, no objective yet."""
        prob = pulp.LpProblem(name, sense)
        # Two separate decisions per player: captain him, or flex him.
        c = {i: pulp.LpVariable(f"c_{i}", cat="Binary") for i in players}
        f = {i: pulp.LpVariable(f"f_{i}", cat="Binary") for i in players}

        prob += pulp.lpSum(c[i] for i in players) == 1
        prob += pulp.lpSum(f[i] for i in players) == SHOWDOWN_ROSTER_SIZE - 1

        # A player can't be both captain and flex.
        for i in players:
            prob += c[i] + f[i] <= 1

        # Captain costs 1.5x salary.
        prob += pulp.lpSum(cpt_salary[i] * c[i] + salary[i] * f[i]
                           for i in players) <= SALARY_CAP

        # Must use both teams: cap any single team at 5 of the 6 spots.
        for t in teams:
            prob += pulp.lpSum(c[i] + f[i] for i in players
                               if team[i] == t) <= SHOWDOWN_ROSTER_SIZE - 1

        for i in players:
            if usage[i] >= max_appearances:
                prob += c[i] + f[i] == 0

        for prev in lineups:
            prev_players = [prev["captain"]] + prev["flex"]
            prob += pulp.lpSum(c[i] + f[i] for i in prev_players) <= max_shared

        return prob, c, f

    def points(c, f):
        return pulp.lpSum(CAPTAIN_MULTIPLIER * score[i] * c[i] + score[i] * f[i]
                          for i in players)

    solver = pulp.PULP_CBC_CMD(msg=False)

    for k in range(num_lineups):
        prob, c, f = build(f"showdown_{k}", pulp.LpMaximize)
        # Captain scores 1.5x; flex 1x. Legacy leverage penalty applies to both.
        prob += pulp.lpSum(
            (CAPTAIN_MULTIPLIER * score[i] - leverage_weight * own[i]) * c[i]
            + (score[i] - leverage_weight * own[i]) * f[i]
            for i in players
        )
        status = prob.solve(solver)
        if pulp.LpStatus[status] != "Optimal":
            if verbose:
                print(f"  Stopped after {len(lineups)} lineup(s).")
            break

        captain = [i for i in players if c[i].value() > 0.5][0]
        flex = [i for i in players if f[i].value() > 0.5]

        # Leverage: least-owned lineup within `leverage_budget` points.
        if leverage_budget > 0:
            best = (CAPTAIN_MULTIPLIER * score[captain]
                    + sum(score[i] for i in flex))
            prob2, c2, f2 = build(f"sd_lev_{k}", pulp.LpMinimize)
            prob2 += points(c2, f2) >= best - leverage_budget
            prob2 += pulp.lpSum((own[i] - 0.001 * score[i]) * (c2[i] + f2[i])
                                for i in players)
            if pulp.LpStatus[prob2.solve(solver)] == "Optimal":
                captain = [i for i in players if c2[i].value() > 0.5][0]
                flex = [i for i in players if f2[i].value() > 0.5]

        lineups.append({"captain": captain, "flex": flex})
        for i in [captain] + flex:
            usage[i] += 1

    return lineups


def showdown_totals(lineup, df, score_col="Projection"):
    """Salary and points for one Showdown lineup, with the 1.5x captain bonus."""
    cap, flex = lineup["captain"], lineup["flex"]
    salary = int(df.loc[cap, "CptSalary"] + df.loc[flex, "Salary"].sum())
    points = float(CAPTAIN_MULTIPLIER * df.loc[cap, score_col]
                   + df.loc[flex, score_col].sum())
    return salary, round(points, 1)
