"""
app.py
------
The friendly web-app version of the optimizer.

It uses the SAME engine you already tested (loader.py, optimizer.py,
export.py) — this file just puts buttons, sliders, and tables on top so you
never have to type commands.

You don't run this the normal way. Either double-click the "Start DK
Optimizer" launcher, or run:

    ./venv/bin/streamlit run app.py

...and it opens in your web browser.
"""

import os

import pandas as pd
import streamlit as st

import loader
import keystore
import metrics
import optimizer
import export
import results
import vegas

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE_SALARIES = os.path.join(HERE, "data", "sample_salaries.csv")
SAMPLE_PROJECTIONS = os.path.join(HERE, "data", "sample_projections.csv")

# Slot order used to lay out each lineup as a readable row.
SLOTS = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST"]


# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------
st.set_page_config(page_title="DK NFL Optimizer", page_icon="🏈", layout="wide")

st.title("🏈 DraftKings NFL Lineup Optimizer")
st.caption("Upload your files, set your rules, click Generate. Same engine, no typing.")


# ---------------------------------------------------------------------------
# Sidebar: all the inputs live here so the main area stays for results.
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("1. Your data")

    source = st.radio(
        "Where should the players come from?",
        ["Use sample data (try it now)",
         "Upload my own files",
         "Auto-fetch Vegas projections (free)"],
    )

    salary_file = None
    projections_file = None
    api_key = None
    drop_inactive = False

    if source == "Upload my own files":
        salary_file = st.file_uploader(
            "Salary CSV (DraftKings export)", type=["csv"],
            help="The salary file you download from DraftKings.",
        )
        projections_file = st.file_uploader(
            "Projections CSV (optional)", type=["csv"],
            help="Columns: Name, ProjectedPoints. If skipped, DraftKings "
                 "AvgPointsPerGame is used instead.",
        )

    elif source == "Auto-fetch Vegas projections (free)":
        st.caption("Projections built automatically from live betting lines. "
                   "Get a free key at the-odds-api.com.")
        salary_file = st.file_uploader(
            "Salary CSV (DraftKings export)", type=["csv"],
            help="Still needed — it provides salaries and positions.",
        )
        # If a key was saved on this computer before, pre-fill it.
        saved_key = keystore.load_key()
        api_key = st.text_input(
            "Free API key", type="password", value=saved_key or "",
            help="Paste it once and tick 'Remember' — it stays on this Mac.",
        )
        remember = st.checkbox("Remember this key on this computer",
                               value=bool(saved_key))

        # Step 1: list the game days. Listing games is FREE — only pulling
        # props costs credits — so always look before you spend.
        if st.button("🔍 Check slates (free)", width='stretch'):
            if not api_key:
                st.warning("Paste your free API key first.")
            else:
                if remember:
                    keystore.save_key(api_key)
                try:
                    groups = vegas.group_by_gameday(vegas.fetch_events(api_key))
                    st.session_state["gamedays"] = [
                        {"label": lbl, "key": k, "events": evs}
                        for lbl, k, evs in groups[:10]
                    ]
                except vegas.VegasError as e:
                    st.error(str(e))

        # Step 2: pick the exact slate you're playing, see the cost, then fetch.
        gamedays = st.session_state.get("gamedays")
        if gamedays:
            labels = [g["label"] for g in gamedays]
            # Default to the biggest slate (usually the Sunday main slate).
            default = max(range(len(gamedays)),
                          key=lambda i: len(gamedays[i]["events"]))
            chosen = st.selectbox("Which slate are you playing?", labels,
                                  index=default)
            picked = next(g for g in gamedays if g["label"] == chosen)
            cost = vegas.estimate_cost(len(picked["events"]))
            st.info(f"Fetching this slate costs **{cost} credits**.")
            with st.expander("Games in this slate"):
                st.write("\n".join(
                    f"- {e['away_team']} @ {e['home_team']}"
                    for e in picked["events"]))

            if st.button("🔄 Fetch Vegas projections", type="primary",
                         width='stretch'):
                try:
                    with st.spinner("Pulling betting lines from all books..."):
                        rows, meta = vegas.fetch_projections_for(
                            api_key, picked["events"])
                    st.session_state["vegas_rows"] = rows
                    st.session_state["vegas_meta"] = meta
                except vegas.VegasError as e:
                    st.session_state.pop("vegas_rows", None)
                    st.error(str(e))

        if saved_key and st.button("Forget saved key", width='stretch'):
            keystore.forget_key()
            st.rerun()

        drop_inactive = st.checkbox(
            "Drop players with no Vegas line (recommended)", value=True,
            help="Sportsbooks pull a player's props when he's ruled OUT. "
                 "Without this, an inactive star falls back to his season "
                 "average and can get rostered, scoring zero. Defenses are "
                 "always kept — they never have betting lines.",
        )

        meta = st.session_state.get("vegas_meta")
        if "vegas_rows" in st.session_state and meta:
            st.success(
                f"Got projections for {meta['players']} players from "
                f"{meta['games']} games "
                f"(used ~{meta.get('credits_used', '?')} credits, "
                f"{meta.get('credits_remaining', '?')} left)."
            )
            with st.expander("Preview the fetched projections"):
                st.dataframe(
                    pd.DataFrame(st.session_state["vegas_rows"]).head(40),
                    width='stretch', hide_index=True,
                )

    else:
        st.info("Using the built-in sample slate (88 players, 4 games).")
        use_sample_projections = st.checkbox(
            "Also use the sample projections file", value=True
        )

    st.header("2. Your rules")
    num_lineups = st.slider("How many lineups?", 1, 150, 20)
    max_shared = st.slider(
        "Max players two lineups can share", 1, 8, 6,
        help="Lower = more different lineups.",
    )
    max_exposure = st.slider(
        "Max exposure per player (%)", 10, 100, 60,
        help="No single player appears in more than this share of lineups.",
    )

    st.header("3. Strategy")
    contest_format = st.radio(
        "Contest format",
        ["Auto-detect", "Classic (full slate)", "Showdown (single game)"],
        help="Classic = 9 players across many games. Showdown = 6 players from "
             "ONE game with a 1.5x Captain. Auto-detect reads your salary file.",
    )
    contest_type = st.radio(
        "Optimize for",
        ["Tournaments (upside)", "Cash games (safe)"],
        help="Tournaments use each player's ceiling (upside). Cash games use "
             "average points.",
    )
    objective = "ceiling" if contest_type.startswith("Tournaments") else "mean"

    leverage = st.slider(
        "Leverage — projected points to give up for uniqueness", 0, 20, 0,
        help="The optimizer finds the best lineup, then the least-popular "
             "lineup within this many points of it. 0 = just the best lineup. "
             "Cash games: 0. Small tournaments: 3–6. Big tournaments: 8–15.",
    )

    stack_size = st.slider(
        "Stack: QB + this many of his own WR/TE", 0, 3, 0,
        help="Pairs your QB with his own pass-catchers. Big driver of "
             "tournament upside. 0 = off.",
    )
    bring_back = st.slider(
        "Bring-back: players from the opposing team", 0, 2, 0,
        help="Adds a player from the other side of your QB's game — pays off "
             "in high-scoring shootouts. 0 = off.",
    )

    generate = st.button("⚡ Generate Lineups", type="primary", width='stretch')


