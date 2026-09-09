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
    contest_type = st.radio(
        "Optimize for",
        ["Tournaments (upside)", "Cash games (safe)"],
        help="Tournaments use each player's ceiling (upside). Cash games use "
             "average points.",
    )
    objective = "ceiling" if contest_type.startswith("Tournaments") else "mean"

    leverage = st.slider(
        "Leverage — fade popular players", 0, 10, 0,
        help="0 = ignore ownership (chase points). Higher = avoid the crowd's "
             "popular picks to stand out in tournaments.",
    )
    # Turn the 0-10 dial into the penalty the optimizer uses.
    leverage_weight = leverage * 0.03

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


def build_exposure_table(lineups, df):
    """How often each player was used, as a count and a percentage."""
    counts = {}
    for lineup in lineups:
        for i in lineup:
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
            df = loader.load_salaries(salary_input)
            df = loader.apply_projections(df, projections_input)
            df = metrics.enrich(df)   # add Ceiling + Ownership (or estimates)
            lineups = optimizer.optimize(
                df,
                num_lineups=num_lineups,
                max_shared=max_shared,
                max_exposure_pct=max_exposure / 100.0,
                objective=objective,
                leverage_weight=leverage_weight,
                stack_size=stack_size,
                bring_back=bring_back,
                verbose=False,
            )

        # Save into session so results survive the download-button rerun.
        st.session_state["df"] = df
        st.session_state["lineups"] = lineups
        st.session_state["requested"] = num_lineups

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
        c1, c2, c3 = st.columns(3)
        c1.metric("Lineups built", f"{len(lineups)}", f"of {requested} requested")
        avg_proj = round(
            sum(float(df.loc[lu, "Projection"].sum()) for lu in lineups) / len(lineups), 1)
        c2.metric("Avg projected points", avg_proj)
        players_used = len({i for lu in lineups for i in lu})
        c3.metric("Unique players used", players_used)

        if len(lineups) < requested:
            st.info(
                f"Built {len(lineups)} of {requested}. The diversity rules ran "
                "out of room — loosen 'max shared' or raise 'max exposure' for more."
            )

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
            if missing:
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
        csv_text = export.lineups_to_csv_string(lineups, df)
        st.download_button(
            "⬇️ Download DraftKings upload CSV",
            data=csv_text,
            file_name="lineups.csv",
            mime="text/csv",
        )

        # Entry card first: it's what you need for single-entry contests.
        tab0, tab1, tab2 = st.tabs(
            ["🎯 Entry card", "📋 All lineups", "📊 Player exposure"])

        with tab0:
            if len(lineups) > 1:
                pick = st.selectbox(
                    "Which lineup?",
                    range(1, len(lineups) + 1),
                    format_func=lambda n: (
                        f"Lineup {n} — "
                        f"{round(float(df.loc[lineups[n-1], 'Projection'].sum()), 1)} pts"
                    ),
                )
            else:
                pick = 1
            st.caption("Type these into DraftKings, slot by slot.")
            show_entry_card(lineups[pick - 1], df)

        with tab1:
            table = build_lineup_table(lineups, df)
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
else:
    st.info("👈 Set your options in the sidebar, then click **Generate Lineups**.")
