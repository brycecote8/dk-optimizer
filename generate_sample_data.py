"""
generate_sample_data.py
------------------------
Creates two fake CSV files so we can test the optimizer WITHOUT real data:

  data/sample_salaries.csv     - looks like a real DraftKings NFL salary export
  data/sample_projections.csv  - a separate projections file (Name, ProjectedPoints)

Run it with:  python generate_sample_data.py

The data is generated with a fixed random "seed" so you get the SAME players
and numbers every time. That makes testing predictable.
"""

import csv
import os
import random

# A "seed" locks the randomness so results are repeatable.
random.seed(42)

# Where to put the files. os.path keeps this working on any computer.
HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# 1) Define the "slate": which teams play, and in which games.
#    A DraftKings slate is a set of games. Each game has two teams.
# ---------------------------------------------------------------------------
GAMES = [
    ("KC", "BUF"),   # Game 1
    ("SF", "DAL"),   # Game 2
    ("MIA", "PHI"),  # Game 3
    ("CIN", "BAL"),  # Game 4
]

# How many players of each position to create PER TEAM.
# This gives us a big enough pool to build 20 different lineups.
PER_TEAM = {
    "QB": 1,
    "RB": 3,
    "WR": 4,
    "TE": 2,
    "DST": 1,
}

# Realistic-ish salary ranges ($) for each position on DraftKings.
SALARY_RANGE = {
    "QB": (6000, 8200),
    "RB": (4200, 9000),
    "WR": (3600, 8600),
    "TE": (2800, 6200),
    "DST": (2200, 3800),
}

# Rough points-per-dollar so higher salary usually means higher projection,
# but with some noise so the optimizer has interesting trade-offs to make.
POINTS_PER_1000 = {
    "QB": 2.6,
    "RB": 2.5,
    "WR": 2.5,
    "TE": 2.2,
    "DST": 3.0,
}


def make_game_info(home, away):
    """DraftKings writes game info like 'KC@BUF 09/08/2024 01:00PM ET'."""
    return f"{away}@{home} 09/08/2024 01:00PM ET"


def build_players():
    players = []
    next_id = 30000001  # fake DraftKings player IDs, just need to be unique

    for home, away in GAMES:
        game_info = make_game_info(home, away)
        for team in (home, away):
            for pos, count in PER_TEAM.items():
                for n in range(1, count + 1):
                    lo, hi = SALARY_RANGE[pos]
                    # Round salaries to the nearest $100, like DraftKings does.
                    salary = random.randint(lo // 100, hi // 100) * 100

                    # Projection = salary-based base + random noise.
                    base = (salary / 1000.0) * POINTS_PER_1000[pos]
                    noise = random.uniform(-3.0, 3.0)
                    avg_points = max(0.0, round(base + noise, 1))

                    name = f"{team} {pos}{n}"
                    players.append({
                        "Position": pos,
                        "Name": name,
                        "ID": next_id,
                        "Salary": salary,
                        "GameInfo": game_info,
                        "TeamAbbrev": team,
                        "AvgPointsPerGame": avg_points,
                    })
                    next_id += 1
    return players


def write_salaries(players):
    """Write the DraftKings-style salary file."""
    path = os.path.join(DATA_DIR, "sample_salaries.csv")
    # These are the columns DraftKings gives you (plus ID, which real
    # exports also include and which we need for the upload file later).
    fields = ["Position", "Name", "ID", "Salary",
              "GameInfo", "TeamAbbrev", "AvgPointsPerGame"]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for p in players:
            writer.writerow({k: p[k] for k in fields})
    return path


def write_projections(players):
    """
    Write a SEPARATE projections file (Name, ProjectedPoints).
    We nudge each number a little away from AvgPointsPerGame so you can SEE
    that importing projections actually changes the optimizer's choices.
    """
    path = os.path.join(DATA_DIR, "sample_projections.csv")
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Name", "ProjectedPoints"])
        for p in players:
            projected = max(0.0, round(p["AvgPointsPerGame"] + random.uniform(-2.5, 4.0), 1))
            writer.writerow([p["Name"], projected])
    return path


if __name__ == "__main__":
    players = build_players()
    sal_path = write_salaries(players)
    proj_path = write_projections(players)
    print(f"Created {len(players)} players.")
    print(f"  Salaries    -> {sal_path}")
    print(f"  Projections -> {proj_path}")
