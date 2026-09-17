"""
loader.py
---------
Reads your input files and hands back a clean table of players.

Two jobs:
  1) load_salaries()    - read the DraftKings salary CSV export.
  2) apply_projections() - decide each player's projected points, either from
                           a separate projections file OR (fallback) from the
                           DraftKings AvgPointsPerGame column.

We use "pandas", a library for working with spreadsheet-like tables.
A pandas table is called a "DataFrame".
"""

import re

import pandas as pd

# Name suffixes to ignore when matching (so "Michael Pittman Jr." matches
# "Michael Pittman").
_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def normalize_name(s):
    """Lowercase, strip punctuation and suffixes so names match more forgivingly."""
    s = str(s).lower()
    s = re.sub(r"[^a-z0-9 ]", "", s)
    parts = [p for p in s.split() if p not in _NAME_SUFFIXES]
    return " ".join(parts)


# The columns we require from the salary file. If any are missing we stop
# and tell you exactly which one, instead of failing in a confusing way later.
REQUIRED_SALARY_COLUMNS = [
    "Position", "Name", "Salary", "GameInfo", "TeamAbbrev", "AvgPointsPerGame",
]

# DraftKings sometimes labels its game column "Game Info" (with a space).
# We accept either and normalize it to "GameInfo".
COLUMN_ALIASES = {
    "Game Info": "GameInfo",
    "Name + ID": "NameID",
}


def load_salaries(csv_path):
    """
    Read the salary CSV and return a cleaned pandas DataFrame.
    Guarantees the columns: Position, Name, Salary, GameInfo, TeamAbbrev,
    AvgPointsPerGame, and (if present) ID.
    """
    df = pd.read_csv(csv_path)

    # Trim stray spaces from column names, then apply the aliases above.
    df.columns = [c.strip() for c in df.columns]
    df = df.rename(columns=COLUMN_ALIASES)

    # Check nothing important is missing.
    missing = [c for c in REQUIRED_SALARY_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            "Your salary file is missing these required columns: "
            f"{missing}. Found columns: {list(df.columns)}"
        )

    # Clean up the values.
    df["Position"] = df["Position"].astype(str).str.strip().str.upper()
    df["Name"] = df["Name"].astype(str).str.strip()
    df["TeamAbbrev"] = df["TeamAbbrev"].astype(str).str.strip().str.upper()

    # Salary can arrive as "5,000" or "$5000"; strip junk and make it a number.
    df["Salary"] = (
        df["Salary"].astype(str)
        .str.replace(r"[^0-9.]", "", regex=True)
        .astype(float)
        .astype(int)
    )

    df["AvgPointsPerGame"] = pd.to_numeric(
        df["AvgPointsPerGame"], errors="coerce"
    ).fillna(0.0)

    # If there's no ID column (a simplified file), create one from the row
    # number so the rest of the program still works.
    if "ID" not in df.columns:
        df["ID"] = ["NOID-" + str(i) for i in range(len(df))]
    df["ID"] = df["ID"].astype(str).str.strip()

    # Keep only valid DraftKings NFL positions. Kickers only exist in
    # Showdown (single-game) contests, never in Classic.
    valid = {"QB", "RB", "WR", "TE", "DST", "K"}
    before = len(df)
    df = df[df["Position"].isin(valid)].reset_index(drop=True)
    dropped = before - len(df)
    if dropped:
        print(f"  (Ignored {dropped} row(s) with non-NFL positions.)")

    # Normalize the Roster Position column if present (Showdown files use it
    # to mark the CPT and FLEX copies of each player).
    if "Roster Position" in df.columns:
        df = df.rename(columns={"Roster Position": "RosterPosition"})
    if "RosterPosition" in df.columns:
        df["RosterPosition"] = (
            df["RosterPosition"].astype(str).str.strip().str.upper())

    return df


# DraftKings injury statuses that mean the player will not play. "Q"
# (questionable) is deliberately NOT here — most questionable players suit up.
NOT_PLAYING = {"OUT", "O", "IR", "D", "DOUBTFUL", "PUP", "NA", "SUSP", "SUS", "NFI"}


def drop_injured(df):
    """
    Remove players DraftKings itself marks as not playing.

    Real DraftKings exports carry a Status column (OUT, IR, Q, ...). It is the
    most direct injury signal we have — far more reliable than inferring an
    injury from a missing betting line. Returns (clean_df, dropped_names).
    """
    if "Status" not in df.columns:
        return df, []
    status = df["Status"].fillna("").astype(str).str.strip().str.upper()
    out = status.isin(NOT_PLAYING)
    dropped = df.loc[out, "Name"].tolist()
    return df[~out].reset_index(drop=True), dropped


def is_showdown(df):
    """
    True if this looks like a DraftKings Showdown (single-game) salary file.

    Showdown exports list every player twice — once as CPT and once as FLEX —
    and cover exactly one game.
    """
    if "RosterPosition" in df.columns and (df["RosterPosition"] == "CPT").any():
        return True
    return df["GameInfo"].nunique() == 1


