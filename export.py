"""
export.py
---------
Turns the optimizer's lineups into the CSV that DraftKings' "bulk upload"
feature expects.

DraftKings wants exactly these 9 columns, in this order:
    QB, RB, RB, WR, WR, WR, TE, FLEX, DST
and each cell holds the player, written as "Name (ID)".

The tricky part is the FLEX slot: it holds the EXTRA running back, receiver,
or tight end (whichever position has one more than its minimum). This file
figures out which player that is and slots everyone correctly.
"""

import csv
import io

# The exact column order DraftKings requires for NFL Classic uploads.
DK_UPLOAD_HEADER = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST"]


def _cell(row):
    """Format one player the way DraftKings reads it: 'Name (ID)'."""
    return f"{row['Name']} ({row['ID']})"


def assign_slots(lineup_indexes, df):
    """
    Given the 9 chosen player row-numbers, return them arranged into the
    DraftKings slot order: [QB, RB, RB, WR, WR, WR, TE, FLEX, DST].
    """
    # Group the chosen players by position.
    by_pos = {"QB": [], "RB": [], "WR": [], "TE": [], "DST": []}
    for i in lineup_indexes:
        by_pos[df.loc[i, "Position"]].append(i)

    # Fill the required slots first; whatever is left over is the FLEX.
    qb = by_pos["QB"][:1]
    rb = by_pos["RB"][:2]
    wr = by_pos["WR"][:3]
    te = by_pos["TE"][:1]
    dst = by_pos["DST"][:1]

    used = set(qb + rb + wr + te + dst)
    flex = [i for i in lineup_indexes if i not in used]  # the one extra player

    ordered = qb + rb + wr + te + flex + dst
    return ordered


def _write_rows(writer, lineups, df):
    """Shared logic: write the header and one row per lineup."""
    writer.writerow(DK_UPLOAD_HEADER)
    for lineup in lineups:
        ordered = assign_slots(lineup, df)
        writer.writerow([_cell(df.loc[i]) for i in ordered])


def export_lineups(lineups, df, out_path):
    """
    Write all lineups to `out_path` in DraftKings bulk-upload format.
    Returns the path written.
    """
    with open(out_path, "w", newline="") as f:
        _write_rows(csv.writer(f), lineups, df)
    return out_path


def lineups_to_csv_string(lineups, df):
    """
    Same output as export_lineups, but returned as a text string instead of
    written to disk. The web app uses this to power its Download button.
    """
    buffer = io.StringIO()
    _write_rows(csv.writer(buffer), lineups, df)
    return buffer.getvalue()


# DraftKings Showdown (single-game) upload columns.
DK_SHOWDOWN_HEADER = ["CPT", "FLEX", "FLEX", "FLEX", "FLEX", "FLEX"]


def _showdown_cell(row, as_captain=False):
    """
    Format one Showdown player. Captains have their OWN DraftKings ID, so the
    upload file must use the captain ID in the CPT column.
    """
    pid = row["CptID"] if as_captain and "CptID" in row.index else row["ID"]
    return f"{row['Name']} ({pid})"


def showdown_to_csv_string(lineups, df):
    """Showdown lineups as a DraftKings-format CSV string."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(DK_SHOWDOWN_HEADER)
    for lu in lineups:
        cells = [_showdown_cell(df.loc[lu["captain"]], as_captain=True)]
        cells += [_showdown_cell(df.loc[i]) for i in lu["flex"]]
        writer.writerow(cells)
    return buffer.getvalue()
