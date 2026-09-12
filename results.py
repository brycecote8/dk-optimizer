"""
results.py
----------
Keeps a record of the lineups you actually entered, and what they scored.

This is how you answer "are my settings any good?" — not by arguing about
theory, but by measuring. Every saved lineup records the settings that built
it (leverage, stack, ceiling vs mean), so after a few weeks you can compare
how each combination actually performed.

Everything is stored in one plain CSV (results/history.csv) that you can open
in Excel any time. It is NOT committed to git — it's your personal record.
"""

import csv
import os
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(HERE, "results")
HISTORY = os.path.join(RESULTS_DIR, "history.csv")

FIELDS = [
    "id", "saved_at", "slate", "format",
    "objective", "leverage", "stack", "bring_back",
    "players", "salary", "projected", "total_own",
    "actual", "contest", "entry_fee", "winnings", "notes",
]


def _ensure():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    if not os.path.exists(HISTORY):
        with open(HISTORY, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writeheader()


def load_history():
    """Every saved lineup, newest first. Returns a list of dicts."""
    _ensure()
    with open(HISTORY, newline="") as f:
        rows = list(csv.DictReader(f))
    return list(reversed(rows))


def save_lineup(players, salary, projected, total_own, settings,
                slate="", fmt="classic", notes=""):
    """
    Record one lineup you entered. `players` is a list of names in slot order.
    `settings` is a dict with objective/leverage/stack/bring_back.
    Returns the new entry's id.
    """
    _ensure()
    existing = load_history()
    new_id = str(len(existing) + 1)
    row = {
        "id": new_id,
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "slate": slate,
        "format": fmt,
        "objective": settings.get("objective", ""),
        "leverage": settings.get("leverage", ""),
        "stack": settings.get("stack", ""),
        "bring_back": settings.get("bring_back", ""),
        "players": " | ".join(players),
        "salary": salary,
        "projected": projected,
        "total_own": total_own,
        "actual": "", "contest": "", "entry_fee": "", "winnings": "",
        "notes": notes,
    }
    with open(HISTORY, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=FIELDS).writerow(row)
    return new_id


def update_entry(entry_id, **changes):
    """
    Fill in how a lineup actually did (actual score, winnings, etc).
    Only the fields you pass are changed.
    """
    _ensure()
    with open(HISTORY, newline="") as f:
        rows = list(csv.DictReader(f))
    hit = False
    for r in rows:
        if r["id"] == str(entry_id):
            for k, v in changes.items():
                if k in FIELDS:
                    r[k] = v
            hit = True
    if hit:
        with open(HISTORY, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
    return hit


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def summary_by_settings():
    """
    Group scored lineups by the settings that built them, so you can see which
    combination actually performs. Only counts lineups you've entered a real
    score for.
    """
    rows = [r for r in load_history() if _num(r.get("actual")) is not None]
    groups = {}
    for r in rows:
        key = (f"{r['objective']} | lev {r['leverage']} | "
               f"stack {r['stack']} | bring-back {r['bring_back']}")
        g = groups.setdefault(key, {"n": 0, "actual": 0.0, "projected": 0.0,
                                    "fee": 0.0, "won": 0.0})
        g["n"] += 1
        g["actual"] += _num(r["actual"]) or 0.0
        g["projected"] += _num(r["projected"]) or 0.0
        g["fee"] += _num(r.get("entry_fee")) or 0.0
        g["won"] += _num(r.get("winnings")) or 0.0

    out = []
    for key, g in groups.items():
        n = g["n"]
        out.append({
            "Settings": key,
            "Lineups": n,
            "Avg actual": round(g["actual"] / n, 1),
            "Avg projected": round(g["projected"] / n, 1),
            # Positive means you beat the projection on average.
            "Beat projection by": round((g["actual"] - g["projected"]) / n, 1),
            "Profit": round(g["won"] - g["fee"], 2),
        })
    out.sort(key=lambda r: r["Avg actual"], reverse=True)
    return out