# ---------------------------------------------------------------------------
# Helpers to turn results into nice tables.
# ---------------------------------------------------------------------------
def build_lineup_table(lineups, df):
    """One row per lineup: the 9 players plus Salary and Projected totals."""
    rows = []
    for n, lineup in enumerate(lineups, start=1):
        ordered = export.assign_slots(lineup, df)
        row = {"Lineup": n}
        for slot, i in zip(SLOTS, ordered):
            # If a slot label repeats (RB, WR), give the column a number.
            col = slot
            k = 2
            while col in row:
                col = f"{slot}{k}"
                k += 1
            row[col] = df.loc[i, "Name"]
        row["Salary"] = int(df.loc[lineup, "Salary"].sum())
        row["Proj"] = round(float(df.loc[lineup, "Projection"].sum()), 1)
        if "Ownership" in df.columns:
            row["Total Own%"] = round(float(df.loc[lineup, "Ownership"].sum()), 1)
        rows.append(row)
    return pd.DataFrame(rows)


def show_entry_card(lineup, df):
    """
    Show ONE lineup in a big, readable layout meant for typing straight into
    the DraftKings website (single-entry contests, where there's no file to
    upload). Includes a copy-friendly list of just the names.
    """
    ordered = export.assign_slots(lineup, df)

    total_salary = int(df.loc[lineup, "Salary"].sum())
    total_proj = round(float(df.loc[lineup, "Projection"].sum()), 1)
    left = 50000 - total_salary

    c1, c2, c3 = st.columns(3)
    c1.metric("Projected points", total_proj)
    c2.metric("Salary used", f"${total_salary:,}", f"${left:,} left")
    if "Ownership" in df.columns:
        c3.metric("Total field ownership",
                  f"{round(float(df.loc[lineup, 'Ownership'].sum()))}%",
                  help="Lower = more contrarian than the crowd.")

    # A markdown table renders large and clear — easy to read while typing.
    rows = ["| Slot | Player | Team | Salary | Proj |",
            "|---|---|---|---|---|"]
    for slot, i in zip(SLOTS, ordered):
        r = df.loc[i]
        rows.append(f"| **{slot}** | **{r['Name']}** | {r['TeamAbbrev']} | "
                    f"${int(r['Salary']):,} | {r['Projection']} |")
    st.markdown("\n".join(rows))

    # st.code gives a one-click copy button in the corner.
    st.caption("Copy-friendly list:")
    st.code("\n".join(f"{slot}: {df.loc[i, 'Name']}"
                      for slot, i in zip(SLOTS, ordered)), language="text")


