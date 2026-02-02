import os
import json
import tempfile
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ==========================
# CONFIG
# ==========================
SHEET_NAME = os.environ["SHEET_NAME"]
WORKSHEET_NAME = os.environ["WORKSHEET_NAME"]
EXPORT_IMAGE = False               # You can still enable PNG export
EXPORT_HTML = True                 # Interactive HTML version
OUTPUT_DIR = "charts"             # Folder for generated charts

# Ensure output directory exists
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ==========================
# GOOGLE SHEETS CONNECTION
# ==========================
scope = ["https://spreadsheets.google.com/feeds",
         "https://www.googleapis.com/auth/drive"]

if "GSPREAD_SA_JSON" in os.environ:
    # Running in GitHub Actions
    sa_info = json.loads(os.environ["GSPREAD_SA_JSON"])

    with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".json") as f:
        json.dump(sa_info, f)
        sa_path = f.name

    creds = ServiceAccountCredentials.from_json_keyfile_name(sa_path, scope)

else:
    # Running locally
    creds = ServiceAccountCredentials.from_json_keyfile_name(
        "service_account.json", scope
    )

client = gspread.authorize(creds)
sheet = client.open(SHEET_NAME).worksheet(WORKSHEET_NAME)

data = pd.DataFrame(sheet.get_all_records())

# ==========================
# TIME CONVERSION
# ==========================
def mmsscc_to_seconds(t):
    m, rest = t.split(":")
    s, cc = rest.split(".")
    return int(m)*60 + int(s) + int(cc)/100

