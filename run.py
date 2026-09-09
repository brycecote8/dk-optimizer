"""
run.py
------
The one command you run. It:
  1) reads the salary file (and optional projections file),
  2) builds the lineups,
  3) prints them in a readable way in the terminal,
  4) writes the DraftKings upload CSV,
  5) double-checks that CSV is valid.

Basic use (uses the sample data):
    python run.py

Common options:
    python run.py --salaries data/sample_salaries.csv \
                  --projections data/sample_projections.csv \
                  --lineups 20 \
                  --output output/lineups.csv
"""

import argparse
import csv
import os

import loader
import optimizer
import export


# DraftKings slot order, repeated here so run.py can sanity-check the export.
EXPECTED_HEADER = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST"]


def parse_args():
    here = os.path.dirname(os.path.abspath(__file__))
    p = argparse.ArgumentParser(description="DraftKings NFL lineup optimizer.")
    p.add_argument("--salaries",
                   default=os.path.join(here, "data", "sample_salaries.csv"),
                   help="Path to the DraftKings salary CSV export.")
    p.add_argument("--projections", default=None,
                   help="Optional path to a projections CSV (Name, ProjectedPoints). "
                        "If omitted, DraftKings AvgPointsPerGame is used.")
    p.add_argument("--lineups", type=int, default=20,
                   help="How many lineups to generate (default 20).")
    p.add_argument("--max-shared", type=int, default=6,
                   help="Max players two lineups may share (default 6).")
    p.add_argument("--max-exposure", type=float, default=0.60,
                   help="Max fraction of lineups any one player can appear in "
                        "(default 0.60 = 60%%).")
    p.add_argument("--output",
                   default=os.path.join(here, "output", "lineups.csv"),
                   help="Where to write the DraftKings upload CSV.")
    return p.parse_args()


def print_lineups(lineups, df):
    """Print each lineup as a small readable table in the terminal."""
    for n, lineup in enumerate(lineups, start=1):
        ordered = export.assign_slots(lineup, df)
        total_salary = int(df.loc[lineup, "Salary"].sum())
        total_proj = round(float(df.loc[lineup, "Projection"].sum()), 1)

        print(f"\nLineup {n}   "
              f"Projected: {total_proj} pts   Salary: ${total_salary:,} / $50,000")
        print("  " + "-" * 52)
        slot_names = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST"]
        for slot, i in zip(slot_names, ordered):
            row = df.loc[i]
            print(f"  {slot:<5} {row['Name']:<10} {row['TeamAbbrev']:<4} "
                  f"${int(row['Salary']):>6,}   {row['Projection']:>5} pts")


def print_exposure(lineups, df):
    """Show how often each player was used, as a % of all lineups."""
    if not lineups:
        return
    counts = {}
    for lineup in lineups:
        for i in lineup:
            counts[i] = counts.get(i, 0) + 1

    total = len(lineups)
    print(f"\nPlayer exposure (used in how many of the {total} lineups):")
    print("  " + "-" * 40)
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    for i, c in ranked:
        row = df.loc[i]
        pct = round(100 * c / total)
        print(f"  {row['Name']:<10} {row['Position']:<4} "
              f"{c:>2}/{total}  ({pct:>3}%)")


def validate_export(path):
    """
    Re-open the exported CSV and confirm it is a valid DraftKings upload file:
    correct header, and every row has 9 non-empty player cells.
    """
    with open(path, newline="") as f:
        rows = list(csv.reader(f))

    if not rows:
        raise ValueError("Export is empty.")

    header = rows[0]
    if header != EXPECTED_HEADER:
        raise ValueError(f"Header is wrong.\n  expected: {EXPECTED_HEADER}\n  got:      {header}")

    for n, row in enumerate(rows[1:], start=1):
        if len(row) != 9:
            raise ValueError(f"Lineup {n} has {len(row)} columns, expected 9.")
        if any(cell.strip() == "" for cell in row):
            raise ValueError(f"Lineup {n} has an empty slot.")

    return len(rows) - 1  # number of lineups


def main():
    args = parse_args()

    print("=" * 60)
    print("DraftKings NFL Lineup Optimizer")
    print("=" * 60)

    # Step 1: load the salary file.
    print(f"\n[1/4] Reading salaries: {args.salaries}")
    df = loader.load_salaries(args.salaries)
    print(f"      Loaded {len(df)} players.")

    # Step 2: attach projections (imported file OR AvgPointsPerGame fallback).
    if args.projections:
        print(f"[2/4] Reading projections: {args.projections}")
    else:
        print("[2/4] No projections file given -> using DraftKings AvgPointsPerGame.")
    df = loader.apply_projections(df, args.projections)

    # Step 3: optimize.
    print(f"[3/4] Building up to {args.lineups} lineups "
          f"(max {args.max_shared} shared, max {int(args.max_exposure * 100)}% exposure)...")
    lineups = optimizer.optimize(
        df,
        num_lineups=args.lineups,
        max_shared=args.max_shared,
        max_exposure_pct=args.max_exposure,
    )
    print(f"      Built {len(lineups)} lineup(s).")

    if not lineups:
        print("\nNo lineups could be built. Check your player pool / rules.")
        return

    # Show them.
    print_lineups(lineups, df)
    print_exposure(lineups, df)

    # Step 4: export + validate.
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    export.export_lineups(lineups, df, args.output)
    count = validate_export(args.output)
    print(f"\n[4/4] Exported {count} lineups -> {args.output}")
    print("      Export validated: header correct, all 9 slots filled. ✓")


if __name__ == "__main__":
    main()