def sd_players(lu):
    """All 6 player indexes of a Showdown lineup, captain first."""
    return [lu["captain"]] + lu["flex"]


def build_showdown_table(lineups, df):
    """One row per Showdown lineup: captain, the 5 flex, salary and points."""
    rows = []
    for n, lu in enumerate(lineups, start=1):
        sal, pts = optimizer.showdown_totals(lu, df)
        row = {"Lineup": n, "CPT": df.loc[lu["captain"], "Name"]}
        for j, i in enumerate(lu["flex"], start=1):
            row[f"FLEX{j}"] = df.loc[i, "Name"]
        row["Salary"] = sal
        row["Proj"] = pts
        if "Ownership" in df.columns:
            row["Total Own%"] = round(
                float(df.loc[sd_players(lu), "Ownership"].sum()), 1)
        rows.append(row)
    return pd.DataFrame(rows)


def show_showdown_card(lu, df):
    """One Showdown lineup, laid out for typing into DraftKings."""
    sal, pts = optimizer.showdown_totals(lu, df)
    c1, c2, c3 = st.columns(3)
    c1.metric("Projected points", pts)
    c2.metric("Salary used", f"${sal:,}", f"${50000 - sal:,} left")
    if "Ownership" in df.columns:
        c3.metric("Total field ownership",
                  f"{round(float(df.loc[sd_players(lu), 'Ownership'].sum()))}%")

    cap = df.loc[lu["captain"]]
    rows = ["| Slot | Player | Team | Salary | Proj |", "|---|---|---|---|---|",
            f"| **CPT** | **{cap['Name']}** | {cap['TeamAbbrev']} | "
            f"${int(cap['CptSalary']):,} | {round(cap['Projection'] * 1.5, 1)} (1.5x) |"]
    for i in lu["flex"]:
        r = df.loc[i]
        rows.append(f"| FLEX | **{r['Name']}** | {r['TeamAbbrev']} | "
                    f"${int(r['Salary']):,} | {r['Projection']} |")
    st.markdown("\n".join(rows))

    st.caption("Copy-friendly list:")
    lines = [f"CPT: {cap['Name']}"] + [f"FLEX: {df.loc[i, 'Name']}" for i in lu["flex"]]
    st.code("\n".join(lines), language="text")