def seconds_to_mmsscc(sec):
    m = int(sec // 60)
    s = int(sec % 60)
    cc = int(round((sec - int(sec)) * 100))
    return f"{m}:{s:02}.{cc:02}"

data["Date"] = pd.to_datetime(data["Date"])
data["Time_sec"] = data["Time"].apply(mmsscc_to_seconds)

# ==========================
# LOOP THROUGH TRACKS
# ==========================
for track in data["Track"].unique():
    TRACK_SELECTED = track
    df = data[data["Track"] == TRACK_SELECTED].sort_values("Date").reset_index(drop=True)
    
    df["DateStr"] = df["Date"].dt.strftime("%m-%d-%y")
    df["Best_Time"] = df["Time_sec"].cummin()
    
    # Identify record breaks
    record_df = df[df["Time_sec"] == df["Best_Time"]].copy()

    # Build step ranges (start → next change)
    record_df["End_Date"] = record_df["Date"].shift(-1)
    record_df.loc[record_df.index[-1], "End_Date"] = record_df["Date"].iloc[-1]

    # String dates for categorical axis
    record_df["StartStr"] = record_df["Date"].dt.strftime("%m-%d-%y")
    record_df["EndStr"] = record_df["End_Date"].dt.strftime("%m-%d-%y")

    # ==========================
    # CHART
    # ==========================
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=False,
        row_heights=[0.65, 0.35],
        vertical_spacing=0.08,
        specs=[
            [{"type": "scatter"}],
            [{"type": "table"}]
        ]
    )

    palette = px.colors.qualitative.Dark24
    color_map = dict(zip(df["Player"].unique(), palette))

    # Indices where a new record is set

    record_points = df[df["Best_Time"].diff() != 0]

    shown_players = set()

    for i in range(len(record_df)):
        row = record_df.iloc[i]

        start_idx = df.index.get_loc(row.name)

        if i < len(record_df) - 1:
            next_row = record_df.iloc[i + 1]
            end_idx = df.index.get_loc(next_row.name)
        else:
            end_idx = len(df) - 1

        seg = df.iloc[start_idx:end_idx + 1]

        holder = row["Player"]
        show_legend = holder not in shown_players
        shown_players.add(holder)

        fig.add_trace(go.Scatter(
            x=seg["DateStr"],
            y=seg["Best_Time"],
            mode="lines",
            name=holder,
            showlegend=show_legend,
            hoverinfo="skip",
            line=dict(
                shape="hv",
                width=4,
                color=color_map[holder]
            ),
        ),
        row=1,
        col=1
    )

    fig.add_trace(go.Scatter(
        x=record_points["DateStr"],
        y=record_points["Best_Time"],
        mode="markers",
        name="Record",
        showlegend=False,
        marker=dict(
            size=8,
            color="black",
            symbol="circle"
        ),
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>"
            "Player: %{customdata[1]}<br>"
            "Time: %{customdata[2]}"
            "<extra></extra>"
        ),
        customdata=list(zip(
            record_points["DateStr"],
            record_points["Player"],
            record_points["Best_Time"].map(seconds_to_mmsscc)
        ))
        ),
        row=1,
        col=1
    )

    # ==========================
    # TABLE (Record Progression)
    # ==========================
    table_df = record_points.copy()
    table_df = table_df.sort_values("Best_Time", ascending=True)

    table_df["Date"] = table_df["Date"].dt.strftime("%m-%d-%y")
    table_df["Time"] = table_df["Best_Time"].apply(seconds_to_mmsscc)

    table_df = table_df[["Date", "Player", "Time"]]

    fig.add_trace(
        go.Table(
            header=dict(
                values=["Date", "Player", "Time"],
                fill_color="#EEEEEE",
                align="left",
                font=dict(size=12, color="black")
            ),
            cells=dict(
                values=[
                    table_df["Date"],
                    table_df["Player"],
                    table_df["Time"]
                ],
                fill_color="white",
                align="left",
                font=dict(size=11)
            )
        ),
        row=2,
        col=1
    )
        
    # ==========================
    # AXES & FORMATTING
    # ==========================
    def choose_tick_step(span):
        if span <= 0.6:
            return 0.05 
        elif span <= 1.5:
            return 0.1
        elif span <= 3:
            return 0.25
        elif span <= 6:
            return 0.5
        else:
            return 1.0

    def generate_ticks(min_val, max_val, step):
        start = (int(min_val / step)) * step
        ticks = []
        val = start
        while val <= max_val + 1e-6:
            ticks.append(round(val, 3))
            val += step
        return ticks

    y_min = df["Best_Time"].min()
    y_max = df["Best_Time"].max()

    padding = max(0.2, (y_max - y_min) * 0.15)
    y_lo = y_min - padding
    y_hi = y_max + padding

    span = y_hi - y_lo
    step = choose_tick_step(span)

    first_date_rows = df.loc[
        df["DateStr"].ne(df["DateStr"].shift())
    ]

    x_tick_vals = first_date_rows["DateStr"].tolist()
    x_tick_text = x_tick_vals

    y_tick_vals = generate_ticks(y_lo, y_hi, step)
    y_tick_labels = [seconds_to_mmsscc(t) for t in y_tick_vals]

    x_dates = df["Date"].dt.strftime("%m-%d-%y")

    if len(y_tick_vals) > 12:
        y_tick_vals = y_tick_vals[::2]
        y_tick_labels = y_tick_labels[::2]

    fig.update_yaxes(
        title="3 Lap Time",
        range=[y_lo, y_hi],
        tickvals=y_tick_vals,
        ticktext=y_tick_labels,
    )

    fig.update_xaxes(
        type="category",
        categoryorder="array",
        categoryarray=df["DateStr"].tolist(),
        tickmode="array",
        tickvals=x_tick_vals,
        ticktext=x_tick_text,
        tickangle=-30,
        title="Date",
        row=1,
        col=1
    )

    fig.update_layout(
        title=f"{TRACK_SELECTED} – Record Progression",
        hovermode="closest",
        legend_title="Record Holder",
        template="seaborn",
        height=1200,
        margin=dict(t=60, b=40)
    )

    # ==========================
    # EXPORT
    # ==========================
    safe_name = TRACK_SELECTED.lower().replace(" ", "_")
    output_path = os.path.join(OUTPUT_DIR, f"{safe_name}.html")
    fig.write_html(output_path)