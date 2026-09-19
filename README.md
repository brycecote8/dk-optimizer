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

### Showdown / Captain Mode (single-game contests)

DraftKings runs single-game slates (Thursday night, Monday night) as
**Showdown**, which is a different game entirely:

| | Classic | Showdown |
|---|---|---|
| Players | 9 | 6 |
| Positions | 1 QB, 2 RB, 3 WR, 1 TE, 1 FLEX, 1 DST | 1 CPT + 5 FLEX (any position) |
| Captain | — | scores **1.5x** points, costs **1.5x** salary |
| Games | 2+ required | exactly 1, must use **both teams** |
| Kickers | no | yes |

The app **auto-detects** which one your salary file is (Showdown exports list
every player twice, as CPT and FLEX, and cover one game). You can override it
with the **Contest format** control under Strategy.

Because the Captain costs 1.5x salary as well as scoring 1.5x, picking him is
a real trade-off — the optimizer solves it rather than just captaining your
highest-projected player. Stacking and bring-back don't apply in Showdown
(there's only one game), but ceiling and leverage do.

### Auto-fetch Vegas projections (free)

Instead of finding projections yourself, the app can build them from live
betting lines — the sharpest free projections there are.

One-time setup:
1. Go to **the-odds-api.com** and sign up for a free key (takes ~2 minutes).
2. In the app, choose **"Auto-fetch Vegas projections (free)"**.
3. Upload your DraftKings salary CSV (still needed for salaries/positions).
4. Paste your key, tick **Remember this key on this computer**, and click
   **🔍 Check slates (free)**.
5. Pick the slate you're playing from the dropdown. The app shows exactly how
   many credits that slate costs before you spend anything.
6. Click **🔄 Fetch Vegas projections**, then check the **Preview the fetched
   projections** expander — the top names should look like real stars.
7. Click **Generate Lineups**.

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
| Sunday main slate | ~13 | ~80 |
| Monday night | 1 | 6 |
| **Per week (all three)** | | **~90** |
| **Per month** | | **~390 of 500** ✅ |

Fetching the *full week* three times a week instead costs ~1,240/month and
will blow the budget in under two weeks. Always use **🔍 Check slates (free)**
and pick the single slate you're actually playing — the app shows the exact
cost before you spend anything.

Re-generating lineups is free; it reuses the projections you already fetched.
Only click Fetch again when lines have moved (e.g. injury news).

### Tracking your results (📈 My results tab)

Theory can't tell you whether your settings are good — only measurement can.
After you enter a lineup on DraftKings, click **💾 Save this lineup to my
results**. It records the lineup *and the settings that built it* (ceiling vs
mean, leverage, stack, bring-back).

Once the games finish, open the **📈 My results** tab and enter the actual
score (plus entry fee and winnings if you want profit tracked). The summary
table then groups every scored lineup by its settings, so you can see which
combination is genuinely working for you.

Everything lives in `results/history.csv` — a plain spreadsheet you can open
in Excel. It is git-ignored, so your personal record never leaves your Mac.

> Give it several weeks. Five lineups is noise; a month of Sundays starts to
> be signal.

### When to fetch projections

Fetch **once, late** — about an hour before kickoff. NFL inactives are
announced 90 minutes before the first game, which is the biggest information
event of the week. Before that you're guessing about questionable players;
after it, the betting lines have absorbed the news. For a 1:00pm ET Sunday
slate, fetch between **11:30am and 12:30pm ET**.

When a player is ruled out, sportsbooks pull his props entirely. The app uses
that as the signal to drop him from the pool (see "Drop players with no Vegas
line"), which is why fetching after inactives matters so much.

### Injured players

Real DraftKings salary files include a `Status` column. The app always removes
players DraftKings marks OUT, IR, Doubtful, or suspended before optimizing.
Questionable (Q) players are kept, since most of them play.

### Strategy controls (section 3 in the app)

Two different things, easy to confuse:

- **Roster format** is *which roster you fill*: Classic (9 players, many
  games) or Showdown (6 players, one game). Your salary file decides it.
- **Payout style** is *how the prize money is split*: top-heavy tournament,
  or even-payout 50/50 / double-up. That's the contest you click on at
  DraftKings.

They're independent. Classic and Showdown each run as tournaments **and** as
50/50s. Payout style is what should drive your strategy:

| Payout style | Optimize for | Leverage | Stack | Bring-back | Risk |
|---|---|---|---|---|---|
| Top-heavy: small tournament (default) | Ceiling | 2 | 2 | 1 | Higher by design. Most entries lose. |
| Top-heavy: large tournament | Ceiling | 8 | 2 | 1 | Highest. Built to look nothing like the crowd. |
| Even payout: 50/50, double-up | Floor | 0 | 0 | 0 | Lower. Beat half the field, flat payout. |

Tournament settings chase upside and deliberately trade projected points for
lower ownership. That is right for tournaments and wrong for even-payout
contests: they produce lineups that lose most weeks and occasionally finish
big. If you want steadier results, enter a 50/50 instead and switch this to
**Even payout** — that works in Classic and Showdown alike.

Pick **Custom** to adjust them yourself.

### Defenses

Defenses have no player props. When you fetch Vegas projections, the app also
pulls every game's spread and total (one call, 2 credits) and projects each
defense from how many points its opponent is expected to score, weighted
through DraftKings' points-allowed tiers. Without this, a defense's projection
is last season's average and ignores who it's playing.

What the individual controls do:

- **Optimize for** — *Floor* is a player's bad-day score, *Ceiling* his
  big-day score, *Average* the middle. Floors come from the betting lines
  themselves: points from catches and yards are steady, points from
  touchdowns are close to a coin flip, so two players with the same
  projection can have very different bad days.
- **Leverage** — how many projected points you'll give up to be different.
  The optimizer finds the best lineup, then the least-popular lineup within
  that many points of it. Cash games: 0. Small tournaments: 3–6. Big
  tournaments: 8–15.
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
