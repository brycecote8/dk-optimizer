# DK Optimizer — DraftKings NFL Lineup Optimizer

Generates optimal DraftKings NFL Classic lineups from a salary CSV and
(optionally) your own projections, then exports them ready for bulk upload.

## What it does

- Reads a DraftKings NFL salary CSV export.
- Uses either your imported projections OR DraftKings' `AvgPointsPerGame`.
- Builds lineups that obey all DraftKings Classic rules:
  - 1 QB, 2 RB, 3 WR, 1 TE, 1 FLEX (RB/WR/TE), 1 DST
  - $50,000 salary cap
  - Max 8 players from one team
  - Players from at least 2 different games
- Keeps the set diverse:
  - No two lineups share more than 6 players
  - No player appears in more than 60% of lineups (default)
- Exports a valid DraftKings bulk-upload CSV.

## Easiest way: the web app (no typing)

Double-click **`Start DK Optimizer.command`** in the `dk-optimizer` folder.
A browser tab opens with buttons and sliders:

1. Choose sample data or upload your own salary/projections CSVs.
2. Set how many lineups and your diversity rules with the sliders.
3. Click **Generate Lineups**.
4. Review the lineups and exposure tables, then click
   **Download DraftKings upload CSV**.

To stop the app, close the little terminal window that opened alongside it.

### Entering one lineup (single-entry contests)

The **🎯 Entry card** tab shows one lineup at a time in a big, readable layout
with a copy-friendly name list — made for typing straight into the DraftKings
website. Generate a handful of lineups, use the dropdown to compare them, and
enter the one you like. No file upload needed.

The **Download DraftKings upload CSV** button is for bulk entry (many lineups
at once) — useful later for NBA.

### Auto-fetch Vegas projections (free)

Instead of finding projections yourself, the app can build them from live
betting lines — the sharpest free projections there are.

One-time setup:
1. Go to **the-odds-api.com** and sign up for a free key (takes ~2 minutes).
2. In the app, choose **"Auto-fetch Vegas projections (free)"**.
3. Upload your DraftKings salary CSV (still needed for salaries/positions).
4. Paste your key, tick **Remember this key on this computer**, and click
   **🔄 Fetch Vegas projections**.
5. Check the **Preview the fetched projections** expander — the top names
   should look like real stars. Then click **Generate Lineups**.

The saved key lives in a `.apikey` file in this folder, readable only by your
user account and excluded from git. **Forget saved key** in the app deletes it.

After generating, the app reports how many players matched. Defenses always
fall back to DraftKings averages (they have no betting lines) — that's normal.
If a well-known starter shows up in the "fell back" list, that's a name
mismatch worth reporting.

The app pulls each player's betting lines (passing/rushing/receiving yards,
catches, touchdown odds) from all major books, averages them, and converts
them to DraftKings points automatically. Defense (DST) has no betting lines,
so it falls back to AvgPointsPerGame.

### API credits (free tier = 500/month)

Listing the slates is **free**. Only fetching props costs credits, at
**6 credits per game**:

| Slate | Games | Cost |
|---|---|---|
| Thursday night | 1 | 6 |
| Sunday main slate | ~13 | ~78 |
| Monday night | 1 | 6 |
| **Per week (all three)** | | **~90** |
| **Per month** | | **~390 of 500** ✅ |

Fetching the *full week* three times a week instead costs ~1,240/month and
will blow the budget in under two weeks. Always use **🔍 Check slates (free)**
and pick the single slate you're actually playing — the app shows the exact
cost before you spend anything.

Re-generating lineups is free; it reuses the projections you already fetched.
Only click Fetch again when lines have moved (e.g. injury news).

### Strategy controls (section 3 in the app)

These are what make lineups better than a basic free optimizer:

- **Optimize for** — *Tournaments* uses each player's ceiling (upside);
  *Cash games* uses average points.
- **Leverage** — how hard to fade popular (high-ownership) players. 0 chases
  raw points; higher makes contrarian lineups that stand out in tournaments.
- **Stack** — pairs your QB with his own WR/TE (correlation = upside).
- **Bring-back** — adds a player from the opposing team in your QB's game.

If your projections CSV includes optional `Ceiling` and/or `Ownership`
columns, the app uses them. If not, it estimates both from projection, salary,
and matchup (clearly labeled as estimates).

> First time only: macOS may say the file is from an "unidentified developer."
> Right-click the file → **Open** → **Open**, and it'll trust it from then on.

The rest of this README covers the command-line version, which does the exact
same thing.

## One-time setup

Already done, but if you ever move to a new computer:

```bash
cd dk-optimizer
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

## How to run it

Everything runs through `run.py`. Always use the project's own Python at
`./venv/bin/python` so it finds the installed libraries.

**1. Make the sample test data (only needed once, or to reset it):**

```bash
./venv/bin/python generate_sample_data.py
```

**2. Run with the sample data (simplest):**

```bash
./venv/bin/python run.py
```

**3. Run with imported projections:**

```bash
./venv/bin/python run.py --projections data/sample_projections.csv
```

**4. Run with your OWN real files:**

```bash
./venv/bin/python run.py \
  --salaries data/DKSalaries.csv \
  --projections data/my_projections.csv \
  --lineups 20 \
  --output output/lineups.csv
```

The finished upload file is written to `output/lineups.csv`.

## Options

| Option           | Default                     | Meaning                                        |
|------------------|-----------------------------|------------------------------------------------|
| `--salaries`     | `data/sample_salaries.csv`  | DraftKings salary CSV export                    |
| `--projections`  | *(none → AvgPointsPerGame)* | Your projections CSV (`Name, ProjectedPoints`) |
| `--lineups`      | `20`                        | How many lineups to build                      |
| `--max-shared`   | `6`                         | Max players any two lineups may share          |
| `--max-exposure` | `0.60`                      | Max share of lineups one player can appear in  |
| `--output`       | `output/lineups.csv`        | Where to write the upload file                 |

## Input file formats

**Salary CSV** (standard DraftKings export) needs these columns:
`Position, Name, Salary, GameInfo, TeamAbbrev, AvgPointsPerGame`.
An `ID` column is used if present (real DraftKings exports include it and the
upload file needs it).

**Projections CSV** needs: `Name, ProjectedPoints`. Players are matched by
`Name`; anyone not listed falls back to `AvgPointsPerGame`.

## Project files

| File                       | Purpose                                        |
|----------------------------|------------------------------------------------|
| `run.py`                   | The command you run; ties everything together  |
| `loader.py`                | Reads salary + projections files               |
| `optimizer.py`             | The PuLP math engine that picks lineups        |
| `export.py`                | Writes the DraftKings bulk-upload CSV          |
| `generate_sample_data.py`  | Creates fake test data                         |