def render_results_tab():
    """Your saved lineups: enter what they actually scored, see what works."""
    history = results.load_history()
    if not history:
        st.info("No saved lineups yet. Save one from the **🎯 Entry card** tab "
                "after you enter it on DraftKings.")
        return

    st.subheader("Enter what a lineup actually scored")
    unscored = [r for r in history if not r.get("actual")]
    target = unscored or history
    choice = st.selectbox(
        "Which entry?",
        [r["id"] for r in target],
        format_func=lambda i: next(
            f"#{r['id']} — {r['slate'] or r['saved_at']} "
            f"(projected {r['projected']})" for r in target if r["id"] == i),
    )
    c1, c2, c3 = st.columns(3)
    actual = c1.number_input("Actual score", min_value=0.0, step=0.1)
    fee = c2.number_input("Entry fee ($)", min_value=0.0, step=1.0)
    won = c3.number_input("Winnings ($)", min_value=0.0, step=1.0)
    if st.button("Save score"):
        results.update_entry(choice, actual=actual, entry_fee=fee, winnings=won)
        st.success(f"Recorded for entry #{choice}.")
        st.rerun()

    st.divider()
    st.subheader("Which settings are actually working?")
    summary = results.summary_by_settings()
    if summary:
        st.dataframe(pd.DataFrame(summary), width='stretch', hide_index=True)
        st.caption("'Beat projection by' shows whether your lineups outscored "
                   "what the model expected. Give it several weeks — a handful "
                   "of lineups is noise, not signal.")
    else:
        st.info("Enter a few real scores above and this table will fill in.")

    st.divider()
    st.subheader("All saved lineups")
    st.dataframe(pd.DataFrame(history), width='stretch', hide_index=True)


def build_exposure_table(lineups, df):
    """How often each player was used, as a count and a percentage."""
    counts = {}
    for lineup in lineups:
        members = sd_players(lineup) if isinstance(lineup, dict) else lineup
        for i in members:
            counts[i] = counts.get(i, 0) + 1
    total = len(lineups)
    rows = []
    for i, c in counts.items():
        entry = {
            "Player": df.loc[i, "Name"],
            "Pos": df.loc[i, "Position"],
            "Team": df.loc[i, "TeamAbbrev"],
            "Lineups": c,
            "Exposure %": round(100 * c / total),
        }
        if "Ownership" in df.columns:
            # The crowd's projected ownership, for comparison to YOUR exposure.
            entry["Field Own %"] = round(float(df.loc[i, "Ownership"]))
        rows.append(entry)
    out = pd.DataFrame(rows).sort_values(
        "Lineups", ascending=False).reset_index(drop=True)
    return out