def prepare_showdown(df):
    """
    Collapse a Showdown salary file to ONE row per player, with two salaries:

        Salary     - the normal (FLEX) price
        CptSalary  - the Captain price (1.5x, where a Captain scores 1.5x too)

    Real DraftKings exports include both rows; if only one is present we derive
    the Captain price the way DraftKings does, at 1.5x.
    """
    df = df.copy()

    if "RosterPosition" in df.columns and (df["RosterPosition"] == "CPT").any():
        flex = df[df["RosterPosition"] != "CPT"].copy()
        cpt = df[df["RosterPosition"] == "CPT"].copy()
        cpt_salary = dict(zip(cpt["Name"], cpt["Salary"]))
        cpt_id = dict(zip(cpt["Name"], cpt["ID"]))
        base = flex.reset_index(drop=True)
        base["CptSalary"] = [
            int(cpt_salary.get(n, round(s * 1.5)))
            for n, s in zip(base["Name"], base["Salary"])
        ]
        # Captains have their own DraftKings ID — needed for the upload file.
        base["CptID"] = [str(cpt_id.get(n, i))
                         for n, i in zip(base["Name"], base["ID"])]
    else:
        base = df.reset_index(drop=True)
        base["CptSalary"] = (base["Salary"] * 1.5).round().astype(int)
        base["CptID"] = base["ID"]

    return base


def apply_projections(df, projections=None, drop_unmatched=False):
    """
    Add a 'Projection' column to the players table.

    `projections` may be:
      - None            -> everyone uses DraftKings AvgPointsPerGame.
      - a file path/CSV -> read it (needs Name, ProjectedPoints columns).
      - a DataFrame     -> used directly (e.g. handed over from the Vegas
                           auto-fetcher).

    Players are matched by name (forgiving of punctuation/suffixes). Anyone not
    found falls back to AvgPointsPerGame so no one is left at zero by accident.

    `drop_unmatched` matters a lot with Vegas projections. When a player is
    ruled OUT, sportsbooks PULL his props entirely — so "no Vegas line" is a
    strong signal he is not playing. Falling back to his season average would
    make an inactive star look like a great value and get him rostered, where
    he scores zero. With drop_unmatched=True those players are removed from
    the pool instead. Defenses are always kept, since they never have props.
    """
    df = df.copy()

    if projections is None:
        df["Projection"] = df["AvgPointsPerGame"]
        df["ProjectionSource"] = "AvgPointsPerGame (fallback)"
        return df

    if isinstance(projections, pd.DataFrame):
        proj = projections.copy()
    else:
        proj = pd.read_csv(projections)
    proj.columns = [c.strip() for c in proj.columns]

    for col in ("Name", "ProjectedPoints"):
        if col not in proj.columns:
            raise ValueError(
                "Your projections need columns 'Name' and "
                f"'ProjectedPoints'. Found: {list(proj.columns)}"
            )

    proj["Name"] = proj["Name"].astype(str).str.strip()
    proj["ProjectedPoints"] = pd.to_numeric(
        proj["ProjectedPoints"], errors="coerce"
    )

    # Look up by exact name first, then by a normalized name as a backup.
    lookup = dict(zip(proj["Name"], proj["ProjectedPoints"]))
    norm_lookup = {normalize_name(n): v
                   for n, v in zip(proj["Name"], proj["ProjectedPoints"])}

    projections_out = []
    sources = []
    matched = 0
    for _, row in df.iterrows():
        val = lookup.get(row["Name"])
        if val is None or pd.isna(val):
            val = norm_lookup.get(normalize_name(row["Name"]))
        if val is not None and not pd.isna(val):
            projections_out.append(float(val))
            sources.append("Imported projection")
            matched += 1
        else:
            projections_out.append(float(row["AvgPointsPerGame"]))
            sources.append("AvgPointsPerGame (fallback)")

    df["Projection"] = projections_out
    df["ProjectionSource"] = sources
    print(f"  Matched {matched} of {len(df)} players to imported projections "
          f"({len(df) - matched} used AvgPointsPerGame fallback).")

    # Record how the match went so the app can show it. DST is listed
    # separately because defenses never have betting props — falling back for
    # them is expected, not a problem.
    unmatched = df[df["ProjectionSource"] != "Imported projection"]
    unmatched_names = unmatched.loc[
        unmatched["Position"] != "DST", "Name"].tolist()
    stats = {
        "matched": matched,
        "total": len(df),
        "unmatched_names": unmatched_names,
        "unmatched_dst": int((unmatched["Position"] == "DST").sum()),
        "dropped": [],
    }

    if drop_unmatched and unmatched_names:
        # Keep defenses (never have props); drop everyone else with no line.
        keep = (df["ProjectionSource"] == "Imported projection") | (df["Position"] == "DST")
        stats["dropped"] = unmatched_names
        df = df[keep].reset_index(drop=True)
        print(f"  Dropped {len(unmatched_names)} player(s) with no projection "
              "(likely inactive).")

    df.attrs["match_stats"] = stats

    # Optional bonus columns: if the projections file also has Ceiling or
    # Ownership, carry them over (matched by Name). Anything not provided is
    # estimated later in metrics.py.
    for extra in ("Ceiling", "Ownership"):
        if extra in proj.columns:
            extra_lookup = dict(zip(proj["Name"],
                                    pd.to_numeric(proj[extra], errors="coerce")))
            df[extra] = [extra_lookup.get(name) for name in df["Name"]]

    return df
