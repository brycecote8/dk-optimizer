"""
metrics.py
----------
Adds two extra numbers to each player that tournaments care about:

  Ceiling   - a player's realistic BEST-case game (their upside), used when you
              optimize for tournaments instead of cash games.
  Ownership - the % of the field expected to roster this player. Low ownership
              on a good player = "leverage" = how you separate from the crowd.

If your projections file already has 'Ceiling' or 'Ownership' columns, we use
those. If not, we ESTIMATE them from projection, salary, and matchup. The
estimates are clearly labeled as estimates — real ownership data is the one
thing paid sites truly have an edge on, but a good estimate captures most of it.
"""

import pandas as pd

# How much boom each position typically has. Receivers and tight ends are
# "boomier" (bigger ceilings) than running backs and quarterbacks.
CEILING_MULTIPLIER = {
    "QB": 1.30,
    "RB": 1.45,
    "WR": 1.65,
    "TE": 1.70,
    "DST": 1.75,
}


def ensure_ceiling(df):
    """
    Guarantee a 'Ceiling' column. If it's missing (or empty), estimate it as
    Projection * a position-based upside multiplier.
    """
    df = df.copy()
    if "Ceiling" in df.columns and df["Ceiling"].notna().any():
        df["Ceiling"] = pd.to_numeric(df["Ceiling"], errors="coerce")
        # Fill any blanks with the estimate so no player is left empty.
        est = df.apply(_estimate_ceiling, axis=1)
        df["Ceiling"] = df["Ceiling"].fillna(est)
        df["CeilingSource"] = df["Ceiling"].notna().map(
            {True: "Imported", False: "Estimated"})
        return df

    df["Ceiling"] = df.apply(_estimate_ceiling, axis=1)
    df["CeilingSource"] = "Estimated"
    return df


def _estimate_ceiling(row):
    mult = CEILING_MULTIPLIER.get(row["Position"], 1.4)
    return round(float(row["Projection"]) * mult, 1)


def ensure_floor(df):
    """
    Guarantee a 'Floor' column: a realistic bad game. Vegas-derived floors
    come from the projections themselves (steady yards and catches versus
    all-or-nothing touchdowns). Without them, estimate at 60% of projection.
    """
    df = df.copy()
    if "Floor" in df.columns and df["Floor"].notna().any():
        df["Floor"] = pd.to_numeric(df["Floor"], errors="coerce")
        df["Floor"] = df["Floor"].fillna((df["Projection"] * 0.60).round(1))
        return df
    df["Floor"] = (df["Projection"] * 0.60).round(1)
    return df


def ensure_ownership(df):
    """
    Guarantee an 'Ownership' column (a percentage, e.g. 25.0 means 25%).

    If missing, ESTIMATE it. The estimate is built on the idea that the crowd
    piles onto "value" — lots of projected points for a low salary. So:
        value = projected points per $1,000 of salary
        popularity ~ value AND raw projection
    We then stretch those popularity scores onto a realistic 1%-45% range.
    """
    df = df.copy()
    if "Ownership" in df.columns and df["Ownership"].notna().any():
        df["Ownership"] = pd.to_numeric(df["Ownership"], errors="coerce")
        df["Ownership"] = df["Ownership"].fillna(df["Ownership"].median())
        df["OwnershipSource"] = "Imported"
        return df

    proj = df["Projection"].clip(lower=0)
    salary_k = (df["Salary"] / 1000.0).clip(lower=0.1)
    value = proj / salary_k                      # points per $1,000

    # Popularity score: value matters most, but raw ceiling of points helps too.
    raw = (value ** 1.5) * proj

    # Stretch onto a 1%-45% range so it looks like real ownership.
    lo, hi = raw.min(), raw.max()
    if hi > lo:
        own = 1.0 + 44.0 * (raw - lo) / (hi - lo)
    else:
        own = pd.Series(10.0, index=df.index)

    df["Ownership"] = own.round(1)
    df["OwnershipSource"] = "Estimated"
    return df


def enrich(df):
    """Add Ceiling, Floor and Ownership in one call."""
    return ensure_ownership(ensure_floor(ensure_ceiling(df)))
