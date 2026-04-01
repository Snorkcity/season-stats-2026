import dash
from dash import dcc, html, Input, Output, State, callback
import dash_bootstrap_components as dbc
import pandas as pd
from dash import dash_table
from dash import ctx
from dash import Dash
import plotly.express as px
import gspread
import plotly.graph_objects as go
from oauth2client.service_account import ServiceAccountCredentials
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from datetime import datetime
from io import BytesIO
from plotly.io import to_image
import os
import numpy as np
import json
from dotenv import load_dotenv
from itertools import chain
from flask import request
import datetime


# this is the setup area of the code

# Enable suppressing callback exceptions
app = dash.Dash(__name__, suppress_callback_exceptions=True)
server = app.server  # ✅ This is the line you must add for Railway


APP_VERSION = "2026_v1.08"

#------Root Page Logging------
@app.server.before_request
def log_root_hits():
    # Only log the root page ("/")
    if request.path == "/":
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ua = request.headers.get("User-Agent", "Unknown UA")
        print(f"[PAGE VIEW] {now}  path=/  user_agent={ua}")


# Load .env if it exists (safe for local and Render)
load_dotenv()

# Google Sheets API scope
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

# Choose credentials source
if os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"):
    #print("🌐 Using Render env variable")
    creds_dict = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
elif os.path.exists("service_account.json"):  # 👈 updated file name here
    #print("🖥️ Using local service_account.json")
    creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
else:
    raise EnvironmentError("❌ No credentials found. Set env var or add service_account.json.")

# Authorize client
client = gspread.authorize(creds)

# --------------------------------------
# Which team this app focuses on
# --------------------------------------
FOCUS_TEAM = "Belconnen"
PANEL_BG = "#0F2C44"

TEAM_MAP = {
    "1sts": "Belconnen",
    "Reserves": "BelReserves",
}

SQUAD_SHEET_MAP = {
    "1sts": "2026_season-stats-1sts",
    "Reserves": "2026_season-stats-Reserves",
}


# ============================
# APP DATA LOAD (v2)
# ============================

def load_app_sheet(sheet_name, squad_label):
    ss = client.open(sheet_name)

    player_df = pd.DataFrame(
        ss.worksheet("player-based").get_all_records()
    )
    team_df = pd.DataFrame(
        ss.worksheet("team-based").get_all_records()
    )
    league_df = pd.DataFrame(
        ss.worksheet("league-based").get_all_records()
    )

    # ---------- tidy headers ----------
    player_df.columns = [c.strip() for c in player_df.columns]
    team_df.columns = [c.strip() for c in team_df.columns]
    league_df.columns = [c.strip() for c in league_df.columns]

    # ---------- add squad selector column ----------
    player_df["Team"] = squad_label
    team_df["Team"] = squad_label
    league_df["Team"] = squad_label

    # ---------- normalise common fields ----------
    if "Match ID" in player_df.columns:
        player_df["Match ID"] = player_df["Match ID"].astype(str).str.strip()

    if "Match ID" in team_df.columns:
        team_df["Match ID"] = team_df["Match ID"].astype(str).str.strip()

    if "Match ID" in league_df.columns:
        league_df["Match ID"] = league_df["Match ID"].astype(str).str.strip()

    if "Goal X" in league_df.columns:
        league_df["Goal X"] = pd.to_numeric(league_df["Goal X"], errors="coerce")

    if "Goal Y" in league_df.columns:
        league_df["Goal Y"] = pd.to_numeric(league_df["Goal Y"], errors="coerce")

    if "Minute Scored" in league_df.columns:
        league_df["Minute Scored"] = pd.to_numeric(league_df["Minute Scored"], errors="coerce")

    return player_df, team_df, league_df


# ---------- load both squad files ----------
player_data_1sts, team_data_1sts, league_goal_data_1sts = load_app_sheet(
    SQUAD_SHEET_MAP["1sts"], "1sts"
)

player_data_reserves, team_data_reserves, league_goal_data_reserves = load_app_sheet(
    SQUAD_SHEET_MAP["Reserves"], "Reserves"
)

# ---------- combined datasets used by app ----------
player_data = pd.concat(
    [player_data_1sts, player_data_reserves],
    ignore_index=True
)

team_data = pd.concat(
    [team_data_1sts, team_data_reserves],
    ignore_index=True
)

league_goal_data = pd.concat(
    [league_goal_data_1sts, league_goal_data_reserves],
    ignore_index=True
)


#================================================
# helper text code starting now ------------
#===============================================

# --- League data preprocessing for opponent insights ---

# Ensure Minute Scored is numeric
league_goal_data["Minute Scored"] = pd.to_numeric(
    league_goal_data["Minute Scored"],
    errors="coerce"
)

# Ensure Match Date is datetime
league_goal_data["Match Date"] = pd.to_datetime(
    league_goal_data["Match Date"],
    errors="coerce"
)

# Derive Year for tournament filtering
league_goal_data["Year"] = league_goal_data["Match Date"].dt.year


# Result: For = scored by Olyroos, Against = scored by opponent
league_goal_data["Result"] = league_goal_data["Scorer Team"].apply(
    lambda t: "For" if t == FOCUS_TEAM else "Against"
)

# Opponent: always the *other* team in the game, from Olyroos perspective
def derive_opponent(row):
    # Goals involving Olyroos
    if row["Home Team"] == FOCUS_TEAM and isinstance(row["Away Team"], str):
        return row["Away Team"]
    if row["Away Team"] == FOCUS_TEAM and isinstance(row["Home Team"], str):
        return row["Home Team"]

    return ""

league_goal_data["Opponent"] = league_goal_data.apply(derive_opponent, axis=1)

# Opponent options for dropdowns
opponent_options = sorted(
    [o for o in league_goal_data["Opponent"].unique() if o not in ("", None)]
)

# still using Match ID for now
#match_options = sorted(league_goal_data["Match ID"].unique())

# ---get the against opponent--- helper for opponent tab#
def get_against_team(row, team_name):
    """
    For a given team_name, return the OTHER team in that match.
    Used for 'who they scored against' and 'who scored against them'.
    """
    if row.get("Home Team") == team_name and isinstance(row.get("Away Team"), str):
        return row["Away Team"]
    if row.get("Away Team") == team_name and isinstance(row.get("Home Team"), str):
        return row["Home Team"]
    return None



# ------------------------------------------------------
# Add Opponent column (who Olyroos is facing)
# ------------------------------------------------------
def extract_opponent(row):
    # If Olyroos is the home team → opponent = away team
    if row["Home Team"] == FOCUS_TEAM:
        return row["Away Team"]

    # If Olyroos is the away team → opponent = home team
    if row["Away Team"] == FOCUS_TEAM:
        return row["Home Team"]

    # Otherwise this match does not involve Olyroos
    return None

league_goal_data["Opponent"] = league_goal_data.apply(extract_opponent, axis=1)

# ------------------------------------------------------
# Opponent dropdown options (guaranteed to include "ALL")
# ------------------------------------------------------
_opponent_values = sorted({
    opp
    for opp in league_goal_data["Opponent"].unique()
    if isinstance(opp, str) and opp.strip()
})

OPPONENT_OPTIONS = (
    [{"label": "All Opponents", "value": "ALL"}] +
    [{"label": opp, "value": opp} for opp in _opponent_values]
)


# Tag with team label for clarity / future reuse
#player_data["Team"] = "Belconnen"
#team_data["Team"] = "Belconnen"
#if "Team" not in goal_data.columns:
#    goal_data["Team"] = "Belconnen"



button_style = {
    "backgroundColor": "#0D0D0E",   # → teal 00A896 (Aussie performance vibe) charcoal 083A32
    "color": "white",
    "border": "1px solid #004F44",  # → deep teal outline
    "padding": "10px 16px",
    "marginRight": "10px",
    "borderRadius": "6px",
    "fontWeight": "bold",
    "fontFamily": "Segoe UI",
    "cursor": "pointer",
    "boxShadow": "2px 2px 5px rgba(0,0,0,0.25)",
    "textAlign": "center",
}


# Reusable font styles
base_font = {
    "fontFamily": "Segoe UI",
    "fontSize": "14px",
}

title_font = {
    "fontFamily": "Segoe UI Black",
    "fontSize": "18px",
}

# --- Opponent colours ---
TEAM_COLORS = {
    "Tuggeranong": "green",
    "Croatia": "crimson",
    "Olympic": "navy",
    "Majura": "royalblue",
    "ANU": "orange",
    "Wanderers": "firebrick",
    "TuggeranongRes": "green",
    "CroatiaRes": "crimson",
    "OlympicRes": "navy",
    "MajuraRes": "royalblue",
    "ANURes": "orange",
    "WanderersRes": "firebrick",
    "Belconnen": "skyblue",
    "BelReserves": "skyblue",
}

DEFAULT_COLOR = "gray"


# ============================
# MATCH LOOKUP (still useful if team_data has Match ID / Opponent)
# ============================

#MATCH_LOOKUP = (
#    team_data[["Match ID", "Team", "Opponent"]]
#    .drop_duplicates()
#    .assign(
#        **{
#            "Match ID": lambda d: d["Match ID"].astype(str).str.strip(),
#            "Team": lambda d: d["Team"].astype(str).str.strip(),
#            "Opponent": lambda d: d["Opponent"].astype(str).str.strip(),
#        }
#    )
#)
#
ALIASES = {
    "Canberra Croatia": "Croatia",
    "Canberra Olympic": "Olympic",
    "Gungahlin United": "Gungahlin",
    "Weston Molonglo": "Wanderers",
}

def normalize_club(s):
    if not isinstance(s, str):
        return s
    s = str(s).strip()
    return ALIASES.get(s, s)

#MATCH_LOOKUP["Opponent"] = MATCH_LOOKUP["Opponent"].apply(normalize_club)



#====== helper code for alphabrtical dropdown opponent list in opponent insights=======
league_teams = sorted(
    pd.concat([
        league_goal_data["Home Team"],
        league_goal_data["Away Team"]
    ])
    .dropna()
    .unique()
)

LEAGUE_OPPONENT_OPTIONS = (
    [{"label": "ALL", "value": "ALL"}] +
    [{"label": t, "value": t} for t in league_teams]
)

# ----------------------------------------------------------------------------
# Opponent dropdown control - where you choose what dropdown options there are
# ----------------------------------------------------------------------------

USE_LIMITED_OPPONENTS = False  # True = only LIMITED_OPPONENTS, False = all teams

LIMITED_OPPONENTS = [
    "Thailand-U23",
    "Iraq-U23",
    "China-U23",
    "Olyroos",
    # add more here as needed
]

# All teams that appear in the league data (do NOT remove focus team)
all_teams = sorted(
    set(league_goal_data["Home Team"].dropna().unique())
    | set(league_goal_data["Away Team"].dropna().unique())
)


# i was using the below but olyroos wasn't in the list so i starting using code chunk above.
# All teams that appear in the league data (minus the focus team)
#all_teams = sorted(
#    set(league_goal_data["Home Team"].dropna().unique())
#    | set(league_goal_data["Away Team"].dropna().unique())
#)
#all_teams = [t for t in all_teams if t != FOCUS_TEAM]

# Decide which list to use
if USE_LIMITED_OPPONENTS:
    opponents_for_dropdown = [t for t in all_teams if t in LIMITED_OPPONENTS]
else:
    opponents_for_dropdown = all_teams

# Build dropdown options (include ALL)
opponent_dropdown_options = (
    [{"label": "ALL", "value": "ALL"}] +
    [{"label": t, "value": t} for t in opponents_for_dropdown]
)

# Default to ALL
OPPONENT_DEFAULT_VALUE = "ALL"


#-----------
# Helper code for coach insights in opponent insights tab
#--------

def get_first_subs(player_data, league_goal_data, selected_opponent):
    df = player_data.copy()

    # Only opponent players
    df["Country"] = df["Country"].astype(str).str.strip()
    df = df[df["Country"] == selected_opponent].copy()

    # Tactical subs only
    df = df[
        (df["Start"].str.lower() == "no") &
        (df["Appearance"].str.lower() == "yes")
    ].copy()

    df["Mins Played"] = pd.to_numeric(df["Mins Played"], errors="coerce")
    df["Sub Minute"] = 90 - df["Mins Played"]
    df = df[df["Sub Minute"].notna()].copy()

    if df.empty:
        return pd.DataFrame()

    # First sub per match
    first_subs = (
        df.sort_values("Sub Minute")
          .groupby("Match ID", as_index=False)
          .first()
    )

    return first_subs


#-----------
# Helper code - 2 - for coach insights in opponent insights tab
#--------
def build_coach_behaviour_game_state_summary(
    player_df,
    goals_df,
    selected_opponent
):
    """
    Builds coach behaviour metrics:
    - Avg first sub minute by game state (W/D/L)
    - Avg subs per game
    - Goal impact within 15 mins after first sub
    """

    # -------------------------
    # Base filters
    # -------------------------
    pdf = player_df.copy()
    gdf = goals_df.copy()

    # Only opponent matches
    pdf = pdf[pdf["Country"] == selected_opponent]
    gdf = gdf[
        (gdf["Home Team"] == selected_opponent) |
        (gdf["Away Team"] == selected_opponent)
    ]

    if pdf.empty:
        return None

    # -------------------------
    # Identify substitutions
    # -------------------------
    subs = pdf[
        (pdf["Start"].str.lower() == "no") &
        (pdf["Appearance"].str.lower() == "yes")
    ].copy()

    subs["Sub Minute"] = 90 - pd.to_numeric(subs["Mins Played"], errors="coerce")
    subs = subs[subs["Sub Minute"].notna()]

    if subs.empty:
        return None

    # -------------------------
    # First sub per match
    # -------------------------
    first_subs = (
        subs.sort_values("Sub Minute")
            .groupby("Match ID")
            .first()
            .reset_index()
    )

    # -------------------------
    # Game state at sub time
    # -------------------------
    def game_state_at_minute(match_id, minute):
        goals = gdf[
            (gdf["Match ID"] == match_id) &
            (gdf["Minute Scored"] <= minute)
        ]

        goals_for = (goals["Scorer Team"] == selected_opponent).sum()
        goals_against = (goals["Scorer Team"] != selected_opponent).sum()

        if goals_for > goals_against:
            return "Winning"
        if goals_for < goals_against:
            return "Losing"
        return "Drawing"

    first_subs["Game State"] = first_subs.apply(
        lambda r: game_state_at_minute(r["Match ID"], r["Sub Minute"]),
        axis=1
    )

    # -------------------------
    # Avg first sub by state
    # -------------------------
    avg_first_sub_by_state = (
        first_subs.groupby("Game State")["Sub Minute"]
        .mean()
        .round(1)
        .to_dict()
    )

    # -------------------------
    # Avg subs per game
    # -------------------------
    avg_subs_per_game = subs.groupby("Match ID").size().mean()
    avg_subs_per_game = round(avg_subs_per_game, 1)

    # -------------------------
    # Impact after first sub
    # -------------------------
    impact = {"For": 0, "Against": 0, "No Goal": 0}

    for _, row in first_subs.iterrows():
        m_id = row["Match ID"]
        start = row["Sub Minute"]
        end = start + 15

        window = gdf[
            (gdf["Match ID"] == m_id) &
            (gdf["Minute Scored"] > start) &
            (gdf["Minute Scored"] <= end)
        ]

        if window.empty:
            impact["No Goal"] += 1
        elif (window["Scorer Team"] == selected_opponent).any():
            impact["For"] += 1
        else:
            impact["Against"] += 1

    # -------------------------
    # Return structured result
    # -------------------------
    return {
        "avg_first_sub_by_state": avg_first_sub_by_state,
        "avg_subs_per_game": avg_subs_per_game,
        "post_sub_impact": impact,
        "matches": len(first_subs),
    }



# =========================================================
# BIG MOMENT GOALS
# =========================================================

def get_score_before_goal(match_df: pd.DataFrame, idx: int, focus_team: str) -> tuple[int, int]:
    """
    Returns (focus_team_score_before, opp_score_before) before the goal at row idx.
    Assumes match_df is sorted by Minute Scored and only contains rows for one match.
    """
    prior = match_df.iloc[:idx]

    focus_before = (prior["Scorer Team"] == focus_team).sum()
    opp_before = (prior["Scorer Team"] != focus_team).sum()

    return int(focus_before), int(opp_before)


def build_big_moment_goals_df(
    league_goal_data: pd.DataFrame,
    selected_squad: str,
    selected_team: str,
) -> pd.DataFrame:
    """
    Returns one row per 'big moment goal' scored by selected_team with columns:
    Player Name | Match ID | Opponent | Big Moment Type
    """

    df = league_goal_data.copy()

    # squad filter
    if "Team" in df.columns:
        df["Team"] = df["Team"].astype(str).str.strip()
        df = df[df["Team"] == str(selected_squad).strip()].copy()

    # normalise
    for c in ["Match ID", "Home Team", "Away Team", "Scorer Team", "Scorer", "Full-score"]:
        if c in df.columns:
            df[c] = df[c].fillna("").astype(str).str.strip()

    df["Minute Scored"] = pd.to_numeric(df["Minute Scored"], errors="coerce")
    df = df.dropna(subset=["Minute Scored"]).copy()

    # only matches involving selected team
    df = df[
        (df["Home Team"] == selected_team) |
        (df["Away Team"] == selected_team)
    ].copy()

    # only goals scored by selected team
    df = df[df["Scorer Team"] == selected_team].copy()

    # remove OG
    df = df[df["Scorer"].str.upper() != "OG"].copy()

    if df.empty:
        return pd.DataFrame(columns=["Player Name", "Match ID", "Opponent", "Big Moment Type"])

    # opponent
    df["Opponent"] = np.where(
        df["Home Team"] == selected_team,
        df["Away Team"],
        df["Home Team"]
    )

    # sort match events safely
    sort_cols = ["Minute Scored"]
    if "Scorer" in df.columns:
        sort_cols.append("Scorer")

    all_events = league_goal_data.copy()
    if "Team" in all_events.columns:
        all_events["Team"] = all_events["Team"].astype(str).str.strip()
        all_events = all_events[all_events["Team"] == str(selected_squad).strip()].copy()

    for c in ["Match ID", "Home Team", "Away Team", "Scorer Team", "Scorer", "Full-score"]:
        if c in all_events.columns:
            all_events[c] = all_events[c].fillna("").astype(str).str.strip()

    all_events["Minute Scored"] = pd.to_numeric(all_events["Minute Scored"], errors="coerce")
    all_events = all_events.dropna(subset=["Minute Scored"]).copy()

    all_events = all_events[
        (all_events["Home Team"] == selected_team) |
        (all_events["Away Team"] == selected_team)
    ].copy()

    results = []

    for match_id, match_df in all_events.groupby("Match ID"):
        match_df = match_df.sort_values(["Minute Scored"]).reset_index(drop=True)

        if match_df.empty:
            continue

        home_team = match_df["Home Team"].iloc[0]
        away_team = match_df["Away Team"].iloc[0]
        opponent = away_team if home_team == selected_team else home_team

        # final score
        team_final = (match_df["Scorer Team"] == selected_team).sum()
        opp_final = (match_df["Scorer Team"] != selected_team).sum()

        for i, row in match_df.iterrows():
            if row["Scorer Team"] != selected_team:
                continue

            scorer = row["Scorer"]
            if str(scorer).upper() == "OG" or str(scorer).strip() == "":
                continue

            team_before, opp_before = get_score_before_goal(match_df, i, selected_team)
            team_after = team_before + 1
            opp_after = opp_before

            category = None

            # 1) Match winner
            # team wins, and this goal creates the final winning margin
            # example final 2-1 -> goal to make 2-1
            if team_final > opp_final:
                final_margin = team_final - opp_final
                current_margin = team_after - opp_after
                if current_margin == final_margin:
                    category = "Match Winner"

            # 2) Match-tying goal
            # example final 1-1 -> goal that makes it 1-1
            if category is None and team_final == opp_final:
                if team_after == opp_after:
                    category = "Match-Tying Goal"

            # 3) Go-ahead goal held
            # first goal that puts team in front and they never lose that lead
            if category is None and team_final > opp_final:
                if team_after > opp_after:
                    future = match_df.iloc[i + 1 :].copy()

                    # running state after this goal
                    t_score = team_after
                    o_score = opp_after
                    lost_lead = False

                    for _, fut in future.iterrows():
                        if fut["Scorer Team"] == selected_team:
                            t_score += 1
                        else:
                            o_score += 1

                        if t_score <= o_score:
                            lost_lead = True
                            break

                    if not lost_lead:
                        category = "Go-Ahead Goal Held"

            if category is not None:
                results.append({
                    "Player Name": scorer,
                    "Match ID": match_id,
                    "Opponent": opponent,
                    "Big Moment Type": category,
                })

    if not results:
        return pd.DataFrame(columns=["Player Name", "Match ID", "Opponent", "Big Moment Type"])

    out = pd.DataFrame(results)

    # remove duplicates if a goal satisfies more than one label
    # keep Match Winner > Match-Tying Goal > Go-Ahead Goal Held
    priority = {
        "Match Winner": 1,
        "Match-Tying Goal": 2,
        "Go-Ahead Goal Held": 3,
    }
    out["Priority"] = out["Big Moment Type"].map(priority)
    out = out.sort_values(["Match ID", "Player Name", "Priority"])
    out = out.drop_duplicates(subset=["Match ID", "Player Name"], keep="first")
    out = out.drop(columns=["Priority"])

    return out






# Helper function for building 5-min response charts
def build_five_min_response_df_for_team(league_goal_data, selected_team):
    """
    Build 5-minute response metrics for `selected_team` using league_goal_data.
    Returns a tidy DataFrame with columns:
      - Situation ("After Scoring" / "After Conceding")
      - Outcome
      - Count
      - Base
      - Pct
    """
    # Work on a copy so we don't mutate the global df
    df = league_goal_data.copy()

    # ---- Basic column sanity check ----
    required_cols = {"Minute Scored", "Scorer Team", "Home Team", "Away Team"}
    if not required_cols.issubset(df.columns):
        return pd.DataFrame(columns=["Situation", "Outcome", "Count", "Base", "Pct"])

    # Standardise minute
    df["Minute Scored"] = pd.to_numeric(df["Minute Scored"], errors="coerce")
    df = df.dropna(subset=["Minute Scored"])

    if df.empty:
        return pd.DataFrame(columns=["Situation", "Outcome", "Count", "Base", "Pct"])

    # Build a match key
    if "Match ID" in df.columns:
        df["Match Key"] = df["Match ID"].astype(str)
    elif {"Match Date", "Home Team", "Away Team"}.issubset(df.columns):
        df["Match Key"] = (
            df["Match Date"].astype(str)
            + "_" + df["Home Team"].astype(str)
            + "_" + df["Away Team"].astype(str)
        )
    else:
        df["Match Key"] = df.index.astype(str)

    # Conceding team = the other team in the match
    def get_conceding_team(row):
        if row["Scorer Team"] == row["Home Team"]:
            return row["Away Team"]
        else:
            return row["Home Team"]

    df["Conceding Team"] = df.apply(get_conceding_team, axis=1)

    # Only matches where selected_team is involved
    df_team = df[
        (df["Home Team"] == selected_team) |
        (df["Away Team"] == selected_team)
    ].copy()

    if df_team.empty:
        return pd.DataFrame(columns=["Situation", "Outcome", "Count", "Base", "Pct"])

    windows = []  # store per-window stats

    # Process match by match
    for match_key, match_df in df_team.groupby("Match Key"):
        match_df = match_df.sort_values("Minute Scored")

        last_score_trigger_min = -999
        last_concede_trigger_min = -999

        for _, row in match_df.iterrows():
            minute = row["Minute Scored"]
            scorer = row["Scorer Team"]
            conceding = row["Conceding Team"]

            if scorer == selected_team:
                if minute > last_score_trigger_min + 5:
                    window_end = minute + 5
                    future = match_df[
                        (match_df["Minute Scored"] > minute) &
                        (match_df["Minute Scored"] <= window_end)
                    ]
                    goals_for = (future["Scorer Team"] == selected_team).sum()
                    goals_against = (future["Scorer Team"] != selected_team).sum()
                    windows.append({
                        "Situation": "After Scoring",
                        "Trigger Minute": minute,
                        "Match Key": match_key,
                        "Goals For In Window": goals_for,
                        "Goals Against In Window": goals_against,
                    })
                    last_score_trigger_min = minute

            elif conceding == selected_team:
                if minute > last_concede_trigger_min + 5:
                    window_end = minute + 5
                    future = match_df[
                        (match_df["Minute Scored"] > minute) &
                        (match_df["Minute Scored"] <= window_end)
                    ]
                    goals_for = (future["Scorer Team"] == selected_team).sum()
                    goals_against = (future["Scorer Team"] != selected_team).sum()
                    windows.append({
                        "Situation": "After Conceding",
                        "Trigger Minute": minute,
                        "Match Key": match_key,
                        "Goals For In Window": goals_for,
                        "Goals Against In Window": goals_against,
                    })
                    last_concede_trigger_min = minute

    if not windows:
        return pd.DataFrame(columns=["Situation", "Outcome", "Count", "Base", "Pct"])

    windows_df = pd.DataFrame(windows)

    def pct(count, base):
        return 0 if base == 0 else (count / base) * 100

    # Aggregation
    scored_windows = windows_df[windows_df["Situation"] == "After Scoring"]
    conceded_windows = windows_df[windows_df["Situation"] == "After Conceding"]

    total_scored = len(scored_windows)
    total_conceded = len(conceded_windows)

    punished_after_scoring = (scored_windows["Goals Against In Window"] >= 1).sum()
    extended_after_scoring = (scored_windows["Goals For In Window"] >= 1).sum()

    bounce_back = (conceded_windows["Goals For In Window"] >= 1).sum()
    collapse_again = (conceded_windows["Goals Against In Window"] >= 1).sum()

    data_rows = [
        {
            "Situation": "After Scoring",
            "Outcome": "Conceded within 5 mins",
            "Count": int(punished_after_scoring),
            "Base": int(total_scored),
            "Pct": pct(punished_after_scoring, total_scored),
        },
        {
            "Situation": "After Scoring",
            "Outcome": "Scored again within 5 mins",
            "Count": int(extended_after_scoring),
            "Base": int(total_scored),
            "Pct": pct(extended_after_scoring, total_scored),
        },
        {
            "Situation": "After Conceding",
            "Outcome": "Scored within 5 mins",
            "Count": int(bounce_back),
            "Base": int(total_conceded),
            "Pct": pct(bounce_back, total_conceded),
        },
        {
            "Situation": "After Conceding",
            "Outcome": "Conceded again within 5 mins",
            "Count": int(collapse_again),
            "Base": int(total_conceded),
            "Pct": pct(collapse_again, total_conceded),
        },
    ]

    return pd.DataFrame(data_rows)


def build_five_min_response_df(league_goal_data):
    """
    Backwards-compatible wrapper for existing Olyroos charts.
    Behaviour is unchanged – still uses FOCUS_TEAM.
    """
    return build_five_min_response_df_for_team(league_goal_data, FOCUS_TEAM)



# ------------------------------------------------------
# Helper: 5-min response by opponent (for any team)
# ------------------------------------------------------
def build_five_min_response_by_opponent(league_goal_data, selected_team):
    """
    Returns per-event breakdown:
      Situation (After Scoring / After Conceding)
      Outcome   (Scored again / Conceded within / etc.)
      OpponentTeam (who they're doing it to / who is punishing them)
      Count
      Matches (list of Match IDs where these events occurred)
    """

    df = league_goal_data.copy()

    df["Minute Scored"] = pd.to_numeric(df["Minute Scored"], errors="coerce")
    df = df.dropna(subset=["Minute Scored"])

    # Match key
    if "Match ID" in df.columns:
        df["Match Key"] = df["Match ID"].astype(str)
    else:
        df["Match Key"] = (
            df["Match Date"].astype(str)
            + "_" + df["Home Team"].astype(str)
            + "_" + df["Away Team"].astype(str)
        )

    # Conceding team
    def get_conceding_team(row):
        if row["Scorer Team"] == row["Home Team"]:
            return row["Away Team"]
        else:
            return row["Home Team"]

    df["Conceding Team"] = df.apply(get_conceding_team, axis=1)

    # Only matches with selected_team
    df_team = df[
        (df["Home Team"] == selected_team) |
        (df["Away Team"] == selected_team)
    ].copy()

    if df_team.empty:
        return pd.DataFrame(columns=["Situation", "Outcome", "OpponentTeam", "Count", "Matches"])

    events = []

    for match_key, match_df in df_team.groupby("Match Key"):
        match_df = match_df.sort_values("Minute Scored")

        last_score_trigger_min = -999
        last_concede_trigger_min = -999

        for idx, row in match_df.iterrows():
            minute = row["Minute Scored"]
            scorer = row["Scorer Team"]
            conceding = row["Conceding Team"]

            # After SCORING windows
            if scorer == selected_team:
                if minute > last_score_trigger_min + 5:
                    window_end = minute + 5
                    future = match_df[
                        (match_df["Minute Scored"] > minute) &
                        (match_df["Minute Scored"] <= window_end)
                    ]

                    for _, fut in future.iterrows():
                        fut_scorer = fut["Scorer Team"]
                        fut_conceding = fut["Conceding Team"]

                        if fut_scorer == selected_team:
                            # We scored again – opponent is the team we scored against
                            events.append({
                                "Situation": "After Scoring",
                                "Outcome": "Scored again within 5 mins",
                                "OpponentTeam": fut_conceding,  # punished team
                                "MatchID": fut["Match ID"],
                            })
                        else:
                            # We conceded – opponent is the team scoring against us
                            events.append({
                                "Situation": "After Scoring",
                                "Outcome": "Conceded within 5 mins",
                                "OpponentTeam": fut_scorer,  # punishing team
                                "MatchID": fut["Match ID"],
                            })

                    last_score_trigger_min = minute

            # After CONCEDING windows
            elif conceding == selected_team:
                if minute > last_concede_trigger_min + 5:
                    window_end = minute + 5
                    future = match_df[
                        (match_df["Minute Scored"] > minute) &
                        (match_df["Minute Scored"] <= window_end)
                    ]

                    for _, fut in future.iterrows():
                        fut_scorer = fut["Scorer Team"]
                        fut_conceding = fut["Conceding Team"]

                        if fut_scorer == selected_team:
                            # We scored in response – opponent is team we scored against
                            events.append({
                                "Situation": "After Conceding",
                                "Outcome": "Scored within 5 mins",
                                "OpponentTeam": fut_conceding,  # punished team
                                "MatchID": fut["Match ID"],
                            })
                        else:
                            # We conceded again – opponent is team scoring against us
                            events.append({
                                "Situation": "After Conceding",
                                "Outcome": "Conceded again within 5 mins",
                                "OpponentTeam": fut_scorer,  # punishing team
                                "MatchID": fut["Match ID"],
                            })

                    last_concede_trigger_min = minute

    if not events:
        return pd.DataFrame(columns=["Situation", "Outcome", "OpponentTeam", "Count", "Matches"])

    events_df = pd.DataFrame(events)

    grouped = (
        events_df
        .groupby(["Situation", "Outcome", "OpponentTeam"])
        .agg(
            Count=("MatchID", "size"),
            Matches=("MatchID", lambda x: sorted(set(x)))
        )
        .reset_index()
    )

    return grouped

# ------------------------------------------------------
# Helper: First Goal Value Index for Olyroos
# ------------------------------------------------------
def build_first_goal_index_df(df_league):
    """
    For each Olyroos match, determine:
      - who scored first
      - match result (W/D/L for Olyroos)
    Then aggregate scenarios:
      - Scored First
      - Conceded First
    and compute games, results, and avg points.
    'No Goals' is ignored for charting.
    """
    df = df_league.copy()

    # Only matches where Olyroos is involved
    df = df[
        (df["Home Team"] == FOCUS_TEAM) |
        (df["Away Team"] == FOCUS_TEAM)
    ].copy()

    if df.empty:
        return pd.DataFrame(columns=[
            "Scenario", "Games", "Wins", "Draws", "Losses",
            "Points", "Avg Points"
        ])

    df["Minute Scored"] = pd.to_numeric(df["Minute Scored"], errors="coerce")

    records = []

    for match_key, match_df in df.groupby("Match ID"):
        match_df = match_df.copy()

        home_team = match_df["Home Team"].iloc[0]
        away_team = match_df["Away Team"].iloc[0]
        full_score = str(match_df["Full-score"].iloc[0]) if "Full-score" in match_df.columns else None

        # Result for Olyroos
        result = None
        points = 0

        if full_score and "-" in full_score:
            parts = full_score.split("-")
            try:
                home_goals = int(parts[0].strip())
                away_goals = int(parts[1].strip())
            except ValueError:
                home_goals = away_goals = None

            if home_goals is not None and away_goals is not None:
                if home_team == FOCUS_TEAM:
                    our_goals, opp_goals = home_goals, away_goals
                else:
                    our_goals, opp_goals = away_goals, home_goals

                if our_goals > opp_goals:
                    result = "Win"
                    points = 3
                elif our_goals == opp_goals:
                    result = "Draw"
                    points = 1
                else:
                    result = "Loss"
                    points = 0

        # Who scored first?
        goals_only = match_df.dropna(subset=["Minute Scored"])
        if not goals_only.empty:
            first_row = goals_only.sort_values("Minute Scored").iloc[0]
            first_scorer_team = first_row["Scorer Team"]
            if first_scorer_team == FOCUS_TEAM:
                scenario = "Scored First"
            else:
                scenario = "Conceded First"
        else:
            # No goals → don't include in either scenario
            continue

        records.append({
            "Match ID": match_key,
            "Scenario": scenario,
            "Result": result,
            "Points": points,
        })

    # If still nothing after skipping no-goal games
    if not records:
        return pd.DataFrame(columns=[
            "Scenario", "Games", "Wins", "Draws", "Losses",
            "Points", "Avg Points"
        ])

    rec_df = pd.DataFrame(records)

    # Aggregate per scenario
    rows = []
    for scenario, grp in rec_df.groupby("Scenario"):
        games = len(grp)
        wins = (grp["Result"] == "Win").sum()
        draws = (grp["Result"] == "Draw").sum()
        losses = (grp["Result"] == "Loss").sum()
        total_points = grp["Points"].sum()
        avg_points = total_points / games if games > 0 else 0.0

        rows.append({
            "Scenario": scenario,
            "Games": games,
            "Wins": int(wins),
            "Draws": int(draws),
            "Losses": int(losses),
            "Points": int(total_points),
            "Avg Points": avg_points,
        })

    # 🔹 Ensure both scenarios exist, even if 0 games
    scenarios = {row["Scenario"] for row in rows}
    for scenario in ["Scored First", "Conceded First"]:
        if scenario not in scenarios:
            rows.append({
                "Scenario": scenario,
                "Games": 0,
                "Wins": 0,
                "Draws": 0,
                "Losses": 0,
                "Points": 0,
                "Avg Points": 0.0,
            })

    # Return in fixed order
    metrics_df = pd.DataFrame(rows)
    metrics_df["Scenario"] = pd.Categorical(
        metrics_df["Scenario"],
        categories=["Scored First", "Conceded First"],
        ordered=True
    )
    metrics_df = metrics_df.sort_values("Scenario")

    return metrics_df

def build_first_goal_matchlevel_df(df):
    """
    Returns match-level first-goal scenarios:
    One row per match with:
      Scenario (Scored First / Conceded First)
      OpponentTeam
      Outcome (Win/Draw/Loss)
    """

    df = df.copy()
    df["Minute Scored"] = pd.to_numeric(df["Minute Scored"], errors="coerce")

    matches = []

    for match_id, match_df in df.groupby("Match ID"):
        match_df = match_df.sort_values("Minute Scored")

        if match_df.empty:
            continue

        home = match_df["Home Team"].iloc[0]
        away = match_df["Away Team"].iloc[0]

        # First goal
        first_row = match_df.iloc[0]
        first_team = first_row["Scorer Team"]

        if first_team == FOCUS_TEAM:
            scenario = "Scored First"
            opponent = away if home == FOCUS_TEAM else home
        else:
            scenario = "Conceded First"
            opponent = away if first_team == home else home

        # full-time outcome for Olyroos
        full_score = match_df["Full-score"].iloc[0]
        gf, ga = map(int, full_score.split("-"))

        if gf > ga:
            outcome = "Win"
        elif gf == ga:
            outcome = "Draw"
        else:
            outcome = "Loss"

        matches.append({
            "MatchID": match_id,
            "Scenario": scenario,
            "OpponentTeam": opponent,
            "Outcome": outcome,
        })

    return pd.DataFrame(matches)

def build_first_goal_index_df_for_team(df_league, team_name):
    """
    Generic version of first goal value index for any team.

    For each match involving `team_name`:
      - determine who scored first
      - determine result for `team_name` (W/D/L)
    Aggregate into:
      - Scenario: "Scored First" / "Conceded First"
      - Games, Wins, Draws, Losses, Points, Avg Points

    Always returns both scenarios, even if 0 games in one.
    """
    df = df_league.copy()

    # Only matches where team_name is involved
    df = df[
        (df["Home Team"] == team_name) |
        (df["Away Team"] == team_name)
    ].copy()

    if df.empty:
        return pd.DataFrame(columns=[
            "Scenario", "Games", "Wins", "Draws", "Losses",
            "Points", "Avg Points"
        ])

    df["Minute Scored"] = pd.to_numeric(df["Minute Scored"], errors="coerce")

    records = []

    for match_key, match_df in df.groupby("Match ID"):
        match_df = match_df.copy()

        home_team = match_df["Home Team"].iloc[0]
        away_team = match_df["Away Team"].iloc[0]
        full_score = str(match_df["Full-score"].iloc[0]) if "Full-score" in match_df.columns else None

        # Result for this team
        result = None
        points = 0

        if full_score and "-" in full_score:
            parts = full_score.split("-")
            try:
                home_goals = int(parts[0].strip())
                away_goals = int(parts[1].strip())
            except ValueError:
                home_goals = away_goals = None

            if home_goals is not None and away_goals is not None:
                if home_team == team_name:
                    our_goals, opp_goals = home_goals, away_goals
                else:
                    our_goals, opp_goals = away_goals, home_goals

                if our_goals > opp_goals:
                    result = "Win"
                    points = 3
                elif our_goals == opp_goals:
                    result = "Draw"
                    points = 1
                else:
                    result = "Loss"
                    points = 0

        # Who scored first?
        goals_only = match_df.dropna(subset=["Minute Scored"])
        if not goals_only.empty:
            first_row = goals_only.sort_values("Minute Scored").iloc[0]
            first_scorer_team = first_row["Scorer Team"]
            if first_scorer_team == team_name:
                scenario = "Scored First"
            else:
                scenario = "Conceded First"
        else:
            continue

        records.append({
            "Match ID": match_key,
            "Scenario": scenario,
            "Result": result,
            "Points": points,
        })

    if not records:
        return pd.DataFrame(columns=[
            "Scenario", "Games", "Wins", "Draws", "Losses",
            "Points", "Avg Points"
        ])

    rec_df = pd.DataFrame(records)

    rows = []
    for scenario, grp in rec_df.groupby("Scenario"):
        games = len(grp)
        wins = (grp["Result"] == "Win").sum()
        draws = (grp["Result"] == "Draw").sum()
        losses = (grp["Result"] == "Loss").sum()
        total_points = grp["Points"].sum()
        avg_points = total_points / games if games > 0 else 0.0

        rows.append({
            "Scenario": scenario,
            "Games": int(games),
            "Wins": int(wins),
            "Draws": int(draws),
            "Losses": int(losses),
            "Points": int(total_points),
            "Avg Points": float(avg_points),
        })

    scenarios_present = {row["Scenario"] for row in rows}
    for scenario in ["Scored First", "Conceded First"]:
        if scenario not in scenarios_present:
            rows.append({
                "Scenario": scenario,
                "Games": 0,
                "Wins": 0,
                "Draws": 0,
                "Losses": 0,
                "Points": 0,
                "Avg Points": 0.0,
            })

    metrics_df = pd.DataFrame(rows)
    metrics_df["Scenario"] = pd.Categorical(
        metrics_df["Scenario"],
        categories=["Scored First", "Conceded First"],
        ordered=True,
    )
    metrics_df = metrics_df.sort_values("Scenario").reset_index(drop=True)

    return metrics_df


def build_first_goal_value_long(df_league, team_name):
    """
    Build long-form First Goal Value Index data for a given team.

    Output columns:
      - Code          (SF-W, SF-D, SF-L, CF-W, CF-D, CF-L)
      - Scenario      ("SF" or "CF")
      - Outcome       ("W", "D", "L")
      - OpponentTeam  (opponent name)
      - SliceCount    (# of matches for this (Code, OpponentTeam))
      - MatchIDs      (comma-separated string of match IDs)
      - ScenarioBase  (total matches in this scenario SF/CF)
      - OutcomeTotal  (total matches in this Code, across all opponents)
      - OutcomePct    (OutcomeTotal / ScenarioBase * 100)
    """

    df = df_league.copy()

    # Only matches where this team is involved
    df = df[
        (df["Home Team"] == team_name) |
        (df["Away Team"] == team_name)
    ].copy()

    if df.empty:
        return pd.DataFrame(columns=[
            "Code", "Scenario", "Outcome", "OpponentTeam",
            "SliceCount", "MatchIDs", "ScenarioBase",
            "OutcomeTotal", "OutcomePct"
        ])

    df["Minute Scored"] = pd.to_numeric(df["Minute Scored"], errors="coerce")

    match_records = []

    for match_id, match_df in df.groupby("Match ID"):
        match_df = match_df.sort_values("Minute Scored")

        home = match_df["Home Team"].iloc[0]
        away = match_df["Away Team"].iloc[0]

        # Full-time result
        full_score = str(match_df["Full-score"].iloc[0]) if "Full-score" in match_df.columns else None
        if not full_score or "-" not in full_score:
            continue

        try:
            gf, ga = [int(x.strip()) for x in full_score.split("-")]
        except ValueError:
            continue

        # Goals for/against from team_name perspective
        if home == team_name:
            our_goals, opp_goals = gf, ga
            opponent_team = away
        else:
            our_goals, opp_goals = ga, gf
            opponent_team = home

        if our_goals > opp_goals:
            outcome = "W"
        elif our_goals == opp_goals:
            outcome = "D"
        else:
            outcome = "L"

        # First goal
        goals_only = match_df.dropna(subset=["Minute Scored"])
        if goals_only.empty:
            # No goals -> exclude from SF/CF stats
            continue

        first_row = goals_only.iloc[0]
        first_scorer = first_row["Scorer Team"]

        if first_scorer == team_name:
            scenario = "SF"
        else:
            scenario = "CF"

        code = f"{scenario}-{outcome}"

        match_records.append({
            "MatchID": match_id,
            "Scenario": scenario,
            "Outcome": outcome,
            "Code": code,
            "OpponentTeam": opponent_team,
        })

    if not match_records:
        return pd.DataFrame(columns=[
            "Code", "Scenario", "Outcome", "OpponentTeam",
            "SliceCount", "MatchIDs", "ScenarioBase",
            "OutcomeTotal", "OutcomePct"
        ])

    rec_df = pd.DataFrame(match_records)

    # Total matches per scenario (SF / CF)
    scenario_base = (
        rec_df.groupby("Scenario")["MatchID"]
        .nunique()
        .to_dict()
    )

    # Aggregate per Code + Opponent
    grouped = (
        rec_df
        .groupby(["Code", "Scenario", "Outcome", "OpponentTeam"])
        .agg(
            SliceCount=("MatchID", "nunique"),
            MatchIDs=("MatchID", lambda x: ", ".join(sorted(set(map(str, x)))))
        )
        .reset_index()
    )

    # Total matches per Code across all opponents
    code_totals = (
        grouped.groupby(["Code", "Scenario"])["SliceCount"]
        .sum()
        .rename("OutcomeTotal")
        .reset_index()
    )

    grouped = grouped.merge(
        code_totals,
        on=["Code", "Scenario"],
        how="left"
    )

    # Attach ScenarioBase + OutcomePct
    grouped["ScenarioBase"] = grouped["Scenario"].map(scenario_base).fillna(0).astype(int)
    grouped["OutcomePct"] = grouped.apply(
        lambda r: (r["OutcomeTotal"] / r["ScenarioBase"] * 100.0) if r["ScenarioBase"] > 0 else 0.0,
        axis=1
    )

    return grouped

# ------ HELPER CODE FOR OPPONENT INSIGHTS TAB GOALS SCORED BY TYPE--------
def abbreviate_goal_type(code: str) -> str | None:
    """
    Turn Goal Type like 'R-FT-DT' into 'FT-DT' for axis labels.
    For SP-* types, return as-is.
    """
    if not isinstance(code, str):
        return None
    code = code.strip()
    if code.startswith("R-"):
        parts = code.split("-")
        if len(parts) >= 3:
            return parts[-2] + "-" + parts[-1]
    return code




# ---------- HELPER: Goal map for FOCUS TEAM (e.g. Olyroos) ----------
#def build_focus_team_goal_map(league_goal_data, selected_opponent, goal_filter="ALL"):
def build_focus_team_goal_map(league_goal_data, selected_team, selected_opponent, goal_filter="ALL"):
    """
    Goal location map for the focus team (FOCUS_TEAM).

    - Filters to matches involving FOCUS_TEAM.
    - Optional opponent filter (dropdown).
    - Optional goal type filter (ALL, GS, GC, GS_BT, etc.).
    - Shows:
        • Goals Scored = blue circles
        • Goals Conceded = red X
    """

    #selected_team = FOCUS_TEAM  # e.g. "Olyroos"

    # No team? Just return empty fig (safety)
    if not selected_team:
        return go.Figure()

    df = league_goal_data.copy()

    # 1) Only matches where the focus team is involved
    df = df[
        (df["Home Team"] == selected_team)
        | (df["Away Team"] == selected_team)
    ].copy()

    if df.empty:
        fig = go.Figure()
        fig.update_layout(
            title=f"{selected_team} – No goals recorded in league data",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(family="Segoe UI", color="white"),
            xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
            yaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
        )
        return fig

    # 2) Ensure numeric minutes & coords
    df["Minute Scored"] = pd.to_numeric(df["Minute Scored"], errors="coerce")
    df["Goal X"] = pd.to_numeric(df["Goal X"], errors="coerce")
    df["Goal Y"] = pd.to_numeric(df["Goal Y"], errors="coerce")
    df = df.dropna(subset=["Goal X", "Goal Y", "Minute Scored"])

    # 3) Normalise goal-type codes (for regain / SP-C matching)
    df["GoalTypeNorm"] = (
        df["Goal Type"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.upper()
    )

    # 4) Who they are playing against in each row (relative to FOCUS_TEAM)
    def _against_team(row):
        if row["Home Team"] == selected_team:
            return row["Away Team"]
        elif row["Away Team"] == selected_team:
            return row["Home Team"]
        return None

    df["Against Team"] = df.apply(_against_team, axis=1)

    # 5) Optional opponent filter from dropdown
    if selected_opponent and selected_opponent != "ALL":
        df = df[df["Against Team"] == selected_opponent].copy()
        if df.empty:
            fig = go.Figure()
            fig.update_layout(
                title=f"{selected_team} – No goals vs {selected_opponent}",
                plot_bgcolor="black",
                paper_bgcolor="black",
                font=dict(family="Segoe UI", color="white"),
                xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
                yaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
            )
            return fig

    # 6) For / Against relative to FOCUS_TEAM
    df["ResultForTeam"] = df["Scorer Team"].apply(
        lambda t: "For" if t == selected_team else "Against"
    )

    # 7) Apply goal_filter (same options as opponent insights)
    gf = (goal_filter or "ALL").upper()

    if gf == "ALL":
        pass
    elif gf == "ALL_CORNERS":
        df = df[df["GoalTypeNorm"] == "SP-C"]
    elif gf == "ALL_SP":  # 👈 NEW: all set pieces, not just corners
        df = df[df["GoalTypeNorm"].str.startswith("SP-")]
    elif gf == "GS":
        df = df[df["ResultForTeam"] == "For"]
    elif gf == "GC":
        df = df[df["ResultForTeam"] == "Against"]
    elif gf == "GS_BT":
        df = df[
            (df["ResultForTeam"] == "For")
            & (df["GoalTypeNorm"].str.startswith("R-BT-"))
        ]
    elif gf == "GS_MT":
        df = df[
            (df["ResultForTeam"] == "For")
            & (df["GoalTypeNorm"].str.startswith("R-MT-"))
        ]
    elif gf == "GS_FT":
        df = df[
            (df["ResultForTeam"] == "For")
            & (df["GoalTypeNorm"].str.startswith("R-FT-"))
        ]
    elif gf == "GC_BT":
        df = df[
            (df["ResultForTeam"] == "Against")
            & (df["GoalTypeNorm"].str.startswith("R-BT-"))
        ]
    elif gf == "GC_MT":
        df = df[
            (df["ResultForTeam"] == "Against")
            & (df["GoalTypeNorm"].str.startswith("R-MT-"))
        ]
    elif gf == "GC_FT":
        df = df[
            (df["ResultForTeam"] == "Against")
            & (df["GoalTypeNorm"].str.startswith("R-FT-"))
        ]

    if df.empty:
        fig = go.Figure()
        fig.update_layout(
            title=f"{selected_team} – No goals matching filter",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(family="Segoe UI", color="white"),
            xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
            yaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
        )
        return fig

    # 8) Re-split after filtering
    df_for = df[df["ResultForTeam"] == "For"].copy()
    df_against = df[df["ResultForTeam"] == "Against"].copy()

    fig = go.Figure()

    # ---------------- Pitch / box / goal shapes ----------------
    fig.add_shape(
        type="rect",
        x0=20, y0=0,
        x1=80, y1=18,
        line=dict(color="white", width=2),
    )
    fig.add_shape(
        type="line",
        x0=0, y0=0,
        x1=100, y1=0,
        line=dict(color="white", width=2),
    )
    fig.add_shape(
        type="rect",
        x0=36, y0=0,
        x1=64, y1=6,
        line=dict(color="white", width=2),
    )
    fig.add_shape(
        type="rect",
        x0=44, y0=-3,
        x1=56, y1=0,
        line=dict(color="white", width=2),
    )

    arc_left = 38
    arc_right = 62
    arc_top_y = 18
    arc_depth_y = 24

    fig.add_shape(
        type="path",
        path=f"M {arc_left} {arc_top_y} Q 50 {arc_depth_y} {arc_right} {arc_top_y}",
        line=dict(color="white", width=2),
    )

    # ---------------- Goal points & hover ----------------

    # Goals For this team (BLUE circles)
    if not df_for.empty:
        fig.add_trace(
            go.Scatter(
                x=df_for["Goal X"],
                y=df_for["Goal Y"],
                mode="markers",
                name="Goals Scored",
                marker=dict(
                    size=10,
                    symbol="circle",
                    color="#4F81BD",  # blue 1E90FF
                    #line=dict(color="white", width=1), #---white line around it
                ),
                customdata=df_for[
                    [
                        "Against Team",
                        "Scorer",
                        "GoalTypeNorm",
                        "Finish Type",
                        "Minute Scored",
                        "First-time finish",
                    ]
                ].values,
                hovertemplate=(
                    "Vs: %{customdata[0]}<br>"
                    "Scorer: %{customdata[1]}<br>"
                    "Goal Type: %{customdata[2]}<br>"
                    "Finish: %{customdata[3]}<br>"
                    "Minute: %{customdata[4]}<br>"
                    "First-time: %{customdata[5]}<br>"
                    "<extra></extra>"
                ),
            )
        )

    # Goals Against this team (RED X)
    if not df_against.empty:
        fig.add_trace(
            go.Scatter(
                x=df_against["Goal X"],
                y=df_against["Goal Y"],
                mode="markers",
                name="Goals Conceded",
                marker=dict(
                    size=12,
                    symbol="x",
                    color="#FF4444",  # red
                ),
                customdata=df_against[
                    [
                        "Against Team",
                        "Scorer",
                        "GoalTypeNorm",
                        "Finish Type",
                        "Minute Scored",
                        "First-time finish",
                    ]
                ].values,
                hovertemplate=(
                    "Vs: %{customdata[0]}<br>"
                    "Scorer: %{customdata[1]}<br>"
                    "Goal Type: %{customdata[2]}<br>"
                    "Finish: %{customdata[3]}<br>"
                    "Minute: %{customdata[4]}<br>"
                    "First-time: %{customdata[5]}<br>"
                    "<extra></extra>"
                ),
            )
        )

    fig.update_layout(
        title=f"{selected_team} – Goal Location Map (For & Against)",
        height=550,
        plot_bgcolor="black",
        paper_bgcolor="black",
        font=dict(family="Segoe UI", color="white", size=14),
        legend=dict(
            orientation="h",
            x=0.5,
            xanchor="center",
            y=1.05,
        ),
        margin=dict(l=20, r=20, t=60, b=20),
        xaxis=dict(
            range=[0, 100],
            showgrid=False,
            showticklabels=False,
            zeroline=False,
        ),
        yaxis=dict(
            range=[35, -5],  # same flip as before
            showgrid=False,
            showticklabels=False,
            zeroline=False,
        ),
    )

    return fig




# -----------HELPER FOR GOAL MAP - IN OPPONENT INSIGHTS------
def build_goal_map_for_team(league_goal_data, selected_team, goal_filter="ALL"):
    """
    Build a goal location map.

    - If selected_team == "ALL": show ALL league goals (neutral markers)
    - If specific team: show Goals For (blue ●) and Goals Against (red ✕)
    """

    if not selected_team:
        return go.Figure()

    df = league_goal_data.copy()
    is_all = (selected_team == "ALL")
    gf = (goal_filter or "ALL").upper()

    # ---------------- FILTER MATCHES ----------------
    if not is_all:
        df = df[
            (df["Home Team"] == selected_team) |
            (df["Away Team"] == selected_team)
        ].copy()

    if df.empty:
        fig = go.Figure()
        fig.update_layout(
            title="No goals recorded",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(family="Segoe UI", color="white"),
            xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
            yaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
        )
        return fig

    # ---------------- BASIC CLEANING ----------------
    df["Minute Scored"] = pd.to_numeric(df["Minute Scored"], errors="coerce")
    df["Goal X"] = pd.to_numeric(df["Goal X"], errors="coerce")
    df["Goal Y"] = pd.to_numeric(df["Goal Y"], errors="coerce")
    df = df.dropna(subset=["Goal X", "Goal Y", "Minute Scored"])

    for c in ["Goal Type", "Scorer", "Home Team", "Away Team", "Scorer Team"]:
        if c in df.columns:
            df[c] = df[c].fillna("").astype(str).str.strip()

    if "Finish Type" not in df.columns:
        df["Finish Type"] = ""
    if "First-time finish" not in df.columns:
        df["First-time finish"] = ""

    df["GoalTypeNorm"] = (
        df["Goal Type"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.upper()
    )

    # ---------------- RESULT CONTEXT ----------------
    if not is_all:
        df["ResultForTeam"] = df["Scorer Team"].apply(
            lambda t: "For" if t == selected_team else "Against"
        )

        def _against(row):
            return row["Away Team"] if row["Home Team"] == selected_team else row["Home Team"]

        df["Against Team"] = df.apply(_against, axis=1)
    else:
        df["Against Team"] = ""

    # ---------------- APPLY FILTER ----------------
    if is_all:
        if gf == "ALL_CORNERS":
            df = df[df["GoalTypeNorm"] == "SP-C"]
        elif gf == "ALL_SP":
            df = df[df["GoalTypeNorm"].str.startswith("SP-")]
    else:
        if gf == "GS":
            df = df[df["ResultForTeam"] == "For"]
        elif gf == "GC":
            df = df[df["ResultForTeam"] == "Against"]
        elif gf == "GS_BT":
            df = df[(df["ResultForTeam"] == "For") & df["GoalTypeNorm"].str.startswith("R-BT-")]
        elif gf == "GS_MT":
            df = df[(df["ResultForTeam"] == "For") & df["GoalTypeNorm"].str.startswith("R-MT-")]
        elif gf == "GS_FT":
            df = df[(df["ResultForTeam"] == "For") & df["GoalTypeNorm"].str.startswith("R-FT-")]
        elif gf == "GC_BT":
            df = df[(df["ResultForTeam"] == "Against") & df["GoalTypeNorm"].str.startswith("R-BT-")]
        elif gf == "GC_MT":
            df = df[(df["ResultForTeam"] == "Against") & df["GoalTypeNorm"].str.startswith("R-MT-")]
        elif gf == "GC_FT":
            df = df[(df["ResultForTeam"] == "Against") & df["GoalTypeNorm"].str.startswith("R-FT-")]

    if df.empty:
        fig = go.Figure()
        fig.update_layout(
            title="No goals matching filter",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(family="Segoe UI", color="white"),
            xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
            yaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
        )
        return fig

    # ---------------- SPLIT ----------------
    if is_all:
        df_all = df.copy()
        df_for = pd.DataFrame()
        df_against = pd.DataFrame()
    else:
        df_for = df[df["ResultForTeam"] == "For"].copy()
        df_against = df[df["ResultForTeam"] == "Against"].copy()

    fig = go.Figure()

    # ---------------- PITCH ----------------
    fig.add_shape(type="rect", x0=20, y0=0, x1=80, y1=18, line=dict(color="white", width=2))
    fig.add_shape(type="line", x0=0, y0=0, x1=100, y1=0, line=dict(color="white", width=2))
    fig.add_shape(type="rect", x0=36, y0=0, x1=64, y1=6, line=dict(color="white", width=2))
    fig.add_shape(type="rect", x0=44, y0=-3, x1=56, y1=0, line=dict(color="white", width=2))
    fig.add_shape(
        type="path",
        path="M 38 18 Q 50 24 62 18",
        line=dict(color="white", width=2),
    )

    # ---------------- PLOTS ----------------
    if is_all:
        fig.add_trace(
            go.Scatter(
                x=df_all["Goal X"],
                y=df_all["Goal Y"],
                mode="markers",
                name="All Goals",
                marker=dict(size=9, color="#6EC1FF"),
                customdata=df_all[
                    [
                        "Scorer Team",
                        "Scorer",
                        "GoalTypeNorm",
                        "Finish Type",
                        "Minute Scored",
                        "First-time finish",
                    ]
                ].values,
                hovertemplate=(
                    "Team: %{customdata[0]}<br>"
                    "Scorer: %{customdata[1]}<br>"
                    "Goal Type: %{customdata[2]}<br>"
                    "Finish: %{customdata[3]}<br>"
                    "Minute: %{customdata[4]}<br>"
                    "First-time: %{customdata[5]}<br>"
                    "<extra></extra>"
                ),
            )
        )

    if not df_for.empty:
        fig.add_trace(
            go.Scatter(
                x=df_for["Goal X"],
                y=df_for["Goal Y"],
                mode="markers",
                name="Goals Scored",
                marker=dict(
                    size=10,
                    symbol="circle",
                    color="#4F81BD",
                ),
                customdata=df_for[
                    [
                        "Against Team",
                        "Scorer",
                        "GoalTypeNorm",
                        "Finish Type",
                        "Minute Scored",
                        "First-time finish",
                    ]
                ].values,
                hovertemplate=(
                    "Vs: %{customdata[0]}<br>"
                    "Scorer: %{customdata[1]}<br>"
                    "Goal Type: %{customdata[2]}<br>"
                    "Finish: %{customdata[3]}<br>"
                    "Minute: %{customdata[4]}<br>"
                    "First-time: %{customdata[5]}<br>"
                    "<extra></extra>"
                ),
            )
        )

    if not df_against.empty:
        fig.add_trace(
            go.Scatter(
                x=df_against["Goal X"],
                y=df_against["Goal Y"],
                mode="markers",
                name="Goals Conceded",
                marker=dict(
                    size=12,
                    symbol="x",
                    color="#FF4444",
                ),
                customdata=df_against[
                    [
                        "Against Team",
                        "Scorer",
                        "GoalTypeNorm",
                        "Finish Type",
                        "Minute Scored",
                        "First-time finish",
                    ]
                ].values,
                hovertemplate=(
                    "Vs: %{customdata[0]}<br>"
                    "Scorer: %{customdata[1]}<br>"
                    "Goal Type: %{customdata[2]}<br>"
                    "Finish: %{customdata[3]}<br>"
                    "Minute: %{customdata[4]}<br>"
                    "First-time: %{customdata[5]}<br>"
                    "<extra></extra>"
                ),
            )
        )

    # ---------------- LAYOUT ----------------
    fig.update_layout(
        title="League-wide Goal Location Map" if is_all else f"{selected_team} – Goal Location Map",
        height=550,
        plot_bgcolor="black",
        paper_bgcolor="black",
        font=dict(family="Segoe UI", color="white"),
        legend=dict(orientation="h", x=0.5, xanchor="center", y=1.05),
        margin=dict(l=20, r=20, t=60, b=20),
        xaxis=dict(range=[0, 100], showgrid=False, showticklabels=False, zeroline=False),
        yaxis=dict(range=[35, -5], showgrid=False, showticklabels=False, zeroline=False),
    )

    return fig



## helper for bar charts not being fat, and zero values
def safe_bar_height(v):
    """Keep zero-value bars visible with a tiny placeholder height."""
    return 0.0001 if v == 0 else v

# chart header function
def chart_header(title_text, tooltip_text, helper_id):
    return html.Div(
        [
            # LEFT: Chart title
            html.H3(
                title_text,
                style={
                    "color": "white",
                    "fontFamily": title_font["fontFamily"],
                    "margin": 0,
                },
            ),

            # RIGHT: info icon
            html.Span(
                "ⓘ",
                id=helper_id,
                style={
                    "color": "white",
                    "cursor": "pointer",
                    "fontSize": "18px",
                    "padding": "4px 6px",
                    "borderRadius": "50%",
                },
            ),

            # Tooltip
            dbc.Tooltip(
                (
                    "This chart is interactive - click legend items to toggle.\n\n"
                    + tooltip_text
                ),
                target=helper_id,
                placement="left",
                style={
                    "backgroundColor": "#222",   # dark grey tooltip
                    "color": "white",            # white text
                    "fontFamily": "Segoe UI",    # match app font
                    "fontSize": "13px",
                    "padding": "10px",
                    "borderRadius": "6px",
                    "maxWidth": "450px",
                    "whiteSpace": "pre-line",    # preserve line breaks
                },
            ),
        ],
        style={
            "display": "flex",
            "justifyContent": "space-between",
            "alignItems": "center",
            "padding": "0 40px 10px 40px",
        },
    )



# ==========================================
# TEAM INSIGHTS LAYOUT (use collapsibles)
# ==========================================
team_insights_layout = dbc.Container(
    [

        # ---------------------------------------
        # GOALS SCORED
        ## ---------------------------------------
        #dbc.Button(
        #    [
        #        html.Span("▼", id="gs-arrow"),  # open by default
        #        html.Span("", style={"marginLeft": "6px"}),
        #    ],
        #    id="toggle-gs",
        #    color="primary",
        #    className="mb-2",
        #),
        
        

        dbc.Collapse(
            #id="collapse-gs",
            #is_open=True,
            children=[

                # =================================================
                # League Ladder Table
                # =================================================
                html.Div([

                    chart_header(
                        "League Ladder",
                        (
                            "Shows the current league standings based on completed league matches only.\n"
                            "Teams are ranked by points, then goal difference, then goals scored.\n"
                            "The ladder will remain empty until league results are entered."
                        ),
                        "league-ladder-helper"
                    ),

                    html.Div([
                        html.Button(
                            "Update Ladder",
                            id="update-league-button",
                            n_clicks=0,
                            style=button_style
                        )
                    ], style={
                        "textAlign": "left",
                        "padding": "10px",
                        "paddingLeft": "40px"
                    }),

                    dash_table.DataTable(
                        id="league-ladder",
                        fixed_columns={"headers": True},
                        style_cell={
                            "textAlign": "center",
                            "fontFamily": "Segoe UI",
                            "fontSize": "12px",
                            "fontWeight": "bold",
                            "padding": "4px",
                            "whiteSpace": "nowrap",
                            "overflow": "hidden",
                            "textOverflow": "ellipsis",
                            "minWidth": "0px",
                            "maxWidth": "100px",
                            "backgroundColor": "black",
                            "color": "white",
                            "border": "1px solid #333",
                        },
                        style_header={
                            "backgroundColor": "black",
                            "color": "white",
                            "fontFamily": title_font["fontFamily"],
                            "fontWeight": "bold",
                            "fontSize": "13px",
                            "padding": "6px",
                            "border": "1px solid #333",
                        },
                        style_data_conditional=[],
                        style_table={
                            "overflowX": "auto",
                            "maxHeight": "400px",
                            "width": "100%",
                            "maxWidth": "700px",
                            "margin": "auto",
                            "border": "1px solid white",
                            "borderRadius": "6px",
                        },
                        style_cell_conditional=[
                            {"if": {"column_id": "Team"}, "minWidth": "100px", "maxWidth": "120px", "width": "120px"},
                            {"if": {"column_id": "P"}, "minWidth": "40px", "maxWidth": "40px", "width": "40px"},
                            {"if": {"column_id": "W"}, "minWidth": "40px", "maxWidth": "40px", "width": "40px"},
                            {"if": {"column_id": "D"}, "minWidth": "40px", "maxWidth": "40px", "width": "40px"},
                            {"if": {"column_id": "L"}, "minWidth": "40px", "maxWidth": "40px", "width": "40px"},
                            {"if": {"column_id": "F"}, "minWidth": "40px", "maxWidth": "40px", "width": "40px"},
                            {"if": {"column_id": "A"}, "minWidth": "40px", "maxWidth": "40px", "width": "40px"},
                            {"if": {"column_id": "GD"}, "minWidth": "50px", "maxWidth": "50px", "width": "50px"},
                            {"if": {"column_id": "PTS"}, "minWidth": "50px", "maxWidth": "50px", "width": "50px"},
                        ],
                        page_size=20,
                    ),

                ], style={
                    "backgroundColor": PANEL_BG,
                    "padding": "20px",
                    "border": "1px solid white",
                    "borderRadius": "10px",
                    "marginBottom": "10px"
                }),

                html.Div(id="ladder-note", style={
                    "color": "white",
                    "fontSize": "13px",
                    "marginTop": "5px",
                    "marginBottom": "15px",
                    "fontFamily": "Segoe UI",
                    "textAlign": "center"
                }),



                # === Goals Scored by Interval – with Last 4 toggle ===
                html.Div([

                    # ----- Title + helper banner -----
                    chart_header(
                        f"{FOCUS_TEAM} – Goals Scored by Interval",
                        (
                            "It shows when goals are scored across the game.\n "
                            "Few goals between 0–15 minutes may suggest slow starts or low early focus.\n "
                            "If the team rarely concedes between 31–45 minutes, they may maintain concentration well.\n"
                            "High goals between 46–60 minutes can indicate strong halftime preparation.\n "
                            "A lot of goals between 76–90 minutes can point to fitness or effective substitutions.\n "
                                                        
                        ),
                        "goals-interval-helper"
                    ),

                    # ----- Button + Status Row -----
                    html.Div([

                        # Left: toggle button
                        html.Div([
                            html.Button(
                                "Show Last 4 Rounds",
                                id="last-4-interval-button",
                                n_clicks=0,
                                style=button_style
                            )
                        ], style={
                            "display": "inline-block",
                            "textAlign": "left",
                            "width": "33%",
                        }),

                        # Centre spacer (keeps the same grid layout)
                        html.Div([], style={
                            "display": "inline-block",
                            "textAlign": "center",
                            "width": "33%",
                        }),

                        # Right: status text
                        html.Div([
                            html.Div(
                                id="last-4-interval-status",
                                style={
                                    "color": "white",
                                    "fontWeight": "bold",
                                    "paddingTop": "8px",
                                    "fontFamily": base_font["fontFamily"],
                                }
                            )
                        ], style={
                            "display": "inline-block",
                            "textAlign": "right",
                            "width": "33%",
                        }),

                    ], style={
                        "display": "flex",
                        "justifyContent": "space-between",
                        "padding": "10px 40px",
                    }),

                    # ----- Chart -----
                    dcc.Graph(
                        id="goals-by-interval",
                        style={"backgroundColor": "black"}
                    ),

                ], style={
                    "backgroundColor": PANEL_BG,
                    "padding": "20px",
                    "border": "1px solid white",
                    "borderRadius": "10px",
                    "marginBottom": "20px",
                }),
                
                # ----- Chart -----



                
                # === Goals Scored by Type – with Last 4 Rounds toggle ===
                html.Div([

                    # ----- Title + helper banner -----
                    chart_header(
                        title_text=f"{FOCUS_TEAM} – Goals Scored by Type",
                        tooltip_text=(
                            "Shows how goals are scored by their type.\n\n"
                            "Set pieces:\n"
                            "- Corners (SP-C)\n"
                            "- Throw-ins (SP-T)\n"
                            "- Penalties (SP-P)\n"
                            "- Free kicks (SP-F)\n\n"
                            "Open play goals come from regaining the ball in a third of the pitch:\n"
                            "- R-FT = Regain in Front Third\n"
                            "- R-MT = Regain in Middle Third\n"
                            "- R-BT = Regain in Back Third\n\n"
                            "DT = During Transition – goal scored while opponent is disorganised "
                            "(e.g. counter-attacks, fast breaks).\n"
                            "AT = After Transition – goal scored while opponent is organised "
                            "and in settled possession (build-up goals).\n\n"
                            "Use the Last 4 Rounds toggle to focus on recent trends only."
                        ),
                        helper_id="goals-type-scored-helper",
                    ),

                    # ----- Button + Status Row -----
                    html.Div([

                        # Left: button
                        html.Div([
                            html.Button(
                                "Show Last 4 Rounds",
                                id="last-4-rounds-button",
                                n_clicks=0,
                                style=button_style,
                            )
                        ], style={
                            "display": "inline-block",
                            "textAlign": "left",
                            "width": "33%",
                        }),

                        # Centre: empty (keeps spacing consistent)
                        html.Div([], style={
                            "display": "inline-block",
                            "textAlign": "center",
                            "width": "33%",
                        }),

                        # Right: status text
                        html.Div([
                            html.Div(
                                id="last-4-status",
                                style={
                                    "color": "white",
                                    "fontWeight": "bold",
                                    "paddingTop": "8px",
                                    "fontFamily": base_font["fontFamily"],
                                },
                            )
                        ], style={
                            "display": "inline-block",
                            "textAlign": "right",
                            "width": "33%",
                        }),
                    ], style={
                        "display": "flex",
                        "justifyContent": "space-between",
                        "padding": "10px 40px",
                    }),

                    # ----- Chart -----
                    dcc.Graph(
                        id="goals-by-type",
                        style={"backgroundColor": "black"},
                    ),

                ], style={
                    "backgroundColor": PANEL_BG,  # old blue 1E3A5F
                    "padding": "20px",
                    "border": "1px solid white",
                    "borderRadius": "10px",
                    "marginBottom": "20px",
                }),


                # === GS – Detail ===
                # === Goal Detail by Type – Assist/Buildup/Finish via dropdown ===
                html.Div([

                    # ----- Title + helper banner -----
                    chart_header(
                        f"{FOCUS_TEAM} – Goal Detail by Type (Buildup | Assist | Finish etc - dropdown)",
                        (
                            "Shows different aspects of how goals were scored. Use the dropdown to switch between:\n\n"
                            "- Assist type: e.g. build-up assist, cutback, counter, in-swinging corner, etc.\n"
                            "- Buildup Lane: whether the attack went down the Left, Centre, or Right side.\n"
                            "- How penetrated: did we go AROUND them, THROUGH them, or OVER them.\n"
                            "- Finish Type: the style of the final action.\n"
                            "- First-time finish: whether the finish was immediate or controlled first.\n\n"
                            "Bars are stacked by Goal Type (regains and set pieces), so you can see how these patterns "
                            "link to where and how the ball was won."
                        ),
                        "goal-detail-scored-helper"
                    ),

                    # ----- Top control row: empty | dropdown | empty (match 3-column pattern) -----
                    html.Div([
                        # Left spacer
                        html.Div([], style={
                            "display": "inline-block",
                            "textAlign": "left",
                            "width": "33%"
                        }),

                        # Centre: dropdown
                        html.Div([
                            dcc.Dropdown(
                                id="goal-context-dimension",
                                options=[
                                    {"label": "Assist type",        "value": "Assist type"},
                                    {"label": "Buildup Lane",       "value": "Buildup Lane"},
                                    {"label": "Finish Type",        "value": "Finish Type"},
                                    {"label": "How penetrated",     "value": "How penetrated"},
                                    {"label": "First-time finish",  "value": "First-time finish"},
                                ],
                                value="Assist type",
                                clearable=False,
                                placeholder="Select context dimension",
                                style={
                                    "width": "300px",
                                    "margin": "0 auto",
                                    "color": "black",
                                    "fontFamily": title_font["fontFamily"],
                                    "fontSize": "14px",
                                },
                            )
                        ], style={
                            "display": "inline-block",
                            "textAlign": "center",
                            "width": "33%"
                        }),

                        # Right spacer
                        html.Div([], style={
                            "display": "inline-block",
                            "textAlign": "right",
                            "width": "33%"
                        }),
                    ], style={
                        "display": "flex",
                        "justifyContent": "space-between",
                        "padding": "10px 40px"
                    }),

                    # ----- Chart -----
                    dcc.Graph(
                        id="goal-context-by-type",
                        style={"backgroundColor": "black"}
                    ),

                ], style={
                    "backgroundColor": PANEL_BG,
                    "padding": "20px",
                    "border": "1px solid white",
                    "borderRadius": "10px",
                    "marginBottom": "20px"
                }),

                # === Pass-String by Goal Type – Goals Scored ===
                html.Div([

                    # ----- Title + helper banner -----
                    chart_header(
                        title_text=f"{FOCUS_TEAM} – Pass-String by Goal Type",
                        tooltip_text=(
                            "A pass-string is the sequence of passes leading up to a goal.\n\n"
                            "Examples:\n"
                            "- 1 pass: usually a regain or set piece with a single immediate action.\n"
                            "- 2–4 passes: short combinations or quick attacks.\n"
                            "- 5+ passes: sustained possession, longer build-up sequences.\n\n"
                            "This chart shows how many passes were involved before each goal, "
                            "grouped by the goal type (e.g., R-FT-DT, MT-AT, set pieces, etc.)."
                        ),
                        helper_id="passstring-scored-helper",
                    ),

                    # ----- Chart -----
                    dcc.Graph(
                        id="passstring-by-type",
                        style={"backgroundColor": "black"},
                    ),

                ], style={
                    "backgroundColor": PANEL_BG,
                    "padding": "20px",
                    "border": "1px solid white",
                    "borderRadius": "10px",
                    "marginBottom": "20px",
                }),
                
                
                                    
                # === GS – Pie ===
                # Goal Type Pie Chart Section (Scored & Conceded)
                # Shared opponent filter for all 4 pies
                html.Div([
                    dcc.Dropdown(
                        id="goaltype-opponent-filter",
                        options=[{"label": "ALL", "value": "ALL"}] +
                                [{"label": opp, "value": opp} for opp in sorted(team_data["Opponent"].unique())],
                        value=None,                       # no pre-selected value, shows placeholder
                        placeholder="Filter by Opponent",
                        clearable=True,
                        style={
                            "width": "300px",
                            "margin": "0 auto",
                            "color": "black",             # applies once an option is selected
                            "fontFamily": "Segoe UI Black",
                            "fontSize": "14px"
                        }
                    )
                ], style={
                    "display": "inline-block",
                    "textAlign": "center",
                    "width": "100%",
                    "margin": "0 0 12px 0"
                }),
                        

                # === Goals Scored – Breakdown by Type (Pies) ===
                html.Div([

                    chart_header(
                        "Goals Scored – Breakdown by Type",
                        (
                            "Top row pies show how your team SCORES its goals.\n\n"
                            "Left pie (Open Play – Regains):\n"
                            "- Breaks down goals by where possession was regained:\n"
                            "  • R-FT: Front Third regain\n"
                            "  • R-MT: Middle Third regain\n"
                            "  • R-BT: Back Third regain\n"
                            "- And whether the goal came DURING transition (DT) or AFTER transition (AT).\n\n"
                            "Right pie (Set Pieces):\n"
                            "- Shows the proportion of goals scored from set pieces:\n"
                            "  • Corners (SP-C), Throw-ins (SP-T), Penalties (SP-P), Free kicks (SP-F).\n\n"
                            "Hover info shows: raw goal count, percentage of total goals, and total team goals.\n"
                            "Benchmarks (general football): ~28% of goals from set pieces, ~72% from open play.\n"
                            "Middle-third regains are usually the largest share (~47%), with front/back third "
                            "regains often around 10% each depending on style.\n\n"
                            "Use the Opponent filter above to see these patterns for a specific opponent or across all games."
                        ),
                        "goaltype-scored-helper"
                    ),

                    html.Div([
                        dcc.Graph(id="scored-regain-pie",    style={"backgroundColor": "black", "width": "48%"}),
                        dcc.Graph(id="scored-setpiece-pie",  style={"backgroundColor": "black", "width": "48%"}),
                    ], style={"display": "flex", "justifyContent": "space-between"}),

                ], style={
                    "backgroundColor": PANEL_BG,  # 1E3A5F
                    "padding": "20px",
                    "border": "1px solid white",
                    "borderRadius": "10px",
                    "marginBottom": "20px"
                }),
                
                
                # === GS – 5-Min Resolution ===
                # === 5-Minute Response After Goals (Olyroos focus) ===
                html.Div([

                    # ----- Title + helper banner -----
                    chart_header(
                        f"{FOCUS_TEAM} – 5-Minute Response After Goals",
                        (
                            "Every time you score or concede a goal in a match, this chart opens a 5-minute window and checks "
                            "what happens next.\n\n"
                            "It tracks whether, in the 5 minutes after a goal:\n"
                            "- Your team scores again (positive mentality / pressure after scoring).\n"
                            "- Your team concedes (loss of focus or poor response after key moments).\n"
                            "- No further goals occur (neutral response).\n\n"
                            "This helps you understand mentality and game management around big moments:\n"
                            "- After YOU score: do you stay focused or concede quickly?\n"
                            "- After YOU concede: do you react strongly and respond with a goal?\n\n"
                            "Use the Last 4 Rounds toggle to focus on recent behaviour and the Opponent filter "
                            "to see patterns against specific teams."
                        ),
                        "five-min-response-helper"
                    ),

                    # ----- Top control row: button | dropdown | status -----
                    html.Div([
                        html.Div([
                            html.Button(
                                "Show Last 4 Rounds",
                                id="five-min-last4-button",
                                n_clicks=0,
                                style=button_style
                            )
                        ], style={
                            "display": "inline-block",
                            "textAlign": "left",
                            "width": "33%"
                        }),

                        html.Div([
                            dcc.Dropdown(
                                id="five-min-opponent-selector",
                                options=OPPONENT_OPTIONS,
                                value="ALL",
                                clearable=False,
                                placeholder="Filter by Opponent",
                                style={
                                    "width": "300px",
                                    "margin": "0 auto",
                                    "color": "black",
                                    "fontFamily": title_font["fontFamily"],
                                    "fontSize": "14px"
                                }
                            )
                        ], style={
                            "display": "inline-block",
                            "textAlign": "center",
                            "width": "33%"
                        }),

                        html.Div([
                            html.Div(
                                id="five-min-last4-status",
                                style={
                                    "color": "white",
                                    "fontWeight": "bold",
                                    "paddingTop": "8px",
                                    "fontFamily": base_font["fontFamily"],   # Segoe UI
                                    "fontSize": "14px"
                                }
                            )
                        ], style={
                            "display": "inline-block",
                            "textAlign": "right",
                            "width": "33%"
                        }),
                    ], style={
                        "display": "flex",
                        "justifyContent": "space-between",
                        "padding": "10px 40px"
                    }),

                    # ----- Chart -----
                    dcc.Graph(
                        id="five-min-response-bar",
                        style={"backgroundColor": "black"}
                    ),

                ], style={
                    "backgroundColor": PANEL_BG,  # 1E3A5F
                    "padding": "20px",
                    "border": "1px solid white",
                    "borderRadius": "10px",
                    "marginBottom": "20px"
                }),
                html.Br(),

                    
                # === 5-Minute Response – Opponent Breakdown ===
                html.Div([

                    # ----- Title + helper banner -----
                    chart_header(
                        "5-Minute Response – Opponent Breakdown",
                        (
                            "Shows which opponents were involved when your team responded within the 5-minute windows "
                            "after goals.\n\n"
                            "This breaks down:\n"
                            "- Opponents you scored AGAINST quickly after scoring (double-punch moments).\n"
                            "- Opponents you scored against quickly AFTER conceding (positive reaction).\n"
                            "- Opponents who scored against YOU quickly after you scored (loss of focus).\n"
                            "- Opponents who repeated goals after scoring (pressure moments).\n\n"
                            "This helps identify which opponents:\n"
                            "- Struggle to regain control after they concede.\n"
                            "- Punish you quickly after you score.\n"
                            "- Are involved in repeated 5-minute swings.\n\n"
                            "Use this alongside the main 5-minute response chart to understand where the patterns come from."
                        ),
                        "five-min-response-opponent-helper"
                    ),

                    # ----- Chart -----
                    dcc.Graph(
                        id="five-min-response-opponent-bar",
                        style={"backgroundColor": "black"}
                    ),

                ], style={
                    "backgroundColor": PANEL_BG,  # 1E3A5F
                    "padding": "20px",
                    "border": "1px solid white",
                    "borderRadius": "10px",
                    "marginBottom": "20px"
                }),
                html.Br(),
                
                # ---------- GOAL MAP SECTION ----------
                
                # ---------- GOAL LOCATION MAP SECTION ----------
                html.Div(
                    children=[

                        # ----- Header row: title + opponent dropdown -----
                        html.Div(
                            [
                                # Left: title
                                html.Div(
                                    [
                                        html.H4(
                                            "Goal Location Map",
                                            style={
                                                "color": "white",
                                                "textAlign": "left",
                                                "fontFamily": "Segoe UI Black",
                                                "marginTop": "0px",
                                                "marginBottom": "0px",
                                                "fontSize": "22px",
                                            },
                                        )
                                    ],
                                    style={
                                        "display": "inline-block",
                                        "textAlign": "left",
                                        "width": "33%",
                                    },
                                ),

                                # Centre: opponent dropdown
                                html.Div(
                                    [
                                        dcc.Dropdown(
                                            id="goalmap-opponent-filter",
                                            options=[{"label": "ALL", "value": "ALL"}]
                                            + [{"label": o, "value": o} for o in opponent_options],
                                            value="ALL",
                                            clearable=False,
                                            placeholder="Filter by Opponent",
                                            style={
                                                "width": "300px",
                                                "margin": "0 auto",
                                                "color": "black",
                                                "fontFamily": title_font["fontFamily"],
                                                "fontSize": "14px",
                                            },
                                        )
                                    ],
                                    style={
                                        "display": "inline-block",
                                        "textAlign": "center",
                                        "width": "33%",
                                    },
                                ),

                                # Right: empty (keeps alignment)
                                html.Div(
                                    [],
                                    style={
                                        "display": "inline-block",
                                        "textAlign": "right",
                                        "width": "33%",
                                    },
                                ),
                            ],
                            style={
                                "display": "flex",
                                "justifyContent": "space-between",
                                "padding": "10px 40px",
                            },
                        ),

                        # ----- Second row: goal-type filter dropdown -----
                        html.Div(
                            [
                                html.Div([], style={"display": "inline-block", "width": "33%"}),

                                html.Div(
                                    [
                                        dcc.Dropdown(
                                            id="goalmap-type-filter",
                                            options=[
                                                {"label": "All Goals",                 "value": "ALL"},
                                                {"label": "All Corners (SP-C)",        "value": "ALL_CORNERS"},
                                                {"label": "All Set Pieces (SP-*)",     "value": "ALL_SP"},
                                                {"label": "Goals Scored (GS)",         "value": "GS"},
                                                {"label": "Goals Conceded (GC)",       "value": "GC"},
                                                {"label": "GS – Back Third Regain",    "value": "GS_BT"},
                                                {"label": "GS – Middle Third Regain",  "value": "GS_MT"},
                                                {"label": "GS – Front Third Regain",   "value": "GS_FT"},
                                                {"label": "GC – Back Third Regain",    "value": "GC_BT"},
                                                {"label": "GC – Middle Third Regain",  "value": "GC_MT"},
                                                {"label": "GC – Front Third Regain",   "value": "GC_FT"},
                                            ],
                                            value="ALL",
                                            clearable=False,
                                            placeholder="Filter by goal type",
                                            style={
                                                "width": "300px",
                                                "margin": "0 auto 10px auto",
                                                "color": "black",
                                                "fontFamily": title_font["fontFamily"],
                                                "fontSize": "14px",
                                            },
                                        )
                                    ],
                                    style={
                                        "display": "inline-block",
                                        "textAlign": "center",
                                        "width": "33%",
                                    },
                                ),

                                html.Div([], style={"display": "inline-block", "width": "33%"}),
                            ],
                            style={
                                "display": "flex",
                                "justifyContent": "space-between",
                                "padding": "0px 40px 10px 40px",
                            },
                        ),

                        # ----- Chart -----
                        dcc.Graph(
                            id="goal-map-figure",
                            style={"backgroundColor": "black"},
                        ),
                    ],
                    style={
                        "backgroundColor": PANEL_BG,
                        "padding": "20px",
                        "border": "1px solid white",
                        "borderRadius": "10px",
                        "marginBottom": "20px",
                    },
                ),
                html.Br(),







                
                
                # html.Div([...]),
            ],
        ),

        html.Hr(),

        # ---------------------------------------
        # GOALS CONCEDED
        # ---------------------------------------
        #dbc.Button(
        #    [
        #        html.Span("", id="gc-arrow"),  # closed by default
        #        html.Span("", style={"marginLeft": "6px"}),
        #    ],
        #    id="toggle-gc",
        #    color="danger",
        #    className="mb-2",
        #),
        

        dbc.Collapse(
            #id="collapse-gc",
            #is_open=False,
            children=[
                # === GC by Interval ===
                # === Goals Conceded by Interval – with Last 4 toggle ===
                html.Div([

                    # ----- Title + helper banner -----
                    chart_header(
                        title_text=f"{FOCUS_TEAM} – Goals Conceded by Interval",
                        tooltip_text=(
                            "Shows when goals are conceded across the 90 minutes.\n"
                            "- More goals between 0–15 mins may suggest slow defensive starts or poor early focus.\n"
                            "- If very few goals are conceded between 31–45 mins, it can indicate good mid-half concentration.\n"
                            "- Conceding more between 46–60 mins may highlight post-halftime lapses.\n"
                            "- A spike between 76–90 mins can point to fatigue, poor game management, or ineffective substitutions.\n\n"
                            "Use the Last 4 Rounds toggle to see recent trend only."
                        ),
                        helper_id="goals-interval-conceded-helper",
                    ),

                    # ----- Button + Status Row -----
                    html.Div([

                        # Left: toggle button
                        html.Div([
                            html.Button(
                                "Show Last 4 Rounds",
                                id="last-4-interval-button-conceded",
                                n_clicks=0,
                                style=button_style,
                            )
                        ], style={
                            "display": "inline-block",
                            "textAlign": "left",
                            "width": "33%",
                        }),

                        # Centre: empty spacer
                        html.Div([], style={
                            "display": "inline-block",
                            "textAlign": "center",
                            "width": "33%",
                        }),

                        # Right: status text
                        html.Div([
                            html.Div(
                                id="last-4-interval-status-conceded",
                                style={
                                    "color": "white",
                                    "fontWeight": "bold",
                                    "paddingTop": "8px",
                                    "fontFamily": base_font["fontFamily"],
                                },
                            )
                        ], style={
                            "display": "inline-block",
                            "textAlign": "right",
                            "width": "33%",
                        }),

                    ], style={
                        "display": "flex",
                        "justifyContent": "space-between",
                        "padding": "10px 40px",
                    }),

                    # ----- Chart -----
                    dcc.Graph(
                        id="conceded-by-interval",
                        style={"backgroundColor": "black"},
                    ),

                ], style={
                    "backgroundColor": PANEL_BG,  # 145B44 1E3A5F
                    "padding": "20px",
                    "border": "1px solid white",
                    "borderRadius": "10px",
                    "marginBottom": "20px",
                }),


                # === GC by Type ===
                # === Goals Conceded by Type – with Last 4 Rounds toggle ===
                html.Div([

                    # ----- Title + helper banner -----
                    chart_header(
                        f"{FOCUS_TEAM} – Goals Conceded by Type",
                        (
                            "Shows how goals are conceded by their type.\n\n"
                            "Set pieces:\n"
                            "- Corners (SP-C)\n"
                            "- Throw-ins (SP-T)\n"
                            "- Penalties (SP-P)\n"
                            "- Free kicks (SP-F)\n\n"
                            "Open play goals are grouped by where the opponent won the ball:\n"
                            "- R-FT = Regain in YOUR front third (dangerous – close to goal)\n"
                            "- R-MT = Regain in middle third\n"
                            "- R-BT = Regain in back third\n\n"
                            "DT = During Transition – conceded while disorganised "
                            "(e.g. losing the ball and being countered).\n"
                            "AT = After Transition – conceded once the opponent has settled possession.\n\n"
                            "Use the Last 4 Rounds toggle to focus on more recent defensive trends."
                        ),
                        "goals-type-conceded-helper"
                    ),

                    # ----- Button + Status Row -----
                        html.Div([

                            # Left: button
                            html.Div([
                                html.Button(
                                    "Show Last 4 Rounds",
                                    id="last-4-rounds-button-conceded",
                                    n_clicks=0,
                                    style=button_style
                                )
                            ], style={
                                "display": "inline-block",
                                "textAlign": "left",
                                "width": "33%"
                            }),

                            # Centre: empty spacer
                            html.Div([], style={
                                "display": "inline-block",
                                "textAlign": "center",
                                "width": "33%"
                            }),

                            # Right: status text
                            html.Div([
                                html.Div(
                                    id="last-4-status-conceded",
                                    style={
                                        "color": "white",
                                        "fontWeight": "bold",
                                        "paddingTop": "8px",
                                        "fontFamily": base_font["fontFamily"]
                                    }
                                )
                            ], style={
                                "display": "inline-block",
                                "textAlign": "right",
                                "width": "33%"
                            }),

                        ], style={
                            "display": "flex",
                            "justifyContent": "space-between",
                            "padding": "10px 40px"
                        }),

                        # ----- Chart -----
                        dcc.Graph(
                            id="conceded-by-type",
                            style={"backgroundColor": "black"}
                        ),

                    ], style={
                        "backgroundColor": PANEL_BG,
                        "padding": "20px",
                        "border": "1px solid white",
                        "borderRadius": "10px",
                        "marginBottom": "20px"
                    }),


                # === GC – Detail ===
                # === Goal Detail by Type – Conceded (Assist/Buildup/Finish via dropdown) ===
                html.Div([

                    # ----- Title + helper banner -----
                    chart_header(
                        f"{FOCUS_TEAM} – Goal Detail by Type (Conceded)",
                        (
                            "Breaks down how goals were conceded across five key dimensions:\n\n"
                            "• Assist Type – the type of action that created the chance "
                            "(e.g., cutback, cross, through-ball, counter-attack delivery).\n"
                            "• Buildup Lane – whether the opposition created the chance on your Left, Centre, or Right.\n"
                            "• How Penetrated – did they go around, through, or over your defensive structure.\n"
                            "• Finish Type – the style of the opponent’s final action.\n"
                            "• First-Time Finish – whether the opponent scored immediately or after controlling the ball.\n\n"
                            "Bars are stacked by Goal Type (regains & set pieces) so you can see how the *type of chance* "
                            "links to *where and how* the ball was lost or turned over.\n"
                            "Use the dropdown to explore patterns or consistent vulnerabilities."
                        ),
                        "goal-detail-conceded-helper"
                    ),

                    # ----- Top control row: empty | dropdown | empty -----
                    html.Div([
                        # Left spacer
                        html.Div([], style={
                            "display": "inline-block",
                            "textAlign": "left",
                            "width": "33%"
                        }),

                        # Centre: dropdown
                        html.Div([
                            dcc.Dropdown(
                                id="goal-context-dimension-conceded",
                                options=[
                                    {"label": "Assist type",        "value": "assist_type"},
                                    {"label": "Buildup Lane",       "value": "buildup_lane"},
                                    {"label": "Finish Type",        "value": "finish_type"},
                                    {"label": "How penetrated",     "value": "how_penetrated"},
                                    {"label": "First-time finish",  "value": "first_time_finish"},
                                ],
                                value="assist_type",
                                clearable=False,
                                placeholder="Select context dimension",
                                style={
                                    "width": "300px",
                                    "margin": "0 auto",
                                    "color": "black",
                                    "fontFamily": title_font["fontFamily"],
                                    "fontSize": "14px",
                                },
                            )
                        ], style={
                            "display": "inline-block",
                            "textAlign": "center",
                            "width": "33%"
                        }),

                        # Right spacer
                        html.Div([], style={
                            "display": "inline-block",
                            "textAlign": "right",
                            "width": "33%"
                        }),

                    ], style={
                        "display": "flex",
                        "justifyContent": "space-between",
                        "padding": "10px 40px"
                    }),

                    # ----- Chart -----
                    dcc.Graph(
                        id="goal-context-by-type-conceded",
                        style={"backgroundColor": "black"},
                    ),

                ], style={
                    "backgroundColor": PANEL_BG,
                    "padding": "20px",
                    "border": "1px solid white",
                    "borderRadius": "10px",
                    "marginBottom": "20px",
                }),
                
                # === Pass-String (Conceded) – to build later ===
                # html.Div([...]),

                # === GC – Pie ===
                # === Goals Conceded – Breakdown by Type (Pies) ===
                html.Div([

                    chart_header(
                        "Goals Conceded – Breakdown by Type",
                        (
                            "Bottom row pies show how goals are CONCEDED against your team.\n\n"
                            "Left pie (Open Play – Regains):\n"
                            "- Where the opponent won the ball before scoring:\n"
                            "  • R-FT: Regain in your defensive third (very dangerous – close to goal)\n"
                            "  • R-MT: Regain in middle third\n"
                            "  • R-BT: Regain in their defensive third\n"
                            "- DT (During Transition) = conceded while disorganised (e.g. counter-attacks).\n"
                            "- AT (After Transition) = conceded once the opponent has settled possession.\n\n"
                            "Right pie (Set Pieces):\n"
                            "- Proportion of goals conceded from corners, throw-ins, penalties, and free kicks.\n\n"
                            "Hover info shows goal counts, percentage of total conceded, and total goals conceded.\n"
                            "Compare these to the scored pies and general benchmarks to see whether you are "
                            "over- or under-exposed in certain areas (e.g. set-piece defending, transition moments).\n\n"
                            "Use the Opponent filter above to focus on a specific opponent or view all opponents combined."
                        ),
                        "goaltype-conceded-helper"
                    ),

                    html.Div([
                        dcc.Graph(id="conceded-regain-pie",   style={"backgroundColor": "black", "width": "48%"}),
                        dcc.Graph(id="conceded-setpiece-pie", style={"backgroundColor": "black", "width": "48%"}),
                    ], style={"display": "flex", "justifyContent": "space-between"}),

                ], style={
                    "backgroundColor": PANEL_BG,  # 1E3A5F
                    "padding": "20px",
                    "border": "1px solid white",
                    "borderRadius": "10px",
                    "marginBottom": "20px"
                }),
                
                html.Br(),


                            
            ],
        ),

        

        # ---------------------------------------
        # CONTEXT
        # ---------------------------------------
        #dbc.Button(
        #    [
        #        html.Span("►", id="context-arrow"),  # closed by default
        #        html.Span("  Context", style={"marginLeft": "6px"}),
        #    ],
        #    id="toggle-context",
        #    color="secondary",
        #    className="mb-2",
        #),
        
        

        dbc.Collapse(
            #id="collapse-context",
            #is_open=False,
            children=[
                # === First Goal Value ===
                # === First Goal Value Index (Olyroos) ===
                html.Div([

                    # ----- Title + helper banner -----
                    chart_header(
                        f"{FOCUS_TEAM} – First Goal Value Index",
                        (
                            "Shows what happens in games after the FIRST goal is scored.\n\n"
                            "When Olyroos score first:\n"
                            "- How often do you go on to WIN?\n"
                            "- How often do you LOSE the lead and DRAW?\n"
                            "- How often do you still LOSE the game?\n\n"
                            "When the OPPONENT scores first:\n"
                            "- How often do you go on to LOSE?\n"
                            "- How often do you come back to a DRAW?\n"
                            "- How often do you TURN IT INTO A WIN?\n\n"
                            "This gives a feel for how valuable the first goal is to your team, "
                            "and how resilient you are when you fall behind.\n"
                            "Use the Last 4 Rounds toggle to focus on recent form."
                        ),
                        "first-goal-index-helper"
                    ),

                    # ----- Button + Status Row -----
                    html.Div([
                        html.Div([
                            html.Button(
                                "Show Last 4 Rounds",
                                id="first-goal-last4-button",
                                n_clicks=0,
                                style=button_style
                            )
                        ], style={
                            "display": "inline-block",
                            "textAlign": "left",
                            "width": "50%"
                        }),

                        html.Div([
                            html.Div(
                                id="first-goal-last4-status",
                                style={
                                    "color": "white",
                                    "fontWeight": "bold",
                                    "paddingTop": "8px",
                                    "fontFamily": base_font["fontFamily"],
                                    "fontSize": "14px"
                                }
                            )
                        ], style={
                            "display": "inline-block",
                            "textAlign": "right",
                            "width": "50%"
                        }),
                    ], style={
                        "display": "flex",
                        "justifyContent": "space-between",
                        "padding": "10px 40px"
                    }),

                    # ----- Chart -----
                    dcc.Graph(
                        id="first-goal-index-bar",
                        style={"backgroundColor": "black"}
                    ),

                ], style={
                    "backgroundColor": PANEL_BG,  # old blue 1E3A5F
                    "padding": "20px",
                    "border": "1px solid white",
                    "borderRadius": "10px",
                    "marginBottom": "20px"
                }),
                html.Br(),

                # Philosophy Alignment / Magic Quadrant
                html.Div([

                    chart_header(
                        "Philosophy Alignment: Quadrant",
                        (
                            "Shows how closely match performances align with the intended playing model.\n"
                            "X-axis = Possession (%).\n"
                            "Y-axis = Quadrant Points.\n"
                            "The vertical line marks 50% possession and the horizontal line marks 0 quadrant points."
                        ),
                        "quadrant-helper"
                    ),

                    dcc.Graph(
                        id="quadrant-alignment-chart",
                        style={"backgroundColor": "black"}
                    )

                ], style={
                    "backgroundColor": PANEL_BG,
                    "padding": "20px",
                    "border": "1px solid white",
                    "borderRadius": "10px",
                    "marginBottom": "20px"
                }),
                
            ],
        ),

    ],
    fluid=True,
)

# ==========================================
# PLAYER INSIGHTS LAYOUT
# ==========================================
player_insights_layout = dbc.Container(
    [

        # ---------------------------------------
        # Goals per Minute
        # ---------------------------------------
        # === Goals Per Minute ===
        html.Div([

            # ----- Title + helper banner -----
            chart_header(
                "Goals Per Minute",
                (
                    "Shows how many minutes each player takes, on average, to score a goal.\n\n"
                    "Minutes per Goal (MPG):\n"
                    "- Lower MPG = more efficient or more frequent scorer.\n"
                    "- Higher MPG = scores less often or plays fewer scoring minutes.\n\n"
                    "Sorting options:\n"
                    "- High to Low / Low to High: sorts players by MPG efficiency.\n"
                    "- Total Goals: sorts by raw goal count and shows the opponents "
                    "each player scored against (stacked bars).\n\n"
                    "Tip: use the Total Goals button to quickly see who players "
                    "have scored against, and whether their goals come from a wide spread of opponents "
                    "or just a few teams."
                ),
                "goals-per-minute-helper"
            ),

            # ----- Sort Buttons -----
            html.Div([
                html.Button("High to Low",   id="sort-high-goals",  n_clicks=0, style=button_style),
                html.Button("Low to High",   id="sort-low-goals",   n_clicks=0, style=button_style),
                html.Button("Total Goals",   id="sort-total-goals", n_clicks=0, style=button_style),
            ], style={
                "textAlign": "left",
                "padding": "10px",
                "paddingLeft": "40px"
            }),

            # ----- Chart -----
            dcc.Graph(
                id="goals-per-minute",
                style={"backgroundColor": "black"}
            ),

        ], style={
            "backgroundColor": PANEL_BG,
            "padding": "20px",
            "border": "1px solid white",
            "borderRadius": "10px",
            "marginBottom": "20px"
        }),
        html.Br(),

        # === Assists Per Minute ===
        html.Div([

            # ----- Title + helper banner -----
            chart_header(
                "Assists Per Minute",
                (
                    "Shows how many minutes each player takes, on average, to register an assist.\n\n"
                    "Minutes per Assist (MPA):\n"
                    "- Lower MPA = creates goals more frequently.\n"
                    "- Higher MPA = less frequent assister or fewer assisting minutes.\n\n"
                    "Sorting options:\n"
                    "- High to Low / Low to High: sorts players by assist efficiency (MPA).\n"
                    "- Total Assists: sorts by raw assist count and (if stacked) can show which opponents "
                    "those assists came against.\n\n"
                    "Use this to identify your key creators and compare their output to playing time."
                ),
                "assists-per-minute-helper"
            ),

            # ----- Sort Buttons -----
            html.Div([
                html.Button("High to Low",     id="sort-high-assists",   n_clicks=0, style=button_style),
                html.Button("Low to High",     id="sort-low-assists",    n_clicks=0, style=button_style),
                html.Button("Total Assists",   id="sort-total-assists",  n_clicks=0, style=button_style),
            ], style={
                "textAlign": "left",
                "padding": "10px",
                "paddingLeft": "40px"
            }),

            # ----- Chart -----
            dcc.Graph(
                id="assists-per-minute",
                style={"backgroundColor": "black"}
            ),

        ], style={
            "backgroundColor": PANEL_BG,
            "padding": "20px",
            "border": "1px solid white",
            "borderRadius": "10px",
            "marginBottom": "20px"
        }),

        html.Br(),

        

        # === Goal Contributions Per Minute ===
        html.Div([

            # ----- Title + helper banner -----
            chart_header(
                "Goal Contributions Per Minute",
                (
                    "Combines goals and assists into a single measure: total goal contributions per minute.\n\n"
                    "A 'contribution' = Goal + Assist.\n"
                    "Minutes per Contribution (MPC):\n"
                    "- Lower MPC = player is directly involved in goals more often.\n"
                    "- Higher MPC = fewer direct involvements relative to minutes played.\n\n"
                    "Sorting options:\n"
                    "- High to Low / Low to High: sorts by contribution efficiency (MPC).\n"
                    "- Total Contributions: sorts by total (Goals + Assists), and can show which opponents "
                    "those contributions came against if the bars are stacked.\n\n"
                    "Use this to see overall attacking impact, not just pure finishing or pure creation."
                ),
                "goal-contributions-helper"
            ),

            # ----- Sort Buttons -----
            html.Div([
                html.Button("High to Low",          id="sort-high-contrib",   n_clicks=0, style=button_style),
                html.Button("Low to High",          id="sort-low-contrib",    n_clicks=0, style=button_style),
                html.Button("Total Contributions",  id="sort-total-contrib",  n_clicks=0, style=button_style),
            ], style={
                "textAlign": "left",
                "padding": "10px",
                "paddingLeft": "40px"
            }),

            # ----- Chart -----
            dcc.Graph(
                id="goal-contributions",
                style={"backgroundColor": "black"}
            ),

        ], style={
            "backgroundColor": PANEL_BG,
            "padding": "20px",
            "border": "1px solid white",
            "borderRadius": "10px",
            "marginBottom": "20px"
        }),

        html.Br(),

        # =========================================================
        # big moment goals layout
        # =========================================================

        html.Div([
            html.Div([
                dcc.Dropdown(
                    id="big-moment-goal-filter",
                    options=[
                        {"label": "All Big Moment Goals", "value": "ALL"},
                        {"label": "Match Winners", "value": "Match Winner"},
                        {"label": "Come Back Goals - to draw", "value": "Match-Tying Goal"},
                        {"label": "Go-Ahead Goals & held win", "value": "Go-Ahead Goal Held"},
                    ],
                    value="ALL",
                    clearable=False,
                    style={
                        "width": "260px",
                        "color": "black",
                        "fontFamily": "Segoe UI Black",
                        "fontSize": "14px",
                    },
                ),
            ], style={"display": "flex", "justifyContent": "center", "paddingBottom": "10px"}),

            dcc.Graph(id="big-moment-goals-chart", style={"backgroundColor": "black"})
        ], style={
            "backgroundColor": PANEL_BG,
            "padding": "20px",
            "border": "1px solid white",
            "borderRadius": "10px",
            "marginBottom": "20px"
        }),
        html.Br(),

        # Goals Conceded While On Field
        html.Div([
            html.Div([
                html.Button("High to Low", id="sort-high-gc", n_clicks=0, style=button_style),
                html.Button("Low to High", id="sort-low-gc", n_clicks=0, style=button_style),
                html.Button("Total Conceded", id="sort-total-gc", n_clicks=0, style=button_style)
            ], style={"textAlign": "left", "padding": "10px", "paddingLeft": "40px"}),

            dcc.Graph(id="goals-conceded-chart", style={"backgroundColor": "black"})
        ], style={
            "backgroundColor": PANEL_BG,
            "padding": "20px",
            "border": "1px solid white",
            "borderRadius": "10px",
            "marginBottom": "20px"
        }),

        html.Br(),
        
        # Effectiveness Chart Layout
        html.Div([
            html.Div([
                html.Button("High to Low", id="btn-high-eff", n_clicks=0, style=button_style),
                html.Button("Low to High", id="btn-low-eff", n_clicks=0, style=button_style),
                html.Button("Total Effectiveness", id="btn-total-eff", n_clicks=0, style=button_style),
                html.Button("Last 4 Rounds", id="btn-last-4-eff", n_clicks=0, style=button_style),
                html.Button("Reset", id="btn-reset-eff", n_clicks=0, style=button_style),
            ], style={"textAlign": "left", "padding": "10px", "paddingLeft": "40px"}),

            dcc.Graph(id="player-effectiveness-chart", style={"backgroundColor": "black"})
        ], style={
            "backgroundColor": PANEL_BG,
            "padding": "20px",
            "border": "1px solid white",
            "borderRadius": "10px",
            "marginBottom": "20px"
        }),

        html.Br(),


        # total starts and appearances 
        html.Div([
            html.Div([
                html.Button("High to Low (Starts)",   id="sort-high-starts",          n_clicks=0, style=button_style),
                html.Button("Low to High (Starts)",   id="sort-low-starts",           n_clicks=0, style=button_style),
                html.Button("Appearances",            id="sort-total-appearances",    n_clicks=0, style=button_style),
            ], style={"textAlign": "left", "padding": "10px", "paddingLeft": "40px"}),

            dcc.Graph(id="starts-appearances-chart", style={"backgroundColor": "black"})
        ], style={
            "backgroundColor": PANEL_BG,
            "padding": "20px",
            "border": "1px solid white",
            "borderRadius": "10px",
            "marginBottom": "20px"
        }),

        # Total mins played
        html.Div([
            html.Div([
                html.Button("High to Low",        id="sort-high-mins",   n_clicks=0, style=button_style),
                html.Button("Low to High",        id="sort-low-mins",    n_clicks=0, style=button_style),
                html.Button("Avg Mins per App",   id="sort-avg-mins",    n_clicks=0, style=button_style),
            ], style={"textAlign": "left", "padding": "10px", "paddingLeft": "40px"}),

            dcc.Graph(id="minutes-played-chart", style={"backgroundColor": "black"})
        ], style={
            "backgroundColor": PANEL_BG,
            "padding": "20px",
            "border": "1px solid white",
            "borderRadius": "10px",
            "marginBottom": "20px"
        }),
        
        

    ],
    fluid=True,
)

# ==========================================
# OPPONENT INSIGHTS LAYOUT
# ==========================================

# Build opponent options from league_goal_data (you can adjust later)
league_opponents = sorted({
    t for t in league_goal_data["Home Team"].dropna().unique()
    if isinstance(t, str) and t.strip()
} | {
    t for t in league_goal_data["Away Team"].dropna().unique()
    if isinstance(t, str) and t.strip()
})

LEAGUE_OPPONENT_OPTIONS = (
    [{"label": "ALL Opponents", "value": "ALL"}]
    + [{"label": t, "value": t} for t in league_opponents if t != FOCUS_TEAM]
)

# Make sure every league opponent has a colour
for t in league_opponents:
    if t not in TEAM_COLORS:
        TEAM_COLORS[t] = DEFAULT_COLOR


opponent_insights_layout = dbc.Container(
    [

        # ---------- Opponent selector + summary ----------
        html.Div(
            [
                html.H3(
                    "Opponent Insights",
                    style={
                        "color": "white",
                        "fontFamily": title_font["fontFamily"],
                        "marginBottom": "5px",
                    },
                ),

                html.P(
                    (
                        "Select an opponent to view their game behaviours across tracked matches: "
                        "shapes, timings, goal types, and key patterns."
                    ),
                    style={
                        "color": "white",
                        "fontFamily": base_font["fontFamily"],
                        "fontSize": "13px",
                        "marginBottom": "12px",
                    },
                ),

                # ---------- Dropdown (toggle removed) ----------
                html.Div(
                    [
                        dcc.Dropdown(
                            id="opponent-select",
                            options=opponent_dropdown_options,
                            value=OPPONENT_DEFAULT_VALUE,
                            clearable=False,
                            placeholder="Select Opponent",
                            style={
                                "width": "300px",
                                "color": "black",
                                "fontFamily": title_font["fontFamily"],
                                "fontSize": "14px",
                            },
                        ),
                    ],
                    style={
                        "display": "flex",
                        "justifyContent": "center",
                        "alignItems": "center",
                        "maxWidth": "650px",
                        "margin": "0 auto",
                    },
                ),

                html.Br(),


                # ---------- Summary block ----------
                html.Div(
                    id="opponent-summary",
                    style={
                        "color": "white",
                        "fontFamily": base_font["fontFamily"],
                        "fontSize": "13px",
                        "lineHeight": "1.5",
                    },
                ),
            ],
            style={
                "backgroundColor": PANEL_BG,
                "padding": "20px",
                "border": "1px solid white",
                "borderRadius": "10px",
                "marginBottom": "20px",
            },
        ),

        # === Opponent Match List – Context Overview ===
        html.Div([
            html.H3(
                "Opponent Match List",
                style={
                    "color": "white",
                    "fontFamily": title_font["fontFamily"],
                    "marginBottom": "12px",
                },
            ),

            html.P(
                "Matches analysed for selected opponent will show here."
                "",
                style={
                    "color": "white",
                    "fontFamily": base_font["fontFamily"],
                    "fontSize": "13px",
                    "marginBottom": "15px",
                },
            ),

            dcc.Loading(
                [
                    html.Div(
                        id="opp-match-list-table",
                        style={"width": "100%"},
                    ),
                ],
                type="circle",
                color="#FFFFFF"
            ),
        ],
        style={
            "backgroundColor": PANEL_BG,
            "padding": "20px",
            "border": "1px solid white",
            "borderRadius": "10px",
            "marginBottom": "20px",
        }),

        # ---------- Coach Behaviour Summary ----------
        html.Div(
            [
                html.H3(
                    "Coach Behaviour – In-Game Management",
                    style={
                        "color": "white",
                        "fontFamily": title_font["fontFamily"],
                        "marginBottom": "8px",
                    },
                ),

                html.Div(
                    id="opp-coach-behaviour-summary",
                    style={
                        "color": "white",
                        "fontFamily": base_font["fontFamily"],
                        "fontSize": "13px",
                        "lineHeight": "1.6",
                    },
                ),
            ],
            style={
                "backgroundColor": PANEL_BG,
                "padding": "16px",
                "border": "1px solid white",
                "borderRadius": "10px",
                "marginBottom": "20px",
            },
        ),

        
        
        # ---------- Goals Scored by the Opponent ----------
        html.Div(
            [
                html.H2(
                    "Goals Scored – Behaviour & Patterns",
                    style={
                        "color": "white",
                        "fontFamily": title_font["fontFamily"],
                        "marginBottom": "15px",
                        "textAlign": "center",
                        "marginBottom": "20px", 
                    },
                ),

                # Goals by interval (opponent insights layout)
                html.Div(
                    [
                        chart_header(
                            "Goals Scored by Interval",
                            (
                                "Shows which minute phases the opponent scores most often across recorded matches.\n\n"
                                "Patterns to look for:\n"
                                "- High 0–15 scoring → fast starters, strong initial intensity.\n"
                                "- High 31–45 scoring → press and regain behaviour before half time.\n"
                                "- High 46–60 scoring → halftime tactical adjustments.\n"
                                "- High 76–90 scoring → fitness, substitutions, tempo control.\n\n"
                                "Stacked bars show WHO they scored against, helping you detect if trends repeat "
                                "against similar-strength teams or only versus weaker sides."
                            ),
                            helper_id="opp-goals-interval-helper",
                        ),

                        dcc.Graph(
                            id="opp-scored-interval",
                            style={"backgroundColor": "black"},
                        ),
                    ],
                    style={
                        "backgroundColor": PANEL_BG,
                        "padding": "20px",
                        "border": "1px solid white",
                        "borderRadius": "10px",
                        "marginBottom": "20px",
                    },
                ),

               
                # === Goals Scored by Type (Opponent Tab) ===
                html.Div(
                    [
                        chart_header(
                            title_text="Goals Scored by Type",
                            tooltip_text=(
                                "Shows how this opponent scores its goals by type.\n\n"
                                "Set pieces:\n"
                                "- Corners (SP-C)\n"
                                "- Throw-ins (SP-T)\n"
                                "- Penalties (SP-P)\n"
                                "- Free kicks (SP-F)\n\n"
                                "Open-play goals are grouped by where THEY win the ball:\n"
                                "- R-FT = Regain in Front Third\n"
                                "- R-MT = Regain in Middle Third\n"
                                "- R-BT = Regain in Back Third\n\n"
                                "DT = During Transition – goals scored while the opponent is disorganised "
                                "(e.g. counter-attacks, fast breaks).\n"
                                "AT = After Transition – goals scored once the opponent is set and organised.\n\n"
                                "Bars are stacked by the team they scored against, so you can see which opponents "
                                "they hurt most with each goal type."
                            ),
                            helper_id="opp-goals-type-scored-helper",
                        ),
                        dcc.Graph(
                            id="opp-scored-type",
                            style={"backgroundColor": "black"},
                        ),
                    ],
                    style={
                        "backgroundColor": PANEL_BG,
                        "padding": "20px",
                        "border": "1px solid white",
                        "borderRadius": "10px",
                        "marginBottom": "20px",
                    },
                ),



                # Goal Type Pies (Scored)(opponent insights layout)
                # ---------- Goals Scored – Type Breakdown (Pies) ----------
                html.Div(
                    [
                        chart_header(
                            "Goal Type Breakdown – Goals Scored",
                            (
                                "Top row pies show how the SELECTED OPPONENT scores its goals in the games you have tracked.\n\n"
                                "Left pie (Open Play – Regains):\n"
                                "- Breaks down goals by where possession was regained:\n"
                                "  • R-FT: Front Third regain\n"
                                "  • R-MT: Middle Third regain\n"
                                "  • R-BT: Back Third regain\n"
                                "- And whether the goal came DURING transition (DT) or AFTER transition (AT).\n\n"
                                "Right pie (Set Pieces):\n"
                                "- Shows the proportion of goals scored from set pieces:\n"
                                "  • Corners (SP-C), Throw-ins (SP-T), Penalties (SP-P), Free kicks (SP-F).\n\n"
                                "Percentages are based on ALL goals scored by the selected opponent in your league-based tab."
                            ),
                            "opp-goaltype-scored-helper",
                        ),

                        html.Div(
                            [
                                dcc.Graph(
                                    id="opp-scored-regain-pie",
                                    style={"backgroundColor": "black", "width": "48%"},
                                ),
                                dcc.Graph(
                                    id="opp-scored-setpiece-pie",
                                    style={"backgroundColor": "black", "width": "48%"},
                                ),
                            ],
                            style={"display": "flex", "justifyContent": "space-between"},
                        ),
                    ],
                    style={
                        "backgroundColor": PANEL_BG,
                        "padding": "20px",
                        "border": "1px solid white",
                        "borderRadius": "10px",
                        "marginBottom": "20px",
                    },
                ),


                # Goal Detail (Scored)(opponent insights layout)
                # ---------- Goal Detail by Type – Goals Scored (Opponent perspective) ----------
                html.Div(
                    [
                        chart_header(
                            "Goal Detail by Type – Goals Scored",
                            (
                                "Shows how the SELECTED OPPONENT scores its goals across different dimensions.\n\n"
                                "Use the dropdown to switch between:\n"
                                "- Assist type – e.g. cutback, cross, through-ball, counter-attack delivery.\n"
                                "- Buildup Lane – whether attacks go Left, Centre, or Right.\n"
                                "- How penetrated – went AROUND, THROUGH, or OVER the opponent.\n"
                                "- Finish Type – the style of the final action.\n"
                                "- First-time finish – immediate finishes vs controlled finishes.\n\n"
                                "Bars are stacked by Goal Type (regains & set pieces), so you can see how the chance "
                                "type links to where and how the ball was won."
                            ),
                            "opp-goal-detail-scored-helper",
                        ),

                        # --- 3-column row: spacer | dropdown | spacer ---
                        html.Div(
                            [
                                html.Div([], style={
                                    "display": "inline-block",
                                    "textAlign": "left",
                                    "width": "33%",
                                }),

                                html.Div(
                                    [
                                        dcc.Dropdown(
                                            id="opp-goal-context-dimension",
                                            options=[
                                                {"label": "Assist type",       "value": "Assist type"},
                                                {"label": "Buildup Lane",      "value": "Buildup Lane"},
                                                {"label": "Finish Type",       "value": "Finish Type"},
                                                {"label": "How penetrated",    "value": "How penetrated"},
                                                {"label": "First-time finish", "value": "First-time finish"},
                                            ],
                                            value="Assist type",
                                            clearable=False,
                                            placeholder="Select context dimension",
                                            style={
                                                "width": "300px",
                                                "margin": "0 auto",
                                                "color": "black",
                                                "fontFamily": title_font["fontFamily"],
                                                "fontSize": "14px",
                                            },
                                        )
                                    ],
                                    style={
                                        "display": "inline-block",
                                        "textAlign": "center",
                                        "width": "33%",
                                    },
                                ),

                                html.Div([], style={
                                    "display": "inline-block",
                                    "textAlign": "right",
                                    "width": "33%",
                                }),
                            ],
                            style={
                                "display": "flex",
                                "justifyContent": "space-between",
                                "padding": "10px 40px",
                            },
                        ),

                        dcc.Graph(
                            id="opp-goal-context-by-type",
                            style={"backgroundColor": "black"},
                        ),
                    ],
                    style={
                        "backgroundColor": PANEL_BG,
                        "padding": "20px",
                        "border": "1px solid white",
                        "borderRadius": "10px",
                        "marginBottom": "20px",
                    },
                ),

            ]
        ),

        # ---------- Goals Conceded by the Opponent ----------(opponent insights layout)
        html.Div(
            [
                html.H2(
                    "Goals Conceded – Behaviour & Weaknesses",
                    style={
                        "color": "white",
                        "fontFamily": title_font["fontFamily"],
                        "marginBottom": "15px",
                        "textAlign": "center", 
                    },
                ),

                # goals Conceded by interval (opponent insights layout)
                html.Div(
                    [
                        chart_header(
                            "Goals Conceded by Interval",
                            (
                                "Shows when the selected opponent concedes goals in their matches.\n\n"
                                "Patterns to look for:\n"
                                "- Concedes early (0–15): slow starters, vulnerable during first phase of build-up.\n"
                                "- Concedes before halftime (31–45): structural fatigue or poor game-state control.\n"
                                "- Concedes after halftime (46–60): tactical adjustment vulnerability.\n"
                                "- Concedes late (76–90): conditioning issues, substitutions, or losing control of tempo.\n\n"
                                "Bars are stacked by the teams who scored against them, helping you see whether "
                                "these patterns repeat against strong sides only, or consistently across opponents."
                            ),
                            helper_id="opp-conceded-interval-helper",
                        ),

                        dcc.Graph(
                            id="opp-conceded-interval",
                            style={"backgroundColor": "black"},
                        ),
                    ],
                    style={
                        "backgroundColor": PANEL_BG,
                        "padding": "20px",
                        "border": "1px solid white",
                        "borderRadius": "10px",
                        "marginBottom": "20px",
                    },
                ),


                # goals Conceded by type (opponent insights tab)
                html.Div(
                    [
                        chart_header(
                            title_text="Goals Conceded by Type",
                            tooltip_text=(
                                "Shows how this opponent CONCEDES goals by type.\n\n"
                                "Set pieces:\n"
                                "- Corners (SP-C)\n"
                                "- Throw-ins (SP-T)\n"
                                "- Penalties (SP-P)\n"
                                "- Free kicks (SP-F)\n\n"
                                "Open-play goals are grouped by where the OTHER TEAM wins the ball:\n"
                                "- R-FT = Regain in THEIR defensive third (your attacking third)\n"
                                "- R-MT = Regain in middle third\n"
                                "- R-BT = Regain in THEIR attacking third\n\n"
                                "DT = During Transition – they concede while disorganised (e.g. losing it and being countered).\n"
                                "AT = After Transition – concede once the opponent has settled possession.\n\n"
                                "Bars are stacked by the team scoring against them, so you can see who has exploited "
                                "each weakness."
                            ),
                            helper_id="opp-goals-type-conceded-helper",
                        ),
                        dcc.Graph(
                            id="opp-conceded-type",
                            style={"backgroundColor": "black"},
                        ),
                    ],
                    style={
                        "backgroundColor": PANEL_BG,
                        "padding": "20px",
                        "border": "1px solid white",
                        "borderRadius": "10px",
                        "marginBottom": "20px",
                    },
                ),


                # Conceded Goal Type Pies (opponent insights layout)
                # ---------- Goals Conceded – Type Breakdown (Pies) ----------
                html.Div(
                    [
                        chart_header(
                            "Goal Type Breakdown – Goals Conceded",
                            (
                                "Bottom row pies show how the SELECTED OPPONENT concedes goals in your tracked games.\n\n"
                                "Left pie (Open Play – Regains):\n"
                                "- Where the OPPOSITION won the ball before scoring:\n"
                                "  • R-FT: Regain in opponent's defensive third (close to goal)\n"
                                "  • R-MT: Regain in middle third\n"
                                "  • R-BT: Regain in their own third\n"
                                "- DT (During Transition): conceded while disorganised (counter-attacks).\n"
                                "- AT (After Transition): conceded after the opposition has settled possession.\n\n"
                                "Right pie (Set Pieces):\n"
                                "- Proportion of goals conceded from corners, throw-ins, penalties, and free kicks.\n\n"
                                "Percentages are based on ALL goals conceded by the selected opponent "
                                "in the league-based tab."
                            ),
                            "opp-goaltype-conceded-helper",
                        ),

                        html.Div(
                            [
                                dcc.Graph(
                                    id="opp-conceded-regain-pie",
                                    style={"backgroundColor": "black", "width": "48%"},
                                ),
                                dcc.Graph(
                                    id="opp-conceded-setpiece-pie",
                                    style={"backgroundColor": "black", "width": "48%"},
                                ),
                            ],
                            style={"display": "flex", "justifyContent": "space-between"},
                        ),
                    ],
                    style={
                        "backgroundColor": PANEL_BG,
                        "padding": "20px",
                        "border": "1px solid white",
                        "borderRadius": "10px",
                        "marginBottom": "20px",
                    },
                ),

                

                # (opponent insights layout)
                # ---------- Goal Detail by Type – Goals Conceded (Opponent perspective) ----------
                html.Div(
                    [
                        chart_header(
                            "Goal Detail by Type – Goals Conceded",
                            (
                                "Shows how the SELECTED OPPONENT concedes goals across the same dimensions.\n\n"
                                "Dimensions:\n"
                                "• Assist type – what kind of pass or action created the chance.\n"
                                "• Buildup Lane – which side of the pitch the chance came from.\n"
                                "• How penetrated – AROUND / THROUGH / OVER their structure.\n"
                                "• Finish Type – style of the opponent's finishing action.\n"
                                "• First-time finish – immediate vs controlled finishes.\n\n"
                                "Bars are stacked by Goal Type (regains & set pieces), so you can see how their "
                                "defensive weaknesses connect to where and how they lose the ball."
                            ),
                            "opp-goal-detail-conceded-helper",
                        ),

                        html.Div(
                            [
                                html.Div([], style={
                                    "display": "inline-block",
                                    "textAlign": "left",
                                    "width": "33%",
                                }),

                                html.Div(
                                    [
                                        dcc.Dropdown(
                                            id="opp-goal-context-dimension-conceded",
                                            options=[
                                                {"label": "Assist type",       "value": "Assist type"},
                                                {"label": "Buildup Lane",      "value": "Buildup Lane"},
                                                {"label": "Finish Type",       "value": "Finish Type"},
                                                {"label": "How penetrated",    "value": "How penetrated"},
                                                {"label": "First-time finish", "value": "First-time finish"},
                                            ],
                                            value="Assist type",
                                            clearable=False,
                                            placeholder="Select context dimension",
                                            style={
                                                "width": "300px",
                                                "margin": "0 auto",
                                                "color": "black",
                                                "fontFamily": title_font["fontFamily"],
                                                "fontSize": "14px",
                                            },
                                        )
                                    ],
                                    style={
                                        "display": "inline-block",
                                        "textAlign": "center",
                                        "width": "33%",
                                    },
                                ),

                                html.Div([], style={
                                    "display": "inline-block",
                                    "textAlign": "right",
                                    "width": "33%",
                                }),

                            ],
                            style={
                                "display": "flex",
                                "justifyContent": "space-between",
                                "padding": "10px 40px",
                            },
                        ),

                        dcc.Graph(
                            id="opp-goal-context-by-type-conceded",
                            style={"backgroundColor": "black"},
                        ),
                    ],
                    style={
                        "backgroundColor": PANEL_BG,
                        "padding": "20px",
                        "border": "1px solid white",
                        "borderRadius": "10px",
                        "marginBottom": "20px",
                    },
                ),

            ]
        ),


        
        # ---------- 5-min response ----------(opponent insights layout)
        html.Div(
            [
                chart_header(
                    "5-Minute Response After Goals (Opponent Profile)",
                    (
                        "For the selected team, every time they score or concede a goal, "
                        "a 5-minute window is opened to see what happens next.\n\n"
                        "This shows, for that opponent:\n"
                        "- After Scoring: how often they score again, concede, or see no further goals.\n"
                        "- After Conceding: how often they respond with a goal or concede again.\n\n"
                        "Gives a quick sense of their mentality and game management around key moments."
                    ),
                    "opp-five-min-response-helper",
                ),
                dcc.Graph(
                    id="opp-five-min-response-bar",
                    style={"backgroundColor": "black"},
                ),
            ],
            style={
                "backgroundColor": PANEL_BG,
                "padding": "20px",
                "border": "1px solid white",
                "borderRadius": "10px",
                "marginBottom": "20px",
            },
        ),

        # ---------- 5-Minute Response – Opponents involved ----------
        html.Div(
            [
                chart_header(
                    "5-Minute Response – Teams Involved in Swings",
                    (
                        "Shows which opponents are involved in 5-minute swings for the selected team.\n\n"
                        "For this team, it breaks down by opponent:\n"
                        "- Games where they scored again quickly after scoring.\n"
                        "- Games where they conceded quickly after scoring.\n"
                        "- Games where they scored quickly after conceding.\n"
                        "- Games where they conceded again quickly after conceding.\n\n"
                        "Helps highlight who they double-punch, and who punishes them in the 5-minute windows."
                    ),
                    "opp-five-min-response-opponent-helper",
                ),
                dcc.Graph(
                    id="opp-five-min-response-opponent-bar",
                    style={"backgroundColor": "black"},
                ),
            ],
            style={
                "backgroundColor": PANEL_BG,
                "padding": "20px",
                "border": "1px solid white",
                "borderRadius": "10px",
                "marginBottom": "20px",
            },
        ),


        # ---------- Goal map location ----------(opponent insights layout)
        html.Div(
            children=[
                # ---- Title + helper banner ----
                chart_header(
                    "Goal Location Map – Scored & Conceded",
                    (
                        "Shows where this opponent scores and concedes their goals across all tracked matches.\n\n"
                        "• Circles = goals they scored (FOR).\n"
                        "• Crosses = goals they conceded (AGAINST).\n\n"
                        "Use the opponent selector at the top of the tab to switch teams and "
                        "the filter below to focus on specific goal types or regain zones."
                    ),
                    "opp-goal-map-helper",
                ),

                # ---- Goal-type filter dropdown (consistent styling) ----
                html.Div(
                    [
                        dcc.Dropdown(
                            id="opp-goalmap-filter",
                            options=[
                                {"label": "ALL Goals",           "value": "ALL"},
                                {"label": "ALL Corners (SP-C)",  "value": "ALL_CORNERS"},
                                {"label": "All Set Pieces (SP-*)",     "value": "ALL_SP"},
                                {"label": "Goals Scored (GS)",   "value": "GS"},
                                {"label": "Goals Conceded (GC)", "value": "GC"},
                                {"label": "GS – BT Regain",      "value": "GS_BT"},
                                {"label": "GS – MT Regain",      "value": "GS_MT"},
                                {"label": "GS – FT Regain",      "value": "GS_FT"},
                                {"label": "GC – BT Regain",      "value": "GC_BT"},
                                {"label": "GC – MT Regain",      "value": "GC_MT"},
                                {"label": "GC – FT Regain",      "value": "GC_FT"},
                            ],
                            value="ALL",
                            clearable=False,
                            placeholder="Select goal type",
                            style={
                                "width": "300px",
                                "margin": "0 auto",
                                "color": "black",
                                "fontFamily": title_font["fontFamily"],  # matches your other dropdowns
                                "fontSize": "14px",
                            },
                        )
                    ],
                    style={
                        "display": "inline-block",
                        "textAlign": "center",
                        "width": "100%",   # centred like your existing UI
                        "paddingBottom": "15px",
                    },
                ),


                # ---- Chart ----
                dcc.Graph(
                    id="opp-goal-map-figure",
                    style={"backgroundColor": "black"},
                ),
            ],
            style={
                "backgroundColor": PANEL_BG,
                "padding": "20px",
                "border": "1px solid white",
                "borderRadius": "10px",
                "marginBottom": "20px",
            },
        ),


        # ---------- First goal value index ----------(opponent insights layout)
        # === First Goal Value Index – Selected Opponent ===
        html.Div([

            chart_header(
                "First Goal Value Index – Selected Opponent",
                (
                    "Shows how this opponent performs depending on who scores the FIRST goal.\n\n"
                    "When THEY score first:\n"
                    "- How often do they GO ON TO WIN?\n"
                    "- How often do they get pegged back to a DRAW?\n"
                    "- How often do they still LOSE the game?\n\n"
                    "When they CONCEDE first:\n"
                    "- How often do they LOSE from behind?\n"
                    "- How often do they claw it back to a DRAW?\n"
                    "- How often do they TURN IT INTO A WIN?\n\n"
                    "Bars show the percentage of games in each scenario that ended in Win / Draw / Loss.\n"
                    "Use this as a mentality / resilience profile for the selected opponent."
                ),
                "opp-first-goal-index-helper",
            ),

            dcc.Graph(
                id="opp-first-goal-index-bar",
                style={"backgroundColor": "black"},
            ),

        ], style={
            "backgroundColor": PANEL_BG,
            "padding": "20px",
            "border": "1px solid white",
            "borderRadius": "10px",
            "marginBottom": "20px",
        }),


        # ---------- Placeholder for future player charts vs opponent ----------(opponent insights layout)
        # === Opponent – Goals Per Minute ===
        html.Div([

            chart_header(
                "Opponent – Goals Per Minute",
                (
                    "For the selected opponent, shows how many minutes each player takes, "
                    "on average, to score a goal.\n\n"
                    "Minutes per Goal (MPG):\n"
                    "- Lower MPG = more efficient or more frequent scorer.\n"
                    "- Higher MPG = scores less often or plays fewer scoring minutes.\n\n"
                    "Sorting options:\n"
                    "- High to Low / Low to High: sorts players by MPG efficiency.\n"
                    "- Total Goals: sorts by raw goal count and shows which teams "
                    "those goals were scored against (stacked bars).\n\n"
                    "Use this to identify the main scoring threats for the selected opponent."
                ),
                "opp-goals-per-minute-helper"
            ),

            # Sort buttons (separate IDs from Player Insights tab)
            html.Div([
                html.Button("High to Low",   id="opp-sort-high-goals",  n_clicks=0, style=button_style),
                html.Button("Low to High",   id="opp-sort-low-goals",   n_clicks=0, style=button_style),
                html.Button("Total Goals",   id="opp-sort-total-goals", n_clicks=0, style=button_style),
            ], style={
                "textAlign": "left",
                "padding": "10px",
                "paddingLeft": "40px",
            }),

            dcc.Graph(
                id="opp-goals-per-minute",
                style={"backgroundColor": "black"}
            ),

        ], style={
            "backgroundColor": PANEL_BG,
            "padding": "20px",
            "border": "1px solid white",
            "borderRadius": "10px",
            "marginBottom": "20px",
        }),
        html.Br(),

        # === Opponent – Assists Per Minute Opponent Insights tab===
        html.Div([

            chart_header(
                "Opponent – Assists Per Minute",
                (
                    "For the selected opponent, shows how many minutes each player takes, "
                    "on average, to register an assist.\n\n"
                    "Minutes per Assist (MPA):\n"
                    "- Lower MPA = creates goals more frequently.\n"
                    "- Higher MPA = less frequent assister or fewer assisting minutes.\n\n"
                    "Sorting options:\n"
                    "- High to Low / Low to High: sorts players by assist efficiency (MPA).\n"
                    "- Total Assists: sorts by raw assist count and shows which teams "
                    "those assists came against (stacked bars).\n\n"
                    "Use this to identify the main creators for the selected opponent."
                ),
                "opp-assists-per-minute-helper"
            ),

            # Sort Buttons (separate IDs from Player Insights tab)
            html.Div([
                html.Button("High to Low",   id="opp-sort-high-assists",   n_clicks=0, style=button_style),
                html.Button("Low to High",   id="opp-sort-low-assists",    n_clicks=0, style=button_style),
                html.Button("Total Assists", id="opp-sort-total-assists",  n_clicks=0, style=button_style),
            ], style={
                "textAlign": "left",
                "padding": "10px",
                "paddingLeft": "40px",
            }),

            dcc.Graph(
                id="opp-assists-per-minute",
                style={"backgroundColor": "black"}
            ),

        ], style={
            "backgroundColor": PANEL_BG,
            "padding": "20px",
            "border": "1px solid white",
            "borderRadius": "10px",
            "marginBottom": "20px",
        }),
        html.Br(),



        


        # === Opponent – Contributions Per Minute Opponent Insights tab ===
        html.Div([

            chart_header(
                "Opponent – Goal Contributions Per Minute",
                (
                    "For the selected opponent, combines goals and assists into a single measure: "
                    "total goal contributions per minute.\n\n"
                    "A 'contribution' = Goal + Assist.\n"
                    "Minutes per Contribution (MPC):\n"
                    "- Lower MPC = player is directly involved in goals more often.\n"
                    "- Higher MPC = fewer direct involvements relative to minutes played.\n\n"
                    "Sorting options:\n"
                    "- High to Low / Low to High: sorts by contribution efficiency (MPC).\n"
                    "- Total Contributions: sorts by total (Goals + Assists), and shows which teams "
                    "those contributions came against (stacked bars).\n\n"
                    "Use this to see the overall attacking impact of the selected opponent's players."
                ),
                "opp-goal-contributions-helper"
            ),

            html.Div([
                html.Button("High to Low",         id="opp-sort-high-contrib",   n_clicks=0, style=button_style),
                html.Button("Low to High",         id="opp-sort-low-contrib",    n_clicks=0, style=button_style),
                html.Button("Total Contributions", id="opp-sort-total-contrib",  n_clicks=0, style=button_style),
            ], style={
                "textAlign": "left",
                "padding": "10px",
                "paddingLeft": "40px",
            }),

            dcc.Graph(
                id="opp-goal-contributions",
                style={"backgroundColor": "black"}
            ),

        ], style={
            "backgroundColor": PANEL_BG,
            "padding": "20px",
            "border": "1px solid white",
            "borderRadius": "10px",
            "marginBottom": "20px",
        }),
        html.Br(),

        
        # === Opponent – Starts and Appearances Opponent Insights tab ===
        html.Div([
            html.Div([
                html.Button("High to Low (Starts)",  id="opp-sort-high-starts",       n_clicks=0, style=button_style),
                html.Button("Low to High (Starts)",  id="opp-sort-low-starts",        n_clicks=0, style=button_style),
                html.Button("Appearances",           id="opp-sort-total-appearances", n_clicks=0, style=button_style),
            ], style={"textAlign": "left", "padding": "10px", "paddingLeft": "40px"}),

            dcc.Graph(id="opp-starts-appearances-chart", style={"backgroundColor": "black"}),
        ], style={
            "backgroundColor": PANEL_BG,
            "padding": "20px",
            "border": "1px solid white",
            "borderRadius": "10px",
            "marginBottom": "20px",
        }),


        # === Opponent – Total minutes Opponent Insights tab===
        html.Div([
            html.Div([
                html.Button("High to Low",       id="opp-sort-high-mins",  n_clicks=0, style=button_style),
                html.Button("Low to High",       id="opp-sort-low-mins",   n_clicks=0, style=button_style),
                html.Button("Avg Mins per App",  id="opp-sort-avg-mins",   n_clicks=0, style=button_style),
            ], style={"textAlign": "left", "padding": "10px", "paddingLeft": "40px"}),

            dcc.Graph(id="opp-minutes-played-chart", style={"backgroundColor": "black"}),
        ], style={
            "backgroundColor": PANEL_BG,
            "padding": "20px",
            "border": "1px solid white",
            "borderRadius": "10px",
            "marginBottom": "20px",
        }),



    ],
    fluid=True,
)



# ----------these layouts are not in any of the team, player or opponent tabs--------------

# ---------- DASH LAYOUT ----------
app.layout = html.Div(
    [

        # ---------- Banner Title ----------
        html.Div(
            style={
                "backgroundColor": "black",
                "padding": "30px 10px",
                "textAlign": "center",
                "marginBottom": "30px",
                "borderRadius": "8px",
            },
            children=[
                html.H1(
                    "Belco NPLW – Season Stats Dashboard",
                    style={
                        "color": "white",
                        "fontFamily": title_font["fontFamily"],
                        "fontWeight": "bold",
                        "fontSize": "40px",
                        "margin": "0",
                    },
                )
            ],
        ),

        html.Div(style={"height": "20px"}),

        # ---------- Team Selector ----------
        html.Div(
            [

                html.Div(
                    [
                        dcc.Dropdown(
                            id="team-select",
                            options=[
                                {"label": "1sts", "value": "1sts"},
                                {"label": "Reserves", "value": "Reserves"},
                            ],
                            value="1sts",
                            clearable=False,
                            style={
                                "width": "220px",
                                "color": "black",
                                "fontFamily": title_font["fontFamily"],
                                "fontSize": "14px",
                            },
                        ),
                    ],
                    style={
                        "display": "flex",
                        "justifyContent": "center",
                        "alignItems": "center",
                        "gap": "10px",
                        "padding": "10px",
                        "margin": "0 auto",
                        "paddingLeft": "40px",
                        "marginBottom": "10px",
                        "flexWrap": "wrap",
                    },
                ),

                html.P(
                    (
                        "Select which team’s season data to view (1sts or Reserves). "
                        "All charts and insights below will update to match your selection."
                    ),
                    style={
                        "color": "white",
                        "fontFamily": base_font["fontFamily"],
                        "fontSize": "13px",
                        "textAlign": "center",
                        "marginBottom": "0",
                    },
                ),

            ],
            style={
                "backgroundColor": PANEL_BG,
                "padding": "15px",
                "border": "1px solid white",
                "borderRadius": "10px",
                "marginBottom": "20px",
            },
        ),



        # ===== Top Tabs =====
        dcc.Tabs(
            id="main-tabs",
            value="team-tab",
            children=[
                dcc.Tab(
                    label="Team Insights",
                    value="team-tab",
                    className="custom-tab",
                    selected_className="custom-tab--selected",
                ),
                dcc.Tab(
                    label="Player Insights",
                    value="player-tab",
                    className="custom-tab",
                    selected_className="custom-tab--selected",
                ),
                dcc.Tab(
                    label="Opponent Insights",
                    value="opponent-tab",
                    className="custom-tab",
                    selected_className="custom-tab--selected",
                ),
            ],
            className="custom-tabs",
            style={"color": "white"},
        ),

        html.Br(),

        # ===== Tab content area =====
        html.Div(id="main-content", style={"marginTop": "20px"}),
    ],
    # style={"backgroundColor": "#0A3D2E", "padding": "20px", "minHeight": "100vh"},
    style={"backgroundColor": "#121212", "padding": "20px", "minHeight": "100vh"},

)

   
    
    #-------------TEAM BEHAVIOURS + GAME CONTROL-----------------

    
    
# old ending to layout section
#], style={"backgroundColor": "#0A3D2E", "padding": "20px", "minHeight": "100vh"}) #  old colour #1E3A5F

    #----------------PLAYER LAYER------------------
    #html.Div(style={"height": "20px"}),

    # ---------- Team Section Header ----------
    #html.H2(
    #    "Player Statistics",
    #    style={
    #        "textAlign": "center",
    #        "color": "white",
    #        "fontFamily": title_font["fontFamily"],
    #        "marginBottom": "20px",
    #        "textDecoration": "underline"
    #    }
    #),

    #html.Div(style={"height": "20px"}),





    # Clean Sheet Contributions
    #html.Div([
    #    html.Div([
    #        html.Button("Last 4 Rounds", id="btn-last-4-cs", n_clicks=0, style=button_style),
    #        html.Button("Reset View", id="btn-reset-cs", n_clicks=0, style=button_style)
    #    ], style={"textAlign": "left", "padding": "10px", "paddingLeft": "40px"}),

    #    dcc.Graph(id="defender-clean-sheet-chart", style={"backgroundColor": "black"})
    #], style={
    #    "backgroundColor": "#1E3A5F",
    #    "padding": "20px",
    #    "border": "1px solid white",
    #    "borderRadius": "10px",
    #    "marginBottom": "20px"
    #}),
    


    # SOMETHING TO DO WITH THE QUDRANT
    #html.Div([
    #    dcc.Graph(id="quadrant-alignment-chart", style={"backgroundColor": "black"})
    #], style={
    #    "backgroundColor": "#1E3A5F",
    #    "padding": "20px",
    #    "border": "1px solid white",
    #    "borderRadius": "10px",
    #    "marginBottom": "20px"
    #}),
   

    





# callbacks start here.

# Define maps (can optionally move these outside the function later)
scored_map = {
    "R-FT-DT": {
        "insight": "We're pressing high and winning the ball in the final third during transitions. This shows our front-line pressure is working well.",
        "training": "Reinforce counter-pressing and quick attacking combinations after a turnover in the final third."
    },
    "R-FT-AT": {
        "insight": "We're controlling possession in the final third and breaking teams down in settled play.",
        "training": "Focus on patient build-up play and finding space through short combinations near the box."
    },
    "R-MT-DT": {
        "insight": "We're scoring through fast transitions after winning the ball in midfield. Our middle-third pressure is paying off.",
        "training": "Work on winning the ball in midfield and launching fast, direct attacks toward goal."
    },
    "R-MT-AT": {
        "insight": "Our midfield dominance is converting into goals from organised play, not just counters.",
        "training": "Improve midfield positioning and movement patterns to consistently create from this area."
    },
    "R-BT-DT": {
        "insight": "We’re launching quick counter-attacks from deep and catching teams unprepared.",
        "training": "Develop passing options and quick decision-making when building from the back under pressure."
    },
    "R-BT-AT": {
        "insight": "Our patient play from deep is turning into goals — a sign of structured build-up and good spacing.",
        "training": "Work on structured build-up patterns and supporting angles when playing out from the back."
    },
    "SP-C": {
        "insight": "We're a real threat from corners — timing, delivery and movement in the box are effective.",
        "training": "Reinforce set-piece routines with particular focus on movement patterns and delivery zones."
    },
    "SP-T": {
        "insight": "We're creating goals from throw-ins — an underused but valuable source of attack.",
        "training": "Sharpen throw-in routines and options for receiving under pressure."
    },
    "SP-P": {
        "insight": "We’re drawing penalties, which shows intelligent movement and pressure in the box.",
        "training": "Encourage attacking players to take on defenders and make runs across defenders in the area."
    },
    "SP-F": {
        "insight": "We're scoring from free kicks — good technique or clever execution is making a difference.",
        "training": "Practice direct and indirect free kicks with emphasis on variety and timing of runs."
    }
}


conceded_map = {
    "R-FT-DT": {
        "insight": "We're being pressed high and losing the ball in dangerous areas, leading to goals.",
        "training": "Improve decision-making and technical execution when playing out under pressure."
    },
    "R-FT-AT": {
        "insight": "We're allowing teams to dominate us in our defensive third with sustained pressure.",
        "training": "Work on defensive shape and compactness in the final third, especially during extended phases."
    },
    "R-MT-DT": {
        "insight": "We're getting hit on the counter after losing possession in midfield.",
        "training": "Drill recovery runs and defensive reactions immediately after losing the ball in midfield."
    },
    "R-MT-AT": {
        "insight": "We’re conceding from structured midfield play — teams are picking us apart centrally.",
        "training": "Tighten midfield marking, screen passing lanes, and improve spatial awareness."
    },
    "R-BT-DT": {
        "insight": "We're conceding goals after turning over the ball in our defensive third.",
        "training": "Focus on decision-making under pressure and supporting angles during build-out."
    },
    "R-BT-AT": {
        "insight": "We're breaking down defensively in settled play deep in our half.",
        "training": "Reinforce defensive structure, compactness, and discipline near our penalty box."
    },
    "SP-C": {
        "insight": "Corners are causing us trouble — either from poor marking or second ball issues.",
        "training": "Work on zonal or man-marking schemes, and ensure defenders know their roles on set pieces."
    },
    "SP-T": {
        "insight": "We're conceding from throw-ins — potentially due to lapses in focus or second ball reactions.",
        "training": "Reinforce defending throw-ins and transition reactions after restarts."
    },
    "SP-P": {
        "insight": "We've conceded penalties — suggests poor timing or decision-making when defending in the box.",
        "training": "Emphasise defensive discipline and body positioning inside the area."
    },
    "SP-F": {
        "insight": "Free kicks are exposing us — timing, wall set-up, or marking might be to blame.",
        "training": "Review defensive set-up and reactions for free kicks around the box."
    }
}


# callback for the league table
@app.callback(
    Output("league-ladder", "data"),
    Output("league-ladder", "columns"),
    Output("league-ladder", "style_data_conditional"),
    Output("ladder-note", "children"),
    Input("update-league-button", "n_clicks"),
    Input("team-select", "value"),
)
def update_league_ladder_table(n_clicks, selected_squad):
    df = league_goal_data.copy()

    # Filter to selected squad rows
    if "Team" in df.columns:
        df["Team"] = df["Team"].astype(str).str.strip()
        df = df[df["Team"] == str(selected_squad).strip()].copy()

    # Basic cleaning
    for c in ["Match ID", "Home Team", "Away Team", "Full-score"]:
        if c in df.columns:
            df[c] = df[c].fillna("").astype(str).str.strip()

    # League rounds only (supports R1, R2, R1-BEL-MAJ etc.)
    df = df[df["Match ID"].str.startswith("R")].copy()

    if df.empty:
        return [], [], [], "No completed league results available yet."

    # One row per match result
    df_unique = df.drop_duplicates(
        subset=["Match ID", "Home Team", "Away Team", "Full-score"]
    ).copy()

    def extract_score(score):
        try:
            h, a = str(score).split("-")
            return int(h.strip()), int(a.strip())
        except Exception:
            return None, None

    ladder = {}

    for _, row in df_unique.iterrows():
        home = row["Home Team"]
        away = row["Away Team"]
        hg, ag = extract_score(row["Full-score"])

        # Skip games with no valid result entered yet
        if hg is None or ag is None:
            continue

        for team in [home, away]:
            if team not in ladder:
                ladder[team] = {
                    "P": 0, "W": 0, "D": 0, "L": 0,
                    "F": 0, "A": 0, "GD": 0, "PTS": 0
                }

        ladder[home]["P"] += 1
        ladder[away]["P"] += 1
        ladder[home]["F"] += hg
        ladder[home]["A"] += ag
        ladder[away]["F"] += ag
        ladder[away]["A"] += hg

        if hg > ag:
            ladder[home]["W"] += 1
            ladder[away]["L"] += 1
            ladder[home]["PTS"] += 3
        elif hg < ag:
            ladder[away]["W"] += 1
            ladder[home]["L"] += 1
            ladder[away]["PTS"] += 3
        else:
            ladder[home]["D"] += 1
            ladder[away]["D"] += 1
            ladder[home]["PTS"] += 1
            ladder[away]["PTS"] += 1

    if not ladder:
        return [], [], [], "No completed league results available yet."

    df_ladder = pd.DataFrame.from_dict(ladder, orient="index")
    df_ladder["GD"] = df_ladder["F"] - df_ladder["A"]
    df_ladder["Team"] = df_ladder.index
    df_ladder = df_ladder[["Team", "P", "W", "D", "L", "F", "A", "GD", "PTS"]]
    df_ladder = df_ladder.sort_values(
        by=["PTS", "GD", "F"],
        ascending=[False, False, False]
    ).reset_index(drop=True)

    data = df_ladder.to_dict("records")
    columns = [{"name": col, "id": col} for col in df_ladder.columns]

    team_colors = {
        "Tuggeranong": "green",
        "Croatia": "crimson",
        "Olympic": "navy",
        "Gungahlin": "#FF1493",
        "Majura": "royalblue",
        "ANU": "orange",
        "Wanderers": "firebrick",
        "Belconnen": "skyblue",
        "Belconnen Reserves": "skyblue",
        "TuggeranongRes": "green",
        "CroatiaRes": "crimson",
        "OlympicRes": "navy",
        "MajuraRes": "royalblue",
        "ANURes": "orange",
        "WanderersRes": "firebrick",
        "Belconnen": "skyblue",
        "BelReserves": "skyblue",
    }

    style_data_conditional = [
        {
            "if": {"row_index": "odd"},
            "backgroundColor": "#303332",
        }
    ]

    for team, color in team_colors.items():
        style_data_conditional.append({
            "if": {"filter_query": f'{{Team}} = "{team}"'},
            "backgroundColor": color,
            "color": "white" if color not in ["skyblue", "orange", "yellow"] else "black",
        })

    return data, columns, style_data_conditional, ""


# The routing callback for the tabs up top of chart
@callback(
    Output("main-content", "children"),
    Input("main-tabs", "value"),
)
def render_tab(selected_tab):
    if selected_tab == "team-tab":
        return team_insights_layout

    if selected_tab == "player-tab":
        return player_insights_layout

    if selected_tab == "opponent-tab":
        return opponent_insights_layout

    # Fallback (if somehow none match)
    return team_insights_layout



# collapsible callbacks


# --- Goals Scored collapse ---
from dash import callback, Output, Input, State

# --- Toggle Goals Scored section ---
@callback(
    Output("collapse-gs", "is_open"),
    Output("gs-arrow", "children"),
    Input("toggle-gs", "n_clicks"),
    State("collapse-gs", "is_open"),
    prevent_initial_call=True,
)
def toggle_gs_section(n_clicks, is_open):
    # Flip open/closed
    new_open = not is_open
    new_arrow = "▼" if new_open else "►"
    return new_open, new_arrow


# --- Toggle Goals Conceded section ---
@callback(
    Output("collapse-gc", "is_open"),
    Output("gc-arrow", "children"),
    Input("toggle-gc", "n_clicks"),
    State("collapse-gc", "is_open"),
    prevent_initial_call=True,
)
def toggle_gc_section(n_clicks, is_open):
    new_open = not is_open
    new_arrow = "▼" if new_open else "►"
    return new_open, new_arrow


# --- Toggle Context section ---
@callback(
    Output("collapse-context", "is_open"),
    Output("context-arrow", "children"),
    Input("toggle-context", "n_clicks"),
    State("collapse-context", "is_open"),
    prevent_initial_call=True,
)
def toggle_context_section(n_clicks, is_open):
    new_open = not is_open
    new_arrow = "▼" if new_open else "►"
    return new_open, new_arrow




# callback for goal location map (FOCUS TEAM – Team Insights tab)
@app.callback(
    Output("goal-map-figure", "figure"),
    [
        Input("team-select", "value"),      # NEW
        Input("goalmap-opponent-filter", "value"),
        Input("goalmap-type-filter", "value"),
    ],
)
def update_goal_map(selected_squad, selected_opponent, goal_filter):

    selected_team = TEAM_MAP.get(selected_squad, FOCUS_TEAM)

    return build_focus_team_goal_map(
        league_goal_data,
        selected_team,
        selected_opponent,
        goal_filter,
    )





# Callback for 5-min-window response (no inputs – always FOCUS_TEAM from league_goal_data)
@callback(
    Output("five-min-response-bar", "figure"),
    Output("five-min-last4-status", "children"),
    Input("team-select", "value"),
    Input("five-min-opponent-selector", "value"),
    Input("five-min-last4-button", "n_clicks"),
)
def update_five_min_response_chart(selected_squad, selected_opponent, n_clicks):
    selected_team = TEAM_MAP.get(selected_squad, FOCUS_TEAM)
    is_last4 = bool(n_clicks and n_clicks % 2 == 1)

    # Start from full league data
    df = league_goal_data.copy()

    # 🔍 DEBUG 1: before any filters
    #print("DEBUG – initial df rows:", len(df))

    # Restrict to Olyroos fixtures
    df = df[
        (df["Home Team"] == selected_team) |
        (df["Away Team"] == selected_team)
    ].copy()

    #print("DEBUG – after FOCUS_TEAM filter:", len(df), "rows")

    # Opponent filter (skip when "ALL")
    if selected_opponent and selected_opponent != "ALL":
        df = df[
            ((df["Home Team"] == selected_team) & (df["Away Team"] == selected_opponent)) |
            ((df["Away Team"] == selected_team) & (df["Home Team"] == selected_opponent))

        ].copy()

    #print("DEBUG – after opponent filter:", len(df), "rows; selected_opponent =", selected_opponent)

    status_text = ""

    # Last 4 rounds filter
    if is_last4:
        df_oly = league_goal_data[
            (league_goal_data["Home Team"] == selected_team) |
            (league_goal_data["Away Team"] == selected_team)
        ].copy()

        all_dates = pd.to_datetime(df_oly["Match Date"], errors="coerce").dropna().unique()
        all_dates = sorted(all_dates)

        if all_dates:
            last4_dates = all_dates[-4:] if len(all_dates) >= 4 else all_dates
            df["Match Date Parsed"] = pd.to_datetime(df["Match Date"], errors="coerce")
            df = df[df["Match Date Parsed"].isin(last4_dates)].copy()
            status_text = "SHOWING : Last 4 rounds"

    #print("DEBUG – after last4 filter:", len(df), "rows; is_last4 =", is_last4)

    #metrics_df = build_five_min_response_df(df)
    metrics_df = build_five_min_response_df_for_team(df, selected_team)


    #print("DEBUG – metrics_df rows:", len(metrics_df))

    fig = go.Figure()

    opp_suffix = "" if selected_opponent in (None, "ALL") else f" vs {selected_opponent}"
    mode_suffix = " – Last 4 Rounds" if is_last4 else ""

    if metrics_df.empty:
        fig.update_layout(
            title=f"{selected_team} – 5-Minute Response After Goals{opp_suffix}{mode_suffix} (No Data)",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
            xaxis_title="Situation",
            yaxis_title="Percentage of Windows (%)",
        )
        return fig, status_text

    legend_labels = {
        "Scored again within 5 mins": "Scored again",
        "Conceded within 5 mins": "Conceded",
        "Scored within 5 mins": "Scored",
        "Conceded again within 5 mins": "Conceded again",
    }

    outcome_order = [
        "Scored again within 5 mins",
        "Conceded within 5 mins",
        "Scored within 5 mins",
        "Conceded again within 5 mins",
    ]

    for outcome in outcome_order:
        if outcome not in metrics_df["Outcome"].unique():
            continue

        subset = metrics_df[metrics_df["Outcome"] == outcome]

        fig.add_trace(go.Bar(
            name=legend_labels.get(outcome, outcome),
            x=subset["Situation"],
            y=subset["Pct"],
            text=subset["Count"],
            textposition="outside",
            hovertemplate=(
                "Situation: %{x}<br>"
                f"Outcome: {outcome}<br>"
                "Count: %{customdata[0]} of %{customdata[1]} windows<br>"
                "Percentage: %{y:.1f}%<extra></extra>"
            ),
            customdata=subset[["Count", "Base"]].values,
        ))

    fig.update_layout(
        barmode="group",
        title=f"{selected_team} – 5-Minute Response After Goals{opp_suffix}{mode_suffix}",
        plot_bgcolor="black",
        paper_bgcolor="black",
        font=dict(color="white", family="Segoe UI"),
        xaxis_title="Situation",
        yaxis_title="Percentage of Windows (%)",
        yaxis=dict(
            showgrid=False,
            #showgrid=True,
            #gridcolor="#333333",
            zeroline=False,
        ),
        yaxis_tickformat=".0f",
        legend_title="Outcome",
        hoverlabel=dict(font=dict(family="Segoe UI")),
        margin=dict(t=40, b=40),
    )

    return fig, status_text



# callback for 5-min-window-response - STACKED by team
@callback(
    Output("five-min-response-opponent-bar", "figure"),
    Input("team-select", "value"),
    Input("five-min-last4-button", "n_clicks"),
)
def update_five_min_response_by_opponent_chart(selected_squad, n_clicks):
    selected_team = TEAM_MAP.get(selected_squad, FOCUS_TEAM)


    df = build_five_min_response_by_opponent(league_goal_data, selected_team)

    if df.empty:
        fig = go.Figure()
        fig.update_layout(
            title=f"{selected_team} – 5-Minute Response by Opponent (No Data)",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
            xaxis_title="Situation + Response",
            yaxis_title="Number of 5-Minute Response Events",
        )
        return fig

    # ---- Map outcomes to short labels for consistency ----
    def map_outcome_short(row):
        if row["Situation"] == "After Scoring":
            if "Scored again" in row["Outcome"]:
                return "Scored again"
            else:
                return "Conceded"
        else:  # After Conceding
            if "Scored within" in row["Outcome"]:
                return "Scored"
            else:
                return "Conceded"

    df["OutcomeShort"] = df.apply(map_outcome_short, axis=1)

    # Normalise opponent names for colours
    df["OpponentTeamNorm"] = df["OpponentTeam"].apply(normalize_club)

    # Fixed combo order (logical left→right)
    combo_order = [
        ("After Scoring", "Scored again"),
        ("After Scoring", "Conceded"),
        ("After Conceding", "Scored"),
        ("After Conceding", "Conceded"),
    ]

    # Label for each situation+outcome on the x-axis
    label_map = {
        ("After Scoring", "Scored again"): "AS – Scored",
        ("After Scoring", "Conceded"): "AS – Conceded",
        ("After Conceding", "Scored"): "AC – Scored",
        ("After Conceding", "Conceded"): "AC – Conceded",
    }

    
    spacer_label = " "  # used as a visual gap between AS and AC blocks

    fig = go.Figure()
    seen_opponents = set()

    for situation, outcome_short in combo_order:
        x_label = label_map[(situation, outcome_short)]
        combo_df = df[
            (df["Situation"] == situation) &
            (df["OutcomeShort"] == outcome_short)
        ]

        if combo_df.empty:
            # Force an empty category with a transparent bar
            fig.add_trace(go.Bar(
                name="(no events)",
                x=[x_label],
                y=[0.0001],
                marker_color="rgba(0,0,0,0)",
                showlegend=False,
                hoverinfo="skip"
            ))
            continue

        #x_label = label_map[(situation, outcome_short)]

        for opp in combo_df["OpponentTeam"].unique():
            sub = combo_df[combo_df["OpponentTeam"] == opp]

            total_count = int(sub["Count"].sum())

            match_lists = sub["Matches"].tolist()
            flat = sorted(set(chain.from_iterable(
                m if isinstance(m, list) else [m] for m in match_lists
            )))
            matches_str = ", ".join(str(m) for m in flat) if flat else "–"

            opp_norm = normalize_club(opp)
            color = TEAM_COLORS.get(opp_norm, DEFAULT_COLOR)

            fig.add_trace(go.Bar(
                name=opp,
                x=[x_label],  # situation + response as the x-category
                y=[total_count],
                marker_color=color,
                legendgroup=opp,
                showlegend=(opp not in seen_opponents),
                customdata=[[matches_str]],
                hovertemplate=(
                    "Situation: " + situation + "<br>"
                    "Outcome: " + outcome_short + "<br>"
                    "Team involved: " + opp + "<br>"
                    "Events: %{y}<br>"
                    "Matches: %{customdata[0]}<extra></extra>"
                )
            ))

            seen_opponents.add(opp)

    # Add a transparent spacer bar so the gap category always exists
    fig.add_trace(go.Bar(
        name="spacer",
        x=[spacer_label],
        y=[0.0001],
        marker_color="rgba(0,0,0,0)",
        showlegend=False,
        hoverinfo="skip",
    ))

    fig.update_layout(
        barmode="stack",  # stacks by opponent within each situation+response category
        title=f"{selected_team} – 5-Minute Response by Opponent",
        plot_bgcolor="black",
        paper_bgcolor="black",
        font=dict(color="white", family="Segoe UI"),
        xaxis_title="Situation + Response",
        yaxis_title="Number of 5-Minute Response Events",
        yaxis=dict(
            showgrid=False,
            #showgrid=True,
            #gridcolor="#333333",
            zeroline=False
        ),
        yaxis_tickformat=".0f",
        legend_title="Opponent",
        margin=dict(t=40, b=40),
        hoverlabel=dict(font=dict(family="Segoe UI"))
    )

    # Enforce logical left→right order with a visual gap in the middle
    fig.update_xaxes(
        categoryorder="array",
        categoryarray=[
            "AS – Scored",
            "AS – Conceded",
            spacer_label,
            "AC – Scored",
            "AC – Conceded",
        ]
    )

    return fig




#callback for first goal value index
@callback(
    Output("first-goal-index-bar", "figure"),
    Output("first-goal-last4-status", "children"),
    Input("team-select", "value"),
    Input("first-goal-last4-button", "n_clicks"),
)
def update_first_goal_index_chart(selected_squad, n_clicks):
    selected_team = TEAM_MAP.get(selected_squad, FOCUS_TEAM)
    is_last4 = bool(n_clicks and n_clicks % 2 == 1)

    df = league_goal_data.copy()

    # Filter to Olyroos matches
    df = df[
        (df["Home Team"] == selected_team) |
        (df["Away Team"] == selected_team)
    ].copy()

    status_text = ""

    # ---- Last 4 rounds filter (Olyroos fixtures) ----
    if is_last4:
        df_oly = df.copy()
        all_dates = pd.to_datetime(df_oly["Match Date"], errors="coerce").dropna().unique()
        all_dates = sorted(all_dates)

        if all_dates:
            last4_dates = all_dates[-4:] if len(all_dates) >= 4 else all_dates
            df["Match Date Parsed"] = pd.to_datetime(df["Match Date"], errors="coerce")
            df = df[df["Match Date Parsed"].isin(last4_dates)].copy()
            status_text = f"Last 4 rounds ({selected_team} fixtures)"

    long_df = build_first_goal_value_long(df, selected_team)

    fig = go.Figure()

    if long_df.empty:
        fig.update_layout(
            title=f"{selected_team} – First Goal Value Index (No Data)",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
        )
        return fig, status_text

    # We want codes in this order with a gap between SF-* and CF-*
    code_order = ["SF-W", "SF-D", "SF-L", "CF-W", "CF-D", "CF-L"]
    # Numeric positions to force a visual gap: 0,1,2, 4,5,6
    code_to_x = {
        "SF-W": 0,
        "SF-D": 1,
        "SF-L": 2,
        "CF-W": 4,
        "CF-D": 5,
        "CF-L": 6
    }

    # Build lookup for hover meta per Code
    outcome_summary = (
        long_df.groupby(["Code", "Scenario"])
        .agg(
            ScenarioBase=("ScenarioBase", "max"),
            OutcomeTotal=("OutcomeTotal", "max"),
            OutcomePct=("OutcomePct", "max")
        )
        .reset_index()
    )
    summary_lookup = {
        row["Code"]: {
            "ScenarioBase": row["ScenarioBase"],
            "OutcomeTotal": row["OutcomeTotal"],
            "OutcomePct": row["OutcomePct"],
        }
        for _, row in outcome_summary.iterrows()
    }

    # Each trace = one opponent, stacked across the 6 codes
    for opp in sorted(long_df["OpponentTeam"].unique()):
        sub = long_df[long_df["OpponentTeam"] == opp].copy()
        sub["x_pos"] = sub["Code"].map(code_to_x)

        x_vals = []
        y_vals = []
        custom = []

        for code in code_order:
            code_rows = sub[sub["Code"] == code]
            if not code_rows.empty:
                # One slice per (Code, OpponentTeam)
                slice_count = int(code_rows["SliceCount"].sum())
                match_ids_str = code_rows["MatchIDs"].iloc[0]
                meta = summary_lookup.get(code, {
                    "ScenarioBase": 0,
                    "OutcomeTotal": 0,
                    "OutcomePct": 0.0
                })
                scenario_base = int(meta["ScenarioBase"])
                outcome_total = int(meta["OutcomeTotal"])
                outcome_pct = float(meta["OutcomePct"])
            else:
                slice_count = 0
                match_ids_str = ""
                meta = summary_lookup.get(code, {
                    "ScenarioBase": 0,
                    "OutcomeTotal": 0,
                    "OutcomePct": 0.0
                })
                scenario_base = int(meta["ScenarioBase"])
                outcome_total = int(meta["OutcomeTotal"])
                outcome_pct = float(meta["OutcomePct"])

            x_vals.append(code_to_x[code])
            y_vals.append(slice_count)
            custom.append([code, scenario_base, outcome_total, outcome_pct, match_ids_str])

        fig.add_trace(go.Bar(
            name=opp,
            x=x_vals,
            y=y_vals,
            marker_color=TEAM_COLORS.get(str(opp).strip(), "gray"),
            customdata=custom,
            hovertemplate=(
                "Scenario/Result: %{customdata[0]}<br>"
                "Total matches in scenario: %{customdata[1]}<br>"
                "Matches in this result: %{customdata[2]}<br>"
                "% of this scenario: %{customdata[3]:.1f}%<br>"
                "Matches: %{customdata[4]}<extra></extra>"
            )
        ))

    # X-axis ticks and labels with gap between SF-* and CF-*
    tickvals = [0, 1, 2, 4, 5, 6]
    ticktext = ["SF–W", "SF–D", "SF–L", "CF–W", "CF–D", "CF–L"]

    fig.update_layout(
        barmode="stack",
        title=f"{selected_team} – First Goal Value Index",
        plot_bgcolor="black",
        paper_bgcolor="black",
        font=dict(color="white", family="Segoe UI"),
        xaxis=dict(
            title="SF = Scored First, CF = Conceded First",
            tickmode="array",
            tickvals=tickvals,
            ticktext=ticktext,
            showgrid=False,
            zeroline=False,
        ),
        yaxis=dict(
            title="Number of Matches",
            showgrid=False,
            #showgrid=True,
            #gridcolor="#333333",
            zeroline=False,
            tickformat=".0f",
        ),
        legend_title="Opponent",
        hoverlabel=dict(font=dict(family="Segoe UI")),
        margin=dict(t=40, b=40),
    )

    return fig, status_text



# Callback to update Goals Per Minute chart
@callback(
    Output("goals-per-minute", "figure"),
    [
        Input("team-select", "value"),
        Input("sort-high-goals", "n_clicks"),
        Input("sort-low-goals", "n_clicks"),
        Input("sort-total-goals", "n_clicks"),
    ]
)
def update_goals_chart(selected_squad, high_clicks, low_clicks, total_clicks):

    # -------------------------
    # Minutes (FOCUS_TEAM only)
    # -------------------------
    selected_team = TEAM_MAP.get(selected_squad, FOCUS_TEAM)
    minutes_df = player_data.copy()

    # Prefer Team if it exists, otherwise fall back to Country (your current schema)
    if "Team" in minutes_df.columns:
        minutes_df = minutes_df[minutes_df["Team"] == selected_squad].copy()
    elif "Country" in minutes_df.columns:
        minutes_df = minutes_df[minutes_df["Country"] == selected_team].copy()


    minutes_df["Mins Played"] = pd.to_numeric(minutes_df.get("Mins Played"), errors="coerce")
    minutes_df = minutes_df.dropna(subset=["Mins Played"])

    # -------------------------
    # Goals (league_goal_data)
    # -------------------------
    goals_df = league_goal_data.copy()

    # Only goals scored by FOCUS_TEAM (league schema: Scorer Team)
    if "Scorer Team" in goals_df.columns:
        goals_df = goals_df[goals_df["Scorer Team"] == selected_team].copy()

    # Exclude OG safely
    if "Scorer" in goals_df.columns:
        goals_df["Scorer"] = goals_df["Scorer"].fillna("").astype(str)
        goals_df = goals_df[goals_df["Scorer"].str.upper() != "OG"].copy()
    else:
        goals_df["Scorer"] = ""

    # -------------------------
    # Per-player goal context
    # -------------------------
    def summarise_finish_type(s):
        s_clean = s.dropna()
        if s_clean.empty:
            return "No data"
        counts = s_clean.value_counts()
        parts = []
        for val, cnt in counts.items():
            label = str(val)
            lower = label.lower()
            if lower.startswith("left"):
                label = "L"
            elif lower.startswith("right"):
                label = "R"
            elif "head" in lower:
                label = "H"
            parts.append(f"{cnt}-{label}")
        return ", ".join(parts)

    def summarise_ftf(s):
        s_clean = s.dropna().astype(str).str.strip().str.lower()
        if s_clean.empty:
            return "No data"
        total = len(s_clean)
        yes_count = s_clean.isin(["yes", "y", "1", "true"]).sum()
        return f"{yes_count} out of {total}"

    def summarise_minutes(s):
        s_clean = s.dropna()
        if s_clean.empty:
            return "No data"
        try:
            vals = sorted(int(v) for v in s_clean)
        except Exception:
            vals = list(s_clean)
        return ", ".join(str(v) for v in vals)

    extra_context = pd.DataFrame(columns=["Player Name", "Finish Summary", "FTF Summary", "Minutes Summary"])
    needed_cols = ["Finish Type", "First-time finish", "Minute Scored", "Scorer"]
    if not goals_df.empty and all(c in goals_df.columns for c in needed_cols):
        extra_context = (
            goals_df
            .groupby("Scorer")
            .agg({
                "Finish Type": summarise_finish_type,
                "First-time finish": summarise_ftf,
                "Minute Scored": summarise_minutes,
            })
            .reset_index()
            .rename(columns={
                "Scorer": "Player Name",
                "Finish Type": "Finish Summary",
                "First-time finish": "FTF Summary",
                "Minute Scored": "Minutes Summary",
            })
        )

    # -------------------------
    # Totals + merge
    # -------------------------
    goals_count = goals_df["Scorer"].value_counts().reset_index()
    goals_count.columns = ["Player Name", "Goals"]

    mins_grouped = minutes_df.groupby("Player Name", as_index=False)["Mins Played"].sum()

    merged_df = pd.merge(mins_grouped, goals_count, on="Player Name", how="left").fillna(0)
    merged_df["Goals"] = merged_df["Goals"].astype(int)
    merged_df = merged_df[merged_df["Goals"] > 0].copy()

    merged_df["Goals Per Minute"] = merged_df.apply(
        lambda r: (r["Mins Played"] / r["Goals"]) if r["Goals"] > 0 else 0, axis=1
    )
    merged_df["Actual Goals Per Minute"] = merged_df["Goals Per Minute"]
    merged_df["Display Goals Per Minute"] = np.ceil(merged_df["Goals Per Minute"]).clip(upper=270)

    merged_df = merged_df.merge(extra_context, on="Player Name", how="left")
    for col in ["Finish Summary", "FTF Summary", "Minutes Summary"]:
        if col not in merged_df.columns:
            merged_df[col] = "No data"
        merged_df[col] = merged_df[col].fillna("No data")

    # -------------------------
    # View mode + sorting
    # -------------------------
    trig = ctx.triggered_id
    view_mode = "gpm" if trig != "sort-total-goals" else "goals"

    if view_mode == "goals":
        merged_df = merged_df.sort_values("Goals", ascending=False)
    elif trig == "sort-low-goals":
        merged_df = merged_df.sort_values("Goals Per Minute", ascending=False)
    else:
        merged_df = merged_df.sort_values("Goals Per Minute", ascending=True)

    # -------------------------
    # Figure
    # -------------------------
    if view_mode == "goals":
        goals_df2 = goals_df.copy()

        # Keep only goals from matches involving FOCUS_TEAM (home/away)
        if "Home Team" in goals_df2.columns and "Away Team" in goals_df2.columns:
            goals_df2 = goals_df2[
                (goals_df2["Home Team"] == selected_team) | (goals_df2["Away Team"] == selected_team)
            ].copy()

            goals_df2["Opponent"] = np.where(
                goals_df2["Home Team"] == selected_team,
                goals_df2["Away Team"],
                goals_df2["Home Team"],
            )
        else:
            goals_df2["Opponent"] = "Unknown"

        goals_df2["Opponent"] = goals_df2["Opponent"].apply(normalize_club)

        by_opp = (
            goals_df2.groupby(["Scorer", "Opponent"])
                     .size()
                     .reset_index(name="Goals")
                     .rename(columns={"Scorer": "Player Name"})
        )
        by_opp = by_opp[by_opp["Player Name"].isin(merged_df["Player Name"])]

        fig = go.Figure()
        for opp in sorted(by_opp["Opponent"].dropna().unique()):
            sub = by_opp[by_opp["Opponent"] == opp]
            fig.add_trace(go.Bar(
                x=sub["Player Name"],
                y=sub["Goals"],
                name=opp,
                marker_color=TEAM_COLORS.get(opp, "gray"),
                text=sub["Goals"],
                textposition="outside",
                hovertemplate=(
                    "Player: %{x}<br>"
                    f"Opponent: {opp}<br>"
                    "Goals vs Opp: %{y}<extra></extra>"
                ),
            ))

        fig.update_yaxes(
            title="Goals",
            tick0=0,
            dtick=5,
            rangemode="tozero",
            autorange=True,
            showgrid=False,
            zeroline=True,
            zerolinecolor="#555",
        )
        fig.update_traces(cliponaxis=False)
        fig.update_layout(
            barmode="stack",
            title="Goals by Opponent (click legend to filter)",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(size=16, family="Segoe UI", color="white"),
            xaxis=dict(
                tickfont=dict(size=14),
                categoryorder="array",
                categoryarray=list(merged_df["Player Name"]),
                showgrid=False,
            ),
            yaxis=dict(tickfont=dict(size=14)),
            bargap=0.0,
            bargroupgap=0.1,
            hoverlabel=dict(font=dict(family="Segoe UI")),
        )

    else:
        customdata = merged_df[
            ["Goals", "Mins Played", "Display Goals Per Minute", "Finish Summary", "FTF Summary", "Minutes Summary"]
        ].values

        fig = px.bar(
            merged_df,
            x="Player Name",
            y="Display Goals Per Minute",
            color_discrete_sequence=["#77BCE8"],
            title="Minutes per Goal (rounded up, capped at 270)",
            template="plotly_dark",
            text="Goals",
        )
        fig.update_traces(
            textposition="outside",
            marker_line_width=0,
            customdata=customdata,
            hovertemplate=(
                "Player: %{x}<br>"
                "Goals: %{customdata[0]}<br>"
                "Mins Played: %{customdata[1]:.0f}<br>"
                "Mins per Goal: %{customdata[2]:.0f}<br>"
                "Finish Type: %{customdata[3]}<br>"
                "First-time finish: %{customdata[4]}<br>"
                "Minutes scored: %{customdata[5]}<extra></extra>"
            ),
        )
        fig.update_layout(
            yaxis_title="Minutes per Goal",
            uniformtext_minsize=10,
            uniformtext_mode="hide",
            bargap=0.0,
            bargroupgap=0.1,
            font=dict(size=16, family="Segoe UI", color="white"),
            xaxis=dict(
                tickfont=dict(size=14),
                showgrid=False),
            yaxis=dict(
                tickfont=dict(size=14),
                showgrid=False),
            hoverlabel=dict(font=dict(family="Segoe UI")),
            plot_bgcolor="black",
            paper_bgcolor="black",
        )

    return fig


#callback for assists per minute chart
@callback(
    Output("assists-per-minute", "figure"),
    [
        Input("team-select", "value"),
        Input("sort-high-assists", "n_clicks"),
        Input("sort-low-assists", "n_clicks"),
        Input("sort-total-assists", "n_clicks"),
    ]
)
def update_assists_chart(selected_squad, high_clicks, low_clicks, total_clicks):
    # -------------------------
    # Minutes (FOCUS_TEAM only)
    # -------------------------
    selected_team = TEAM_MAP.get(selected_squad, FOCUS_TEAM)
    minutes_df = player_data.copy()
    

    minutes_df["Player Name"] = minutes_df["Player Name"].astype(str).str.strip()


    # Prefer Team if it exists, otherwise fall back to Country (your current schema)
    if "Team" in minutes_df.columns:
        minutes_df = minutes_df[minutes_df["Team"] == selected_squad].copy()
    elif "Country" in minutes_df.columns:
        minutes_df = minutes_df[minutes_df["Country"] == selected_team].copy()



    minutes_df["Mins Played"] = pd.to_numeric(minutes_df.get("Mins Played"), errors="coerce")
    minutes_df = minutes_df.dropna(subset=["Mins Played"])

    minutes_summary = minutes_df.groupby("Player Name", as_index=False)["Mins Played"].sum()

    # -------------------------
    # Goal events (assists live here)
    # league schema: Assist + Scorer Team + Home/Away
    # -------------------------
    events = league_goal_data.copy()

    events["Scorer"] = events["Scorer"].fillna("").astype(str).str.strip()

    assist_col = "Assists" if "Assists" in events.columns else ("Assist" if "Assist" in events.columns else None)
    if assist_col:
        events[assist_col] = events[assist_col].fillna("").astype(str).str.strip()


    # Only goals scored by FOCUS_TEAM (so assists are assists FOR the team)
    if "Scorer Team" in events.columns:
        events = events[events["Scorer Team"] == selected_team].copy()

    # Keep only events from matches involving FOCUS_TEAM (home/away)
    if "Home Team" in events.columns and "Away Team" in events.columns:
        events = events[
            (events["Home Team"] == selected_team) | (events["Away Team"] == selected_team)
        ].copy()

        # Derive Opponent from fixture
        events["Opponent"] = np.where(
            events["Home Team"] == selected_team,
            events["Away Team"],
            events["Home Team"]
        )
    else:
        events["Opponent"] = "Unknown"

    # Optional: normalise opponent names
    events["Opponent"] = events["Opponent"].apply(normalize_club)

    # -------------------------
    # Assists column naming (league-based uses "Assist")
    # -------------------------
    assist_col = "Assists" if "Assists" in events.columns else ("Assist" if "Assist" in events.columns else None)
    if assist_col is None:
        # No assist data available -> return empty figure
        fig = go.Figure()
        fig.update_layout(
            title="Assists Per Minute (No assist column found)",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI", size=16),
            xaxis_title="Player Name",
            yaxis_title="Minutes per Assist",
        )
        return fig

    # -------------------------
    # Count assists per player (overall)
    # -------------------------
    assists_series = events[assist_col].fillna("").astype(str).str.strip()
    assists_series = assists_series[assists_series.str.len() > 0]
    assist_counts = assists_series.value_counts().reset_index()
    assist_counts.columns = ["Player Name", "Assists"]

    # -------------------------
    # Assist type summary (optional)
    # -------------------------
    def summarise_assist_type(s):
        s_clean = s.dropna().astype(str).str.strip()
        if s_clean.empty:
            return "No data"
        counts = s_clean.value_counts()
        parts = [f"{cnt}-{atype}" for atype, cnt in counts.items()]
        return ", ".join(parts)

    assist_type_summary = pd.DataFrame(columns=["Player Name", "Assist Type Summary"])
    if "Assist type" in events.columns:
        assist_type_summary = (
            events.assign(Assist_Player=events[assist_col].fillna("").astype(str).str.strip())
                  .query("Assist_Player != ''")
                  .groupby("Assist_Player")["Assist type"]
                  .apply(summarise_assist_type)
                  .reset_index()
                  .rename(columns={
                      "Assist_Player": "Player Name",
                      "Assist type": "Assist Type Summary"
                  })
        )

    # -------------------------
    # Merge totals (players with >0 assists only)
    # -------------------------
    merged = pd.merge(assist_counts, minutes_summary, on="Player Name", how="left").fillna(0)
    merged = merged[merged["Assists"] > 0].copy()

    merged = merged.merge(assist_type_summary, on="Player Name", how="left")
    if "Assist Type Summary" not in merged.columns:
        merged["Assist Type Summary"] = "No data"
    merged["Assist Type Summary"] = merged["Assist Type Summary"].fillna("No data")

    # Assists per minute (raw + display)
    merged["Assists Per Minute"] = merged.apply(
        lambda r: (r["Mins Played"] / r["Assists"]) if r["Assists"] > 0 else 0, axis=1
    )
    merged["Actual Assists Per Minute"] = merged["Assists Per Minute"]
    merged["Display Assists Per Minute"] = np.ceil(merged["Assists Per Minute"]).clip(upper=270)

    # Which button?
    trig = ctx.triggered_id or "sort-high-assists"
    view_mode = "per_minute"
    if trig == "sort-total-assists":
        view_mode = "assists"

    # Sorting
    if view_mode == "assists":
        merged = merged.sort_values(by="Assists", ascending=False)
    elif trig == "sort-low-assists":
        merged = merged.sort_values(by="Assists Per Minute", ascending=False)
    else:
        merged = merged.sort_values(by="Assists Per Minute", ascending=True)

    # -------------------------
    # Build figure
    # -------------------------
    if view_mode == "assists":
        ev_assists = events.copy()
        ev_assists["Assist_Player"] = ev_assists[assist_col].fillna("").astype(str).str.strip()
        ev_assists = ev_assists[ev_assists["Assist_Player"].str.len() > 0]

        by_opp = (
            ev_assists.groupby(["Assist_Player", "Opponent"])
                      .size()
                      .reset_index(name="Assists")
                      .rename(columns={"Assist_Player": "Player Name"})
        )

        by_opp = by_opp[by_opp["Player Name"].isin(merged["Player Name"])]
        x_order = list(merged["Player Name"])

        fig = go.Figure()
        for opp in sorted(by_opp["Opponent"].dropna().unique()):
            sub = by_opp[by_opp["Opponent"] == opp]
            fig.add_trace(go.Bar(
                x=sub["Player Name"],
                y=sub["Assists"],
                name=opp,
                marker_color=TEAM_COLORS.get(opp, "gray"),
                text=sub["Assists"],
                textposition="outside",
                hovertemplate=(
                    "Player: %{x}<br>"
                    f"Opponent: {opp}<br>"
                    "Assists vs Opp: %{y}<extra></extra>"
                ),
            ))

        fig.update_yaxes(
            title="Assists",
            tick0=0,
            dtick=5,
            rangemode="tozero",
            autorange=True,
            showgrid=True,
            gridcolor="#333",
            zeroline=True,
            zerolinecolor="#555"
        )
        fig.update_traces(cliponaxis=False)
        fig.update_layout(
            barmode="stack",
            title="Assists by Opponent (click legend to filter)",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI", size=16),
            xaxis=dict(
                showgrid=False,
                tickfont=dict(size=14),
                tickangle=-30,
                categoryorder="array",
                categoryarray=x_order
            ),
            yaxis=dict(tickfont=dict(size=14)),
            bargap=0.0,
            bargroupgap=0.1,
            margin=dict(t=40, b=60),
            hoverlabel=dict(font=dict(family="Segoe UI"))
        )

    else:
        x_order = list(merged["Player Name"])
        customdata = merged[[
            "Assists",
            "Mins Played",
            "Display Assists Per Minute",
            "Assist Type Summary",
        ]].values

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=merged["Player Name"],
            y=merged["Display Assists Per Minute"],
            marker_color="#F9DD65",
            width=0.8,
            customdata=customdata,
            text=merged["Assists"],
            textposition="outside",
            hovertemplate=(
                "Player: %{x}<br>"
                "Assists: %{customdata[0]}<br>"
                "Mins Played: %{customdata[1]:.0f}<br>"
                "Mins per Assist: %{customdata[2]:.0f}<br>"
                "Assist types: %{customdata[3]}<extra></extra>"
            )
        ))

        fig.update_yaxes(
            title="Minutes per Assist",
            tick0=0,
            dtick=100,
            rangemode="tozero",
            showgrid=True,
            gridcolor="#333",
            zeroline=True,
            zerolinecolor="#555"
        )
        fig.update_layout(
            title="Assists Per Minute (rounded up, capped 270 mins)",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI", size=16),
            xaxis_title="Player Name",
            xaxis=dict(
                showgrid=False,
                tickfont=dict(size=14),
                tickangle=-30,
                categoryorder="array",
                categoryarray=x_order
            ),
            yaxis=dict(tickfont=dict(size=14)),
            bargap=0.0,
            bargroupgap=0.1,
            margin=dict(t=40, b=60),
            hoverlabel=dict(font=dict(family="Segoe UI"))
        )

    return fig



# Callback to update Goal Contributions Per Minute chart
@callback(
    Output("goal-contributions", "figure"),
    [
        Input("team-select", "value"),
        Input("sort-high-contrib", "n_clicks"),
        Input("sort-low-contrib", "n_clicks"),
        Input("sort-total-contrib", "n_clicks"),
    ]
)
def update_contributions_chart(selected_squad, high_clicks, low_clicks, total_clicks):

    # -------------------------
    # Minutes
    # -------------------------
    selected_team = TEAM_MAP.get(selected_squad, FOCUS_TEAM)
    minutes_df = player_data.copy()
    minutes_df["Player Name"] = minutes_df["Player Name"].astype(str).str.strip()

    if "Team" in minutes_df.columns:
        minutes_df = minutes_df[minutes_df["Team"] == selected_squad].copy()
    elif "Country" in minutes_df.columns:
        minutes_df = minutes_df[minutes_df["Country"] == selected_team].copy()

    minutes_df["Mins Played"] = pd.to_numeric(minutes_df["Mins Played"], errors="coerce")
    minutes_summary = minutes_df.groupby("Player Name", as_index=False)["Mins Played"].sum()

    # -------------------------
    # Goal events (league-based)
    # -------------------------
    events = league_goal_data.copy()

    events["Scorer"] = events["Scorer"].fillna("").astype(str).str.strip()

    # Only goals scored BY selected team
    events = events[events["Scorer Team"] == selected_team].copy()

    # Only matches involving selected team
    events = events[
        (events["Home Team"] == selected_team) | (events["Away Team"] == selected_team)
    ].copy()

    # Derive opponent
    events["Opponent"] = np.where(
        events["Home Team"] == selected_team,
        events["Away Team"],
        events["Home Team"]
    )
    events["Opponent"] = events["Opponent"].apply(normalize_club)

    # -------------------------
    # Goals
    # -------------------------
    goals_only = events[events["Scorer"].str.upper().ne("OG")].copy()
    goals_counts = goals_only["Scorer"].value_counts().reset_index()
    goals_counts.columns = ["Player Name", "Goals"]
    goals_counts["Player Name"] = goals_counts["Player Name"].astype(str).str.strip()

    # -------------------------
    # Assists
    # -------------------------
    assist_col = "Assists" if "Assists" in events.columns else "Assist"
    events[assist_col] = events[assist_col].fillna("").astype(str).str.strip()

    assists_series = events[assist_col]
    assists_series = assists_series[assists_series.str.len() > 0]
    assists_counts = assists_series.value_counts().reset_index()
    assists_counts.columns = ["Player Name", "Assists"]
    assists_counts["Player Name"] = assists_counts["Player Name"].astype(str).str.strip()

    # -------------------------
    # Merge totals
    # -------------------------
    totals = pd.merge(goals_counts, assists_counts, on="Player Name", how="outer").fillna(0)
    totals["Goals"] = totals["Goals"].astype(int)
    totals["Assists"] = totals["Assists"].astype(int)
    totals["Contributions"] = totals["Goals"] + totals["Assists"]

    minutes_summary["Player Name"] = minutes_summary["Player Name"].astype(str).str.strip()

    merged = pd.merge(totals, minutes_summary, on="Player Name", how="left").fillna(0)
    merged = merged[merged["Contributions"] > 0].copy()

    # Minutes per contribution
    merged["Contributions Per Minute"] = merged.apply(
        lambda r: (r["Mins Played"] / r["Contributions"]) if r["Contributions"] > 0 else 0,
        axis=1
    )
    merged["Display Contributions Per Minute"] = np.ceil(
        merged["Contributions Per Minute"]
    ).clip(upper=270)

    # -------------------------
    # Sorting
    # -------------------------
    trig = ctx.triggered_id or "sort-high-contrib"
    view_mode = "per_minute" if trig != "sort-total-contrib" else "contrib"

    if view_mode == "contrib":
        merged = merged.sort_values(by="Contributions", ascending=False)
    elif trig == "sort-low-contrib":
        merged = merged.sort_values(by="Contributions Per Minute", ascending=False)
    else:
        merged = merged.sort_values(by="Contributions Per Minute", ascending=True)


    # -------------------------
    # FIGURE
    # -------------------------
    if view_mode == "contrib":
        g_by_opp = (
            goals_only.groupby(["Scorer", "Opponent"])
                      .size()
                      .reset_index(name="Goals")
                      .rename(columns={"Scorer": "Player Name"})
        )

        ev_assists = events.copy()
        ev_assists["Assist_Player"] = ev_assists[assist_col].fillna("").astype(str).str.strip()
        ev_assists = ev_assists[ev_assists["Assist_Player"].str.len() > 0]

        a_by_opp = (
            ev_assists.groupby(["Assist_Player", "Opponent"])
                      .size()
                      .reset_index(name="Assists")
                      .rename(columns={"Assist_Player": "Player Name"})
        )

        by_opp = pd.merge(g_by_opp, a_by_opp, on=["Player Name", "Opponent"], how="outer").fillna(0)
        by_opp["Contributions"] = by_opp["Goals"].astype(int) + by_opp["Assists"].astype(int)
        by_opp = by_opp[by_opp["Player Name"].isin(merged["Player Name"])]

        fig = go.Figure()
        for opp in sorted(by_opp["Opponent"].dropna().unique()):
            sub = by_opp[by_opp["Opponent"] == opp]
            fig.add_trace(go.Bar(
                x=sub["Player Name"],
                y=sub["Contributions"],
                name=opp,
                marker_color=TEAM_COLORS.get(opp, "gray"),
                text=sub["Contributions"],
                textposition="outside",
            ))

        fig.update_layout(
            barmode="stack",
            title="Goal Contributions by Opponent",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(size=16, family="Segoe UI", color="white"),
            xaxis=dict(
                tickfont=dict(size=14),
                categoryorder="array",
                categoryarray=list(merged["Player Name"]),
                tickangle=-30,
                showgrid=False   # ✅ add this
            ),
            yaxis=dict(
                title="Contributions",
                tickfont=dict(size=14),
                showgrid=False   # ✅ add this
            ),
        )

    else:
        customdata = merged[["Contributions", "Mins Played", "Display Contributions Per Minute"]].values

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=merged["Player Name"],
            y=merged["Display Contributions Per Minute"],
            marker_color="#FF5733",
            customdata=customdata,
            text=merged["Contributions"],
            textposition='outside',
            hovertemplate=(
                "Player: %{x}<br>"
                "Contributions: %{customdata[0]}<br>"
                "Mins Played: %{customdata[1]:.0f}<br>"
                "Mins per Contribution: %{customdata[2]:.0f}<extra></extra>"
            )
        ))

        fig.update_layout(
            title="Goal Contributions Per Minute",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(size=16, family="Segoe UI", color="white"),
            xaxis=dict(
                tickangle=-30,
                showgrid=False   # ✅ add this
            ),
            yaxis=dict(
                title="Minutes per Contribution",
                showgrid=False   # ✅ add this
            ),
        )

    return fig


# =========================================================
# CALLBACK player insights - big moment goals
# =========================================================
@callback(
    Output("big-moment-goals-chart", "figure"),
    [
        Input("team-select", "value"),
        Input("big-moment-goal-filter", "value"),
    ]
)
def update_big_moment_goals_chart(selected_squad, selected_filter):
    selected_team = TEAM_MAP.get(selected_squad, FOCUS_TEAM)

    df = build_big_moment_goals_df(
        league_goal_data=league_goal_data,
        selected_squad=selected_squad,
        selected_team=selected_team,
    )

    if df.empty:
        fig = go.Figure()
        fig.update_layout(
            title=f"{selected_team} – Big Moment Goals",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
            annotations=[
                dict(
                    text="No big moment goals yet",
                    x=0.5, y=0.5,
                    xref="paper", yref="paper",
                    showarrow=False,
                    font=dict(size=18)
                )
            ]
        )
        return fig

    if selected_filter and selected_filter != "ALL":
        df = df[df["Big Moment Type"] == selected_filter].copy()

    if df.empty:
        fig = go.Figure()
        fig.update_layout(
            title=f"{selected_team} – Big Moment Goals",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
            annotations=[
                dict(
                    text="No goals for selected filter",
                    x=0.5, y=0.5,
                    xref="paper", yref="paper",
                    showarrow=False,
                    font=dict(size=18)
                )
            ]
        )
        return fig

    grouped = (
        df.groupby(["Player Name", "Big Moment Type"])
        .agg(
            Count=("Match ID", "size"),
            MatchIDs=("Match ID", lambda x: ", ".join(sorted(set(map(str, x))))),
            Opponents=("Opponent", lambda x: ", ".join(sorted(set(map(str, x))))),
        )
        .reset_index()
    )

    order_df = (
        grouped.groupby("Player Name")["Count"]
        .sum()
        .reset_index()
        .sort_values("Count", ascending=False)
    )
    player_order = order_df["Player Name"].tolist()

    type_order = ["Match Winner", "Match-Tying Goal", "Go-Ahead Goal Held"]

    fig = go.Figure()
    for goal_type in type_order:
        sub = grouped[grouped["Big Moment Type"] == goal_type].copy()
        if sub.empty:
            continue

        fig.add_trace(go.Bar(
            x=sub["Player Name"],
            y=sub["Count"],
            name=goal_type,
            text=sub["Count"],
            textposition="outside",
            customdata=sub[["Big Moment Type", "Opponents", "MatchIDs"]].values,
            hovertemplate=(
                "Player: %{x}<br>"
                "Type: %{customdata[0]}<br>"
                "Goals: %{y}<br>"
                "Opponents: %{customdata[1]}<br>"
                "Match IDs: %{customdata[2]}<extra></extra>"
            ),
        ))

    title_suffix = ""
    if selected_filter and selected_filter != "ALL":
        title_suffix = f" – {selected_filter}"

    fig.update_layout(
        title=f"{selected_team} – Big Moment Goals{title_suffix}",
        barmode="stack",
        plot_bgcolor="black",
        paper_bgcolor="black",
        font=dict(color="white", family="Segoe UI", size=14),
        xaxis=dict(
            title="Player Name",
            categoryorder="array",
            categoryarray=player_order,
            showgrid=False,
            tickangle=-30,
        ),
        yaxis=dict(
            title="Goals",
            showgrid=False,
            tickformat=".0f",
            rangemode="tozero",
        ),
        margin=dict(t=40, b=40),
        bargap=0.1,
        bargroupgap=0.0,
        hoverlabel=dict(font=dict(family="Segoe UI")),
        legend_title="Big Moment Type",
    )

    return fig


# callback to generate clean sheet chart
#@app.callback(
#    Output("defender-clean-sheet-chart", "figure"),
#    [
#        Input("team-selector", "value"),
#        Input("btn-last-4-cs", "n_clicks"),
#        Input("btn-reset-cs", "n_clicks"),
#    ]
#)
def update_clean_sheet_chart(selected_team, last4_clicks, reset_clicks):
    import pandas as pd
    from dash import ctx

    defender_roles = ['CB', 'RB', 'LB', 'WB', 'DM', 'GK']

    # Filter to selected team
    filtered_player_data = player_data[player_data["Team"] == selected_team].copy()
    filtered_team_data = team_data[team_data["Team"] == selected_team].copy()

    # Filter defenders
    defenders_df = filtered_player_data[
        filtered_player_data["Position"].isin(defender_roles)
    ].copy()
    defenders_df["Mins Played"] = pd.to_numeric(defenders_df["Mins Played"], errors="coerce")

    # Clean sheet games only
    clean_sheets_df = filtered_team_data[filtered_team_data["Clean sheet"].str.lower() == "yes"][
        ["Match ID", "Match Date"]
    ].copy()
    clean_sheets_df["Match Date"] = pd.to_datetime(clean_sheets_df["Match Date"], errors="coerce")

    # Merge defender appearances in clean sheet games
    merged = pd.merge(defenders_df, clean_sheets_df, on="Match ID", how="inner")

    # Filter to last 4 rounds if triggered
    if ctx.triggered_id == "btn-last-4-cs":
        recent_dates = clean_sheets_df["Match Date"].dropna().sort_values(ascending=False).unique()[:4]
        merged = merged[merged["Match Date"].isin(recent_dates)]

    # Clean Sheet Points logic
    def calc_cs_points(row):
        mins = row["Mins Played"]
        start = row["Start"].strip().lower() == "yes"
        if start and mins >= 90:
            return 1.0
        elif start and mins < 90:
            return 0.75
        elif not start and mins >= 30:
            return 0.5
        elif not start and mins <= 15:
            return 0.2
        else:
            return 0.0

    merged["CS Points"] = merged.apply(calc_cs_points, axis=1)

    # --- Aggregates ---
    cs_summary = (
        merged.groupby("Player Name")["CS Points"]
        .sum()
        .round(1)
        .reset_index()
    )

    # Add total minutes per player (from full player data, not just merged)
    total_minutes = (
        defenders_df.groupby("Player Name")["Mins Played"]
        .sum()
        .reset_index()
        .rename(columns={"Mins Played": "Total Minutes"})
    )

    # Add match appearances per player
    appearances = (
        defenders_df[defenders_df["Appearance"].str.lower() == "yes"]
        .groupby("Player Name")["Appearance"]
        .count()
        .reset_index()
        .rename(columns={"Appearance": "Matches Played"})
    )

    # Merge extras into CS summary
    cs_summary = cs_summary.merge(total_minutes, on="Player Name", how="left")
    cs_summary = cs_summary.merge(appearances, on="Player Name", how="left")

    # Drop players with 0 CS Points
    cs_summary = cs_summary[cs_summary["CS Points"] > 0]
    cs_summary = cs_summary.sort_values(by="CS Points", ascending=False)

    # Chart
    fig = px.bar(
        cs_summary,
        x="Player Name",
        y="CS Points",

        color_discrete_sequence=["#CBA1FF"],
        title="Defender Clean Sheet Contributions",
        template="plotly_dark",
        text="CS Points"
    )
    fig.update_traces(
        textposition="outside",
        hovertemplate=(
            "Player: %{x}<br>"
            "Matches Played: %{customdata[0]}<br>"
            "Total Minutes: %{customdata[1]}<br>"
            "Clean Sheet Points: %{y}"
        ),
        customdata=cs_summary[["Matches Played", "Total Minutes"]]
    )
    fig.update_layout(
        yaxis_title="Clean Sheet Points",
        uniformtext_minsize=10,
        uniformtext_mode='hide',
        bargap=0.0,
        bargroupgap=0.1,
        font=dict(size=14),
        xaxis=dict(tickfont=dict(size=12)),
        yaxis=dict(tickfont=dict(size=12)),
        hoverlabel=dict(font=dict(family="Segoe UI"))
    )

    return fig


# callback to generate mins per goals conceded while on field chart
@app.callback(
    Output("goals-conceded-chart", "figure"),
    [
        Input("team-select", "value"),
        Input("sort-high-gc", "n_clicks"),
        Input("sort-low-gc", "n_clicks"),
        Input("sort-total-gc", "n_clicks")
    ]
)
def update_goals_conceded_chart(selected_squad, high_clicks, low_clicks, total_clicks):

    # -----------------------------
    # Map UI team -> actual team name
    # -----------------------------
    team_data_name = TEAM_MAP.get(selected_squad, selected_squad)

    defender_roles = ['CB', 'RB', 'LB', 'WB', 'DM', 'DF', 'GK']

    # -----------------------------
    # Player minutes
    # Team   = app squad selector (1sts / Reserves)
    # Country = actual team in the match (Belconnen / BelReserves / Croatia etc.)
    # We need BOTH filters
    # -----------------------------
    p = player_data.copy()
    p["Player Name"] = p["Player Name"].astype(str).str.strip()
    p["Match ID"] = p["Match ID"].astype(str).str.strip()
    p["Position"] = p["Position"].fillna("").astype(str).str.strip()
    p["Start"] = p["Start"].fillna("").astype(str).str.strip().str.lower()
    p["Mins Played"] = pd.to_numeric(p["Mins Played"], errors="coerce")

    if "Team" in p.columns:
        p["Team"] = p["Team"].astype(str).str.strip()
        p = p[p["Team"] == str(selected_squad).strip()].copy()

    if "Country" in p.columns:
        p["Country"] = p["Country"].astype(str).str.strip()
        p = p[p["Country"] == str(team_data_name).strip()].copy()

    filtered_player_data = p[p["Position"].isin(defender_roles)].copy()

    # If no players after filters, return an empty but valid fig
    if filtered_player_data.empty:
        fig = go.Figure()
        fig.update_layout(
            title="Minutes per Goal Conceded (Defensive Roles Only)",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
            xaxis=dict(showgrid=False, zeroline=False),
            yaxis=dict(showgrid=False, zeroline=False),
        )
        fig.add_annotation(
            text=f"No player minutes for {selected_squad} (after filters)",
            x=0.5, y=0.5, xref="paper", yref="paper",
            showarrow=False, font=dict(size=18)
        )
        return fig


    # ---- Goal events: only matches involving selected_team (data name) ----
    g = league_goal_data.copy()
    g["Match ID"] = g["Match ID"].astype(str).str.strip()
    g["Home Team"] = g["Home Team"].fillna("").astype(str).str.strip()
    g["Away Team"] = g["Away Team"].fillna("").astype(str).str.strip()
    g["Scorer Team"] = g["Scorer Team"].fillna("").astype(str).str.strip()
    g["Minute Scored"] = pd.to_numeric(g["Minute Scored"], errors="coerce")
    g = g.dropna(subset=["Minute Scored"])

    g = g[
        (g["Home Team"] == team_data_name) |
        (g["Away Team"] == team_data_name)
    ].copy()

    # Conceded = goals scored by the OTHER team
    # Goals conceded = opponent scored against us
    g = g[
        ((g["Home Team"] == team_data_name) & (g["Scorer Team"] == g["Away Team"])) |
        ((g["Away Team"] == team_data_name) & (g["Scorer Team"] == g["Home Team"]))
    ].copy()


    # Pre-group conceded goal minutes by match for fast lookup
    conceded_minutes_by_match = (
        g.groupby("Match ID")["Minute Scored"]
         .apply(lambda s: s.dropna().astype(float).tolist())
         .to_dict()
    )

    results = []
    for _, row in filtered_player_data.iterrows():
        player = row["Player Name"]
        match_id = row["Match ID"]
        start = row["Start"] == "yes"
        mins_played = row["Mins Played"]

        if pd.isna(mins_played) or mins_played <= 0:
            continue

        # Time on field
        if start:
            time_start = 0.0
            time_end = float(mins_played)
        else:
            # sub on late: assume on-field window ends at 90
            time_end = 90.0
            time_start = max(0.0, 90.0 - float(mins_played))

        # Conceded goals in that match while player is on field
        mins_list = conceded_minutes_by_match.get(match_id, [])
        gc = sum(1 for m in mins_list if (m >= time_start) and (m < time_end))

        results.append({
            "Player Name": player,
            "Minutes Played": float(mins_played),
            "Goals Conceded": int(gc)
        })

    results_df = pd.DataFrame(results)

    if results_df.empty:
        fig = go.Figure()
        fig.update_layout(
            title="Minutes per Goal Conceded (Defensive Roles Only)",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
            xaxis=dict(showgrid=False, zeroline=False),
            yaxis=dict(showgrid=False, zeroline=False),
        )
        fig.add_annotation(
            text=f"No minutes/goals data for {selected_squad}",
            x=0.5, y=0.5, xref="paper", yref="paper",
            showarrow=False, font=dict(size=18)
        )
        return fig

    summary = results_df.groupby("Player Name", as_index=False).agg({
        "Goals Conceded": "sum",
        "Minutes Played": "sum"
    })

    # Keep as-is, but make the threshold safe if you want:
    summary = summary[summary["Minutes Played"] > 0].copy()

    summary["Minutes per GC"] = summary.apply(
        lambda r: int(r["Minutes Played"] / r["Goals Conceded"]) if r["Goals Conceded"] > 0 else 300,
        axis=1
    )

    summary["Label"] = summary.apply(
        lambda r: f'{r["Minutes per GC"]} mins per goal' if r["Goals Conceded"] > 0 else "No goals conceded (300 default)",
        axis=1
    )

    triggered_id = ctx.triggered_id
    if triggered_id == "sort-total-gc":
        summary = summary.sort_values(by="Goals Conceded", ascending=False)
    elif triggered_id == "sort-high-gc":
        summary = summary.sort_values(by="Minutes per GC", ascending=False)
    elif triggered_id == "sort-low-gc":
        summary = summary.sort_values(by="Minutes per GC", ascending=True)
    else:
        summary = summary.sort_values(by="Minutes per GC", ascending=False)

    text_col = "Goals Conceded" if triggered_id == "sort-total-gc" else "Minutes per GC"

    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            x=summary["Player Name"],
            y=summary["Minutes per GC"],
            marker_color="#7FC97F",
            text=summary[text_col],
            textposition="outside",
            customdata=summary[["Minutes Played", "Goals Conceded", "Label"]].values,
            hovertemplate=(
                "Player: %{x}<br>"
                "Minutes Played: %{customdata[0]:.0f}<br>"
                "Goals Conceded: %{customdata[1]}<br>"
                "%{customdata[2]}<extra></extra>"
            ),
        )
    )

    fig.update_layout(
        title="Minutes per Goal Conceded (Defensive Roles Only)",
        yaxis_title="Minutes per Goal Conceded",
        uniformtext_minsize=10,
        uniformtext_mode="hide",
        bargap=0.0,
        bargroupgap=0.1,
        plot_bgcolor="black",
        paper_bgcolor="black",
        font=dict(color="white", size=14),
        xaxis=dict(tickfont=dict(size=12), tickangle=-30, showgrid=False),
        yaxis=dict(tickfont=dict(size=12), showgrid=True, gridcolor="#333"),
        hoverlabel=dict(font=dict(family="Segoe UI"))
    )

    return fig


# callback to generate effectiveness chart (Goals For - Goals Against while on field)
@app.callback(
    Output("player-effectiveness-chart", "figure"),
    [
        Input("team-select", "value"),
        Input("btn-high-eff", "n_clicks"),
        Input("btn-low-eff", "n_clicks"),
        Input("btn-total-eff", "n_clicks"),
        Input("btn-last-4-eff", "n_clicks"),
        Input("btn-reset-eff", "n_clicks"),
    ]
)
def update_player_effectiveness_chart(selected_squad, high_clicks, low_clicks, total_clicks, last4_clicks, reset_clicks):
    from dash import ctx
    import pandas as pd
    import plotly.express as px

    trig = ctx.triggered_id
    selected_team = TEAM_MAP.get(selected_squad, selected_squad)

    # --- player stints: keep only selected squad + actual team players ---
    p = player_data.copy()
    p["Player Name"] = p["Player Name"].astype(str).str.strip()
    p["Match ID"] = p["Match ID"].astype(str).str.strip()
    p["Mins Played"] = pd.to_numeric(p["Mins Played"], errors="coerce")
    p["Start"] = p["Start"].astype(str).str.strip().str.lower().eq("yes")

    if "Team" in p.columns:
        p["Team"] = p["Team"].astype(str).str.strip()
        p = p[p["Team"] == str(selected_squad).strip()].copy()

    if "Country" in p.columns:
        p["Country"] = p["Country"].astype(str).str.strip()
        p = p[p["Country"] == str(selected_team).strip()].copy()

    p = p.dropna(subset=["Mins Played"])
    p = p[p["Mins Played"] > 0].copy()

    if p.empty:
        fig = px.bar(
            pd.DataFrame({"Player Name": [], "Eff per 90": []}),
            x="Player Name",
            y="Eff per 90",
            template="plotly_dark"
        )
        fig.update_layout(title=f"No player minutes found for {selected_squad} (after filters)")
        return fig

    stint_df = pd.DataFrame({
        "Player Name": p["Player Name"],
        "Match ID": p["Match ID"],
        "Mins Played": p["Mins Played"],
        "Start Min": p.apply(lambda r: 0 if r["Start"] else (90 - r["Mins Played"]), axis=1),
        "End Min": p.apply(lambda r: r["Mins Played"] if r["Start"] else 90, axis=1),
    })

    # --- goals involving selected team only ---
    g = league_goal_data.copy()
    g["Match ID"] = g["Match ID"].astype(str).str.strip()
    g["Home Team"] = g["Home Team"].astype(str).str.strip()
    g["Away Team"] = g["Away Team"].astype(str).str.strip()
    g["Scorer Team"] = g["Scorer Team"].fillna("").astype(str).str.strip()
    g["Minute Scored"] = pd.to_numeric(g["Minute Scored"], errors="coerce")
    g = g.dropna(subset=["Minute Scored"])

    g = g[
        (g["Home Team"] == selected_team) |
        (g["Away Team"] == selected_team)
    ].copy()

    # --- last 4 toggle ---
    if trig == "btn-last-4-eff":
        g["Match Date Parsed"] = pd.to_datetime(g["Match Date"], errors="coerce")
        last4 = sorted(g["Match Date Parsed"].dropna().unique())[-4:]
        if len(last4) > 0:
            g = g[g["Match Date Parsed"].isin(last4)].copy()
            stint_df = stint_df[stint_df["Match ID"].isin(g["Match ID"].unique())].copy()

    rows = []
    for _, s in stint_df.iterrows():
        match_goals = g[g["Match ID"] == s["Match ID"]]
        on_field = match_goals[
            (match_goals["Minute Scored"] >= s["Start Min"]) &
            (match_goals["Minute Scored"] <= s["End Min"])
        ]

        goals_for = (on_field["Scorer Team"] == selected_team).sum()
        goals_against = (
            (on_field["Scorer Team"] != "") &
            (on_field["Scorer Team"] != selected_team)
        ).sum()

        rows.append({
            "Player Name": s["Player Name"],
            "Goals For": int(goals_for),
            "Goals Against": int(goals_against),
            "Minutes Played": float(s["Mins Played"]),
            "Apps": 1
        })

    df = pd.DataFrame(rows)

    if df.empty:
        fig = px.bar(
            pd.DataFrame({"Player Name": [], "Eff per 90": []}),
            x="Player Name",
            y="Eff per 90",
            template="plotly_dark"
        )
        fig.update_layout(title="No data after building stints")
        return fig

    df = df.groupby("Player Name", as_index=False).agg({
        "Goals For": "sum",
        "Goals Against": "sum",
        "Minutes Played": "sum",
        "Apps": "sum"
    })

    df = df[df["Minutes Played"] >= 100].copy()

    if df.empty:
        fig = px.bar(
            pd.DataFrame({"Player Name": [], "Eff per 90": []}),
            x="Player Name",
            y="Eff per 90",
            template="plotly_dark"
        )
        fig.update_layout(title=f"No players >=100 mins for {selected_squad}")
        return fig

    df["Effectiveness"] = df["Goals For"] - df["Goals Against"]
    df["Eff per 90"] = ((df["Effectiveness"] / df["Minutes Played"]) * 90).round(0).astype(int)

    sort_by = "Eff per 90"
    if trig == "btn-total-eff":
        sort_by = "Effectiveness"
        df = df.sort_values(by="Effectiveness", ascending=False)
    elif trig == "btn-low-eff":
        df = df.sort_values(by="Eff per 90", ascending=True)
    else:
        df = df.sort_values(by="Eff per 90", ascending=False)

    fig = px.bar(
        df,
        x="Player Name",
        y=sort_by,
        template="plotly_dark",
        title="Player Effectiveness per 90 mins",
        text=("Effectiveness" if sort_by == "Effectiveness" else "Eff per 90")
    )

    fig.update_traces(
        textposition="outside",
        hovertemplate=(
            "Player: %{x}<br>"
            f"{sort_by}: %{{y}}<br>"
            "Total Eff: %{customdata[0]}<br>"
            "Apps: %{customdata[1]}<br>"
            "Minutes: %{customdata[2]:.0f}<br>"
            "Goals For: %{customdata[3]}<br>"
            "Goals Against: %{customdata[4]}<extra></extra>"
        ),
        customdata=df[["Effectiveness", "Apps", "Minutes Played", "Goals For", "Goals Against"]].values
    )

    fig.update_layout(
        xaxis=dict(tickangle=-30),
        hoverlabel=dict(font=dict(family="Segoe UI"))
    )

    return fig








#----------------------------------------------------
#------new callbacks for the Opponent tab------------
#---------------------------------------------------

# callback to drive the options in the opponent dropdown list
@callback(
    Output("opponent-select", "options"),
    Output("opponent-select", "value"),
    Input("team-select", "value"),
    State("opponent-select", "value"),
)
def update_opponent_dropdown(selected_squad, current_value):

    df = league_goal_data.copy()

    # Filter rows belonging to the selected squad dataset
    if "Team" in df.columns:
        df = df[df["Team"] == selected_squad]

    # Get all teams appearing in those matches
    teams = set(df["Home Team"]) | set(df["Away Team"])
    teams = {t for t in teams if pd.notna(t)}

    # Sort alphabetically
    teams = sorted(teams)

    options = [{"label": "ALL", "value": "ALL"}] + [
        {"label": t, "value": t} for t in teams
    ]

    # Keep current value if still valid
    valid_values = {o["value"] for o in options}
    value = current_value if current_value in valid_values else "ALL"

    return options, value

# ----------- GOALS SCORED AND CONCEDED BY INTERVAL ----------
@callback(
    Output("opp-scored-interval", "figure"),
    Output("opp-conceded-interval", "figure"),
    Input("team-select", "value"),
    Input("opponent-select", "value"),
)
def update_opponent_interval_charts(selected_squad, selected_opponent):
    """
    Opponent Insights – Interval charts.

    Chart 1:
        All goals SCORED BY selected_opponent,
        grouped by 15-min interval and stacked by the team they scored against.

    Chart 2:
        All goals CONCEDED BY selected_opponent,
        grouped by 15-min interval and stacked by the team scoring.
    """

    # ==============================
    # 0) NO OPPONENT SELECTED
    # ==============================
    if not selected_opponent:
        empty_fig = go.Figure()
        empty_fig.update_layout(
            title="Select an opponent to view interval trends",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family=base_font["fontFamily"]),
            xaxis=dict(showgrid=False, zeroline=False),
            yaxis=dict(showgrid=False, zeroline=False),
        )
        return empty_fig, empty_fig

    # ==============================
    # Base dataframe
    # ==============================
    df = league_goal_data.copy()

    # Keep only rows from selected squad file
    if "Team" in df.columns:
        df["Team"] = df["Team"].astype(str).str.strip()
        df = df[df["Team"] == str(selected_squad).strip()].copy()

    # Normalise
    for c in ["Home Team", "Away Team", "Scorer Team"]:
        if c in df.columns:
            df[c] = df[c].fillna("").astype(str).str.strip()

    df["Minute Scored"] = pd.to_numeric(df["Minute Scored"], errors="coerce")
    df = df.dropna(subset=["Minute Scored"])

    # Apply your existing binning logic
    df["Minute Bin"] = df["Minute Scored"].apply(bin_minute)

    interval_bins = ["0–15", "16–30", "31–45", "46–60", "61–75", "76–90"]

    # =========================================================
    # 1) GOALS SCORED BY SELECTED OPPONENT
    # =========================================================
    df_scored = df[df["Scorer Team"] == selected_opponent].copy()

    mask_involved_scored = (
        (df_scored["Home Team"] == selected_opponent)
        | (df_scored["Away Team"] == selected_opponent)
    )
    df_scored = df_scored[mask_involved_scored].copy()

    df_scored["Against Team"] = df_scored.apply(
        lambda r: get_against_team(r, selected_opponent),
        axis=1,
    )
    df_scored = df_scored.dropna(subset=["Against Team"])

    if df_scored.empty:
        fig_scored = go.Figure()
        fig_scored.update_layout(
            title=f"{selected_opponent} – No goals scored in tracked matches",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family=base_font["fontFamily"]),
            xaxis_title="Minute Interval",
            yaxis_title="Goals Scored",
            xaxis=dict(showgrid=False, zeroline=False),
            yaxis=dict(showgrid=False, zeroline=False),
        )
    else:
        scored_grouped = (
            df_scored.groupby(["Minute Bin", "Against Team"])
            .size()
            .unstack(fill_value=0)
            .reindex(interval_bins)
            .fillna(0)
        )

        fig_scored = go.Figure()
        for opp_team in scored_grouped.columns:
            fig_scored.add_trace(
                go.Bar(
                    x=scored_grouped.index,
                    y=scored_grouped[opp_team],
                    name=opp_team,
                    marker_color=TEAM_COLORS.get(str(opp_team).strip(), DEFAULT_COLOR),
                    hovertemplate=(
                        "<b>%{fullData.name}</b><br>"
                        "Interval: %{x}<br>"
                        "Goals: %{y}<extra></extra>"
                    ),
                    hoverlabel=dict(font=dict(family="Segoe UI")),
                )
            )

        fig_scored.update_layout(
            title=f"{selected_opponent} – Goals Scored by Interval",
            title_font=dict(size=18, family="Segoe UI"),
            barmode="stack",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
            xaxis_title="Minute Interval",
            yaxis_title="Goals Scored",
            margin=dict(t=40, b=40),
            bargap=0.4,
            bargroupgap=0.1,
            xaxis=dict(showgrid=False),
            yaxis=dict(showgrid=False, tickformat=".0f"),
            legend_title="Opponent",
        )

    # =========================================================
    # 2) GOALS CONCEDED BY SELECTED OPPONENT
    # =========================================================
    if selected_opponent == "ALL":
        df_conceded = df.copy()
        df_conceded["Opp Team"] = df_conceded["Scorer Team"]
    else:
        mask_involved_conceded = (
            (df["Home Team"] == selected_opponent)
            | (df["Away Team"] == selected_opponent)
        )
        mask_conceded = df["Scorer Team"] != selected_opponent

        df_conceded = df[mask_involved_conceded & mask_conceded].copy()
        df_conceded["Opp Team"] = df_conceded["Scorer Team"]

    if df_conceded.empty:
        fig_conceded = go.Figure()
        fig_conceded.update_layout(
            title=f"{selected_opponent} – No goals conceded in tracked matches",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family=base_font["fontFamily"]),
            xaxis_title="Minute Interval",
            yaxis_title="Goals Conceded",
            xaxis=dict(showgrid=False, zeroline=False),
            yaxis=dict(showgrid=False, zeroline=False),
        )
    else:
        conceded_grouped = (
            df_conceded.groupby(["Minute Bin", "Opp Team"])
            .size()
            .unstack(fill_value=0)
            .reindex(interval_bins)
            .fillna(0)
        )

        fig_conceded = go.Figure()
        for opp_team in conceded_grouped.columns:
            fig_conceded.add_trace(
                go.Bar(
                    x=conceded_grouped.index,
                    y=conceded_grouped[opp_team],
                    name=opp_team,
                    marker_color=TEAM_COLORS.get(str(opp_team).strip(), DEFAULT_COLOR),
                    hovertemplate=(
                        "<b>%{fullData.name}</b><br>"
                        "Interval: %{x}<br>"
                        "Goals: %{y}<extra></extra>"
                    ),
                    hoverlabel=dict(font=dict(family="Segoe UI")),
                )
            )

        fig_conceded.update_layout(
            title=(
                "League-wide – Goals Conceded by Interval"
                if selected_opponent == "ALL"
                else f"{selected_opponent} – Goals Conceded by Interval"
            ),
            title_font=dict(size=18, family="Segoe UI"),
            barmode="stack",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
            xaxis_title="Minute Interval",
            yaxis_title="Goals Conceded",
            margin=dict(t=40, b=40),
            bargap=0.4,
            bargroupgap=0.1,
            xaxis=dict(showgrid=False, zeroline=False, showline=False),
            yaxis=dict(showgrid=False, zeroline=False, showline=False),
            legend_title="Opponent",
        )

    return fig_scored, fig_conceded



#---------THIS IS GOALS SCORED AND CONCEDED BY TYPE - OPPONENT TAB--------
@callback(
    Output("opp-scored-type", "figure"),
    Output("opp-conceded-type", "figure"),
    Input("team-select", "value"),
    Input("opponent-select", "value"),
)
def update_opponent_goal_type_charts(selected_squad, selected_opponent):
    """
    Opponent Insights – Goal Type charts.

    1) opp-scored-type:
       All goals SCORED BY `selected_opponent`,
       grouped by Goal Type (abbr) and stacked by the team they scored against.

    2) opp-conceded-type:
       All goals CONCEDED BY `selected_opponent`
       (i.e. scored by other teams in games they're involved in),
       grouped by Goal Type (abbr) and stacked by the team scoring.
    """

    # ==============================
    # 0) NO OPPONENT SELECTED
    # ==============================
    if not selected_opponent:
        empty_scored = go.Figure()
        empty_scored.update_layout(
            title="Select an opponent to view goal type patterns",
            title_font=dict(size=18, family="Segoe UI Black"),
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family=base_font["fontFamily"]),
            xaxis_title="Goal Type",
            yaxis_title="Goals Scored",
            margin=dict(t=40, b=40),
        )
        empty_scored.update_xaxes(showgrid=False, zeroline=False, showline=False)
        empty_scored.update_yaxes(showgrid=False, zeroline=False, showline=False)

        empty_conceded = go.Figure()
        empty_conceded.update_layout(
            title="Select an opponent to view goal type patterns",
            title_font=dict(size=18, family="Segoe UI Black"),
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family=base_font["fontFamily"]),
            xaxis_title="Goal Type",
            yaxis_title="Goals Conceded",
            margin=dict(t=40, b=40),
        )
        empty_conceded.update_xaxes(showgrid=False, zeroline=False, showline=False)
        empty_conceded.update_yaxes(showgrid=False, zeroline=False, showline=False)

        return empty_scored, empty_conceded

    # ==============================
    # Base dataframe
    # ==============================
    df = league_goal_data.copy()

    # Keep only rows from selected squad file
    if "Team" in df.columns:
        df["Team"] = df["Team"].astype(str).str.strip()
        df = df[df["Team"] == str(selected_squad).strip()].copy()

    # Normalise
    for c in ["Home Team", "Away Team", "Scorer Team", "Goal Type"]:
        if c in df.columns:
            df[c] = df[c].fillna("").astype(str).str.strip()

    # Abbreviated goal types
    df["Goal Abbr"] = df["Goal Type"].apply(abbreviate_goal_type)

    # Fixed x-axis ordering
    goal_type_order = [
        "FT-DT", "FT-AT",
        "MT-DT", "MT-AT",
        "BT-DT", "BT-AT",
        "SP-C", "SP-T", "SP-P", "SP-F",
    ]

    # =========================================================
    # 1) GOALS SCORED
    # =========================================================
    if selected_opponent == "ALL":
        df_scored = df.copy()
        df_scored["Against Team"] = df_scored.apply(
            lambda r: get_against_team(r, r["Scorer Team"]),
            axis=1,
        )
    else:
        df_scored = df[df["Scorer Team"] == selected_opponent].copy()

        mask_involved_scored = (
            (df_scored["Home Team"] == selected_opponent)
            | (df_scored["Away Team"] == selected_opponent)
        )
        df_scored = df_scored[mask_involved_scored].copy()

        df_scored["Against Team"] = df_scored.apply(
            lambda r: get_against_team(r, selected_opponent),
            axis=1,
        )

    df_scored = df_scored.dropna(subset=["Against Team"])

    if df_scored.empty:
        fig_scored = go.Figure()
        fig_scored.update_layout(
            title=f"{selected_opponent} – No goals scored in tracked matches",
            title_font=dict(size=18, family="Segoe UI Black"),
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family=base_font["fontFamily"]),
            xaxis_title="Goal Type",
            yaxis_title="Goals Scored",
            margin=dict(t=40, b=40),
        )
        fig_scored.update_xaxes(showgrid=False, zeroline=False, showline=False)
        fig_scored.update_yaxes(showgrid=False, zeroline=False, showline=False)
    else:
        scored_grouped = (
            df_scored.groupby(["Goal Abbr", "Against Team"])
            .size()
            .unstack(fill_value=0)
            .reindex(index=goal_type_order, fill_value=0)
        )

        fig_scored = go.Figure()
        for opp_team in scored_grouped.columns:
            fig_scored.add_trace(
                go.Bar(
                    x=scored_grouped.index,
                    y=scored_grouped[opp_team],
                    name=opp_team,
                    marker_color=TEAM_COLORS.get(str(opp_team).strip(), DEFAULT_COLOR),
                    hovertemplate=(
                        "<b>%{fullData.name}</b><br>"
                        "Goal Type: %{x}<br>"
                        "Goals: %{y}<extra></extra>"
                    ),
                    hoverlabel=dict(font=dict(family="Segoe UI")),
                )
            )

        fig_scored.update_layout(
            title=(
                f"{selected_opponent} – Goals Scored by Type (stacked by opponent)"
                if selected_opponent != "ALL"
                else "ALL Teams – Goals Scored by Type (stacked by opponent)"
            ),
            title_font=dict(size=18, family="Segoe UI Black"),
            barmode="stack",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
            xaxis_title="Goal Type",
            yaxis_title="Goals Scored",
            margin=dict(t=40, b=40),
            bargap=0.3,
            bargroupgap=0.1,
            legend_title="Opponent",
            xaxis=dict(showgrid=False, zeroline=False, showline=False),
            yaxis=dict(showgrid=False, zeroline=False, showline=False),
        )
        fig_scored.update_xaxes(showgrid=False)
        fig_scored.update_yaxes(showgrid=False, tickformat=".0f")

    # =========================================================
    # 2) GOALS CONCEDED
    # =========================================================
    if selected_opponent == "ALL":
        df_conceded = df.copy()
        df_conceded["Opp Team"] = df_conceded["Scorer Team"]
    else:
        mask_involved = (
            (df["Home Team"] == selected_opponent)
            | (df["Away Team"] == selected_opponent)
        )
        mask_conceded = df["Scorer Team"] != selected_opponent

        df_conceded = df[mask_involved & mask_conceded].copy()
        df_conceded["Opp Team"] = df_conceded["Scorer Team"]

    if df_conceded.empty:
        fig_conceded = go.Figure()
        fig_conceded.update_layout(
            title=f"{selected_opponent} – No goals conceded in tracked matches",
            title_font=dict(size=18, family="Segoe UI Black"),
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family=base_font["fontFamily"]),
            xaxis_title="Goal Type",
            yaxis_title="Goals Conceded",
            margin=dict(t=40, b=40),
        )
        fig_conceded.update_xaxes(showgrid=False, zeroline=False, showline=False)
        fig_conceded.update_yaxes(showgrid=False, zeroline=False, showline=False)
    else:
        conceded_grouped = (
            df_conceded.groupby(["Goal Abbr", "Opp Team"])
            .size()
            .unstack(fill_value=0)
            .reindex(index=goal_type_order, fill_value=0)
        )

        fig_conceded = go.Figure()
        for opp_team in conceded_grouped.columns:
            fig_conceded.add_trace(
                go.Bar(
                    x=conceded_grouped.index,
                    y=conceded_grouped[opp_team],
                    name=opp_team,
                    marker_color=TEAM_COLORS.get(str(opp_team).strip(), DEFAULT_COLOR),
                    hovertemplate=(
                        "<b>%{fullData.name}</b><br>"
                        "Goal Type: %{x}<br>"
                        "Goals: %{y}<extra></extra>"
                    ),
                    hoverlabel=dict(font=dict(family="Segoe UI")),
                )
            )

        fig_conceded.update_layout(
            title=(
                f"{selected_opponent} – Goals Conceded by Type (stacked by opponent)"
                if selected_opponent != "ALL"
                else "ALL Teams – Goals Conceded by Type (stacked by scoring team)"
            ),
            title_font=dict(size=18, family="Segoe UI Black"),
            barmode="stack",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
            xaxis_title="Goal Type",
            yaxis_title="Goals Conceded",
            margin=dict(t=40, b=40),
            bargap=0.3,
            bargroupgap=0.1,
            legend_title="Opponent",
            xaxis=dict(showgrid=False, zeroline=False, showline=False),
            yaxis=dict(showgrid=False, zeroline=False, showline=False),
        )
        fig_conceded.update_xaxes(showgrid=False)
        fig_conceded.update_yaxes(showgrid=False, tickformat=".0f")

    return fig_scored, fig_conceded

#------------callback for PIE CHARTS FOR OPPONENT INSIGHTS TAB---------------
@callback(
    Output("opp-scored-regain-pie", "figure"),
    Output("opp-scored-setpiece-pie", "figure"),
    Output("opp-conceded-regain-pie", "figure"),
    Output("opp-conceded-setpiece-pie", "figure"),
    Input("team-select", "value"),
    Input("opponent-select", "value"),
)
def update_opponent_goal_type_pies(selected_squad, selected_opponent):

    """
    Opponent Insights – Goal Type pies.

    Uses league_goal_data and shows, from the SELECTED OPPONENT's perspective:
      - Goals SCORED (two pies: regains + set pieces)
      - Goals CONCEDED (two pies: regains + set pieces)

    IMPORTANT:
    - Only goals with a recognised Goal Type (in goal_type_labels) are counted.
    - Percentages are out of ANALYSED goals only (coded), not total goals.
    """

    # Treat only "no selection" as empty
    if not selected_opponent:
        empty = go.Figure()
        empty.update_layout(
            title="Select an opponent to view goal type breakdown",
            paper_bgcolor="black",
            plot_bgcolor="black",
            font=dict(color="white", family=base_font["fontFamily"]),
        )
        empty.update_xaxes(showgrid=False, zeroline=False, showline=False)
        empty.update_yaxes(showgrid=False, zeroline=False, showline=False)
        return empty, empty, empty, empty

    df = league_goal_data.copy()

    # Keep only rows from selected squad file
    if "Team" in df.columns:
        df["Team"] = df["Team"].astype(str).str.strip()
        df = df[df["Team"] == str(selected_squad).strip()].copy()

    # Basic cleaning
    for c in ["Home Team", "Away Team", "Scorer Team", "Goal Type"]:
        if c in df.columns:
            df[c] = df[c].fillna("").astype(str).str.strip()

    # Only matches where this opponent is involved
    if selected_opponent != "ALL":
        involved_mask = (
            (df["Home Team"] == selected_opponent)
            | (df["Away Team"] == selected_opponent)
        )
        df = df[involved_mask].copy()
    # else: ALL → keep all matches

    if df.empty:
        empty = go.Figure()
        empty.update_layout(
            title=f"{selected_opponent} – No goals in tracked matches",
            paper_bgcolor="black",
            plot_bgcolor="black",
            font=dict(color="white", family=base_font["fontFamily"]),
        )
        empty.update_xaxes(showgrid=False, zeroline=False, showline=False)
        empty.update_yaxes(showgrid=False, zeroline=False, showline=False)
        return empty, empty, empty, empty

    # ----- Label maps & groupings -----
    goal_type_labels = {
        "R-FT-DT": "Regain Front Third – During Transition",
        "R-FT-AT": "Regain Front Third – After Transition",
        "R-MT-DT": "Regain Middle Third – During Transition",
        "R-MT-AT": "Regain Middle Third – After Transition",
        "R-BT-DT": "Regain Back Third – During Transition",
        "R-BT-AT": "Regain Back Third – After Transition",
        "SP-C": "Corners",
        "SP-T": "Throw-Ins",
        "SP-P": "Penalties",
        "SP-F": "Free Kicks",
    }

    regain_codes = [c for c in goal_type_labels if c.startswith("R-")]
    setpiece_codes = [c for c in goal_type_labels if c.startswith("SP-")]

    front_codes = {"R-FT-DT", "R-FT-AT"}
    middle_codes = {"R-MT-DT", "R-MT-AT"}
    back_codes = {"R-BT-DT", "R-BT-AT"}

    # All valid coded goal types
    all_goal_codes = set(goal_type_labels.keys())

    def group_name(code: str) -> str:
        if code in front_codes:
            return "Front-third regains"
        if code in middle_codes:
            return "Middle-third regains"
        if code in back_codes:
            return "Back-third regains"
        return "Set pieces"

    # ----- Separate 'scored' vs 'conceded' from this opponent's perspective -----
    if selected_opponent == "ALL":
        df_scored = df.copy()
        df_conceded = df.copy()
    else:
        df_scored = df[df["Scorer Team"] == selected_opponent].copy()
        df_conceded = df[df["Scorer Team"] != selected_opponent].copy()

    total_scored = len(df_scored)
    total_conceded = len(df_conceded)

    def build_pie_side(filtered_df, valid_codes, title, total_for_side):
        """
        Build a single donut pie for one side (scored or conceded).

        - Only includes goals with a recognised Goal Type (analysed).
        - Percentages are out of ALL analysed goals for that side
          (scored OR conceded), not including unanalysed goals.
        """

        if filtered_df.empty or total_for_side == 0:
            fig = go.Figure()
            fig.update_layout(
                title=title,
                paper_bgcolor="black",
                plot_bgcolor="black",
                font=dict(color="white", family="Segoe UI"),
                annotations=[
                    dict(
                        text="No data",
                        x=0.5,
                        y=0.5,
                        font_size=18,
                        showarrow=False,
                    )
                ],
                margin=dict(t=40, b=20, l=20, r=20),
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=-0.1,
                    xanchor="center",
                    x=0.5,
                ),
            )
            return fig

        analysed_df = filtered_df[filtered_df["Goal Type"].isin(all_goal_codes)].copy()
        analysed_total = len(analysed_df)

        if analysed_total == 0:
            fig = go.Figure(
                go.Pie(
                    labels=["No analysed goals"],
                    values=[1],
                    hole=0.45,
                    textinfo="label",
                    hoverinfo="skip",
                    sort=False,
                    textfont=dict(family="Segoe UI Semibold", size=14),
                )
            )
            fig.update_layout(
                title=title,
                paper_bgcolor="black",
                plot_bgcolor="black",
                font=dict(color="white", family="Segoe UI"),
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=-0.1,
                    xanchor="center",
                    x=0.5,
                ),
                margin=dict(t=40, b=20, l=20, r=20),
            )
            return fig

        subset = analysed_df[analysed_df["Goal Type"].isin(valid_codes)].copy()

        if subset.empty:
            fig = go.Figure(
                go.Pie(
                    labels=["No Data"],
                    values=[1],
                    hole=0.45,
                    textinfo="label",
                    hoverinfo="skip",
                    sort=False,
                    textfont=dict(family="Segoe UI Semibold", size=14),
                )
            )
            fig.update_layout(
                title=title,
                paper_bgcolor="black",
                plot_bgcolor="black",
                font=dict(color="white", family="Segoe UI"),
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=-0.1,
                    xanchor="center",
                    x=0.5,
                ),
                margin=dict(t=40, b=20, l=20, r=20),
            )
            return fig

        counts = subset["Goal Type"].value_counts().sort_index()

        perc_overall = (counts / analysed_total * 100).round(1)
        text_overall = [
            f"{p:.1f}%<br>{c}" for p, c in zip(perc_overall, counts.values)
        ]

        front_total = counts[counts.index.isin(front_codes)].sum()
        middle_total = counts[counts.index.isin(middle_codes)].sum()
        back_total = counts[counts.index.isin(back_codes)].sum()
        sp_total = counts[counts.index.str.startswith("SP-")].sum()

        def group_pct_for(code: str) -> float:
            if analysed_total == 0:
                return 0.0
            if code in front_codes:
                return round(front_total / analysed_total * 100, 1)
            if code in middle_codes:
                return round(middle_total / analysed_total * 100, 1)
            if code in back_codes:
                return round(back_total / analysed_total * 100, 1)
            return round(sp_total / analysed_total * 100, 1)

        labels_short = [
            (code.split("-")[-2] + "-" + code.split("-")[-1])
            if code.startswith("R-")
            else code
            for code in counts.index
        ]

        hover_texts = []
        for code, cnt, pct in zip(counts.index, counts.values, perc_overall.values):
            gname = group_name(code)
            gpct = group_pct_for(code)
            hover_texts.append(
                f"Type: {code} – {goal_type_labels.get(code, code)}"
                f"<br>Goals (coded): {cnt}"
                f"<br>Analysed goals: {analysed_total}"
                f"<br>Percent of analysed: {pct:.1f}%"
                f"<br>Group: {gname} ({gpct:.1f}% of analysed)"
            )

        fig = go.Figure(
            go.Pie(
                labels=labels_short,
                values=counts.values,
                hole=0.45,
                text=text_overall,
                textinfo="label+text",
                hoverinfo="text",
                hovertext=hover_texts,
                sort=False,
                textfont=dict(family="Segoe UI Semibold", size=12),
            )
        )

        fig.update_layout(
            title=title,
            paper_bgcolor="black",
            plot_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=-0.1,
                xanchor="center",
                x=0.5,
            ),
            margin=dict(t=40, b=20, l=20, r=20),
            hoverlabel=dict(font=dict(family="Segoe UI")),
        )
        return fig

    # Titles
    if selected_opponent == "ALL":
        scored_regain_title = "ALL Teams – Regain Types (Goals Scored)"
        scored_sp_title = "ALL Teams – Set Piece Types (Goals Scored)"
        conceded_regain_title = "ALL Teams – Regain Types (Goals Conceded)"
        conceded_sp_title = "ALL Teams – Set Piece Types (Goals Conceded)"
    else:
        scored_regain_title = f"{selected_opponent} – Regain Types (Goals Scored)"
        scored_sp_title = f"{selected_opponent} – Set Piece Types (Goals Scored)"
        conceded_regain_title = f"{selected_opponent} – Regain Types (Goals Conceded)"
        conceded_sp_title = f"{selected_opponent} – Set Piece Types (Goals Conceded)"

    scored_regain_fig = build_pie_side(
        df_scored, regain_codes, scored_regain_title, total_scored
    )
    scored_setpiece_fig = build_pie_side(
        df_scored, setpiece_codes, scored_sp_title, total_scored
    )
    conceded_regain_fig = build_pie_side(
        df_conceded, regain_codes, conceded_regain_title, total_conceded
    )
    conceded_setpiece_fig = build_pie_side(
        df_conceded, setpiece_codes, conceded_sp_title, total_conceded
    )

    return (
        scored_regain_fig,
        scored_setpiece_fig,
        conceded_regain_fig,
        conceded_setpiece_fig,
    )

#------------CALLBACK FOR GOAL DETAIL FOR OPPONENT INSIGHTS TAB-----------------
# Common order of goal types for stacks
OPP_GOAL_TYPE_ORDER = [
    "FT-DT", "FT-AT",
    "MT-DT", "MT-AT",
    "BT-DT", "BT-AT",
    "SP-C", "SP-T", "SP-P", "SP-F",
]


@callback(
    Output("opp-goal-context-by-type", "figure"),
    Input("team-select", "value"),
    Input("opponent-select", "value"),
    Input("opp-goal-context-dimension", "value"),
)
def update_opp_goal_context_scored(selected_squad, selected_opponent, dimension_col):

    """
    Opponent Insights – Goal Detail by Type (GOALS SCORED).

    Uses league_goal_data and shows, for the SELECTED OPPONENT:
      x-axis = chosen dimension (Assist type, Buildup Lane, etc.)
      stacks = Goal Type (FT-DT, FT-AT, ..., SP-F)
      only goals SCORED BY selected_opponent.
    """
    # No selection / ALL -> hint only
    if not selected_opponent or selected_opponent == "ALL":
        fig = go.Figure()
        fig.update_layout(
            title="Select an opponent to view goal detail (scored)",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
            xaxis=dict(showgrid=False, zeroline=False, showline=False),
            yaxis=dict(showgrid=False, zeroline=False, showline=False),
        )
        return fig

    df = league_goal_data.copy()

    # Keep only rows from selected squad file
    if "Team" in df.columns:
        df["Team"] = df["Team"].astype(str).str.strip()
        df = df[df["Team"] == str(selected_squad).strip()].copy()

    # Basic cleaning
    for c in ["Home Team", "Away Team", "Scorer Team", "Goal Type"]:
        if c in df.columns:
            df[c] = df[c].fillna("").astype(str).str.strip()

    # Filter to matches where this opponent is involved
    involved_mask = (
        (df["Home Team"] == selected_opponent)
        | (df["Away Team"] == selected_opponent)
    )
    df = df[involved_mask].copy()

    if df.empty:
        fig = go.Figure()
        fig.update_layout(
            title=f"{selected_opponent} – no tracked matches for goal detail (scored)",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
            xaxis=dict(showgrid=False, zeroline=False, showline=False),
            yaxis=dict(showgrid=False, zeroline=False, showline=False),
        )
        return fig

    # Abbreviated goal types (FT-DT etc)
    df["Goal Abbr"] = df["Goal Type"].apply(abbreviate_goal_type)

    # Only goals scored by this opponent
    df_scored = df[df["Scorer Team"] == selected_opponent].copy()

    if df_scored.empty:
        fig = go.Figure()
        fig.update_layout(
            title=f"{selected_opponent} – no goals scored in tracked matches",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
            xaxis=dict(showgrid=False, zeroline=False, showline=False),
            yaxis=dict(showgrid=False, zeroline=False, showline=False),
        )
        return fig

    # Dimension hygiene
    if dimension_col not in df_scored.columns:
        fig = go.Figure()
        fig.update_layout(
            title=f"{selected_opponent} – {dimension_col} (scored – column missing in data)",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
            xaxis=dict(showgrid=False, zeroline=False, showline=False),
            yaxis=dict(showgrid=False, zeroline=False, showline=False),
        )
        return fig

    df_scored[dimension_col] = df_scored[dimension_col].replace("", pd.NA)
    df_scored = df_scored.dropna(subset=["Goal Abbr", dimension_col]).copy()

    if df_scored.empty:
        fig = go.Figure()
        fig.update_layout(
            title=f"{selected_opponent} – {dimension_col} (scored – no goals recorded with this attribute)",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
            xaxis=dict(showgrid=False, zeroline=False, showline=False),
            yaxis=dict(showgrid=False, zeroline=False, showline=False),
        )
        return fig

    # Group: dimension (x) × goal type (stack)
    grouped = (
        df_scored
        .groupby([dimension_col, "Goal Abbr"])
        .size()
        .unstack("Goal Abbr", fill_value=0)
    )

    grouped = grouped.reindex(columns=OPP_GOAL_TYPE_ORDER, fill_value=0)

    x_categories = list(grouped.index)

    # Optional forced order for lanes
    if dimension_col == "Buildup Lane":
        desired = ["Left", "Centre", "Right"]
        ordered = [x for x in desired if x in grouped.index]
        extras = [x for x in grouped.index if x not in desired]
        x_categories = ordered + extras
        grouped = grouped.reindex(index=x_categories, fill_value=0)

    fig = go.Figure()
    has_data = False

    for gt in OPP_GOAL_TYPE_ORDER:
        if grouped[gt].sum() == 0:
            continue
        has_data = True
        fig.add_trace(
            go.Bar(
                x=x_categories,
                y=grouped[gt],
                name=gt,
                hovertemplate=(
                    "<b>%{x}</b><br>"
                    f"Goal type: {gt}<br>"
                    "Goals scored: %{y}<extra></extra>"
                ),
                hoverlabel=dict(font=dict(family="Segoe UI")),
            )
        )

    if not has_data:
        fig = go.Figure()
        fig.update_layout(
            title=f"{selected_opponent} – {dimension_col} (scored – no goals recorded in this breakdown)",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
            xaxis=dict(showgrid=False, zeroline=False, showline=False),
            yaxis=dict(showgrid=False, zeroline=False, showline=False),
        )
        return fig

    fig.update_layout(
        title=f"{selected_opponent} – {dimension_col} (goals scored, stacked by Goal Type)",
        barmode="stack",
        plot_bgcolor="black",
        paper_bgcolor="black",
        font=dict(color="white", family="Segoe UI"),
        xaxis_title=dimension_col,
        yaxis_title="Goals Scored",
        margin=dict(t=40, b=40),
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=False, tickformat=".0f"),
        bargap=0.3,
        bargroupgap=0.1,
        legend_title="Goal Type",
    )

    return fig


# ------------goals conceded detail chart opponent tab 
@callback(
    Output("opp-goal-context-by-type-conceded", "figure"),
    Input("team-select", "value"),
    Input("opponent-select", "value"),
    Input("opp-goal-context-dimension-conceded", "value"),
)
def update_opp_goal_context_conceded(selected_squad, selected_opponent, dimension_col):

    """
    Opponent Insights – Goal Detail by Type (GOALS CONCEDED).

    Same idea as above, but now from the perspective of goals
    that other teams score AGAINST selected_opponent.
    """
    if not selected_opponent:
        fig = go.Figure()
        fig.update_layout(
            title="Select an opponent to view goal detail (conceded)",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
            xaxis=dict(showgrid=False, zeroline=False, showline=False),
            yaxis=dict(showgrid=False, zeroline=False, showline=False),
        )
        return fig

    df = league_goal_data.copy()

    # Keep only rows from selected squad file
    if "Team" in df.columns:
        df["Team"] = df["Team"].astype(str).str.strip()
        df = df[df["Team"] == str(selected_squad).strip()].copy()

    # Basic cleaning
    for c in ["Home Team", "Away Team", "Scorer Team", "Goal Type"]:
        if c in df.columns:
            df[c] = df[c].fillna("").astype(str).str.strip()

    # Only matches where this opponent is involved
    if selected_opponent != "ALL":
        involved_mask = (
            (df["Home Team"] == selected_opponent)
            | (df["Away Team"] == selected_opponent)
        )
        df = df[involved_mask].copy()
    # else: ALL → keep all matches

    if df.empty:
        fig = go.Figure()
        fig.update_layout(
            title=f"{selected_opponent} – no tracked matches for goal detail (conceded)",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
            xaxis=dict(showgrid=False, zeroline=False, showline=False),
            yaxis=dict(showgrid=False, zeroline=False, showline=False),
        )
        return fig

    df["Goal Abbr"] = df["Goal Type"].apply(abbreviate_goal_type)

    # Goals conceded = scored by someone else
    if selected_opponent == "ALL":
        df_conceded = df.copy()
    else:
        df_conceded = df[df["Scorer Team"] != selected_opponent].copy()

    if df_conceded.empty:
        fig = go.Figure()
        fig.update_layout(
            title=f"{selected_opponent} – no goals conceded in tracked matches",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
            xaxis=dict(showgrid=False, zeroline=False, showline=False),
            yaxis=dict(showgrid=False, zeroline=False, showline=False),
        )
        return fig

    if dimension_col not in df_conceded.columns:
        fig = go.Figure()
        fig.update_layout(
            title=f"{selected_opponent} – {dimension_col} (conceded – column missing in data)",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
            xaxis=dict(showgrid=False, zeroline=False, showline=False),
            yaxis=dict(showgrid=False, zeroline=False, showline=False),
        )
        return fig

    df_conceded[dimension_col] = df_conceded[dimension_col].replace("", pd.NA)
    df_conceded = df_conceded.dropna(subset=["Goal Abbr", dimension_col]).copy()

    if df_conceded.empty:
        fig = go.Figure()
        fig.update_layout(
            title=f"{selected_opponent} – {dimension_col} (conceded – no goals with this attribute)",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
            xaxis=dict(showgrid=False, zeroline=False, showline=False),
            yaxis=dict(showgrid=False, zeroline=False, showline=False),
        )
        return fig

    grouped = (
        df_conceded
        .groupby([dimension_col, "Goal Abbr"])
        .size()
        .unstack("Goal Abbr", fill_value=0)
    )

    grouped = grouped.reindex(columns=OPP_GOAL_TYPE_ORDER, fill_value=0)
    x_categories = list(grouped.index)

    if dimension_col == "Buildup Lane":
        desired = ["Left", "Centre", "Right"]
        ordered = [x for x in desired if x in grouped.index]
        extras = [x for x in grouped.index if x not in desired]
        x_categories = ordered + extras
        grouped = grouped.reindex(index=x_categories, fill_value=0)

    fig = go.Figure()
    has_data = False

    for gt in OPP_GOAL_TYPE_ORDER:
        if grouped[gt].sum() == 0:
            continue
        has_data = True
        fig.add_trace(
            go.Bar(
                x=x_categories,
                y=grouped[gt],
                name=gt,
                hovertemplate=(
                    "<b>%{x}</b><br>"
                    f"Goal type: {gt}<br>"
                    "Goals conceded: %{y}<extra></extra>"
                ),
                hoverlabel=dict(font=dict(family="Segoe UI")),
            )
        )

    if not has_data:
        fig = go.Figure()
        fig.update_layout(
            title=f"{selected_opponent} – {dimension_col} (conceded – no goals recorded in this breakdown)",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
            xaxis=dict(showgrid=False, zeroline=False, showline=False),
            yaxis=dict(showgrid=False, zeroline=False, showline=False),
        )
        return fig

    fig.update_layout(
        title=f"{selected_opponent} – {dimension_col} (goals conceded, stacked by Goal Type)",
        barmode="stack",
        plot_bgcolor="black",
        paper_bgcolor="black",
        font=dict(color="white", family="Segoe UI"),
        xaxis_title=dimension_col,
        yaxis_title="Goals Conceded",
        margin=dict(t=40, b=40),
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=False, tickformat=".0f"),
        bargap=0.3,
        bargroupgap=0.1,
        legend_title="Goal Type",
    )

    return fig


#-----------5-min response charts OPPONENT LAYOUT TAB---------
# -------------------------------------------
# Opponent: 5-minute response after goals
# -------------------------------------------
@callback(
    Output("opp-five-min-response-bar", "figure"),
    Input("team-select", "value"),
    Input("opponent-select", "value"),
)
def update_opp_five_min_response_chart(selected_squad, selected_opponent):
    if not selected_opponent or selected_opponent == "ALL":
        fig = go.Figure()
        fig.update_layout(
            title="Select an opponent to view 5-minute response behaviour",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
            xaxis_title="Situation + Response",
            yaxis_title="Percentage of Windows (%)",
            xaxis=dict(showgrid=False, zeroline=False, showline=False),
            yaxis=dict(showgrid=False, zeroline=False, showline=False),
        )
        return fig

    df = league_goal_data.copy()

    # Keep only rows from selected squad file
    if "Team" in df.columns:
        df["Team"] = df["Team"].astype(str).str.strip()
        df = df[df["Team"] == str(selected_squad).strip()].copy()

    metrics_df = build_five_min_response_df_for_team(
        df, selected_opponent
    )

    # ---------------------------
    # Fixed x-axis layout
    # ---------------------------
    spacer_label = " "
    full_situations = [
        "AS – Scored again",
        "AS – Conceded",
        spacer_label,
        "AC – Scored",
        "AC – Conceded",
    ]

    fig = go.Figure()

    if metrics_df.empty:
        for cat in full_situations:
            fig.add_trace(
                go.Bar(
                    x=[cat],
                    y=[0.0001],
                    marker_color="rgba(0,0,0,0)",
                    showlegend=False,
                    hoverinfo="skip",
                )
            )

        fig.update_layout(
            title=f"{selected_opponent} – 5-Minute Response After Goals (No Data)",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
            xaxis_title="Situation + Response",
            yaxis_title="Percentage of Windows (%)",
            xaxis=dict(showgrid=False, zeroline=False, showline=False),
            yaxis=dict(showgrid=False, zeroline=False, showline=False),
        )
        fig.update_xaxes(categoryorder="array", categoryarray=full_situations)
        return fig

    # Normalised outcome labels
    legend_labels = {
        "Scored within 5 mins": "Scored again",
        "Conceded within 5 mins": "Conceded",
        "Scored again within 5 mins": "Scored again",
        "Conceded again within 5 mins": "Conceded again",
    }

    # Iterate combos so empty ones still render
    for situation, outcome, label in (
        ("After Scoring", "Scored again within 5 mins", "AS – Scored again"),
        ("After Scoring", "Conceded within 5 mins", "AS – Conceded"),
        ("After Conceding", "Scored within 5 mins", "AC – Scored"),
        ("After Conceding", "Conceded again within 5 mins", "AC – Conceded"),
    ):
        subset = metrics_df[
            (metrics_df["Situation"] == situation) &
            (metrics_df["Outcome"] == outcome)
        ]

        if subset.empty:
            fig.add_trace(
                go.Bar(
                    x=[label],
                    y=[0.0001],
                    marker_color="rgba(0,0,0,0)",
                    showlegend=False,
                    hoverinfo="skip",
                )
            )
            continue

        row = subset.iloc[0]
        pct_val = row["Pct"]
        count = row["Count"]
        base = row["Base"]

        legend = legend_labels.get(outcome, outcome)

        fig.add_trace(
            go.Bar(
                name=legend,
                x=[label],
                y=[pct_val],
                text=[count],
                textposition="outside",
                customdata=[[count, base]],
                hovertemplate=(
                    "Situation + Response: %{x}<br>"
                    "Windows: %{customdata[0]} of %{customdata[1]}<br>"
                    "Percentage: %{y:.1f}%<extra></extra>"
                ),
                hoverlabel=dict(font=dict(family="Segoe UI")),
            )
        )

    # Add explicit spacer
    fig.add_trace(
        go.Bar(
            x=[spacer_label],
            y=[0.0001],
            marker_color="rgba(0,0,0,0)",
            showlegend=False,
            hoverinfo="skip",
        )
    )

    fig.update_layout(
        barmode="group",
        title=f"{selected_opponent} – 5-Minute Response After Goals",
        plot_bgcolor="black",
        paper_bgcolor="black",
        font=dict(color="white", family="Segoe UI"),
        xaxis_title="Situation + Response",
        yaxis_title="Percentage of Windows (%)",
        yaxis=dict(
            showgrid=True,
            gridcolor="#333333",
            zeroline=False,
        ),
        yaxis_tickformat=".0f",
        legend_title="Outcome",
        margin=dict(t=40, b=40),
    )

    fig.update_xaxes(
        categoryorder="array",
        categoryarray=full_situations,
    )

    return fig


# ------------------------------------------------------
# Opponent: 5-minute response by teams involved - OPPONENT LAYOUT TAB
# ------------------------------------------------------
@callback(
    Output("opp-five-min-response-opponent-bar", "figure"),
    Input("team-select", "value"),
    Input("opponent-select", "value"),
)
def update_opp_five_min_response_by_opponent_chart(selected_squad, selected_opponent):
    if not selected_opponent or selected_opponent == "ALL":
        fig = go.Figure()
        fig.update_layout(
            title="Select a specific opponent to view who they hurt / who hurts them in 5-minute swings",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
            xaxis_title="Situation + Response",
            yaxis_title="Number of 5-Minute Response Events",
            xaxis=dict(showgrid=False, zeroline=False, showline=False),
            yaxis=dict(showgrid=False, zeroline=False, showline=False),
        )
        return fig

    df_base = league_goal_data.copy()

    # Keep only rows from selected squad file
    if "Team" in df_base.columns:
        df_base["Team"] = df_base["Team"].astype(str).str.strip()
        df_base = df_base[df_base["Team"] == str(selected_squad).strip()].copy()

    df = build_five_min_response_by_opponent(df_base, selected_opponent)

    if df.empty:
        fig = go.Figure()
        fig.update_layout(
            title=f"{selected_opponent} – 5-Minute Response by Opponent (No Data)",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
            xaxis_title="Situation + Response",
            yaxis_title="Number of 5-Minute Response Events",
            xaxis=dict(showgrid=False, zeroline=False, showline=False),
            yaxis=dict(showgrid=False, zeroline=False, showline=False),
        )
        return fig

    # Map outcomes to short labels
    def map_outcome_short(row):
        if row["Situation"] == "After Scoring":
            if "Scored again" in row["Outcome"]:
                return "Scored again"
            else:
                return "Conceded"
        else:  # After Conceding
            if "Scored within" in row["Outcome"]:
                return "Scored"
            else:
                return "Conceded"

    df["OutcomeShort"] = df.apply(map_outcome_short, axis=1)

    # Normalise opponent names for colours
    df["OpponentTeamNorm"] = df["OpponentTeam"].apply(
        lambda name: normalize_club(name) if "normalize_club" in globals() else str(name).strip()
    )

    combo_order = [
        ("After Scoring", "Scored again"),
        ("After Scoring", "Conceded"),
        ("After Conceding", "Scored"),
        ("After Conceding", "Conceded"),
    ]

    label_map = {
        ("After Scoring", "Scored again"): "AS – Scored again",
        ("After Scoring", "Conceded"): "AS – Conceded",
        ("After Conceding", "Scored"): "AC – Scored",
        ("After Conceding", "Conceded"): "AC – Conceded",
    }

    spacer_label = " "  # visual gap between AS and AC blocks

    fig = go.Figure()
    seen_opponents = set()

    for situation, outcome_short in combo_order:
        x_label = label_map[(situation, outcome_short)]

        combo_df = df[
            (df["Situation"] == situation) &
            (df["OutcomeShort"] == outcome_short)
        ]

        if combo_df.empty:
            fig.add_trace(
                go.Bar(
                    name="(no events)",
                    x=[x_label],
                    y=[0.0001],
                    marker_color="rgba(0,0,0,0)",
                    showlegend=False,
                    hoverinfo="skip",
                )
            )
            continue

        for opp in combo_df["OpponentTeam"].unique():
            sub = combo_df[combo_df["OpponentTeam"] == opp]
            total_count = int(sub["Count"].sum())

            match_lists = sub["Matches"].tolist()
            flat = sorted(set(chain.from_iterable(
                m if isinstance(m, list) else [m] for m in match_lists
            )))
            matches_str = ", ".join(str(m) for m in flat) if flat else "–"

            opp_norm = (
                normalize_club(opp)
                if "normalize_club" in globals()
                else str(opp).strip()
            )
            color = TEAM_COLORS.get(opp_norm, DEFAULT_COLOR)

            fig.add_trace(
                go.Bar(
                    name=opp,
                    x=[x_label],
                    y=[total_count],
                    marker_color=color,
                    legendgroup=opp,
                    showlegend=(opp not in seen_opponents),
                    customdata=[[matches_str]],
                    hovertemplate=(
                        "Situation: " + situation + "<br>"
                        "Outcome: " + outcome_short + "<br>"
                        "Team involved: " + opp + "<br>"
                        "Events: %{y}<br>"
                        "Matches: %{customdata[0]}<extra></extra>"
                    ),
                )
            )
            seen_opponents.add(opp)

    # Spacer
    fig.add_trace(
        go.Bar(
            name="spacer",
            x=[spacer_label],
            y=[0.0001],
            marker_color="rgba(0,0,0,0)",
            showlegend=False,
            hoverinfo="skip",
        )
    )

    fig.update_layout(
        barmode="stack",
        title=f"{selected_opponent} – 5-Minute Response by Opponent",
        plot_bgcolor="black",
        paper_bgcolor="black",
        font=dict(color="white", family="Segoe UI"),
        xaxis_title="Situation + Response",
        yaxis_title="Number of 5-Minute Response Events",
        yaxis=dict(
            showgrid=True,
            gridcolor="#333333",
            zeroline=False,
        ),
        yaxis_tickformat=".0f",
        legend_title="Opponent",
        margin=dict(t=40, b=40),
        hoverlabel=dict(font=dict(family="Segoe UI")),
    )

    fig.update_xaxes(
        categoryorder="array",
        categoryarray=[
            "AS – Scored again",
            "AS – Conceded",
            spacer_label,
            "AC – Scored",
            "AC – Conceded",
        ],
    )

    return fig


#-----callback for goal map - opponent insights map---------
@callback(
    Output("opp-goal-map-figure", "figure"),
    [
        Input("team-select", "value"),
        Input("opponent-select", "value"),
        Input("opp-goalmap-filter", "value"),
    ]
)
def update_opp_goal_map(selected_squad, selected_opponent, goal_filter):
    # We only want this when a specific opponent is chosen
    if not selected_opponent:
        fig = go.Figure()
        fig.update_layout(
            title="Select a specific opponent to view their goal location map",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(family="Segoe UI", color="white"),
            xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
            yaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
        )
        return fig

    df_base = league_goal_data.copy()

    # Keep only rows from selected squad file
    if "Team" in df_base.columns:
        df_base["Team"] = df_base["Team"].astype(str).str.strip()
        df_base = df_base[df_base["Team"] == str(selected_squad).strip()].copy()

    if selected_opponent == "ALL":
        # League-wide goal map
        return build_goal_map_for_team(df_base, "ALL", goal_filter)
    else:
        # Single-opponent goal map
        return build_goal_map_for_team(df_base, selected_opponent, goal_filter)



# callback for first goal value chart opponent insight tab----
@callback(
    Output("opp-first-goal-index-bar", "figure"),
    Input("team-select", "value"),
    Input("opponent-select", "value"),
)
def update_opp_first_goal_index_chart(selected_squad, selected_opponent):
    # Need a specific opponent – ALL doesn't make sense here
    if not selected_opponent or selected_opponent == "ALL":
        fig = go.Figure()
        fig.update_layout(
            title="Select a specific opponent to view First Goal Value profile",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
            xaxis_title="Scenario",
            yaxis_title="Percentage of Games (%)",
            xaxis=dict(showgrid=False, zeroline=False, showline=False),
            yaxis=dict(showgrid=False, zeroline=False, showline=False),
        )
        return fig

    df_base = league_goal_data.copy()

    # Keep only rows from selected squad file
    if "Team" in df_base.columns:
        df_base["Team"] = df_base["Team"].astype(str).str.strip()
        df_base = df_base[df_base["Team"] == str(selected_squad).strip()].copy()

    metrics_df = build_first_goal_index_df_for_team(
        df_base, selected_opponent
    )

    # If no games at all (or all 0s)
    if metrics_df.empty or metrics_df["Games"].sum() == 0:
        fig = go.Figure()
        fig.update_layout(
            title=f"{selected_opponent} – First Goal Value Index (No Data)",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
            xaxis_title="Scenario",
            yaxis_title="Percentage of Games (%)",
            xaxis=dict(showgrid=False, zeroline=False),
            yaxis=dict(showgrid=False, zeroline=False, tickformat=".0f"),
        )
        return fig

    # Percentages per scenario
    def pct(part, whole):
        return (part / whole * 100.0) if whole > 0 else 0.0

    metrics_df["WinPct"] = metrics_df.apply(lambda r: pct(r["Wins"], r["Games"]), axis=1)
    metrics_df["DrawPct"] = metrics_df.apply(lambda r: pct(r["Draws"], r["Games"]), axis=1)
    metrics_df["LossPct"] = metrics_df.apply(lambda r: pct(r["Losses"], r["Games"]), axis=1)

    scenario_order = ["Scored First", "Conceded First"]

    # Helper to pull values in fixed scenario order
    def values_for(column):
        vals = []
        for scen in scenario_order:
            row = metrics_df[metrics_df["Scenario"] == scen]
            if not row.empty:
                vals.append(float(row.iloc[0][column]))
            else:
                vals.append(0.0)
        return vals

    win_pct_vals = values_for("WinPct")
    draw_pct_vals = values_for("DrawPct")
    loss_pct_vals = values_for("LossPct")

    games_vals = values_for("Games")  # total games for hover

    fig = go.Figure()

    # Win / Draw / Loss traces (grouped)
    fig.add_trace(
        go.Bar(
            name="Win",
            x=scenario_order,
            y=win_pct_vals,
            customdata=list(zip(games_vals, values_for("Wins"))),
            hovertemplate=(
                "Scenario: %{x}<br>"
                "Result: Win<br>"
                "Games: %{customdata[0]}<br>"
                "Wins: %{customdata[1]}<br>"
                "Win rate: %{y:.1f}%<extra></extra>"
            ),
        )
    )

    fig.add_trace(
        go.Bar(
            name="Draw",
            x=scenario_order,
            y=draw_pct_vals,
            customdata=list(zip(games_vals, values_for("Draws"))),
            hovertemplate=(
                "Scenario: %{x}<br>"
                "Result: Draw<br>"
                "Games: %{customdata[0]}<br>"
                "Draws: %{customdata[1]}<br>"
                "Draw rate: %{y:.1f}%<extra></extra>"
            ),
        )
    )

    fig.add_trace(
        go.Bar(
            name="Loss",
            x=scenario_order,
            y=loss_pct_vals,
            customdata=list(zip(games_vals, values_for("Losses"))),
            hovertemplate=(
                "Scenario: %{x}<br>"
                "Result: Loss<br>"
                "Games: %{customdata[0]}<br>"
                "Losses: %{customdata[1]}<br>"
                "Loss rate: %{y:.1f}%<extra></extra>"
            ),
        )
    )

    fig.update_layout(
        barmode="group",
        title=f"{selected_opponent} – First Goal Value Index",
        plot_bgcolor="black",
        paper_bgcolor="black",
        font=dict(color="white", family="Segoe UI"),
        xaxis=dict(
            title="Scenario",
            categoryorder="array",
            categoryarray=scenario_order,
            showgrid=False,
            zeroline=False,
        ),
        yaxis=dict(
            title="Percentage of Games (%)",
            showgrid=True,
            gridcolor="#333333",
            zeroline=False,
            tickformat=".0f",
        ),
        legend_title="Final Result",
        hoverlabel=dict(font=dict(family="Segoe UI")),
        margin=dict(t=40, b=40),
    )

    return fig


# -------------------------------------------------------------------------
# Opponent Match List Table - Opponent Insights Tab
# -------------------------------------------------------------------------
@callback(
    Output("opp-match-list-table", "children"),
    Input("team-select", "value"),
    Input("opponent-select", "value"),
)
def update_opp_match_list(selected_squad, selected_opponent):
    # If no selection OR ALL -> blank area
    if not selected_opponent or selected_opponent == "ALL":
        return html.P(
            "",
            style={
                "color": "white",
                "fontFamily": base_font["fontFamily"],
                "fontSize": "13px",
                "margin": "10px 0",
            },
        )

    df = league_goal_data.copy()

    # Keep only rows from selected squad file
    if "Team" in df.columns:
        df["Team"] = df["Team"].astype(str).str.strip()
        df = df[df["Team"] == str(selected_squad).strip()].copy()

    # --------------------------
    # FILTER: all matches involving the selected opponent
    # --------------------------
    mask = (
        (df["Home Team"] == selected_opponent) |
        (df["Away Team"] == selected_opponent)
    )
    matches = df.loc[mask].copy()

    if matches.empty:
        return html.P(
            f"No matches found involving {selected_opponent}.",
            style={
                "color": "white",
                "fontFamily": base_font["fontFamily"],
                "fontSize": "13px",
                "margin": "10px 0",
            },
        )

    # Only one row per match
    matches = (
        matches
        .groupby("Match ID")
        .first()
        .reset_index()
    )

    # Ensure Recording column exists
    if "Recording" not in matches.columns:
        matches["Recording"] = ""

    # Proper date handling
    matches["Match Date"] = pd.to_datetime(
        matches["Match Date"],
        errors="coerce"
    )

    # Most recent first
    matches = matches.sort_values("Match Date", ascending=False)

    # Format after sorting for display
    matches["Match Date"] = matches["Match Date"].dt.strftime("%d-%m-%Y")

    # --------------------------
    # RESULT COLUMN (W / D / L)
    # from the perspective of selected_opponent
    # --------------------------
    def compute_result(row):
        score = row.get("Full-score", "")
        home = row.get("Home Team", "")
        away = row.get("Away Team", "")

        if not isinstance(score, str) or "-" not in score:
            return ""

        try:
            home_g, away_g = score.split("-")
            home_g = int(home_g.strip())
            away_g = int(away_g.strip())
        except ValueError:
            return ""

        if home_g == away_g:
            return "D"

        if selected_opponent == home:
            return "W" if home_g > away_g else "L"
        elif selected_opponent == away:
            return "W" if away_g > home_g else "L"
        else:
            return ""

    matches["Result"] = matches.apply(compute_result, axis=1)

    display_cols = [
        "Match Date",
        "Match ID",
        "Recording",
        "Home Team",
        "Away Team",
        "Half-score",
        "Full-score",
        "Result",
    ]

    table_df = matches[display_cols].copy()

    return dash_table.DataTable(
        data=table_df.to_dict("records"),
        columns=[{"name": col, "id": col} for col in table_df.columns],
        style_table={
            "overflowX": "auto",
            "border": "1px solid white",
            "borderRadius": "6px",
        },
        style_as_list_view=True,
        style_header={
            "backgroundColor": "black",
            "color": "white",
            "fontFamily": title_font["fontFamily"],
            "fontSize": "13px",
            "border": "1px solid #333",
            "textAlign": "left",
        },
        style_cell={
            "backgroundColor": "black",
            "color": "white",
            "fontFamily": base_font["fontFamily"],
            "fontSize": "12px",
            "border": "1px solid #333",
            "padding": "6px",
            "textAlign": "left",
        },
        style_data_conditional=[
            {
                "if": {"row_index": "odd"},
                "backgroundColor": "#303332",
            }
        ],
        sort_action="none",
        page_size=50,
    )


#----callback for goals per min - opponent insights tab-----------
@callback(
    Output("opp-goals-per-minute", "figure"),
    [
        Input("opp-sort-high-goals", "n_clicks"),
        Input("opp-sort-low-goals", "n_clicks"),
        Input("opp-sort-total-goals", "n_clicks"),
        Input("team-select", "value"),
        Input("opponent-select", "value"),
    ]
)
def update_opp_goals_per_min(
    high_clicks, low_clicks, total_clicks, selected_squad, selected_opponent):

    # If nothing selected, show message
    if not selected_opponent:
        fig = go.Figure()
        fig.update_layout(
            title="Select an opponent to view goals per minute",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family=base_font["fontFamily"]),
            xaxis=dict(showgrid=False, zeroline=False),
            yaxis=dict(showgrid=False, zeroline=False),
        )
        return fig

    # -----------------------------
    # Minutes dataframe (players of selected opponent)
    # -----------------------------
    minutes_df = player_data.copy()

    # Keep only rows from selected squad file
    if "Team" in minutes_df.columns:
        minutes_df["Team"] = minutes_df["Team"].astype(str).str.strip()
        minutes_df = minutes_df[minutes_df["Team"] == str(selected_squad).strip()].copy()

    if "Country" in minutes_df.columns:
        minutes_df["Country"] = minutes_df["Country"].astype(str).str.strip()
        minutes_df = minutes_df[minutes_df["Country"] == selected_opponent].copy()

    minutes_df["Mins Played"] = pd.to_numeric(minutes_df["Mins Played"], errors="coerce")

    # -----------------------------
    # Goals dataframe (goals scored BY selected opponent)
    # -----------------------------
    goals_df = league_goal_data.copy()

    # Keep only rows from selected squad file
    if "Team" in goals_df.columns:
        goals_df["Team"] = goals_df["Team"].astype(str).str.strip()
        goals_df = goals_df[goals_df["Team"] == str(selected_squad).strip()].copy()

    # Normalise key columns
    for c in ["Home Team", "Away Team", "Scorer Team", "Scorer"]:
        if c in goals_df.columns:
            goals_df[c] = goals_df[c].fillna("").astype(str).str.strip()

    # Only goals where this team is the scorer
    goals_df = goals_df[goals_df["Scorer Team"] == selected_opponent].copy()

    # Optional: keep only games where they are actually home/away (safety)
    if "Home Team" in goals_df.columns and "Away Team" in goals_df.columns:
        mask_involved = (
            (goals_df["Home Team"] == selected_opponent) |
            (goals_df["Away Team"] == selected_opponent)
        )
        goals_df = goals_df[mask_involved].copy()

    # Strip/upper scorer and drop OG if used in your data
    goals_df["Scorer"] = goals_df["Scorer"].astype(str).str.strip()
    goals_df = goals_df[goals_df["Scorer"].str.upper() != "OG"].copy()

    # ============================
    #   PER-PLAYER GOAL CONTEXT
    # ============================
    def summarise_finish_type(s):
        s_clean = s.dropna()
        if s_clean.empty:
            return "No data"
        counts = s_clean.value_counts()
        parts = []
        for val, cnt in counts.items():
            label = str(val)
            lower = label.lower()
            if lower.startswith("left"):
                label = "L"
            elif lower.startswith("right"):
                label = "R"
            elif "head" in lower:
                label = "H"
            parts.append(f"{cnt}-{label}")
        return ", ".join(parts)

    def summarise_ftf(s):
        s_clean = s.dropna().astype(str).str.strip().str.lower()
        if s_clean.empty:
            return "No data"
        total = len(s_clean)
        yes_count = s_clean.isin(["yes", "y", "1", "true"]).sum()
        return f"{yes_count} out of {total}"

    def summarise_minutes(s):
        s_clean = s.dropna()
        if s_clean.empty:
            return "No data"
        try:
            vals = sorted(int(v) for v in s_clean)
        except Exception:
            vals = list(s_clean)
        return ", ".join(str(v) for v in vals)

    # Extra context only if those columns exist
    if (
        not goals_df.empty
        and all(col in goals_df.columns for col in ["Finish Type", "First-time finish", "Minute Scored"])
    ):
        extra_context = (
            goals_df
            .groupby("Scorer")
            .agg({
                "Finish Type": summarise_finish_type,
                "First-time finish": summarise_ftf,
                "Minute Scored": summarise_minutes,
            })
            .reset_index()
            .rename(columns={
                "Scorer": "Player Name",
                "Finish Type": "Finish Summary",
                "First-time finish": "FTF Summary",
                "Minute Scored": "Minutes Summary",
            })
        )
    else:
        extra_context = pd.DataFrame(
            columns=["Player Name", "Finish Summary", "FTF Summary", "Minutes Summary"]
        )

    # -----------------------------
    # Totals per player
    # -----------------------------
    goals_count = goals_df["Scorer"].value_counts().reset_index()
    goals_count.columns = ["Player Name", "Goals"]

    mins_grouped = minutes_df.groupby("Player Name", as_index=False)["Mins Played"].sum()

    merged_df = pd.merge(mins_grouped, goals_count, on="Player Name", how="left").fillna(0)
    merged_df["Goals"] = merged_df["Goals"].astype(int)
    merged_df = merged_df[merged_df["Goals"] > 0].copy()

    if merged_df.empty:
        fig = go.Figure()
        fig.update_layout(
            title=f"{selected_opponent} – No goals scored in tracked matches",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family=base_font["fontFamily"]),
            xaxis=dict(showgrid=False, zeroline=False),
            yaxis=dict(showgrid=False, zeroline=False),
        )
        return fig

    # mins per goal (raw + display)
    merged_df["Goals Per Minute"] = merged_df.apply(
        lambda r: (r["Mins Played"] / r["Goals"]) if r["Goals"] > 0 else 0,
        axis=1,
    )
    merged_df["Actual Goals Per Minute"] = merged_df["Goals Per Minute"]
    merged_df["Display Goals Per Minute"] = np.ceil(
        merged_df["Goals Per Minute"]
    ).clip(upper=270)

    # attach aggregated goal context
    merged_df = merged_df.merge(extra_context, on="Player Name", how="left")
    for col in ["Finish Summary", "FTF Summary", "Minutes Summary"]:
        if col not in merged_df.columns:
            merged_df[col] = "No data"
        merged_df[col] = merged_df[col].fillna("No data")

    # -----------------------------
    # Which view: MPG vs Total Goals
    # -----------------------------
    trig = ctx.triggered_id
    view_mode = "gpm" if trig != "opp-sort-total-goals" else "goals"

    # sorting
    if view_mode == "goals":
        merged_df = merged_df.sort_values("Goals", ascending=False)
    elif trig == "opp-sort-low-goals":
        merged_df = merged_df.sort_values("Goals Per Minute", ascending=False)
    else:
        merged_df = merged_df.sort_values("Goals Per Minute", ascending=True)

    # -----------------------------
    # Build figure
    # -----------------------------
    if view_mode == "goals":
        # Add Opponent team for each goal using get_against_team helper
        goals_df2 = goals_df.copy()
        if "Home Team" in goals_df2.columns and "Away Team" in goals_df2.columns:
            goals_df2["Against Team"] = goals_df2.apply(
                lambda r: get_against_team(r, selected_opponent), axis=1
            )
        else:
            goals_df2["Against Team"] = "Unknown"

        goals_df2 = goals_df2.dropna(subset=["Against Team"])

        by_opp = (
            goals_df2.groupby(["Scorer", "Against Team"])
            .size()
            .reset_index(name="Goals")
            .rename(columns={"Scorer": "Player Name", "Against Team": "Opponent"})
        )

        by_opp = by_opp[by_opp["Player Name"].isin(merged_df["Player Name"])]

        fig = go.Figure()
        for opp in sorted(by_opp["Opponent"].unique()):
            sub = by_opp[by_opp["Opponent"] == opp]
            fig.add_trace(
                go.Bar(
                    x=sub["Player Name"],
                    y=sub["Goals"],
                    name=opp,
                    marker_color=TEAM_COLORS.get(str(opp).strip(), "gray"),
                    text=sub["Goals"],
                    textposition="outside",
                    hovertemplate=(
                        "Player: %{x}<br>"
                        f"Opponent: {opp}<br>"
                        "Goals vs Opp: %{y}<extra></extra>"
                    ),
                )
            )

        fig.update_yaxes(
            title="Goals",
            tick0=0,
            dtick=5,
            rangemode="tozero",
            autorange=True,
            showgrid=False,
            zeroline=True,
            zerolinecolor="#555",
        )
        fig.update_traces(cliponaxis=False)

        fig.update_layout(
            barmode="stack",
            title=f"{selected_opponent} – Goals by Opponent (click legend to filter)",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(size=16, family="Segoe UI", color="white"),
            xaxis=dict(
                tickfont=dict(size=14),
                categoryorder="array",
                categoryarray=list(merged_df["Player Name"]),
                showgrid=False,
            ),
            yaxis=dict(tickfont=dict(size=14)),
            bargap=0.0,
            bargroupgap=0.1,
            hoverlabel=dict(font=dict(family="Segoe UI")),
        )

    else:
        customdata = merged_df[
            [
                "Goals",
                "Mins Played",
                "Display Goals Per Minute",
                "Finish Summary",
                "FTF Summary",
                "Minutes Summary",
            ]
        ].values

        fig = px.bar(
            merged_df,
            x="Player Name",
            y="Display Goals Per Minute",
            color_discrete_sequence=["#77BCE8"],
            title=f"{selected_opponent} – Minutes per Goal (rounded up, capped at 270)",
            template="plotly_dark",
            text="Goals",
        )
        fig.update_traces(
            textposition="outside",
            marker_line_width=0,
            customdata=customdata,
            hovertemplate=(
                "Player: %{x}<br>"
                "Goals: %{customdata[0]}<br>"
                "Mins Played: %{customdata[1]:.0f}<br>"
                "Mins per Goal: %{customdata[2]:.0f}<br>"
                "Finish Type: %{customdata[3]}<br>"
                "First-time finish: %{customdata[4]}<br>"
                "Minutes scored: %{customdata[5]}<extra></extra>"
            ),
        )

        fig.update_layout(
            yaxis_title="Minutes per Goal",
            uniformtext_minsize=10,
            uniformtext_mode="hide",
            bargap=0.0,
            bargroupgap=0.1,
            font=dict(size=16, family="Segoe UI", color="white"),
            xaxis=dict(tickfont=dict(size=14)),
            yaxis=dict(tickfont=dict(size=14)),
            hoverlabel=dict(font=dict(family="Segoe UI")),
            plot_bgcolor="black",
            paper_bgcolor="black",
        )

    return fig


#----callback for assists per min - opponent insights tab-----------
@callback(
    Output("opp-assists-per-minute", "figure"),
    [
        Input("opp-sort-high-assists", "n_clicks"),
        Input("opp-sort-low-assists", "n_clicks"),
        Input("opp-sort-total-assists", "n_clicks"),
        Input("team-select", "value"),
        Input("opponent-select", "value"),
    ]
)
def update_opp_assists_chart(
    high_clicks, low_clicks, total_clicks, selected_squad, selected_opponent):
    # No opponent selected
    if not selected_opponent:
        fig = go.Figure()
        fig.update_layout(
            title="Select an opponent to view assists per minute",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family=base_font["fontFamily"]),
            xaxis=dict(showgrid=False, zeroline=False),
            yaxis=dict(showgrid=False, zeroline=False),
        )
        return fig

    # -----------------------------
    # Minutes (per player) for selected opponent
    # -----------------------------
    minutes_df = player_data.copy()

    # Keep only rows from selected squad file
    if "Team" in minutes_df.columns:
        minutes_df["Team"] = minutes_df["Team"].astype(str).str.strip()
        minutes_df = minutes_df[minutes_df["Team"] == str(selected_squad).strip()].copy()

    if "Country" in minutes_df.columns:
        minutes_df["Country"] = minutes_df["Country"].astype(str).str.strip()
        minutes_df = minutes_df[minutes_df["Country"] == selected_opponent].copy()

    minutes_df["Mins Played"] = pd.to_numeric(minutes_df["Mins Played"], errors="coerce")
    minutes_summary = (
        minutes_df.groupby("Player Name", as_index=False)["Mins Played"].sum()
    )

    # -----------------------------
    # Goal events – only goals scored BY selected_opponent
    # -----------------------------
    events = league_goal_data.copy()

    # Keep only rows from selected squad file
    if "Team" in events.columns:
        events["Team"] = events["Team"].astype(str).str.strip()
        events = events[events["Team"] == str(selected_squad).strip()].copy()

    # Basic cleaning
    for c in ["Home Team", "Away Team", "Scorer Team"]:
        if c in events.columns:
            events[c] = events[c].fillna("").astype(str).str.strip()

    events = events[events["Scorer Team"] == selected_opponent].copy()

    if events.empty:
        fig = go.Figure()
        fig.update_layout(
            title=f"{selected_opponent} – No assists recorded in tracked matches",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family=base_font["fontFamily"]),
            xaxis=dict(showgrid=False, zeroline=False),
            yaxis=dict(showgrid=False, zeroline=False),
        )
        return fig

    # Decide which assist column to use: "Assists" (Olyroos tab) OR "Assist" (league-wide tab)
    if "Assists" in events.columns:
        assist_col = "Assists"
    elif "Assist" in events.columns:
        assist_col = "Assist"
    else:
        fig = go.Figure()
        fig.update_layout(
            title=f"{selected_opponent} – No assist column found (expected 'Assist' or 'Assists')",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family=base_font["fontFamily"]),
            xaxis=dict(showgrid=False, zeroline=False),
            yaxis=dict(showgrid=False, zeroline=False),
        )
        return fig

    # Make sure team is actually home/away and derive Opponent
    if "Home Team" in events.columns and "Away Team" in events.columns:
        mask_involved = (
            (events["Home Team"] == selected_opponent) |
            (events["Away Team"] == selected_opponent)
        )
        events = events[mask_involved].copy()
        events["Opponent"] = events.apply(
            lambda r: get_against_team(r, selected_opponent), axis=1
        )
    else:
        events["Opponent"] = "Unknown"

    # -----------------------------
    # Count assists per player (overall)
    # -----------------------------
    assists_series = events[assist_col].fillna("").astype(str).str.strip()
    assists_series = assists_series[assists_series.str.len() > 0]
    assist_counts = assists_series.value_counts().reset_index()
    assist_counts.columns = ["Player Name", "Assists"]

    if assist_counts.empty:
        fig = go.Figure()
        fig.update_layout(
            title=f"{selected_opponent} – No assists recorded in tracked matches",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family=base_font["fontFamily"]),
            xaxis=dict(showgrid=False, zeroline=False),
            yaxis=dict(showgrid=False, zeroline=False),
        )
        return fig

    # -----------------------------
    # Merge with minutes (minutes may be missing!)
    # -----------------------------
    merged = assist_counts.merge(minutes_summary, on="Player Name", how="left")
    merged["Mins Played"] = pd.to_numeric(merged["Mins Played"], errors="coerce")

    # Placeholder – league tab doesn't have detailed assist types
    merged["Assist Type Summary"] = "No data"

    # Which button?
    trig = ctx.triggered_id or "opp-sort-high-assists"
    view_mode = "per_minute"
    if trig == "opp-sort-total-assists":
        view_mode = "assists"

    # -----------------------------
    # Build "Total Assists" view (always available if we have assists)
    # -----------------------------
    if view_mode == "assists":
        ev_assists = events.copy()
        ev_assists["Assist_Player"] = ev_assists[assist_col].fillna("").astype(str).str.strip()
        ev_assists = ev_assists[ev_assists["Assist_Player"].str.len() > 0]

        by_opp = (
            ev_assists.groupby(["Assist_Player", "Opponent"])
                      .size()
                      .reset_index(name="Assists")
                      .rename(columns={"Assist_Player": "Player Name"})
        )
        by_opp = by_opp[by_opp["Player Name"].isin(merged["Player Name"])]

        # Sort by total assists desc
        merged_sorted = merged.sort_values("Assists", ascending=False)
        x_order = list(merged_sorted["Player Name"])

        fig = go.Figure()
        for opp in sorted(by_opp["Opponent"].dropna().unique()):
            sub = by_opp[by_opp["Opponent"] == opp]
            fig.add_trace(
                go.Bar(
                    x=sub["Player Name"],
                    y=sub["Assists"],
                    name=opp,
                    marker_color=TEAM_COLORS.get(str(opp).strip(), "gray"),
                    text=sub["Assists"],
                    textposition="outside",
                    hovertemplate=(
                        "Player: %{x}<br>"
                        f"Opponent: {opp}<br>"
                        "Assists vs Opp: %{y}<extra></extra>"
                    ),
                )
            )

        fig.update_yaxes(
            title="Assists",
            tick0=0,
            rangemode="tozero",
            autorange=True,
            showgrid=True,
            gridcolor="#333",
            zeroline=True,
            zerolinecolor="#555",
        )
        fig.update_traces(cliponaxis=False)
        fig.update_layout(
            barmode="stack",
            title=f"{selected_opponent} – Assists by Opponent (click legend to filter)",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI", size=16),
            xaxis=dict(
                showgrid=False,
                tickfont=dict(size=14),
                tickangle=-30,
                categoryorder="array",
                categoryarray=x_order,
            ),
            yaxis=dict(tickfont=dict(size=14)),
            bargap=0.0,
            bargroupgap=0.1,
            margin=dict(t=40, b=60),
            hoverlabel=dict(font=dict(family="Segoe UI")),
        )
        return fig

    # -----------------------------
    # Build "Per Minute" view – only for players with minutes
    # -----------------------------
    pm_df = merged.copy()
    pm_df = pm_df[(pm_df["Mins Played"].notna()) & (pm_df["Mins Played"] > 0)]

    if pm_df.empty:
        fig = go.Figure()
        fig.update_layout(
            title=f"{selected_opponent} – Assists recorded but no minutes available for those players",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family=base_font["fontFamily"]),
            xaxis=dict(showgrid=False, zeroline=False),
            yaxis=dict(showgrid=False, zeroline=False),
        )
        return fig

    pm_df["Assists Per Minute"] = pm_df["Mins Played"] / pm_df["Assists"]
    pm_df["Actual Assists Per Minute"] = pm_df["Assists Per Minute"]
    pm_df["Display Assists Per Minute"] = np.ceil(
        pm_df["Assists Per Minute"]
    ).clip(upper=270)

    # Sorting for per-minute view
    if trig == "opp-sort-low-assists":
        pm_df = pm_df.sort_values("Assists Per Minute", ascending=False)
    else:
        pm_df = pm_df.sort_values("Assists Per Minute", ascending=True)

    x_order = list(pm_df["Player Name"])
    customdata = pm_df[
        [
            "Assists",
            "Mins Played",
            "Display Assists Per Minute",
            "Assist Type Summary",
        ]
    ].values

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=pm_df["Player Name"],
            y=pm_df["Display Assists Per Minute"],
            marker_color="#F9DD65",
            width=0.8,
            customdata=customdata,
            text=pm_df["Assists"],
            textposition="outside",
            hovertemplate=(
                "Player: %{x}<br>"
                "Assists: %{customdata[0]}<br>"
                "Mins Played: %{customdata[1]:.0f}<br>"
                "Mins per Assist: %{customdata[2]:.0f}<br>"
                "Assist types: %{customdata[3]}<extra></extra>"
            ),
        )
    )

    fig.update_yaxes(
        title="Minutes per Assist",
        tick0=0,
        rangemode="tozero",
        showgrid=True,
        gridcolor="#333",
        zeroline=True,
        zerolinecolor="#555",
    )
    fig.update_layout(
        title=f"{selected_opponent} – Assists Per Minute (rounded up, capped 270 mins)",
        plot_bgcolor="black",
        paper_bgcolor="black",
        font=dict(color="white", family="Segoe UI", size=16),
        xaxis_title="Player Name",
        xaxis=dict(
            showgrid=False,
            tickfont=dict(size=14),
            tickangle=-30,
            categoryorder="array",
            categoryarray=x_order,
        ),
        yaxis=dict(tickfont=dict(size=14)),
        bargap=0.0,
        bargroupgap=0.1,
        margin=dict(t=40, b=60),
        hoverlabel=dict(font=dict(family="Segoe UI")),
    )

    return fig


#----callback for contributions per min - opponent insights tab-----------
@callback(
    Output("opp-goal-contributions", "figure"),
    [
        Input("opp-sort-high-contrib", "n_clicks"),
        Input("opp-sort-low-contrib", "n_clicks"),
        Input("opp-sort-total-contrib", "n_clicks"),
        Input("team-select", "value"),
        Input("opponent-select", "value"),
    ]
)
def update_opp_contributions_chart(
    high_clicks, low_clicks, total_clicks, selected_squad, selected_opponent):

    # No opponent selected
    if not selected_opponent:
        fig = go.Figure()
        fig.update_layout(
            title="Select an opponent to view goal contributions",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family=base_font["fontFamily"]),
            xaxis=dict(showgrid=False, zeroline=False),
            yaxis=dict(showgrid=False, zeroline=False),
        )
        return fig

    # -----------------------------
    # Minutes per player for selected opponent (from player_data)
    # -----------------------------
    minutes_df = player_data.copy()

    if "Team" in minutes_df.columns:
        minutes_df["Team"] = minutes_df["Team"].astype(str).str.strip()
        minutes_df = minutes_df[minutes_df["Team"] == str(selected_squad).strip()].copy()

    if "Country" in minutes_df.columns:
        minutes_df["Country"] = minutes_df["Country"].astype(str).str.strip()
        minutes_df = minutes_df[minutes_df["Country"] == selected_opponent].copy()

    minutes_df["Mins Played"] = pd.to_numeric(minutes_df["Mins Played"], errors="coerce")
    minutes_summary = (
        minutes_df.groupby("Player Name", as_index=False)["Mins Played"].sum()
    )

    # -----------------------------
    # Goal events – from league_goal_data, goals scored BY selected_opponent
    # -----------------------------
    events = league_goal_data.copy()

    if "Team" in events.columns:
        events["Team"] = events["Team"].astype(str).str.strip()
        events = events[events["Team"] == str(selected_squad).strip()].copy()

    for c in ["Home Team", "Away Team", "Scorer Team", "Scorer"]:
        if c in events.columns:
            events[c] = events[c].fillna("").astype(str).str.strip()

    events = events[events["Scorer Team"] == selected_opponent].copy()

    if events.empty:
        fig = go.Figure()
        fig.update_layout(
            title=f"{selected_opponent} – No goal contributions recorded in tracked matches",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family=base_font["fontFamily"]),
            xaxis=dict(showgrid=False, zeroline=False),
            yaxis=dict(showgrid=False, zeroline=False),
        )
        return fig

    # Determine assist column name ("Assist" in league tab, "Assists" in Olyroos tab)
    if "Assists" in events.columns:
        assist_col = "Assists"
    elif "Assist" in events.columns:
        assist_col = "Assist"
    else:
        assist_col = None  # we can still do goals-only contributions

    # Make sure this team is involved as home/away and derive Opponent via helper
    if "Home Team" in events.columns and "Away Team" in events.columns:
        mask_involved = (
            (events["Home Team"] == selected_opponent) |
            (events["Away Team"] == selected_opponent)
        )
        events = events[mask_involved].copy()
        events["Opponent"] = events.apply(
            lambda r: get_against_team(r, selected_opponent), axis=1
        )
    else:
        events["Opponent"] = "Unknown"

    # -----------------------------
    # Goals per player (exclude OG)
    # -----------------------------
    goals_only = events[events["Scorer"].str.upper().ne("OG")].copy()
    goals_counts = goals_only["Scorer"].value_counts().reset_index()
    goals_counts.columns = ["Player Name", "Goals"]

    # -----------------------------
    # Assists per player (if assist column exists)
    # -----------------------------
    if assist_col is not None:
        assists_series = events[assist_col].fillna("").astype(str).str.strip()
        assists_series = assists_series[assists_series.str.len() > 0]
        assists_counts = assists_series.value_counts().reset_index()
        assists_counts.columns = ["Player Name", "Assists"]
    else:
        assists_counts = pd.DataFrame(columns=["Player Name", "Assists"])

    # -----------------------------
    # Merge goal + assist totals into Contributions
    # -----------------------------
    totals = pd.merge(goals_counts, assists_counts, on="Player Name", how="outer").fillna(0)
    totals["Goals"] = totals["Goals"].astype(int)
    if "Assists" in totals.columns:
        totals["Assists"] = totals["Assists"].astype(int)
    else:
        totals["Assists"] = 0
    totals["Contributions"] = totals["Goals"] + totals["Assists"]

    if totals["Contributions"].sum() == 0:
        fig = go.Figure()
        fig.update_layout(
            title=f"{selected_opponent} – No goal contributions recorded in tracked matches",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family=base_font["fontFamily"]),
            xaxis=dict(showgrid=False, zeroline=False),
            yaxis=dict(showgrid=False, zeroline=False),
        )
        return fig

    # -----------------------------
    # Merge with minutes
    # -----------------------------
    merged = totals.merge(minutes_summary, on="Player Name", how="left")
    merged["Mins Played"] = pd.to_numeric(merged["Mins Played"], errors="coerce")

    # Simple placeholder – we’re not summarising assist types from league tab here
    merged["Assist Type Summary"] = "No data"

    # Button logic
    trig = ctx.triggered_id or "opp-sort-high-contrib"
    view_mode = "per_minute"
    if trig == "opp-sort-total-contrib":
        view_mode = "contrib"

    # -----------------------------
    # View 1: Total Contributions by Opponent (stacked)
    # -----------------------------
    if view_mode == "contrib":
        # Goals per player per opponent
        g_by_opp = (
            goals_only.groupby(["Scorer", "Opponent"])
                      .size()
                      .reset_index(name="Goals")
                      .rename(columns={"Scorer": "Player Name"})
        )

        # Assists per player per opponent (if we have an assist column)
        if assist_col is not None:
            ev_assists = events.copy()
            ev_assists["Assist_Player"] = ev_assists[assist_col].fillna("").astype(str).str.strip()
            ev_assists = ev_assists[ev_assists["Assist_Player"].str.len() > 0]
            a_by_opp = (
                ev_assists.groupby(["Assist_Player", "Opponent"])
                          .size()
                          .reset_index(name="Assists")
                          .rename(columns={"Assist_Player": "Player Name"})
            )
        else:
            a_by_opp = pd.DataFrame(columns=["Player Name", "Opponent", "Assists"])

        # Combine to Contributions per player per opponent
        by_opp = pd.merge(g_by_opp, a_by_opp, on=["Player Name", "Opponent"], how="outer").fillna(0)
        by_opp["Goals"] = by_opp["Goals"].astype(int)
        if "Assists" in by_opp.columns:
            by_opp["Assists"] = by_opp["Assists"].astype(int)
        else:
            by_opp["Assists"] = 0
        by_opp["Contributions"] = by_opp["Goals"] + by_opp["Assists"]

        # Keep only players in current totals list, and order by total contributions
        merged_sorted = merged.sort_values("Contributions", ascending=False)
        by_opp = by_opp[by_opp["Player Name"].isin(merged_sorted["Player Name"])]
        x_order = list(merged_sorted["Player Name"])

        fig = go.Figure()
        for opp in sorted(by_opp["Opponent"].dropna().unique()):
            sub = by_opp[by_opp["Opponent"] == opp]
            fig.add_trace(
                go.Bar(
                    x=sub["Player Name"],
                    y=sub["Contributions"],
                    name=opp,
                    marker_color=TEAM_COLORS.get(str(opp).strip(), DEFAULT_COLOR),
                    text=sub["Contributions"],
                    textposition="outside",
                    hovertemplate=(
                        "Player: %{x}<br>"
                        f"Opponent: {opp}<br>"
                        "Contributions vs Opp: %{y}<extra></extra>"
                    ),
                )
            )

        fig.update_yaxes(
            title="Contributions",
            tick0=0,
            rangemode="tozero",
            autorange=True,
            showgrid=True,
            gridcolor="#333",
            zeroline=True,
            zerolinecolor="#555",
        )
        fig.update_traces(cliponaxis=False)
        fig.update_layout(
            barmode="stack",
            title=f"{selected_opponent} – Goal Contributions by Opponent (click legend to filter)",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(size=16, family="Segoe UI", color="white"),
            xaxis=dict(
                tickfont=dict(size=14),
                categoryorder="array",
                categoryarray=x_order,
                showgrid=False,
                tickangle=-30,
            ),
            yaxis=dict(tickfont=dict(size=14)),
            bargap=0.0,
            bargroupgap=0.1,
            margin=dict(t=40, b=60),
            hoverlabel=dict(font=dict(family="Segoe UI")),
        )
        return fig

    # -----------------------------
    # View 2: Minutes per Contribution
    # -----------------------------
    pm_df = merged.copy()
    pm_df = pm_df[(pm_df["Contributions"] > 0) & pm_df["Mins Played"].notna() & (pm_df["Mins Played"] > 0)]

    if pm_df.empty:
        fig = go.Figure()
        fig.update_layout(
            title=f"{selected_opponent} – Contributions recorded but no minutes available for those players",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family=base_font["fontFamily"]),
            xaxis=dict(showgrid=False, zeroline=False),
            yaxis=dict(showgrid=False, zeroline=False),
        )
        return fig

    pm_df["Contributions Per Minute"] = pm_df["Mins Played"] / pm_df["Contributions"]
    pm_df["Actual Contributions Per Minute"] = pm_df["Contributions Per Minute"]
    pm_df["Display Contributions Per Minute"] = np.ceil(
        pm_df["Contributions Per Minute"]
    ).clip(upper=270)

    # Sorting for MPC view
    if trig == "opp-sort-low-contrib":
        pm_df = pm_df.sort_values("Contributions Per Minute", ascending=False)
    else:
        pm_df = pm_df.sort_values("Contributions Per Minute", ascending=True)

    x_order = list(pm_df["Player Name"])
    customdata = pm_df[
        ["Contributions", "Mins Played", "Display Contributions Per Minute"]
    ].values

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=pm_df["Player Name"],
            y=pm_df["Display Contributions Per Minute"],
            marker_color="#FF5733",
            width=0.8,
            customdata=customdata,
            text=pm_df["Contributions"],
            textposition="outside",
            hovertemplate=(
                "Player: %{x}<br>"
                "Contributions: %{customdata[0]}<br>"
                "Mins Played: %{customdata[1]:.0f}<br>"
                "Mins per Contribution: %{customdata[2]:.0f}<extra></extra>"
            ),
        )
    )

    fig.update_yaxes(
        title="Minutes per Contribution",
        tick0=0,
        rangemode="tozero",
        showgrid=True,
        gridcolor="#333",
        zeroline=True,
        zerolinecolor="#555",
    )
    fig.update_layout(
        title=f"{selected_opponent} – Goal Contributions Per Minute (rounded up, capped 270 mins)",
        plot_bgcolor="black",
        paper_bgcolor="black",
        font=dict(size=16, family="Segoe UI", color="white"),
        xaxis=dict(
            showgrid=False,
            tickfont=dict(size=14),
            tickangle=-30,
            categoryorder="array",
            categoryarray=x_order,
        ),
        yaxis=dict(tickfont=dict(size=14)),
        bargap=0.0,
        bargroupgap=0.1,
        margin=dict(t=40, b=60),
        hoverlabel=dict(font=dict(family="Segoe UI")),
    )

    return fig




# ---- callback for starts and appearances - opponent insights tab ----
@callback(
    Output("opp-starts-appearances-chart", "figure"),
    [
        Input("team-select", "value"),
        Input("opp-sort-high-starts", "n_clicks"),
        Input("opp-sort-low-starts", "n_clicks"),
        Input("opp-sort-total-appearances", "n_clicks"),
        Input("opponent-select", "value"),
    ]
)
def update_opp_starts_appearances_chart(
    selected_squad, high_clicks, low_clicks, total_clicks, selected_opponent
):
    focus_team = TEAM_MAP.get(selected_squad, selected_squad)

    if not selected_opponent:
        fig = go.Figure()
        fig.update_layout(
            title="Select an opponent to view starts and appearances",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(size=14, color="white", family="Segoe UI"),
            xaxis=dict(showgrid=False, zeroline=False),
            yaxis=dict(showgrid=False, zeroline=False),
        )
        return fig

    df = player_data.copy()
    df["Player Name"] = df["Player Name"].astype(str).str.strip()
    df["Match ID"] = df["Match ID"].astype(str).str.strip()
    df["Country"] = df["Country"].astype(str).str.strip()

    if "Team" in df.columns:
        df["Team"] = df["Team"].astype(str).str.strip()
        df = df[df["Team"] == str(selected_squad).strip()].copy()

    # 1) Find matches where the selected Belco squad played this opponent
    belco_match_ids = set(df[df["Country"] == focus_team]["Match ID"].unique())
    opp_match_ids = set(df[df["Country"] == str(selected_opponent).strip()]["Match ID"].unique())
    relevant_match_ids = belco_match_ids.intersection(opp_match_ids)

    # 2) From those matches, keep only opponent players
    df = df[
        (df["Match ID"].isin(relevant_match_ids)) &
        (df["Country"] == str(selected_opponent).strip())
    ].copy()

    if df.empty:
        fig = go.Figure()
        fig.update_layout(
            title=f"{selected_opponent} – no player data recorded vs {focus_team}",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(size=14, color="white", family="Segoe UI"),
            xaxis=dict(showgrid=False, zeroline=False),
            yaxis=dict(showgrid=False, zeroline=False),
        )
        return fig

    # Starts / Apps
    df["Start"] = (
        df["Start"]
        .astype(str).str.strip().str.lower()
        .map({"yes": 1, "no": 0})
        .fillna(0).astype(int)
    )
    df["Appearance"] = (
        df["Appearance"]
        .astype(str).str.strip().str.lower()
        .map({"yes": 1, "no": 0})
        .fillna(0).astype(int)
    )
    df["Mins Played"] = pd.to_numeric(df["Mins Played"], errors="coerce")

    # Discipline flags
    if "Discipline" in df.columns:
        disc_norm = df["Discipline"].fillna("").astype(str).str.strip().str.lower()
        df["DiscYellow"] = (disc_norm == "yellow").astype(int)
        df["DiscRed"] = (disc_norm == "red").astype(int)
    else:
        df["DiscYellow"] = 0
        df["DiscRed"] = 0

    grouped = (
        df.groupby("Player Name")
          .agg({
              "Start": "sum",
              "Appearance": "sum",
              "Mins Played": "sum",
              "DiscYellow": "sum",
              "DiscRed": "sum",
          })
          .reset_index()
    )

    grouped = grouped.rename(columns={"DiscYellow": "Yellow", "DiscRed": "Red"})
    grouped["Total Cards"] = grouped["Yellow"] + grouped["Red"]

    # Sorting
    trig = ctx.triggered_id
    if trig == "opp-sort-low-starts":
        grouped = grouped.sort_values(by="Start", ascending=True)
    elif trig == "opp-sort-total-appearances":
        grouped = grouped.sort_values(by="Appearance", ascending=False)
    else:
        grouped = grouped.sort_values(by="Start", ascending=False)

    fig = go.Figure()

    cd = grouped[[
        "Start",
        "Appearance",
        "Mins Played",
        "Total Cards",
        "Yellow",
        "Red",
    ]]

    fig.add_trace(go.Scatter(
        x=grouped["Player Name"],
        y=grouped["Start"],
        mode="lines+markers",
        name="Starts",
        line=dict(color="#77BCE8", width=3),
        marker=dict(size=8),
        customdata=cd,
        hovertemplate=(
            "<b>Player: %{x}</b><br>"
            "Starts: %{y}<br>"
            "Apps: %{customdata[1]}<br>"
            "Mins: %{customdata[2]:.0f}<br>"
            "Cards: %{customdata[3]} (Y: %{customdata[4]}, R: %{customdata[5]})"
            "<extra></extra>"
        ),
    ))

    fig.add_trace(go.Scatter(
        x=grouped["Player Name"],
        y=grouped["Appearance"],
        mode="lines+markers",
        name="Appearances",
        line=dict(color="#19A030", width=3, dash="dash"),
        marker=dict(size=8),
        customdata=cd,
        hovertemplate=(
            "<b>Player: %{x}</b><br>"
            "Starts: %{customdata[0]}<br>"
            "Apps: %{y}<br>"
            "Mins: %{customdata[2]:.0f}<br>"
            "Cards: %{customdata[3]} (Y: %{customdata[4]}, R: %{customdata[5]})"
            "<extra></extra>"
        ),
    ))

    disc_mask = grouped["Total Cards"] > 0

    fig.add_trace(go.Scatter(
        x=grouped.loc[disc_mask, "Player Name"],
        y=grouped.loc[disc_mask, "Total Cards"],
        mode="markers",
        name="Discipline (Y+R)",
        marker=dict(
            size=10,
            color="#C2DD27",
            symbol="diamond"
        ),
        customdata=grouped.loc[disc_mask, ["Yellow", "Red"]],
        hovertemplate=(
            "<b>Player: %{x}</b><br>"
            "Yellow: %{customdata[0]}<br>"
            "Red: %{customdata[1]}<extra></extra>"
        ),
    ))

    fig.update_layout(
        title=f"{selected_opponent} – Starts and Appearances (with Discipline)",
        plot_bgcolor="black",
        paper_bgcolor="black",
        font=dict(size=14, color="white", family="Segoe UI"),
        xaxis_title="Player Name",
        yaxis_title="Count",
        xaxis=dict(
            showgrid=False,
            tickfont=dict(size=12),
            tickangle=-30,
        ),
        yaxis=dict(
            showgrid=False,
            tickfont=dict(size=12),
            rangemode="tozero"
        ),
        margin=dict(t=40, b=40),
        hoverlabel=dict(font=dict(size=13, family="Segoe UI")),
    )

    return fig


# ---- callback for total mins - opponent insights tab ----
@callback(
    Output("opp-minutes-played-chart", "figure"),
    [
        Input("team-select", "value"),
        Input("opp-sort-high-mins", "n_clicks"),
        Input("opp-sort-low-mins", "n_clicks"),
        Input("opp-sort-avg-mins", "n_clicks"),
        Input("opponent-select", "value"),
    ]
)
def update_opp_minutes_played_chart(
    selected_squad, high_clicks, low_clicks, avg_clicks, selected_opponent
):

    focus_team = TEAM_MAP.get(selected_squad, selected_squad)

    if not selected_opponent:
        fig = go.Figure()
        fig.update_layout(
            title="Select an opponent to view minutes played",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(size=14, color="white", family="Segoe UI"),
        )
        return fig

    df = player_data.copy()

    df["Player Name"] = df["Player Name"].astype(str).str.strip()
    df["Country"] = df["Country"].astype(str).str.strip()
    df["Match ID"] = df["Match ID"].astype(str).str.strip()

    if "Team" in df.columns:
        df["Team"] = df["Team"].astype(str).str.strip()
        df = df[df["Team"] == str(selected_squad).strip()].copy()

    # find matches where Belco squad played this opponent
    belco_matches = set(df[df["Country"] == focus_team]["Match ID"].unique())
    opp_matches = set(df[df["Country"] == selected_opponent]["Match ID"].unique())
    match_ids = belco_matches.intersection(opp_matches)

    # keep only opponent players from those matches
    df = df[
        (df["Match ID"].isin(match_ids)) &
        (df["Country"] == selected_opponent)
    ].copy()

    if df.empty:
        fig = go.Figure()
        fig.update_layout(
            title=f"{selected_opponent} – no player minutes recorded vs {focus_team}",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(size=14, color="white", family="Segoe UI"),
        )
        return fig

    df["Mins Played"] = pd.to_numeric(df["Mins Played"], errors="coerce")

    df["Appearance"] = (
        df["Appearance"]
        .astype(str).str.strip().str.lower()
        .map({"yes": 1, "no": 0})
        .fillna(0).astype(int)
    )

    grouped = (
        df.groupby("Player Name")
          .agg({
              "Mins Played": "sum",
              "Appearance": "sum",
          })
          .reset_index()
    )

    grouped["Avg Mins per App"] = grouped.apply(
        lambda r: round(r["Mins Played"] / r["Appearance"], 1) if r["Appearance"] > 0 else 0,
        axis=1
    )

    trig = ctx.triggered_id

    if trig == "opp-sort-avg-mins":
        grouped = grouped.sort_values(by="Avg Mins per App", ascending=False)
    elif trig == "opp-sort-low-mins":
        grouped = grouped.sort_values(by="Mins Played", ascending=True)
    else:
        grouped = grouped.sort_values(by="Mins Played", ascending=False)

    fig = px.bar(
        grouped,
        x="Player Name",
        y="Mins Played",
        title=f"{selected_opponent} – Total Minutes Played",
        color_discrete_sequence=["#77BCE8"],
        template="plotly_dark",
        text="Mins Played",
    )

    fig.update_traces(
        textposition="outside",
        customdata=grouped[["Appearance", "Avg Mins per App"]],
        hovertemplate=(
            "<b>Player: %{x}</b><br>"
            "Total Mins: %{y:.0f}<br>"
            "Apps: %{customdata[0]}<br>"
            "Avg Mins per App: %{customdata[1]:.1f}<extra></extra>"
        ),
        hoverlabel=dict(font=dict(size=13, family="Segoe UI")),
    )

    fig.update_layout(
        yaxis_title="Minutes Played",
        xaxis=dict(showgrid=False, tickfont=dict(size=12), tickangle=-30),
        yaxis=dict(showgrid=False, tickfont=dict(size=12)),
        plot_bgcolor="black",
        paper_bgcolor="black",
        font=dict(size=14, color="white", family="Segoe UI"),
        margin=dict(t=40, b=40),
        bargap=0.0,
        bargroupgap=0.1,
    )

    return fig


#----------------------------------------------------------
# Opponent / League Coach Behaviour – Opponent Insights Tab
#----------------------------------------------------------
@callback(
    Output("opp-coach-behaviour-summary", "children"),
    [
        Input("team-select", "value"),
        Input("opponent-select", "value"),
    ],
)
def update_opp_coach_behaviour(selected_squad, selected_opponent):

    if not selected_opponent:
        return "Select an opponent to view coach in-game behaviour patterns."

    is_all = (selected_opponent == "ALL")

    # -------------------------------------------------
    # Player / substitution data
    # -------------------------------------------------
    df = player_data.copy()

    # Keep only rows from selected squad file
    if "Team" in df.columns:
        df["Team"] = df["Team"].astype(str).str.strip()
        df = df[df["Team"] == str(selected_squad).strip()].copy()

    df["Player Name"] = df["Player Name"].astype(str).str.strip()

    if "Country" in df.columns:
        df["Country"] = df["Country"].astype(str).str.strip()

    # Filter by opponent ONLY if not ALL
    if "Country" in df.columns and not is_all:
        df = df[df["Country"] == selected_opponent].copy()

    if df.empty:
        return "No substitution data available for this selection."

    # -------------------------------------------------
    # Identify substitutes
    # -------------------------------------------------
    df["Start"] = df["Start"].astype(str).str.lower().str.strip()

    if "Appearance" in df.columns:
        df["Appearance"] = df["Appearance"].astype(str).str.lower().str.strip()
        subs = df[
            (df["Start"] != "yes") &
            (df["Appearance"] == "yes")
        ].copy()
    else:
        subs = df[df["Start"] != "yes"].copy()

    subs["Sub Minute"] = 90 - pd.to_numeric(subs["Mins Played"], errors="coerce")
    subs = subs[subs["Sub Minute"].notna()].copy()

    if subs.empty:
        return "No substitutions identified in the tracked matches."

    # -------------------------------------------------
    # First sub per match
    # -------------------------------------------------
    first_subs = (
        subs.sort_values("Sub Minute")
            .groupby("Match ID")
            .first()
            .reset_index()
    )

    avg_first_sub = round(first_subs["Sub Minute"].mean(), 1)

    first_sub_minutes = (
        first_subs["Sub Minute"]
        .round(0)
        .astype(int)
        .sort_values()
        .tolist()
    )
    first_sub_minutes_text = ", ".join(str(m) for m in first_sub_minutes)

    total_matches = first_subs["Match ID"].nunique()

    # -------------------------------------------------
    # Preferred first substitute logic
    # -------------------------------------------------
    sub_counts = first_subs["Player Name"].value_counts()
    most_common_count = sub_counts.max()
    most_common_subs = sub_counts[sub_counts == most_common_count].index.tolist()

    if most_common_count >= 3:
        sub_text = (
            f"The most frequently used first substitute is {most_common_subs[0]} "
            f"({most_common_count} times), suggesting they are a trusted impact option."
        )
    else:
        sub_text = (
            "There has been no preferred impact-player as the first substitute. "
            "The coach varies who the first change is depending on the game context."
        )

    # -------------------------------------------------
    # Goal data (for game state & impact)
    # -------------------------------------------------
    goals = league_goal_data.copy()

    # Keep only rows from selected squad file
    if "Team" in goals.columns:
        goals["Team"] = goals["Team"].astype(str).str.strip()
        goals = goals[goals["Team"] == str(selected_squad).strip()].copy()

    for c in ["Home Team", "Away Team", "Scorer Team"]:
        if c in goals.columns:
            goals[c] = goals[c].fillna("").astype(str).str.strip()

    goals["Minute Scored"] = pd.to_numeric(goals["Minute Scored"], errors="coerce")

    if not is_all:
        goals = goals[
            (goals["Home Team"] == selected_opponent) |
            (goals["Away Team"] == selected_opponent)
        ].copy()

    # -------------------------------------------------
    # Game state at first sub
    # -------------------------------------------------
    def game_state_at_minute(match_id, sub_minute):
        if is_all:
            return "All matches"

        g = goals[
            (goals["Match ID"] == match_id) &
            (goals["Minute Scored"] < sub_minute)
        ]

        gf = (g["Scorer Team"] == selected_opponent).sum()
        ga = (g["Scorer Team"] != selected_opponent).sum()

        if gf > ga:
            return "Winning"
        elif gf < ga:
            return "Losing"
        return "Drawing"

    first_subs["Game State"] = first_subs.apply(
        lambda r: game_state_at_minute(r["Match ID"], r["Sub Minute"]),
        axis=1
    )

    state_summary = (
        first_subs
        .groupby("Game State")["Sub Minute"]
        .agg(["mean", "count"])
        .reset_index()
    )

    STATE_ORDER = ["Winning", "Drawing", "Losing"] if not is_all else ["All matches"]

    state_lines = []
    for state in STATE_ORDER:
        row = state_summary[state_summary["Game State"] == state]
        if row.empty:
            continue

        minute = int(round(row.iloc[0]["mean"]))
        count = int(row.iloc[0]["count"])

        state_lines.append(
            f"{state} ({count} matches): {minute}′"
        )

    # -------------------------------------------------
    # Substitutions per match
    # -------------------------------------------------
    subs_per_game = (
        subs.groupby("Match ID")
            .size()
            .mean()
            .round(0)
            .astype(int)
    )

    # -------------------------------------------------
    # Goal impact after first sub (15 mins)
    # -------------------------------------------------
    state_impact = {}

    for _, r in first_subs.iterrows():
        match_id = r["Match ID"]
        state = r["Game State"]
        sub_min = r["Sub Minute"]

        if state not in state_impact:
            state_impact[state] = {
                "for": 0,
                "against": 0,
                "no_goal": 0,
                "matches": 0,
                "for_matches": [],
                "against_matches": [],
            }

        state_impact[state]["matches"] += 1

        window = goals[
            (goals["Match ID"] == match_id) &
            (goals["Minute Scored"] > sub_min) &
            (goals["Minute Scored"] <= sub_min + 15)
        ]

        if window.empty:
            state_impact[state]["no_goal"] += 1
        else:
            if not is_all and (window["Scorer Team"] == selected_opponent).any():
                state_impact[state]["for"] += 1
                state_impact[state]["for_matches"].append(match_id)

            if not is_all and (window["Scorer Team"] != selected_opponent).any():
                state_impact[state]["against"] += 1
                state_impact[state]["against_matches"].append(match_id)

    impact_lines = []
    for state in STATE_ORDER:
        if state not in state_impact:
            continue

        s = state_impact[state]
        matches = s["matches"]
        parts = []

        if s["for"] > 0:
            parts.append(f"{s['for']} goal{'s' if s['for'] > 1 else ''} for ({', '.join(s['for_matches'])})")
        if s["against"] > 0:
            parts.append(f"{s['against']} against ({', '.join(s['against_matches'])})")
        if s["no_goal"] > 0 and not parts:
            parts.append("no goal")

        impact_lines.append(
            f"{state} ({matches} matches): " + ", ".join(parts)
        )

    # -------------------------------------------------
    # Narrative output
    # -------------------------------------------------
    title_prefix = (
        "Across all tracked matches"
        if is_all
        else f"For {selected_opponent}"
    )

    return html.Div([
        html.P(
            f"{title_prefix}, the average minute of the first substitution is "
            f"{avg_first_sub:.0f} minutes "
            f"(first sub timings: {first_sub_minutes_text})."
        ),
        html.P(sub_text),
        html.P(
            "Average first substitution timing by game state:",
            style={"marginBottom": "4px"},
        ),
        html.Ul(
            [html.Li(line) for line in state_lines],
            style={"marginTop": "0px"},
        ),
        html.P(
            "In the 15 minutes following the first substitution:",
            style={"marginBottom": "4px"},
        ),
        html.Ul(
            [html.Li(line) for line in impact_lines],
            style={"marginTop": "0px"},
        ),
        html.P(
            f"On average, {subs_per_game} substitutions are made per match."
        ),
    ])


#---------that was the last callback for the opponent insights tab-----------
#----------------------------------------------------------------------------



# this is for the team-insights app.
# callback for starts and appearances
@callback(
    Output("starts-appearances-chart", "figure"),
    [
        Input("team-select", "value"),
        Input("sort-high-starts", "n_clicks"),
        Input("sort-low-starts", "n_clicks"),
        Input("sort-total-appearances", "n_clicks"),
    ]
)
def update_starts_appearances_chart(selected_squad, high_clicks, low_clicks, total_clicks):
    focus_team = TEAM_MAP.get(selected_squad, selected_squad)

    df = player_data.copy()
    df["Player Name"] = df["Player Name"].astype(str).str.strip()

    if "Team" in df.columns:
        df["Team"] = df["Team"].astype(str).str.strip()
        df = df[df["Team"] == str(selected_squad).strip()].copy()

    if "Country" in df.columns:
        df["Country"] = df["Country"].astype(str).str.strip()
        df = df[df["Country"] == focus_team].copy()

    if df.empty:
        fig = go.Figure()
        fig.update_layout(
            title=f"{focus_team} – Starts and Appearances",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(size=14, color="white", family="Segoe UI"),
            xaxis=dict(showgrid=False, zeroline=False),
            yaxis=dict(showgrid=False, zeroline=False),
        )
        return fig

    # Starts / Apps
    df["Start"] = (
        df["Start"]
        .astype(str).str.strip().str.lower()
        .map({"yes": 1, "no": 0})
        .fillna(0).astype(int)
    )
    df["Appearance"] = (
        df["Appearance"]
        .astype(str).str.strip().str.lower()
        .map({"yes": 1, "no": 0})
        .fillna(0).astype(int)
    )
    df["Mins Played"] = pd.to_numeric(df["Mins Played"], errors="coerce")

    # Discipline
    if "Discipline" in df.columns:
        disc_norm = df["Discipline"].fillna("").astype(str).str.strip().str.lower()
        df["DiscYellow"] = (disc_norm == "yellow").astype(int)
        df["DiscRed"] = (disc_norm == "red").astype(int)
    else:
        df["DiscYellow"] = 0
        df["DiscRed"] = 0

    grouped = (
        df.groupby("Player Name")
          .agg({
              "Start": "sum",
              "Appearance": "sum",
              "Mins Played": "sum",
              "DiscYellow": "sum",
              "DiscRed": "sum",
          })
          .reset_index()
    )

    grouped = grouped.rename(columns={"DiscYellow": "Yellow", "DiscRed": "Red"})
    grouped["Total Cards"] = grouped["Yellow"] + grouped["Red"]

    trig = ctx.triggered_id
    if trig == "sort-low-starts":
        grouped = grouped.sort_values(by="Start", ascending=True)
    elif trig == "sort-total-appearances":
        grouped = grouped.sort_values(by="Appearance", ascending=False)
    else:
        grouped = grouped.sort_values(by="Start", ascending=False)

    cd = grouped[["Start", "Appearance", "Mins Played", "Total Cards", "Yellow", "Red"]]

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=grouped["Player Name"],
        y=grouped["Start"],
        mode="lines+markers",
        name="Starts",
        line=dict(color="#77BCE8", width=3),
        marker=dict(size=8),
        customdata=cd,
        hovertemplate=(
            "<b>Player: %{x}</b><br>"
            "Starts: %{y}<br>"
            "Apps: %{customdata[1]}<br>"
            "Mins: %{customdata[2]:.0f}<br>"
            "Cards: %{customdata[3]} (Y: %{customdata[4]}, R: %{customdata[5]})"
            "<extra></extra>"
        ),
    ))

    fig.add_trace(go.Scatter(
        x=grouped["Player Name"],
        y=grouped["Appearance"],
        mode="lines+markers",
        name="Appearances",
        line=dict(color="#16AD16", width=3, dash="dash"),
        marker=dict(size=8),
        customdata=cd,
        hovertemplate=(
            "<b>Player: %{x}</b><br>"
            "Starts: %{customdata[0]}<br>"
            "Apps: %{y}<br>"
            "Mins: %{customdata[2]:.0f}<br>"
            "Cards: %{customdata[3]} (Y: %{customdata[4]}, R: %{customdata[5]})"
            "<extra></extra>"
        ),
    ))

    disc_mask = grouped["Total Cards"] > 0

    fig.add_trace(go.Scatter(
        x=grouped.loc[disc_mask, "Player Name"],
        y=grouped.loc[disc_mask, "Total Cards"],
        mode="markers",
        name="Discipline (Y+R)",
        marker=dict(
            size=10,
            color="#C2DD27",
            symbol="diamond"
        ),
        customdata=grouped.loc[disc_mask, ["Yellow", "Red"]],
        hovertemplate=(
            "<b>Player: %{x}</b><br>"
            "Yellow: %{customdata[0]}<br>"
            "Red: %{customdata[1]}<extra></extra>"
        ),
    ))

    fig.update_layout(
        title=f"{focus_team} – Starts and Appearances (with Discipline)",
        plot_bgcolor="black",
        paper_bgcolor="black",
        font=dict(size=14, color="white", family="Segoe UI"),
        xaxis_title="Player Name",
        yaxis_title="Count",
        xaxis=dict(
            showgrid=False,
            tickfont=dict(size=12),
            tickangle=-30,
        ),
        yaxis=dict(
            showgrid=False,
            tickfont=dict(size=12),
            rangemode="tozero"
        ),
        margin=dict(t=40, b=40),
        hoverlabel=dict(font=dict(size=13, family="Segoe UI")),
    )

    return fig



# total mins played - player-insight tab
@callback(
    Output("minutes-played-chart", "figure"),
    [
        Input("team-select", "value"),
        Input("sort-high-mins", "n_clicks"),
        Input("sort-low-mins", "n_clicks"),
        Input("sort-avg-mins", "n_clicks"),
    ]
)
def update_minutes_played_chart(selected_squad, high_clicks, low_clicks, avg_clicks):

    focus_team = TEAM_MAP.get(selected_squad, selected_squad)

    df = player_data.copy()

    df["Player Name"] = df["Player Name"].astype(str).str.strip()

    if "Team" in df.columns:
        df["Team"] = df["Team"].astype(str).str.strip()
        df = df[df["Team"] == str(selected_squad).strip()].copy()

    if "Country" in df.columns:
        df["Country"] = df["Country"].astype(str).str.strip()
        df = df[df["Country"] == focus_team].copy()

    if df.empty:
        fig = go.Figure()
        fig.update_layout(
            title=f"{focus_team} – Minutes Played",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(size=14, color="white", family="Segoe UI"),
        )
        return fig

    df["Mins Played"] = pd.to_numeric(df["Mins Played"], errors="coerce")

    df["Appearance"] = (
        df["Appearance"]
        .astype(str)
        .str.strip()
        .str.lower()
        .map({"yes": 1, "no": 0})
        .fillna(0)
        .astype(int)
    )

    grouped = (
        df.groupby("Player Name")
          .agg({
              "Mins Played": "sum",
              "Appearance": "sum",
          })
          .reset_index()
    )

    grouped["Avg Mins per App"] = grouped.apply(
        lambda row: round(row["Mins Played"] / row["Appearance"], 1)
        if row["Appearance"] > 0 else 0,
        axis=1
    )

    trig = ctx.triggered_id

    if trig == "sort-avg-mins":
        grouped = grouped.sort_values(by="Avg Mins per App", ascending=False)
    elif trig == "sort-low-mins":
        grouped = grouped.sort_values(by="Mins Played", ascending=True)
    else:
        grouped = grouped.sort_values(by="Mins Played", ascending=False)

    fig = px.bar(
        grouped,
        x="Player Name",
        y="Mins Played",
        title=f"{focus_team} – Total Minutes Played",
        color_discrete_sequence=["#77BCE8"],
        template="plotly_dark",
        text="Mins Played",
    )

    fig.update_traces(
        textposition="outside",
        customdata=grouped[["Appearance", "Avg Mins per App"]],
        hovertemplate=(
            "<b>Player: %{x}</b><br>"
            "Total Mins: %{y:.0f}<br>"
            "Apps: %{customdata[0]}<br>"
            "Avg Mins per App: %{customdata[1]:.1f}<extra></extra>"
        ),
        hoverlabel=dict(font=dict(size=13, family="Segoe UI"))
    )

    fig.update_layout(
        yaxis_title="Minutes Played",
        xaxis=dict(showgrid=False, tickfont=dict(size=12), tickangle=-30),
        yaxis=dict(showgrid=False, tickfont=dict(size=12)),
        plot_bgcolor="black",
        paper_bgcolor="black",
        font=dict(size=14, color="white", family="Segoe UI"),
        margin=dict(t=40, b=40),
        bargap=0.0,
        bargroupgap=0.1,
    )

    return fig






# Common color map
#opponent_colors = {
#    "Tuggeranong": "green",
#    "Croatia": "#B22222",
#    "Olympic": "navy",
#    "Gungahlin": "#FF1493",
#    "Majura": "royalblue",
#    "ANU": "orange",
#    "Wanderers": "#8B0000",
#    "Belconnen": "skyblue"
#}


# goals scored by interval and goals conceded by interval charts
def bin_minute(minute):
    try:
        minute = int(minute)
        if 0 <= minute <= 15:
            return "0–15"
        elif 16 <= minute <= 30:
            return "16–30"
        elif 31 <= minute <= 45:
            return "31–45"
        elif 46 <= minute <= 60:
            return "46–60"
        elif 61 <= minute <= 75:
            return "61–75"
        elif 76 <= minute <= 120:
            return "76–90"
    except:
        return None


@callback(
    Output("goals-by-interval", "figure"),
    Output("last-4-interval-status", "children"),
    Output("conceded-by-interval", "figure"),
    Output("last-4-interval-status-conceded", "children"),
    Input("team-select", "value"),
    Input("last-4-interval-button", "n_clicks"),
    Input("last-4-interval-button-conceded", "n_clicks"),
)
def update_interval_charts(selected_squad, last4_scored_clicks, last4_conceded_clicks):
    selected_team = TEAM_MAP.get(selected_squad, FOCUS_TEAM)

    last4_scored_clicks = last4_scored_clicks or 0
    last4_conceded_clicks = last4_conceded_clicks or 0

    df = league_goal_data.copy()

    # NEW: keep only the selected squad's file rows
    if "Team" in df.columns:
        df["Team"] = df["Team"].astype(str).str.strip()
        df = df[df["Team"] == str(selected_squad).strip()].copy()

    df["Home Team"] = df["Home Team"].astype(str).str.strip()
    df["Away Team"] = df["Away Team"].astype(str).str.strip()
    df["Scorer Team"] = df["Scorer Team"].fillna("").astype(str).str.strip()
    df["Minute Scored"] = pd.to_numeric(df["Minute Scored"], errors="coerce")
    df["Match Date Parsed"] = pd.to_datetime(df["Match Date"], errors="coerce")

    df = df[
        ((df["Home Team"] == selected_team) | (df["Away Team"] == selected_team)) &
        (df["Minute Scored"].notna())
    ].copy()

    # Recompute opponent every time
    df["Opponent"] = np.where(
        df["Home Team"] == selected_team,
        df["Away Team"],
        df["Home Team"]
    )

    all_bins = ["0–15", "16–30", "31–45", "46–60", "61–75", "76–90"]
    df["Minute Bin"] = df["Minute Scored"].apply(bin_minute)


    # Opponent
    if "Opponent" not in df.columns:
        def extract_opponent(row):
            if row["Home Team"] == selected_team:
                return row["Away Team"]
            elif row["Away Team"] == selected_team:
                return row["Home Team"]
            return None
        df["Opponent"] = df.apply(extract_opponent, axis=1)

    # ---- Goals SCORED ----
    df_scored = df[df["Scorer Team"] == selected_team].copy()
    status_scored = ""

    if last4_scored_clicks % 2 == 1:
        all_dates = sorted(df_scored["Match Date Parsed"].dropna().unique())
        if all_dates:
            last4_dates = all_dates[-4:] if len(all_dates) >= 4 else all_dates
            df_scored = df_scored[df_scored["Match Date Parsed"].isin(last4_dates)].copy()
            status_scored = "SHOWING : Last 4 rounds"

    scored_grouped = (
        df_scored.groupby(["Minute Bin", "Opponent"])
        .size()
        .unstack(fill_value=0)
        .reindex(all_bins)
        .fillna(0)
    )

    fig_goals = go.Figure()
    for opp in scored_grouped.columns:
        fig_goals.add_trace(go.Bar(
            x=scored_grouped.index,
            y=scored_grouped[opp],
            name=opp,
            marker_color=TEAM_COLORS.get(str(opp).strip(), "gray"),
            hovertemplate="<b>%{fullData.name}</b><br>Interval: %{x}<br>Goals: %{y}<extra></extra>",
            hoverlabel=dict(font=dict(family="Segoe UI"))
        ))

    fig_goals.update_layout(
        title=f"{selected_team} – Goals Scored by Game Interval",
        barmode="stack",
        plot_bgcolor="black",
        paper_bgcolor="black",
        font=dict(color="white", family="Segoe UI"),
        xaxis_title="Minute Interval",
        yaxis_title="Goals Scored",
        margin=dict(t=40, b=40),
        bargap=0.4,
        bargroupgap=0.1,
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=False, tickformat=".0f"),
        legend_title="Opponent",
    )

    # ---- Goals CONCEDED ----
    df_conceded = df[df["Scorer Team"] != selected_team].copy()
    status_conceded = ""

    if last4_conceded_clicks % 2 == 1:
        all_dates_c = sorted(df_conceded["Match Date Parsed"].dropna().unique())
        if all_dates_c:
            last4_dates_c = all_dates_c[-4:] if len(all_dates_c) >= 4 else all_dates_c
            df_conceded = df_conceded[df_conceded["Match Date Parsed"].isin(last4_dates_c)].copy()
            status_conceded = "SHOWING : Last 4 rounds"

    conceded_grouped = (
        df_conceded.groupby(["Minute Bin", "Opponent"])
        .size()
        .unstack(fill_value=0)
        .reindex(all_bins)
        .fillna(0)
    )

    fig_conceded = go.Figure()
    for opp in conceded_grouped.columns:
        fig_conceded.add_trace(go.Bar(
            x=conceded_grouped.index,
            y=conceded_grouped[opp],
            name=opp,
            marker_color=TEAM_COLORS.get(str(opp).strip(), "gray"),
            hovertemplate="<b>%{fullData.name}</b><br>Interval: %{x}<br>Goals: %{y}<extra></extra>",
            hoverlabel=dict(font=dict(family="Segoe UI"))
        ))

    fig_conceded.update_layout(
        title=f"{selected_team} – Goals Conceded by Game Interval",
        barmode="stack",
        plot_bgcolor="black",
        paper_bgcolor="black",
        font=dict(color="white", family="Segoe UI"),
        xaxis_title="Minute Interval",
        yaxis_title="Goals Conceded",
        margin=dict(t=40, b=40),
        bargap=0.4,
        bargroupgap=0.1,
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=False, tickformat=".0f"),
        legend_title="Opponent",
    )

    return fig_goals, status_scored, fig_conceded, status_conceded



# callbacks for pie charts
@callback(
    Output("scored-regain-pie", "figure"),
    Output("scored-setpiece-pie", "figure"),
    Output("conceded-regain-pie", "figure"),
    Output("conceded-setpiece-pie", "figure"),
    Input("team-select", "value"),
    Input("goaltype-opponent-filter", "value"),
)
def update_goal_type_pies(selected_squad, opponent_choice):
    selected_team = TEAM_MAP.get(selected_squad, FOCUS_TEAM)

    # ---- Base events: ONLY matches involving selected team ----
    events = league_goal_data.copy()

    # Filter by squad file
    if "Team" in events.columns:
        events["Team"] = events["Team"].astype(str).str.strip()
        events = events[events["Team"] == str(selected_squad).strip()].copy()

    # Defensive: normalise key fields used below
    for c in ["Home Team", "Away Team", "Scorer Team", "Goal Type"]:
        if c in events.columns:
            events[c] = events[c].fillna("").astype(str).str.strip()

    # Keep only fixtures involving selected team
    events = events[
        (events["Home Team"] == selected_team) | (events["Away Team"] == selected_team)
    ].copy()

    # Derive Opponent from fixture
    events["Opponent"] = np.where(
        events["Home Team"] == selected_team,
        events["Away Team"],
        events["Home Team"]
    )

    if "normalize_club" in globals():
        events["Opponent"] = events["Opponent"].apply(normalize_club)

    # ---- Optional: filter by single opponent from dropdown ----
    if opponent_choice and opponent_choice != "ALL":
        events = events[events["Opponent"] == opponent_choice].copy()

    # ---- Label map + code groups ----
    goal_type_labels = {
        "R-FT-DT": "Regain Front Third – During Transition",
        "R-FT-AT": "Regain Front Third – After Transition",
        "R-MT-DT": "Regain Middle Third – During Transition",
        "R-MT-AT": "Regain Middle Third – After Transition",
        "R-BT-DT": "Regain Back Third – During Transition",
        "R-BT-AT": "Regain Back Third – After Transition",
        "SP-C": "Corners",
        "SP-T": "Throw-Ins",
        "SP-P": "Penalties",
        "SP-F": "Free Kicks",
    }

    regain_codes = [c for c in goal_type_labels if c.startswith("R-")]
    setpiece_codes = [c for c in goal_type_labels if c.startswith("SP-")]

    # ---- Helpers ----
    def pick(df, side):
        if side == "Scored":
            return df[df["Scorer Team"] == selected_team].copy()
        return df[df["Scorer Team"] != selected_team].copy()

    def build_pie(filtered_df, valid_codes, title, total_for_side):
        if filtered_df.empty or total_for_side == 0:
            fig = go.Figure()
            fig.update_layout(
                title=title,
                paper_bgcolor="black",
                plot_bgcolor="black",
                font=dict(color="white", family="Segoe UI"),
                annotations=[dict(text="No data", x=0.5, y=0.5, font_size=20, showarrow=False)],
                margin=dict(t=40, b=20, l=20, r=20),
                legend=dict(orientation="h", yanchor="bottom", y=-0.1, xanchor="center", x=0.5),
            )
            return fig

        subset = filtered_df[filtered_df["Goal Type"].isin(valid_codes)].copy()
        if subset.empty:
            fig = go.Figure(go.Pie(
                labels=["No Data"],
                values=[1],
                hole=0.45,
                textinfo="label",
                hoverinfo="skip",
                sort=False,
                textfont=dict(family="Segoe UI Semibold", size=14),
            ))
            fig.update_layout(
                title=title,
                paper_bgcolor="black",
                plot_bgcolor="black",
                font=dict(color="white", family="Segoe UI"),
                legend=dict(orientation="h", yanchor="bottom", y=-0.1, xanchor="center", x=0.5),
                margin=dict(t=40, b=20, l=20, r=20),
            )
            return fig

        counts = subset["Goal Type"].value_counts().sort_index()

        perc_overall = (counts / total_for_side * 100).round(1)
        text_overall = [f"{p:.1f}%<br>{c}" for p, c in zip(perc_overall, counts.values)]

        front_codes = {"R-FT-DT", "R-FT-AT"}
        middle_codes = {"R-MT-DT", "R-MT-AT"}
        back_codes = {"R-BT-DT", "R-BT-AT"}

        front_total = counts[counts.index.isin(front_codes)].sum()
        middle_total = counts[counts.index.isin(middle_codes)].sum()
        back_total = counts[counts.index.isin(back_codes)].sum()

        front_pct = (front_total / total_for_side * 100).round(1) if total_for_side else 0.0
        middle_pct = (middle_total / total_for_side * 100).round(1) if total_for_side else 0.0
        back_pct = (back_total / total_for_side * 100).round(1) if total_for_side else 0.0

        def group_name(code):
            if code in front_codes:
                return "Front-third regains"
            if code in middle_codes:
                return "Middle-third regains"
            if code in back_codes:
                return "Back-third regains"
            return "Set pieces"

        def group_pct_for(code):
            if code in front_codes:
                return front_pct
            if code in middle_codes:
                return middle_pct
            if code in back_codes:
                return back_pct
            sp_total = counts[counts.index.str.startswith("SP-")].sum()
            return (sp_total / total_for_side * 100).round(1) if total_for_side else 0.0

        labels_short = [
            (code.split("-")[-2] + "-" + code.split("-")[-1]) if code.startswith("R-") else code
            for code in counts.index
        ]

        hover_texts = []
        for code, cnt, pct in zip(counts.index, counts.values, perc_overall.values):
            gname = group_name(code)
            gpct = group_pct_for(code)
            hover_texts.append(
                f"Type: {code} – {goal_type_labels.get(code, code)}"
                f"<br>Goals: {cnt}"
                f"<br>Total goals: {total_for_side}"
                f"<br>Percent of total: {pct:.1f}%"
                f"<br>Group: {gname} ({gpct:.1f}% of total)"
            )

        fig = go.Figure(go.Pie(
            labels=labels_short,
            values=counts.values,
            hole=0.45,
            text=text_overall,
            textinfo="label+text",
            hoverinfo="text",
            hovertext=hover_texts,
            sort=False,
            textfont=dict(family="Segoe UI Semibold", size=12),
        ))

        fig.update_layout(
            title=title,
            paper_bgcolor="black",
            plot_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
            legend=dict(orientation="h", yanchor="bottom", y=-0.1, xanchor="center", x=0.5),
            margin=dict(t=40, b=20, l=20, r=20),
            hoverlabel=dict(font=dict(family="Segoe UI")),
        )
        return fig

    # ---- Split & totals ----
    scored = pick(events, "Scored")
    conceded = pick(events, "Conceded")

    total_scored = len(scored)
    total_conceded = len(conceded)

    opp_suffix = "" if not opponent_choice or opponent_choice == "ALL" else f" vs {opponent_choice}"

    scored_regain_fig = build_pie(
        scored, regain_codes, f"Regain Types – Goals Scored{opp_suffix}", total_scored
    )
    scored_setpiece_fig = build_pie(
        scored, setpiece_codes, f"Set Piece Types – Goals Scored{opp_suffix}", total_scored
    )
    conceded_regain_fig = build_pie(
        conceded, regain_codes, f"Regain Types – Goals Conceded{opp_suffix}", total_conceded
    )
    conceded_setpiece_fig = build_pie(
        conceded, setpiece_codes, f"Set Piece Types – Goals Conceded{opp_suffix}", total_conceded
    )

    return scored_regain_fig, scored_setpiece_fig, conceded_regain_fig, conceded_setpiece_fig






# last 4 round - ON - button
#@callback(
#    Output("last-4-status", "children"),
#    Input("last-4-rounds-button", "n_clicks")
#)
def update_last4_status(n_clicks):
    if n_clicks % 2 == 1:
        return "Last 4 Rounds: ON"
    return ""

# shows button ON for goal type conceded by interval
#@callback(
#    Output("last-4-status-conceded", "children"),
#    Input("last-4-rounds-button-conceded", "n_clicks")
#)
def update_last4_status_conceded(n_clicks):
    if n_clicks % 2 == 1:
        return "Last 4 Rounds: ON"
    return ""
#===============================
# Goals scored by type callback
#===================================
@callback(
    Output("goals-by-type", "figure"),
    Output("last-4-status", "children"),
    Output("conceded-by-type", "figure"),
    Output("last-4-status-conceded", "children"),
    Input("team-select", "value"),
    Input("last-4-rounds-button", "n_clicks"),
    Input("last-4-rounds-button-conceded", "n_clicks"),
)
def update_stacked_goal_type_charts(selected_squad, last4_scored_clicks, last4_conceded_clicks):

    selected_team = TEAM_MAP.get(selected_squad, FOCUS_TEAM)

    last4_scored_clicks = last4_scored_clicks or 0
    last4_conceded_clicks = last4_conceded_clicks or 0

    df = league_goal_data.copy()

    # keep only the selected squad rows
    if "Team" in df.columns:
        df["Team"] = df["Team"].astype(str).str.strip()
        df = df[df["Team"] == str(selected_squad).strip()].copy()

    df["Home Team"] = df["Home Team"].astype(str).str.strip()
    df["Away Team"] = df["Away Team"].astype(str).str.strip()
    df["Scorer Team"] = df["Scorer Team"].fillna("").astype(str).str.strip()

    df = df[
        (df["Home Team"] == selected_team) |
        (df["Away Team"] == selected_team)
    ].copy()

    df["Match Date Parsed"] = pd.to_datetime(df["Match Date"], errors="coerce")

    # always recompute opponent
    df["Opponent"] = np.where(
        df["Home Team"] == selected_team,
        df["Away Team"],
        df["Home Team"]
    )


    # Opponent column should already exist from earlier, but just in case:
    if "Opponent" not in df.columns:
        def extract_opp(row):
            if row["Home Team"] == FOCUS_TEAM:
                return row["Away Team"]
            elif row["Away Team"] == FOCUS_TEAM:
                return row["Home Team"]
            return None
        df["Opponent"] = df.apply(extract_opp, axis=1)

    # --- Abbreviate goal types for x-axis ---
    def abbreviate(code):
        if not isinstance(code, str):
            return None
        code = code.strip()
        if code.startswith("R-"):
            parts = code.split("-")
            # e.g. "R-FT-DT" → "FT-DT"
            if len(parts) >= 3:
                return parts[-2] + "-" + parts[-1]
        return code

    df["Goal Abbr"] = df["Goal Type"].apply(abbreviate)

    # Fixed order of goal types (even if zero)
    all_types = ["FT-DT", "FT-AT", "MT-DT", "MT-AT", "BT-DT", "BT-AT", "SP-C", "SP-T", "SP-P", "SP-F"]

    # =========================
    #   GOALS SCORED BY TYPE
    # =========================
    df_scored = df[df["Scorer Team"] == selected_team].copy()
    status_scored = ""

    if last4_scored_clicks % 2 == 1:
        all_dates = sorted(df_scored["Match Date Parsed"].dropna().unique())
        if all_dates:
            last4_dates = all_dates[-4:] if len(all_dates) >= 4 else all_dates
            df_scored = df_scored[df_scored["Match Date Parsed"].isin(last4_dates)].copy()
            status_scored = "SHOWING : Last 4 rounds"
        else:
            status_scored = ""
    else:
        status_scored = ""

    scored_grouped = (
        df_scored
        .groupby(["Goal Abbr", "Opponent"])
        .size()
        .unstack(fill_value=0)
        .reindex(index=all_types, fill_value=0)
    )

    fig_scored = go.Figure()
    for opp in scored_grouped.columns:
        fig_scored.add_trace(go.Bar(
            x=scored_grouped.index,
            y=scored_grouped[opp],
            name=opp,
            marker_color=TEAM_COLORS.get(str(opp).strip(), "gray"),
            hovertemplate="<b>%{x}</b><br>%{fullData.name}<br>Scored: %{y}<extra></extra>",
            hoverlabel=dict(font=dict(family="Segoe UI"))
        ))

    fig_scored.update_layout(
        title=f"{selected_team} – Goals Scored by Type (Stacked by Opponent)",
        barmode="stack",
        plot_bgcolor="black",
        paper_bgcolor="black",
        font=dict(color="white", family="Segoe UI"),
        xaxis_title="Goal Type",
        yaxis_title="Goals Scored",
        margin=dict(t=40, b=40),
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=False, tickformat=".0f"),
        bargap=0.3,
        bargroupgap=0.1,
        legend_title="Opponent",
    )

    
    # =========================
    #   GOALS CONCEDED BY TYPE
    # =========================
    df_conceded = df[df["Scorer Team"] != selected_team].copy()
    status_conceded = ""

    if last4_conceded_clicks % 2 == 1:
        all_dates_c = sorted(df_conceded["Match Date Parsed"].dropna().unique())
        if all_dates_c:
            last4_dates_c = all_dates_c[-4:] if len(all_dates_c) >= 4 else all_dates_c
            df_conceded = df_conceded[df_conceded["Match Date Parsed"].isin(last4_dates_c)].copy()
            status_conceded = "SHOWING : Last 4 rounds"
        else:
            status_conceded = ""
    else:
        status_conceded = ""

    conceded_grouped = (
        df_conceded
        .groupby(["Goal Abbr", "Opponent"])
        .size()
        .unstack(fill_value=0)
        .reindex(index=all_types, fill_value=0)
    )

    fig_conceded = go.Figure()
    for opp in conceded_grouped.columns:
        fig_conceded.add_trace(go.Bar(
            x=conceded_grouped.index,
            y=conceded_grouped[opp],
            name=opp,
            marker_color=TEAM_COLORS.get(str(opp).strip(), "gray"),
            hovertemplate="<b>%{x}</b><br>%{fullData.name}<br>Conceded: %{y}<extra></extra>",
            hoverlabel=dict(font=dict(family="Segoe UI"))
        ))

    fig_conceded.update_layout(
        title=f"{selected_team} – Goals Conceded by Type (Stacked by Opponent)",
        barmode="stack",
        plot_bgcolor="black",
        paper_bgcolor="black",
        font=dict(color="white", family="Segoe UI"),
        xaxis_title="Goal Type",
        yaxis_title="Goals Conceded",
        margin=dict(t=40, b=40),
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=False, tickformat=".0f"),
        bargap=0.3,
        bargroupgap=0.1,
        legend_title="Opponent",
    )

    return fig_scored, status_scored, fig_conceded, status_conceded

# Callback for pass-string by type
@callback(
    Output("passstring-by-type", "figure"),
    Input("team-select", "value"),
    Input("last-4-rounds-button", "n_clicks"),
)
def update_passstring_by_goal_type(selected_squad, last4_scored_clicks):

    last4_scored_clicks = last4_scored_clicks or 0

    selected_team = TEAM_MAP.get(selected_squad, FOCUS_TEAM)

    df = league_goal_data.copy()

    # Filter by squad file
    if "Team" in df.columns:
        df["Team"] = df["Team"].astype(str).str.strip()
        df = df[df["Team"] == str(selected_squad).strip()].copy()

    df["Home Team"] = df["Home Team"].astype(str).str.strip()
    df["Away Team"] = df["Away Team"].astype(str).str.strip()
    df["Scorer Team"] = df["Scorer Team"].fillna("").astype(str).str.strip()

    df = df[
        (df["Home Team"] == selected_team) |
        (df["Away Team"] == selected_team)
    ].copy()

    df["Match Date Parsed"] = pd.to_datetime(df["Match Date"], errors="coerce")

    # --- Abbreviate goal types ---
    def abbreviate(code):
        if not isinstance(code, str):
            return None
        code = code.strip()
        if code.startswith("R-"):
            parts = code.split("-")
            if len(parts) >= 3:
                return parts[-2] + "-" + parts[-1]
        return code

    df["Goal Abbr"] = df["Goal Type"].apply(abbreviate)

    all_types = [
        "FT-DT","FT-AT","MT-DT","MT-AT","BT-DT","BT-AT",
        "SP-C","SP-T","SP-P","SP-F"
    ]

    # =========================
    #   FILTER GOALS SCORED
    # =========================
    df_scored = df[df["Scorer Team"] == selected_team].copy()

    if last4_scored_clicks % 2 == 1:
        all_dates = sorted(df_scored["Match Date Parsed"].dropna().unique())
        if all_dates:
            last4_dates = all_dates[-4:] if len(all_dates) >= 4 else all_dates
            df_scored = df_scored[df_scored["Match Date Parsed"].isin(last4_dates)].copy()

    # =========================
    #   PASS STRING BUCKETS
    # =========================
    def bucket_passes(val):
        try:
            n = int(val)
        except (TypeError, ValueError):
            return None

        if n <= 1:
            return "0–1"
        elif 2 <= n <= 4:
            return "2–4"
        elif 5 <= n <= 7:
            return "5–7"
        else:
            return "8+"

    df_scored["Pass Bucket"] = df_scored["Pass-string"].apply(bucket_passes)

    df_scored = df_scored.dropna(subset=["Pass Bucket","Goal Abbr"]).copy()

    bucket_order = ["0–1","2–4","5–7","8+"]

    grouped = (
        df_scored
        .groupby(["Goal Abbr","Pass Bucket"])
        .size()
        .unstack(fill_value=0)
        .reindex(index=all_types, fill_value=0)
    )

    grouped = grouped.reindex(columns=bucket_order, fill_value=0)

    fig = go.Figure()

    for bucket in bucket_order:
        fig.add_trace(go.Bar(
            x=grouped.index,
            y=grouped[bucket],
            name=bucket,
            hovertemplate=(
                "<b>%{x}</b><br>"
                "Pass-string: %{fullData.name}<br>"
                "Goals: %{y}<extra></extra>"
            ),
            hoverlabel=dict(font=dict(family="Segoe UI"))
        ))

    fig.update_layout(
        title=f"{selected_team} – Pass-string by Goal Type (Goals only)",
        barmode="stack",
        plot_bgcolor="black",
        paper_bgcolor="black",
        font=dict(color="white", family="Segoe UI"),
        xaxis_title="Goal Type",
        yaxis_title="Goals Scored",
        margin=dict(t=40, b=40),
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=False, tickformat=".0f"),
        bargap=0.3,
        bargroupgap=0.1,
        legend_title="Pass-string bucket",
    )

    return fig


# callback - Goal Detail by Type – Assist/Buildup/Finish via dropdown
@callback(
    Output("goal-context-by-type", "figure"),
    Input("team-select", "value"),
    Input("last-4-rounds-button", "n_clicks"),
    Input("goal-context-dimension", "value"),
)
def update_goal_context_by_type(selected_squad, last4_scored_clicks, dimension_col):
    last4_scored_clicks = last4_scored_clicks or 0
    selected_team = TEAM_MAP.get(selected_squad, FOCUS_TEAM)

    # Base df: only matches involving selected team, from selected squad file
    df = league_goal_data.copy()

    if "Team" in df.columns:
        df["Team"] = df["Team"].astype(str).str.strip()
        df = df[df["Team"] == str(selected_squad).strip()].copy()

    df["Home Team"] = df["Home Team"].astype(str).str.strip()
    df["Away Team"] = df["Away Team"].astype(str).str.strip()
    df["Scorer Team"] = df["Scorer Team"].fillna("").astype(str).str.strip()

    df = df[
        (df["Home Team"] == selected_team) |
        (df["Away Team"] == selected_team)
    ].copy()

    # Parse match date
    df["Match Date Parsed"] = pd.to_datetime(df["Match Date"], errors="coerce")

    # --- Abbreviate goal types for stacks ---
    def abbreviate(code):
        if not isinstance(code, str):
            return None
        code = code.strip()
        if code.startswith("R-"):
            parts = code.split("-")
            if len(parts) >= 3:
                return parts[-2] + "-" + parts[-1]
        return code

    df["Goal Abbr"] = df["Goal Type"].apply(abbreviate)

    all_types = [
        "FT-DT", "FT-AT", "MT-DT", "MT-AT", "BT-DT", "BT-AT",
        "SP-C", "SP-T", "SP-P", "SP-F"
    ]

    # =========================
    #   FILTER: GOALS SCORED
    # =========================
    df_scored = df[df["Scorer Team"] == selected_team].copy()

    if last4_scored_clicks % 2 == 1:
        all_dates = sorted(df_scored["Match Date Parsed"].dropna().unique())
        if all_dates:
            last4_dates = all_dates[-4:] if len(all_dates) >= 4 else all_dates
            df_scored = df_scored[df_scored["Match Date Parsed"].isin(last4_dates)].copy()

    # =========================
    #   DIMENSION CLEANUP
    # =========================
    if dimension_col not in df_scored.columns:
        empty_fig = go.Figure()
        empty_fig.update_layout(
            title=f"{selected_team} – {dimension_col} (no data available)",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
        )
        return empty_fig

    df_scored[dimension_col] = df_scored[dimension_col].replace("", pd.NA)
    df_scored = df_scored.dropna(subset=["Goal Abbr", dimension_col]).copy()

    # =========================
    #   GROUP: DIMENSION (x) x GOAL TYPE (stack)
    # =========================
    grouped = (
        df_scored
        .groupby([dimension_col, "Goal Abbr"])
        .size()
        .unstack("Goal Abbr", fill_value=0)
    )

    grouped = grouped.reindex(columns=all_types, fill_value=0)

    x_categories = list(grouped.index)

    # =========================
    #   OPTIONAL: FORCE ORDERS
    # =========================
    if dimension_col == "Buildup Lane":
        desired_order = ["Left", "Centre", "Right"]
        ordered = [x for x in desired_order if x in grouped.index]
        extras = [x for x in grouped.index if x not in desired_order]
        x_categories = ordered + extras
        grouped = grouped.reindex(index=x_categories, fill_value=0)

    # =========================
    #   BUILD FIGURE
    # =========================
    fig = go.Figure()
    for gt in all_types:
        if grouped[gt].sum() == 0:
            continue

        fig.add_trace(go.Bar(
            x=x_categories,
            y=grouped[gt],
            name=gt,
            hovertemplate=(
                "<b>%{x}</b><br>"
                "Goal type: " + str(gt) + "<br>"
                "Goals: %{y}<extra></extra>"
            ),
            hoverlabel=dict(font=dict(family="Segoe UI")),
        ))

    fig.update_layout(
        title=f"{selected_team} – {dimension_col} (stacked by Goal Type, goals only)",
        barmode="stack",
        plot_bgcolor="black",
        paper_bgcolor="black",
        font=dict(color="white", family="Segoe UI"),
        xaxis_title=dimension_col,
        yaxis_title="Goals Scored",
        margin=dict(t=40, b=40),
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=False, tickformat=".0f"),
        bargap=0.3,
        bargroupgap=0.1,
        legend_title="Goal Type",
    )

    return fig



# callback - Goal Detail by Type Conceded – Assist/Buildup/Finish via dropdown
@callback(
    Output("goal-context-by-type-conceded", "figure"),
    Input("team-select", "value"),
    Input("last-4-rounds-button", "n_clicks"),
    Input("goal-context-dimension-conceded", "value"),
)
def update_goal_context_by_type_conceded(selected_squad, last4_conceded_clicks, dimension_key):
    last4_conceded_clicks = last4_conceded_clicks or 0
    selected_team = TEAM_MAP.get(selected_squad, FOCUS_TEAM)

    DIMENSION_COLUMN_MAP = {
        "assist_type":       ("Assist type",       "Assist type"),
        "buildup_lane":      ("Buildup Lane",      "Buildup Lane"),
        "finish_type":       ("Finish Type",       "Finish Type"),
        "how_penetrated":    ("How penetrated",    "How penetrated"),
        "first_time_finish": ("First-time finish", "First-time finish"),
    }

    if dimension_key not in DIMENSION_COLUMN_MAP:
        fig = go.Figure()
        fig.update_layout(
            title=f"{selected_team} – (Unknown dimension, conceded)",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
        )
        return fig

    dimension_col, dimension_label = DIMENSION_COLUMN_MAP[dimension_key]

    # Base df: selected squad + matches involving selected team
    df = league_goal_data.copy()

    if "Team" in df.columns:
        df["Team"] = df["Team"].astype(str).str.strip()
        df = df[df["Team"] == str(selected_squad).strip()].copy()

    df["Home Team"] = df["Home Team"].astype(str).str.strip()
    df["Away Team"] = df["Away Team"].astype(str).str.strip()
    df["Scorer Team"] = df["Scorer Team"].fillna("").astype(str).str.strip()

    df = df[
        (df["Home Team"] == selected_team) |
        (df["Away Team"] == selected_team)
    ].copy()

    df["Match Date Parsed"] = pd.to_datetime(df["Match Date"], errors="coerce")

    def abbreviate(code):
        if not isinstance(code, str):
            return None
        code = code.strip()
        if code.startswith("R-"):
            parts = code.split("-")
            if len(parts) >= 3:
                return parts[-2] + "-" + parts[-1]
        return code

    df["Goal Abbr"] = df["Goal Type"].apply(abbreviate)

    all_types = [
        "FT-DT", "FT-AT", "MT-DT", "MT-AT", "BT-DT", "BT-AT",
        "SP-C", "SP-T", "SP-P", "SP-F"
    ]

    # FILTER: goals conceded
    df_conceded = df[df["Scorer Team"] != selected_team].copy()

    if last4_conceded_clicks % 2 == 1:
        all_dates = sorted(df_conceded["Match Date Parsed"].dropna().unique())
        if all_dates:
            last4_dates = all_dates[-4:] if len(all_dates) >= 4 else all_dates
            df_conceded = df_conceded[df_conceded["Match Date Parsed"].isin(last4_dates)].copy()

    if dimension_col not in df_conceded.columns:
        fig = go.Figure()
        fig.update_layout(
            title=f"{selected_team} – {dimension_label} (conceded – no data: column missing)",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
        )
        return fig

    df_conceded[dimension_col] = df_conceded[dimension_col].replace("", pd.NA)
    df_conceded = df_conceded.dropna(subset=["Goal Abbr", dimension_col]).copy()

    if df_conceded.empty:
        fig = go.Figure()
        fig.update_layout(
            title=f"{selected_team} – {dimension_label} (conceded – no goals with this attribute recorded)",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
        )
        return fig

    grouped = (
        df_conceded
        .groupby([dimension_col, "Goal Abbr"])
        .size()
        .unstack("Goal Abbr", fill_value=0)
    )

    grouped = grouped.reindex(columns=all_types, fill_value=0)
    x_categories = list(grouped.index)

    if dimension_col == "Buildup Lane":
        desired_order = ["Left", "Centre", "Right"]
        ordered = [x for x in desired_order if x in grouped.index]
        extras = [x for x in grouped.index if x not in desired_order]
        x_categories = ordered + extras
        grouped = grouped.reindex(index=x_categories, fill_value=0)

    fig = go.Figure()
    has_data = False

    for gt in all_types:
        if grouped[gt].sum() == 0:
            continue
        has_data = True

        fig.add_trace(go.Bar(
            x=x_categories,
            y=grouped[gt],
            name=gt,
            hovertemplate=(
                "<b>%{x}</b><br>"
                "Goal type: " + str(gt) + "<br>"
                "Goals conceded: %{y}<extra></extra>"
            ),
            hoverlabel=dict(font=dict(family="Segoe UI")),
        ))

    if not has_data:
        fig = go.Figure()
        fig.update_layout(
            title=f"{selected_team} – {dimension_label} (conceded – no goals recorded in this breakdown)",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(color="white", family="Segoe UI"),
        )
        return fig

    fig.update_layout(
        title=f"{selected_team} – {dimension_label} (conceded – stacked by Goal Type)",
        barmode="stack",
        plot_bgcolor="black",
        paper_bgcolor="black",
        font=dict(color="white", family="Segoe UI"),
        xaxis_title=dimension_label,
        yaxis_title="Goals Conceded",
        margin=dict(t=40, b=40),
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=False, tickformat=".0f"),
        bargap=0.3,
        bargroupgap=0.1,
        legend_title="Goal Type",
    )

    return fig



# magic quadrant callback
@callback(
    Output("quadrant-alignment-chart", "figure"),
    Input("team-select", "value")
)
def update_quadrant_chart(selected_squad):
    df = team_data.copy()

    # Filter to selected squad file
    if "Team" in df.columns:
        df["Team"] = df["Team"].astype(str).str.strip()
        df = df[df["Team"] == str(selected_squad).strip()].copy()

    # Basic cleaning
    for c in ["Opponent", "Match ID", "Full-score"]:
        if c in df.columns:
            df[c] = df[c].fillna("").astype(str).str.strip()

    for c in ["Possession", "Quadrant Points", "Shots", "Passes", "Opp-passes", "Opp-shots"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=["Possession", "Quadrant Points"]).copy()

    if df.empty:
        fig = go.Figure()
        fig.update_layout(
            title="Philosophy Alignment: Quadrant",
            plot_bgcolor="black",
            paper_bgcolor="black",
            font=dict(size=14, color="white", family="Segoe UI"),
            xaxis=dict(showgrid=False, zeroline=False, showline=False),
            yaxis=dict(showgrid=False, zeroline=False, showline=False),
        )
        fig.add_annotation(
            text="No data available for this squad",
            x=0.5, y=0.5,
            xref="paper", yref="paper",
            showarrow=False,
            font=dict(size=18, color="white", family="Segoe UI")
        )
        return fig

    # Define color map for opponents
    team_colors = {
        "Tuggeranong": "green",
        "Croatia": "crimson",
        "Olympic": "navy",
        "Gungahlin": "#FF1493",
        "Majura": "royalblue",
        "ANU": "orange",
        "Wanderers": "firebrick",
        "TuggeranongRes": "green",
        "CroatiaRes": "crimson",
        "OlympicRes": "navy",
        "GungahlinRes": "#FF1493",
        "MajuraRes": "royalblue",
        "ANURes": "orange",
        "WanderersRes": "firebrick",
    }

    fig = go.Figure()

    for opponent in df["Opponent"].dropna().unique():
        subset = df[df["Opponent"] == opponent].copy()

        fig.add_trace(
            go.Scatter(
                x=subset["Possession"],
                y=subset["Quadrant Points"],
                mode="markers",
                name=opponent,
                marker=dict(
                    size=10,
                    color=team_colors.get(opponent, "gray")
                ),
                customdata=subset[
                    [
                        "Match ID",
                        "Opponent",
                        "Full-score",
                        "Shots",
                        "Passes",
                        "Opp-passes",
                        "Opp-shots",
                    ]
                ].values,
                hovertemplate=(
                    "<b>Match ID:</b> %{customdata[0]}<br>"
                    "<b>Opponent:</b> %{customdata[1]}<br>"
                    "<b>Full Score:</b> %{customdata[2]}<br>"
                    "<b>Possession:</b> %{x}%<br>"
                    "<b>Quadrant Points:</b> %{y}<br>"
                    "<b>Shots:</b> %{customdata[3]}<br>"
                    "<b>Passes:</b> %{customdata[4]}<br>"
                    "<b>Opp Passes:</b> %{customdata[5]}<br>"
                    "<b>Opp Shots:</b> %{customdata[6]}<extra></extra>"
                ),
                hoverlabel=dict(font=dict(size=13, family="Segoe UI")),
            )
        )

    # Vertical midline at 50% possession
    fig.add_shape(
        type="line",
        x0=50, x1=50,
        y0=0, y1=1,
        xref="x", yref="paper",
        line=dict(color="white", dash="dash")
    )

    # Horizontal midline at 0 quadrant points
    fig.add_shape(
        type="line",
        x0=0, x1=1,
        y0=0, y1=0,
        xref="paper", yref="y",
        line=dict(color="white", dash="dash")
    )

    fig.update_layout(
        title="Philosophy Alignment: Quadrant",
        xaxis_title="Possession (%)",
        yaxis_title="Quadrant Points",
        plot_bgcolor="black",
        paper_bgcolor="black",
        font=dict(size=14, color="white", family="Segoe UI"),
        margin=dict(t=40, b=40, l=40, r=40),
        xaxis=dict(
            range=[20, 80],
            showgrid=False,
            tickfont=dict(size=12),
            zeroline=False,
        ),
        yaxis=dict(
            range=[-100, 100],
            showgrid=False,
            tickfont=dict(size=12),
            zeroline=False,
        ),
        hoverlabel=dict(
            font=dict(size=13, family="Segoe UI")
        ),
        legend=dict(
            x=1,
            y=1
        )
    )

    return fig



# Local development entry point
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8050)),
        debug=True
    )