# ---------------------------------------------------------------------------
# When the button is clicked: run the pipeline and stash results.
# ---------------------------------------------------------------------------
if generate:
    try:
        # Figure out the salary + projections inputs based on the chosen source.
        if source == "Upload my own files":
            if salary_file is None:
                st.error("Please upload a salary CSV first (left sidebar).")
                st.stop()
            salary_input = salary_file
            projections_input = projections_file  # may be None

        elif source == "Auto-fetch Vegas projections (free)":
            if salary_file is None:
                st.error("Upload your DraftKings salary CSV first (left sidebar).")
                st.stop()
            if "vegas_rows" not in st.session_state:
                st.error("Click '🔄 Fetch Vegas projections' first (left sidebar).")
                st.stop()
            salary_input = salary_file
            # Hand the fetched projections straight to the loader as a table.
            projections_input = pd.DataFrame(st.session_state["vegas_rows"])

        else:
            salary_input = SAMPLE_SALARIES
            projections_input = SAMPLE_PROJECTIONS if use_sample_projections else None

        with st.spinner("Reading players and building lineups..."):
            raw = loader.load_salaries(salary_input)
            # DraftKings marks injured/inactive players directly. Always honor it.
            raw, injured = loader.drop_injured(raw)
            st.session_state["injured"] = injured

            # Showdown (single-game) files list every player twice and cover
            # one game. They need a completely different optimizer.
            if contest_format == "Auto-detect":
                showdown = loader.is_showdown(raw)
            else:
                showdown = contest_format.startswith("Showdown")

            if showdown:
                df = loader.prepare_showdown(raw)
            else:
                df = raw

            df = loader.apply_projections(df, projections_input,
                                          drop_unmatched=drop_inactive)
            df = metrics.enrich(df)   # add Ceiling + Ownership (or estimates)

            if showdown:
                lineups = optimizer.optimize_showdown(
                    df,
                    num_lineups=num_lineups,
                    max_shared=min(max_shared, 4),
                    max_exposure_pct=max_exposure / 100.0,
                    objective=objective,
                    leverage_budget=leverage,
                    verbose=False,
                )
            else:
                lineups = optimizer.optimize(
                    df,
                    num_lineups=num_lineups,
                    max_shared=max_shared,
                    max_exposure_pct=max_exposure / 100.0,
                    objective=objective,
                    leverage_budget=leverage,
                    stack_size=stack_size,
                    bring_back=bring_back,
                    verbose=False,
                )

        # Save into session so results survive the download-button rerun.
        st.session_state["df"] = df
        st.session_state["lineups"] = lineups
        st.session_state["requested"] = num_lineups
        st.session_state["showdown"] = showdown
        st.session_state["settings"] = {
            "objective": objective, "leverage": leverage,
            "stack": stack_size, "bring_back": bring_back,
        }

    except optimizer.InfeasibleError as e:
        st.error(f"Couldn't build lineups: {e}")
        st.stop()
    except Exception as e:  # noqa: BLE001 - show any error plainly to the user
        st.error(f"Something went wrong: {e}")
        st.stop()


# ---------------------------------------------------------------------------
# Show results (from session, so they persist between clicks).
# ---------------------------------------------------------------------------
if "lineups" in st.session_state:
    df = st.session_state["df"]
    lineups = st.session_state["lineups"]
    requested = st.session_state.get("requested", len(lineups))

    if not lineups:
        st.warning("No valid lineups could be built. Try loosening your rules.")
    else:
        # Top-line summary numbers.
        showdown = st.session_state.get("showdown", False)
        members = (lambda lu: sd_players(lu)) if showdown else (lambda lu: lu)

        c1, c2, c3 = st.columns(3)
        c1.metric("Lineups built", f"{len(lineups)}", f"of {requested} requested")
        if showdown:
            avg_proj = round(sum(optimizer.showdown_totals(lu, df)[1]
                                 for lu in lineups) / len(lineups), 1)
        else:
            avg_proj = round(sum(float(df.loc[lu, "Projection"].sum())
                                 for lu in lineups) / len(lineups), 1)
        c2.metric("Avg projected points", avg_proj)
        players_used = len({i for lu in lineups for i in members(lu)})
        c3.metric("Unique players used", players_used)

        st.caption("**Showdown / Captain Mode** — 6 players from one game."
                   if showdown else
                   "**Classic** — 9 players across the slate.")

        if len(lineups) < requested:
            st.info(
                f"Built {len(lineups)} of {requested}. The diversity rules ran "
                "out of room — loosen 'max shared' or raise 'max exposure' for more."
            )

        injured = st.session_state.get("injured") or []
        if injured:
            st.caption(f"Removed {len(injured)} players DraftKings lists as "
                       "OUT / IR / Doubtful.")

        # Warn if players didn't get real projections (usually a name mismatch).
        stats = df.attrs.get("match_stats")
        if stats:
            missing = stats["unmatched_names"]
            st.caption(
                f"Projections matched {stats['matched']} of {stats['total']} "
                f"players."
                + (f" {stats['unmatched_dst']} defenses used DraftKings averages "
                   "(normal — defenses have no betting lines)."
                   if stats["unmatched_dst"] else "")
            )
            if stats.get("dropped"):
                st.warning(
                    f"Removed {len(stats['dropped'])} player(s) with no Vegas "
                    "line — likely inactive. They can't be rostered.")
                with st.expander("Who was removed"):
                    st.write(", ".join(stats["dropped"][:60]))
            elif missing:
                with st.expander(
                        f"⚠️ {len(missing)} players fell back to DraftKings "
                        "averages — click to see who"):
                    st.write(
                        "These names didn't match your projections source. "
                        "Backups and inactive players are expected here; a "
                        "well-known starter in this list means a name mismatch."
                    )
                    st.write(", ".join(missing[:60]))

        # The all-important download button (for bulk entry / NBA later).
        csv_text = (export.showdown_to_csv_string(lineups, df) if showdown
                    else export.lineups_to_csv_string(lineups, df))
        st.download_button(
            "⬇️ Download DraftKings upload CSV",
            data=csv_text,
            file_name="lineups.csv",
            mime="text/csv",
        )

        # Entry card first: it's what you need for single-entry contests.
        tab0, tab1, tab2, tab3 = st.tabs(
            ["🎯 Entry card", "📋 All lineups", "📊 Player exposure",
             "📈 My results"])

        with tab0:
            if len(lineups) > 1:
                pick = st.selectbox(
                    "Which lineup?",
                    range(1, len(lineups) + 1),
                    format_func=lambda n: (
                        f"Lineup {n} — "
                        + (f"{optimizer.showdown_totals(lineups[n-1], df)[1]} pts"
                           if showdown else
                           f"{round(float(df.loc[lineups[n-1], 'Projection'].sum()), 1)} pts")
                    ),
                )
            else:
                pick = 1
            st.caption("Type these into DraftKings, slot by slot.")
            lu = lineups[pick - 1]
            if showdown:
                show_showdown_card(lu, df)
            else:
                show_entry_card(lu, df)

            # Record what you actually entered, so you can measure later.
            st.divider()
            slate_label = st.text_input(
                "Slate name (for your records)",
                value=str(df["GameInfo"].iloc[0]).split(" ")[0] if len(df) else "",
            )
            if st.button("💾 Save this lineup to my results"):
                if showdown:
                    ordered = [lu["captain"]] + lu["flex"]
                    sal, proj = optimizer.showdown_totals(lu, df)
                else:
                    ordered = export.assign_slots(lu, df)
                    sal = int(df.loc[lu, "Salary"].sum())
                    proj = round(float(df.loc[lu, "Projection"].sum()), 1)
                own = (round(float(df.loc[ordered, "Ownership"].sum()), 1)
                       if "Ownership" in df.columns else "")
                eid = results.save_lineup(
                    [df.loc[i, "Name"] for i in ordered], sal, proj, own,
                    st.session_state.get("settings", {}),
                    slate=slate_label,
                    fmt="showdown" if showdown else "classic",
                )
                st.success(f"Saved as entry #{eid}. Add the real score in "
                           "the **📈 My results** tab after the games.")

        with tab1:
            table = (build_showdown_table(lineups, df) if showdown
                     else build_lineup_table(lineups, df))
            st.dataframe(table, width='stretch', hide_index=True)

        with tab2:
            exposure = build_exposure_table(lineups, df)
            st.dataframe(
                exposure, width='stretch', hide_index=True,
                column_config={
                    "Exposure %": st.column_config.ProgressColumn(
                        "Exposure %", min_value=0, max_value=100, format="%d%%"
                    )
                },
            )

        with tab3:
            render_results_tab()
else:
    st.info("👈 Set your options in the sidebar, then click **Generate Lineups**.")
