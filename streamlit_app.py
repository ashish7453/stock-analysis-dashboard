"""
Streamlit UI for the Analysis Dashboard.

All calculations live in `stock-chart-app-main/app.py` (shared with the Flask UI);
this file only handles inputs, caching and rendering.

Run locally:   streamlit run streamlit_app.py
"""
import io
import os
import re
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(HERE, "stock-chart-app-main")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import importlib                 # noqa: E402
import app as core               # noqa: E402  (needs the sys.path tweak above)

# Streamlit Cloud re-runs this file when the repo updates, but can keep the OLD
# `app` module in memory, mixing new UI code with old calculations. Reload it
# whenever app.py changes on disk, and drop results cached by the old code.
_mtime = os.path.getmtime(core.__file__)
if getattr(core, "_loaded_mtime", None) != _mtime:   # also catches modules loaded by older code
    core = importlib.reload(core)
    st.cache_data.clear()
core._loaded_mtime = _mtime

import charts                    # noqa: E402  Plotly charts (stock-chart-app-main/charts.py)
_cmtime = os.path.getmtime(charts.__file__)
if getattr(charts, "_loaded_mtime", None) != _cmtime:
    charts = importlib.reload(charts)
charts._loaded_mtime = _cmtime
import matplotlib.pyplot as plt  # noqa: E402

st.set_page_config(page_title="Analysis Dashboard", page_icon="📈", layout="wide")
# Use the full width: Streamlit's wide layout still keeps ~80px empty on each
# side, which is wasted space when the app is embedded (e.g. in Google Sites).
st.html("""<style>
[data-testid="stMainBlockContainer"], .block-container {
  padding-left: 1rem !important; padding-right: 1rem !important;
  padding-top: 1rem !important; max-width: 100% !important; }
/* Not embedded: Streamlit's 60px header bar (Deploy / menu) sits on top of the
   page, so leave room for it or it covers the Tool dropdown. */
.stApp:not(.streamlit-embedded) [data-testid="stMainBlockContainer"],
.stApp:not(.streamlit-embedded) .block-container { padding-top: 4rem !important; }
</style>""")

DATA_SOURCE = ("Data: Yahoo Finance (delayed) and NSE/BSE end-of-day files. "
               "Not investment advice.")
CACHE_TTL = 15 * 60          # normal runs: reuse results for 15 minutes
LIVE_TTL = 55                # live mode: refetch roughly every minute
LIVE_EVERY = 60              # live mode refresh interval (seconds)
IST = ZoneInfo("Asia/Kolkata")
PCT = st.column_config.NumberColumn(format="%.2f%%")


def today_ist():
    """Today's date in India. The hosting server runs on UTC, so date.today()
    would still say 'yesterday' between 00:00 and 05:30 IST."""
    return datetime.now(IST).date()


# --------------------------------------------------------------- cached data
@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def cached_range_stats(names: dict, start: str, end: str, version: int = core.CALC_VERSION):
    return core.range_stats(names, start, end)


@st.cache_data(ttl=LIVE_TTL, show_spinner=False)
def live_range_stats(names: dict, start: str, end: str, version: int = core.CALC_VERSION):
    return core.range_stats(names, start, end)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def cached_index_returns(names: dict, today: str, version: int = core.CALC_VERSION):
    return core.compute_index_returns(names, reference_date=today)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def cached_seasonality(ticker: str, years: int, include_partial: bool):
    return core.seasonality_tables(ticker, years, include_partial)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def cached_ohlc(ticker: str, start: str, end: str):
    return core.download_ohlc(ticker, start, end)


# ------------------------------------------------------------------- helpers
PLOTLY_CONFIG = {"displaylogo": False, "scrollZoom": False,
                 "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d"]}


def show_chart(fig):
    """Show a chart: Plotly figures interactively (full width, fixed height that
    fits the screen, following the app's light/dark theme); anything else via show_fig."""
    if hasattr(fig, "to_plotly_json"):
        dark = (getattr(st.context.theme, "type", None) or "light") == "dark"
        charts.apply_ink(fig, "#ffffff" if dark else "#000000")
        st.plotly_chart(fig, width="stretch", theme="streamlit", config=PLOTLY_CONFIG)
    else:
        show_fig(fig)


def show_fig(fig, max_height="85vh"):
    """Show a chart as large as possible WITHOUT being taller than the visible
    area: full width, but capped at `max_height` with its shape kept, so the
    whole chart is on screen (also inside an embed box)."""
    import base64
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    b64 = base64.b64encode(buf.getvalue()).decode()
    st.html(f'<img src="data:image/png;base64,{b64}" alt="chart" style="display:block;'
            f'margin:0 auto;width:auto;height:auto;max-width:100%;max-height:{max_height}">')


def valid_range(start, end):
    if start > end:
        st.error("Start date must be on or before the end date.")
        return False
    if end > today_ist():
        st.warning("End date is in the future; data runs up to the latest close.")
    return True


def column_config(df, price_fmt="%.2f"):
    cfg = {}
    for c in df.columns:
        if c.endswith("(%)") or c.endswith("D %") or c.endswith("High %"):
            cfg[c] = PCT
        elif "Price" in c or "Value" in c or c in ("Range High", "Range Low"):
            cfg[c] = st.column_config.NumberColumn(format=price_fmt)
        elif c.startswith("Rank") or c == "Sum of Ranks":
            cfg[c] = st.column_config.NumberColumn(format="%d")
    return cfg


def download_buttons(df, filename, key, index=False):
    c1, c2, _ = st.columns([1, 1, 4])
    c1.download_button("⬇ CSV", df.to_csv(index=index).encode(), f"{filename}.csv",
                       "text/csv", key=f"{key}_csv")
    buf = io.BytesIO()
    df.to_excel(buf, index=index, sheet_name="Results")
    c2.download_button("⬇ Excel", buf.getvalue(), f"{filename}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       key=f"{key}_xlsx")


def summary_metrics(df, col="Gain (%)", name_fmt=None):
    """Breadth + best/worst row of st.metric cards."""
    v = df.dropna(subset=[col])
    if name_fmt is not None:
        v = name_fmt(v)
    if v.empty:
        return
    best, worst = v.iloc[0], v.iloc[-1]
    m = st.columns(5)
    m[0].metric("Advancing", int((v[col] > 0).sum()))
    m[1].metric("Declining", int((v[col] < 0).sum()))
    m[2].metric("Median", f"{v[col].median():.2f}%")
    m[3].metric("Best", best["Name"], f"{best[col]:.2f}%")
    m[4].metric("Worst", worst["Name"], f"{worst[col]:.2f}%")


def missing_note(df, col, source="Yahoo"):
    missing = df[df[col].isna()]["Name"].tolist() if col in df else []
    if missing:
        st.caption(f"No data from {source} for: " + ", ".join(missing))


# ======================================================= date-range tool body
def _range_body(key, title, names, p, views, price_fmt, unit_note):
    fetch = live_range_stats if p["live"] else cached_range_stats
    with st.spinner(f"Fetching {len(names)} symbols..."):
        try:
            df = fetch(names, p["start"], p["end"], version=core.CALC_VERSION)
        except core.DataUnavailable as e:      # not cached: next click retries
            st.error(str(e))
            return
    if p["live"]:
        st.caption(f"🔴 Live · refreshes every {LIVE_EVERY}s · last update "
                   f"{datetime.now(IST):%H:%M:%S} IST")
    if unit_note:
        st.info(unit_note, icon="ℹ️")
    show_range_results(df, key, title, p, views, price_fmt)


def show_range_results(df, key, title, p, views, price_fmt="%.2f", source="Yahoo Finance",
                       name_fmt=None, live=None):
    """Summary line, metrics, chart, table and downloads for a range_stats frame."""
    v = df.dropna(subset=["Gain (%)"])
    req_start, req_end = pd.Timestamp(p["start"]).date(), pd.Timestamp(p["end"]).date()
    if v.empty:
        st.warning(f"{source} has no closing prices between {req_start:%a %d-%b-%Y} "
                   f"and {req_end:%a %d-%b-%Y} yet (market holiday/weekend, or the day's "
                   "data is not published yet). Try again later or pick an earlier date.")
    else:
        b, l = v["Base Date"].mode().iloc[0], v["Last Date"].mode().iloc[0]
        live = live or {}
        end_txt = (f"today's live value ({l:%a %d-%b-%Y}, {live['as_of']})"
                   if live.get("source") and l == today_ist() else f"close of {l:%a %d-%b-%Y}")
        st.markdown(f"**Gain measured from close of {b:%a %d-%b-%Y} → {end_txt}** "
                    f"(base = last trading day before your start date {req_start:%d-%b-%Y})")
        if l < req_end and req_end.weekday() < 5:
            st.caption(f"⚠️ Latest close available from {source} is {l:%a %d-%b}; "
                       f"no data yet for {req_end:%a %d-%b}.")
    summary_metrics(df, name_fmt=name_fmt)

    view = (st.radio("Chart", list(views), horizontal=True, key=f"{key}_view")
            if len(views) > 1 else next(iter(views)))
    start, end = pd.Timestamp(p["start"]), pd.Timestamp(p["end"])
    fig = views[view](df, f"{title}: {start:%d-%m-%Y} to {end:%d-%m-%Y}")
    if fig is None:
        st.warning("No valid data for this range.")
    else:
        show_chart(fig)

    st.dataframe(df, width="stretch", hide_index=True,
                 column_config=column_config(df, price_fmt))
    st.caption("Gain = close on the end date vs the close of the trading day "
               "BEFORE the start date, so the start day's move is included. Check "
               "Base Date / Last Date in the table. Volatility is "
               "annualised from daily returns. Max drawdown = worst fall from a "
               "peak inside the range.")
    download_buttons(df, f"{key}_{p['start']}_{p['end']}", key)
    missing_note(df, "Gain (%)", source="NSE for this range" if source == "NSE" else source)


_range_static = st.fragment(_range_body)
_range_live = st.fragment(run_every=LIVE_EVERY)(_range_body)


def range_tool(key, title, names, views, button,
               price_fmt="%.2f", unit_note=None, extra=None):
    """Generic 'performance between two dates' page."""
    st.header(title)
    if extra:
        st.caption(extra)
    c1, c2, c3 = st.columns([1, 1, 1])
    start = c1.date_input("Start", today_ist(), key=f"{key}_start")
    end = c2.date_input("End", today_ist(), key=f"{key}_end")
    c3.write("")
    live = c3.toggle("Live auto-refresh", False, key=f"{key}_live",
                     help=f"Re-fetches every {LIVE_EVERY}s. Only used when the end date is today.")
    if st.button(button, type="primary", key=f"{key}_go") and valid_range(start, end):
        st.session_state[key] = {"start": str(start), "end": str(end),
                                 "live": bool(live and end >= today_ist())}
    p = st.session_state.get(key)
    if p:
        (_range_live if p["live"] else _range_static)(
            key, title, names, p, views, price_fmt, unit_note)


# ================================================== 30/60/90-day ranking body
@st.fragment
def _ranking_body(key, title, names, chart_title):
    with st.spinner(f"Pulling 30/60/90-day returns for {len(names)} symbols..."):
        try:
            df = cached_index_returns(names, str(today_ist()), version=core.CALC_VERSION)
        except Exception as e:
            st.error(f"Error: {e}")
            return
    show_ranking_results(df, key, chart_title)


def show_ranking_results(df, key, chart_title, name_fmt=None, index=True):
    """Metrics, strongest/weakest chart, table and downloads for a ranked frame."""
    ok = df.dropna(subset=["Sum of Ranks"])
    if not ok.empty:
        okn = name_fmt(ok) if name_fmt else ok
        m = st.columns(4)
        m[0].metric("Ranked", len(ok))
        m[1].metric("Strongest", okn.iloc[0]["Name"], f"{ok.iloc[0]['30D %']:.2f}% (30D)")
        m[2].metric("Weakest", okn.iloc[-1]["Name"], f"{ok.iloc[-1]['30D %']:.2f}% (30D)")
        m[3].metric("Positive over 90D", f"{int((ok['90D %'] > 0).sum())} / {len(ok)}")

    c1, c2 = st.columns([2, 1])
    which = c1.radio("Chart", ["Strongest", "Weakest"], horizontal=True, key=f"{key}_which",
                     help="Ranked by the sum of 30/60/90-day return ranks (lower = stronger)")
    n = c2.slider("How many", 3, 10, 3, key=f"{key}_n")
    fig = charts.window_bars(name_fmt(df) if name_fmt else df, which.lower(), n=n,
                                  title_prefix=f"{chart_title}: ")
    if fig is None:
        st.warning("No symbol returned complete data.")
    else:
        show_chart(fig)
    st.dataframe(df, width="stretch", hide_index=not index, column_config=column_config(df))
    st.caption("30D % = latest close vs the close 30 days ago (or the last trading "
               "day before that, if it was a holiday); same for 60D and 90D. "
               "Rank 1 = best return in that window. 'Off 90D High' = how far the "
               "last close is below the highest close of the last 90 days.")
    download_buttons(df, f"{key}_{today_ist()}", key, index=index)
    missing_note(df, "Sum of Ranks")


def ranking_tool(key, title, names, chart_title=None, show_header=True):
    if show_header:
        st.header(title)
    if st.button("Run analysis", type="primary", key=f"{key}_go"):
        st.session_state[key] = names
    if st.session_state.get(key) is not None:
        _ranking_body(key, title, st.session_state[key], chart_title or title)


# ====================================== NSE / BSE all-indices (exchange files)
EXCHANGE_TEXT = {
    "NSE": {"host": "nsearchives.nseindia.com", "prefix": r"^Nifty\s*", "empty": "Nifty",
            "live": "today's values come from NSE's live feed (Yahoo as a fallback)"},
    "BSE": {"host": "www.bseindia.com", "prefix": r"^(S&P\s+)?BSE\s*", "empty": "BSE",
            "live": "today's values come from Yahoo for the BSE indices it carries (Sensex, "
                    "Bankex, Auto, IT, FMCG, Healthcare, Metal, Power and others); the rest "
                    "update when BSE publishes the evening file"},
}


@st.cache_data(ttl=600, show_spinner=False)
def cached_exchange_stats(ex: str, start: str, end: str, version: int = core.CALC_VERSION):
    return core.nse_index_stats(start, end, ex=ex)


@st.cache_data(ttl=60, show_spinner=False)          # includes today: refresh each minute
def live_exchange_stats(ex: str, start: str, end: str, version: int = core.CALC_VERSION):
    return core.nse_index_stats(start, end, ex=ex)


@st.cache_data(ttl=60, show_spinner=False)          # includes today's live values
def cached_exchange_returns(ex: str, today: str, version: int = core.CALC_VERSION):
    return core.nse_index_returns(today, ex=ex)


def live_badge(live, ex="NSE"):
    """One line saying where today's numbers came from."""
    if not live:
        return
    total = live.get("total")
    if live.get("source") == "NSE live":
        st.success(f"🔴 Live: today's values from NSE's live feed as of {live['as_of']} "
                   f"({live['count']} indices). Final closes replace these once NSE publishes "
                   "the evening file.", icon="📡")
    elif live.get("source") == "Yahoo" and ex == "BSE":
        st.info(f"🟡 Live: {live['count']} of {total} BSE indices have today's value "
                f"(Yahoo, {live['as_of']}): {', '.join(live.get('names', []))}. BSE's own live "
                "feed blocks automated requests, so the rest update when BSE publishes the "
                "evening file.", icon="📡")
    elif live.get("source") == "Yahoo":
        st.warning(f"🟡 NSE's live feed is unavailable from this server, so today's values "
                   f"come from Yahoo ({live['as_of']}) for {live['count']} of {total} indices. "
                   "The rest show the previous close; see the Last Date column.", icon="📡")
    else:
        st.caption(f"⚠️ Today's live values could not be loaded: {live.get('error', '')}. "
                   "Showing the latest published closes.")


def _short_namer(ex):
    """'Nifty Financial Services 25/50' -> 'Financial Services 25/50',
    'BSE Capital Goods' -> 'Capital Goods' (for charts and metric cards)."""
    t = EXCHANGE_TEXT[ex]

    def short(df):
        d = df.copy()
        d["Name"] = (d["Name"].str.replace(t["prefix"], "", regex=True, case=False)
                     .str.strip().replace("", t["empty"]))
        return d
    return short


_short_names = _short_namer("NSE")


def category_summary(shown, cats):
    """Median / best / worst gain per category, when more than one is shown."""
    if len(cats) != 1 and not shown.dropna(subset=["Gain (%)"]).empty:
        by = (shown.dropna(subset=["Gain (%)"]).groupby("Category")["Gain (%)"]
                   .agg(["count", "median", "max", "min"]).round(2)
                   .rename(columns={"count": "Indices", "median": "Median gain (%)",
                                    "max": "Best (%)", "min": "Worst (%)"})
                   .sort_values("Median gain (%)", ascending=False))
        with st.expander("By category", expanded=True):
            st.dataframe(by, width="stretch")


def exchange_range_page(ex):
    key, title = f"{ex.lower()}all", f"{ex} Indices (All, Date Range)"
    t = EXCHANGE_TEXT[ex]
    st.header(title)
    st.caption(f"Every {ex} index: sectoral, thematic, strategy and broad market, from "
               f"{ex}'s own end-of-day file ({t['host']}), not Yahoo. When the end date is "
               f"today, {t['live']}. Click Run again to refresh (every minute)."
               + (" BSE keeps about the last 18 months of index files." if ex == "BSE" else ""))
    cats_all = core.INDEX_SOURCES[ex]["categories"]
    c1, c2, c3 = st.columns([1, 1, 2])
    start = c1.date_input("Start", today_ist(), key=f"{key}_start")
    end = c2.date_input("End", today_ist(), key=f"{key}_end")
    cats = c3.multiselect("Categories", cats_all, ["Sectoral"], key=f"{key}_cats",
                          help="Leave empty to show every index")
    if st.button(f"Run {ex} indices scan", type="primary", key=f"{key}_go") and valid_range(start, end):
        st.session_state[key] = {"start": str(start), "end": str(end), "live": False}
    p = st.session_state.get(key)
    if not p:
        return
    with st.spinner(f"Downloading {ex} index files..."):
        try:
            fetch = (live_exchange_stats if pd.Timestamp(p["end"]).date() >= today_ist()
                     else cached_exchange_stats)
            df, info = fetch(ex, p["start"], p["end"], version=core.CALC_VERSION)
        except core.DataUnavailable as e:          # not cached: next click retries
            st.error(str(e))
            return
    if info.get("note"):
        st.warning(info["note"])
    if info["quick"]:
        st.info(f"Long range (over {core.NSE_MAX_FULL_DAYS} trading days): gains use the "
                "base and end closes only, so range high/low, drawdown and volatility are "
                "left blank. Use a shorter range for those.", icon="ℹ️")
    live_badge(info.get("live"), ex)
    shown = df[df["Category"].isin(cats)] if cats else df
    shown = shown.reset_index(drop=True)
    today_rows = df[df["Last Date"].astype(str) == str(today_ist())]
    if (not today_rows.empty and pd.Timestamp(p["end"]).date() >= today_ist()
            and shown[shown["Last Date"].astype(str) == str(today_ist())].empty):
        hidden = ", ".join(f"{n} ({c})" for n, c in zip(today_rows["Name"], today_rows["Category"]))
        st.warning(f"Today's live values exist only for {hidden}, which "
                   f"{'is' if len(today_rows) == 1 else 'are'} not in the selected categories. "
                   "Add that category, or pick an earlier end date.")

    category_summary(shown, cats)

    short = _short_namer(ex)
    group = "Category" if len(cats) != 1 else None
    views = {"Market map": lambda d, t: charts.market_map(short(d), t, group_col=group),
             "Ranked bars": lambda d, t: charts.ranked_bars(short(d), t)}
    show_range_results(shown, key, f"{ex} {', '.join(cats) or 'all'} indices", p, views,
                       source=ex, name_fmt=short, live=info.get("live"))


def exchange_ranking_page(ex):
    key = ex.lower()
    st.header(f"{ex} Sector Indices")
    st.caption(f"Every {ex} sectoral index (and, if you choose, thematic, strategy and "
               "broad-market indices) ranked on 30/60/90-day returns, from "
               f"{ex}'s own end-of-day file. When today is included, {EXCHANGE_TEXT[ex]['live']}. "
               "Click Run again to refresh (every minute).")
    cats_all = core.INDEX_SOURCES[ex]["categories"]
    c1, c2 = st.columns([3, 1])
    cats = c1.multiselect("Categories", cats_all, ["Sectoral"], key=f"{key}_cats",
                          help="Ranks are worked out within the categories you pick. "
                               "Leave empty for every index.")
    c2.write("")
    if c2.button("Run analysis", type="primary", key=f"{key}_go", width="stretch"):
        st.session_state[key] = True
    if not st.session_state.get(key):
        return
    with st.spinner(f"Downloading 90 days of {ex} index files (first run takes a few seconds)..."):
        try:
            raw, info = cached_exchange_returns(ex, str(today_ist()), version=core.CALC_VERSION)
            last_day = info["last_day"]
        except core.DataUnavailable as e:          # not cached: next click retries
            st.error(str(e))
            return
    shown = raw[raw["Category"].isin(cats)] if cats else raw
    if shown.empty:
        st.warning("No indices in the selected categories.")
        return
    df = core.rank_returns(shown)
    live = info.get("live") or {}
    upto = ("today's live values" if live.get("source") == "NSE live"
            else f"the close of {pd.Timestamp(last_day):%a %d-%b-%Y}")
    st.markdown(f"**Returns up to {upto}** · {len(df)} indices · "
                f"{', '.join(cats) or 'all categories'}")
    live_badge(live, ex)
    if last_day < today_ist() and today_ist().weekday() < 5 and live.get("source") != "NSE live":
        st.caption(f"⚠️ {ex} has not published {today_ist():%a %d-%b} yet "
                   "(holiday, or before the evening update).")
    show_ranking_results(df.reset_index(drop=True), key, f"{ex} " + (", ".join(cats) or "all"),
                         name_fmt=_short_namer(ex), index=False)


def page_nse_all():
    exchange_range_page("NSE")


def page_bse_all():
    exchange_range_page("BSE")


def page_nse():
    exchange_ranking_page("NSE")


def page_bse():
    exchange_ranking_page("BSE")


# ===================================================================== pages
def page_home():
    st.title("Analysis Dashboard")
    st.caption("Pick a tool from the Tool menu above.")
    st.dataframe(pd.DataFrame([
        ("🇮🇳 Nifty 50 Stock Performance", "All 50 stocks over any date range — heatmap or ranked bars, with drawdown and volatility"),
        ("🇮🇳 NSE Indices (All, Date Range)", "Every NSE sectoral, thematic, strategy and broad-market index over any date range, from NSE's own data"),
        ("🇮🇳 NSE Sector Indices", "Every NSE sectoral index ranked on 30/60/90-day returns, from NSE's own data (thematic/strategy/broad optional)"),
        ("🇮🇳 BSE Indices (All, Date Range)", "Every BSE index (Sensex, BSE 100/500, sectoral, thematic, strategy) over any date range in the last ~18 months, from BSE's own data"),
        ("🇮🇳 BSE Sector Indices", "Every BSE sectoral index ranked on 30/60/90-day returns, from BSE's own data"),
        ("🇮🇳 Stock List Ranking", "Upload any CSV of symbols (Nifty Infra, Media, your watchlist…) and rank them on 30/60/90-day returns"),
        ("🌍 World Indices", "20 global indices ranked on 30/60/90-day returns"),
        ("🌍 Global Indices (Date Range)", "20 global indices over a date range you choose"),
        ("🇺🇸 USA Sectors & Themes (Date Range)", "S&P 500 sectors and US thematic indices (semiconductors, biotech, banks, AI, cybersecurity, clean energy…) over any date range"),
        ("🇺🇸 USA Sector & Theme Rankings", "The same US sectors and themes ranked on 30/60/90-day returns"),
        ("🇺🇸 Nasdaq-100 Stock Performance", "All Nasdaq-100 stocks over any date range: market map by industry, ranked bars, drawdown and volatility"),
        ("🇺🇸 Dow Jones 30 Stock Performance", "All 30 Dow Jones stocks over any date range: market map by sector, ranked bars, drawdown and volatility"),
        ("🌍 Country ETFs (USA)", "44 US-listed single-country ETFs ranked on 30/60/90-day returns"),
        ("🛢️ Commodities", "Gold, silver, oil, gas, base metals over a date range, with optional live refresh"),
        ("💱 Currencies vs USD", "16 currencies' moves against the US dollar over a date range"),
        ("📅 Seasonality", "Month-by-month return heatmap and win rates for any ticker"),
        ("🕯️ Candlestick Chart", "OHLC chart with volume for any Yahoo ticker"),
    ], columns=["Tool", "What it shows"]), hide_index=True, width="stretch")


@st.cache_data(ttl=24 * 3600, show_spinner=False)     # members change rarely: daily refresh
def cached_constituents(list_key: str, version: int = core.CALC_VERSION):
    return core.load_constituents(list_key)


def stock_list_page(list_key, title, button, unit_note=None):
    """Performance of every stock in an index over a date range: market map
    grouped by industry/sector, ranked bars, table (Nifty 50, Nasdaq-100, Dow 30)."""
    cons, src = cached_constituents(list_key, version=core.CALC_VERSION)
    names = dict(zip(cons["Yahoo"], cons["Symbol"]))
    industry = dict(zip(cons["Symbol"], cons["Industry"]))
    views = {"Market map": lambda d, t: charts.market_map(d.assign(Industry=d["Name"].map(industry)),
                                                          t, group_col="Industry"),
             "Ranked bars": charts.ranked_bars}
    range_tool(list_key, title, names, views, button, unit_note=unit_note,
               extra=f"{len(names)} stocks · members: {src}.")


def page_nifty50():
    stock_list_page("nifty50", "Nifty 50 Stock Performance", "Run Nifty 50 scan")


def page_nasdaq100():
    stock_list_page("nasdaq100", "Nasdaq-100 Stock Performance", "Run Nasdaq-100 scan",
                    unit_note="Prices in USD from Yahoo Finance (about 15 minutes delayed "
                              "during the US session).")


def page_dow30():
    stock_list_page("dow30", "Dow Jones 30 Stock Performance", "Run Dow 30 scan",
                    unit_note="Prices in USD from Yahoo Finance (about 15 minutes delayed "
                              "during the US session).")


def page_world():
    ranking_tool("world", "World Indices", core.WORLD_INDICES, "World Indices")


def page_custom():
    range_tool("custom", "Global Indices (Date Range)", core.WORLD_INDICES,
               {"Bars": charts.ranked_bars},
               "Compare indices",
               unit_note="Returns are in each index's local currency.")


# ================================================ USA sectoral & thematic
US_NAMES = {sym: name for sym, (name, _) in core.US_INDICES.items()}
US_CAT = {sym: cat for sym, (_, cat) in core.US_INDICES.items()}
US_NOTE = ("S&P 500 sector indices and US thematic indices from Yahoo Finance, in USD. "
           "Themes with no index on Yahoo use the leading thematic ETF, marked (ETF). "
           "Values include today's US session (about 15 minutes delayed).")


def page_us_range():
    key, title = "usrange", "USA Sectors & Themes (Date Range)"
    st.header(title)
    st.caption(US_NOTE)
    c1, c2, c3 = st.columns([1, 1, 2])
    start = c1.date_input("Start", today_ist(), key=f"{key}_start")
    end = c2.date_input("End", today_ist(), key=f"{key}_end")
    cats = c3.multiselect("Categories", core.US_CATEGORIES, ["Sectoral", "Thematic"],
                          key=f"{key}_cats", help="Leave empty to show everything")
    if st.button("Run USA scan", type="primary", key=f"{key}_go") and valid_range(start, end):
        st.session_state[key] = {"start": str(start), "end": str(end), "live": False}
    p = st.session_state.get(key)
    if not p:
        return
    with st.spinner(f"Fetching {len(US_NAMES)} US indices..."):
        try:
            df = cached_range_stats(US_NAMES, p["start"], p["end"], version=core.CALC_VERSION)
        except core.DataUnavailable as e:          # not cached: next click retries
            st.error(str(e))
            return
    df = df.copy()
    df.insert(1, "Category", df["Symbol"].map(US_CAT))
    shown = (df[df["Category"].isin(cats)] if cats else df).reset_index(drop=True)
    category_summary(shown, cats)
    group = "Category" if len(cats) != 1 else None
    views = {"Market map": lambda d, t: charts.market_map(d, t, group_col=group),
             "Ranked bars": charts.ranked_bars}
    show_range_results(shown, key, f"USA {', '.join(cats) or 'all'}", p, views,
                       source="Yahoo Finance")


def page_us_rank():
    key = "usrank"
    st.header("USA Sector & Theme Rankings")
    st.caption(US_NOTE + " Ranks are worked out within the categories you pick.")
    c1, c2 = st.columns([3, 1])
    cats = c1.multiselect("Categories", core.US_CATEGORIES, ["Sectoral", "Thematic"],
                          key=f"{key}_cats", help="Leave empty to rank everything")
    c2.write("")
    if c2.button("Run analysis", type="primary", key=f"{key}_go", width="stretch"):
        st.session_state[key] = True
    if not st.session_state.get(key):
        return
    with st.spinner(f"Pulling 30/60/90-day returns for {len(US_NAMES)} US indices..."):
        try:
            raw = cached_index_returns(US_NAMES, str(today_ist()), version=core.CALC_VERSION)
        except Exception as e:
            st.error(f"Error: {e}")
            return
    raw = raw.copy()
    raw.insert(1, "Category", raw.index.map(US_CAT))
    shown = raw[raw["Category"].isin(cats)] if cats else raw
    if shown.empty:
        st.warning("No indices in the selected categories.")
        return
    df = core.rank_returns(shown)
    st.markdown(f"**{len(df)} US indices** · {', '.join(cats) or 'all categories'}")
    show_ranking_results(df, key, "USA " + (", ".join(cats) or "all"))


def page_etfs():
    ranking_tool("etfs", "Country ETFs (USA)", core.COUNTRY_ETFS, "Country ETFs")
    st.caption("US-listed ETFs priced in USD, so returns include the currency move "
               "against the dollar.")


def page_commodities():
    range_tool("commod", "Commodities", core.COMMODITIES,
               {"Bars": charts.ranked_bars},
               "Compare commodities",
               extra="Front-month futures on US/LME-linked exchanges, priced in USD.",
               unit_note="Futures roll each month, so a long range can include "
                         "small jumps at contract roll dates.")


def page_currencies():
    range_tool("fx", "Currencies vs USD", core.CURRENCIES,
               {"Bars": charts.ranked_bars},
               "Compare currencies", price_fmt="%.6f",
               unit_note="Positive = the currency strengthened against the US dollar; "
                         "negative = it weakened. Price column = USD per 1 unit.")


def page_stock_list():
    st.header("Stock List Ranking")
    st.caption("Upload an NSE index constituent CSV (from niftyindices.com) or any CSV "
               "with a 'Symbol' column. Without an upload, the Nifty 50 list is used.")
    c1, c2 = st.columns([3, 1])
    up = c1.file_uploader("Symbols CSV", type="csv", key="list_file")
    suffix = c2.selectbox("Exchange", [".NS (NSE)", ".BO (BSE)", "None (US / other)"],
                          key="list_suffix")
    suffix = {".NS (NSE)": ".NS", ".BO (BSE)": ".BO"}.get(suffix, "")
    label = c2.text_input("Chart title", "Stocks", key="list_title")

    if up is not None:
        try:
            names = core.symbols_from_csv(pd.read_csv(up), suffix)
        except Exception as e:
            st.error(f"Could not read the CSV: {e}")
            return
        if not names:
            st.error("No symbols found in that file.")
            return
        st.success(f"{len(names)} symbols loaded from {up.name}"
                   + (" (capped at 500)" if len(names) == 500 else ""))
    else:
        names = {s: s[:-3] for s in core.nifty50_symbols()}
    with st.expander(f"Symbols ({len(names)})"):
        st.write(", ".join(names))

    # Re-run automatically if a different list is loaded
    if st.session_state.get("list") is not None and st.session_state["list"] != names:
        st.session_state["list"] = None
    ranking_tool("list", "Stock List Ranking", names, label, show_header=False)


def page_seasonality():
    st.header("Monthly Seasonality Heatmap")
    c1, c2, c3 = st.columns([2, 1, 1])
    ticker = c1.text_input("Ticker", "RELIANCE.NS").strip().upper()
    years = int(c2.number_input("Lookback (years)", 1, 50, 10))
    c3.write("")
    partial = c3.checkbox("Include current month", False,
                          help="The current month is incomplete, so it is left out by default")
    if st.button("Run seasonality", type="primary") and ticker:
        with st.spinner("Downloading monthly history..."):
            try:
                heat, summary, n_years = cached_seasonality(ticker, years, partial)
            except Exception as e:
                st.error(str(e))
                return
        show_chart(charts.seasonality_heatmap(heat, ticker, n_years))
        ratio = st.column_config.NumberColumn(format="percent")
        st.dataframe(summary, width="stretch", hide_index=True,
                     column_config={c: ratio for c in summary.columns
                                    if c not in ("Month", "Positive", "Negative")})


def page_candle():
    st.header("Candlestick Chart")
    c1, c2, c3 = st.columns([2, 1, 1])
    ticker = c1.text_input("Ticker", "TCS.NS", help="Yahoo symbol, e.g. RELIANCE.NS").strip().upper()
    start = c2.date_input("Start", today_ist(), key="candle_start")
    end = c3.date_input("End", today_ist(), key="candle_end")
    if st.button("Generate chart", type="primary") and ticker and valid_range(start, end):
        with st.spinner("Fetching data..."):
            data = cached_ohlc(ticker, str(start), str(end))
        if data.empty:
            st.error(f"No data found for {ticker}")
            return
        show_chart(charts.candles(ticker, data))



PAGES = {
    "Home": page_home,
    "🇮🇳 Nifty 50 Stock Performance": page_nifty50,
    "🇮🇳 NSE Indices (All, Date Range)": page_nse_all,
    "🇮🇳 NSE Sector Indices": page_nse,
    "🇮🇳 BSE Indices (All, Date Range)": page_bse_all,
    "🇮🇳 BSE Sector Indices": page_bse,
    "🇮🇳 Stock List Ranking": page_stock_list,
    "🌍 World Indices": page_world,
    "🌍 Global Indices (Date Range)": page_custom,
    "🌍 Country ETFs (USA)": page_etfs,
    "🇺🇸 USA Sectors & Themes (Date Range)": page_us_range,
    "🇺🇸 USA Sector & Theme Rankings": page_us_rank,
    "🇺🇸 Nasdaq-100 Stock Performance": page_nasdaq100,
    "🇺🇸 Dow Jones 30 Stock Performance": page_dow30,
    "🛢️ Commodities": page_commodities,
    "💱 Currencies vs USD": page_currencies,
    "📅 Seasonality": page_seasonality,
    "🕯️ Candlestick Chart": page_candle,
}

def _slug(name):
    """'🇮🇳 NSE Sector Indices' -> 'nse-sector-indices' (for ?tool= links)."""
    return re.sub(r"[^a-z0-9]+", "-", name.encode("ascii", "ignore").decode().lower()).strip("-")


# No sidebar: tools are picked from a dropdown at the top of the page. The
# choice is kept in the address (?tool=...), so a link or an embedded page can
# open one tool directly.
_by_slug = {_slug(n): n for n in PAGES}
_by_slug["nifty-50-performance"] = "🇮🇳 Nifty 50 Stock Performance"   # old link keeps working
_names = list(PAGES)
_wanted = _by_slug.get(str(st.query_params.get("tool", "")).lower(), _names[0])

c1, c2 = st.columns([2, 3], vertical_alignment="bottom")
choice = c1.selectbox("Tool", _names, index=_names.index(_wanted), key="tool")
c2.caption(DATA_SOURCE)
if _slug(choice) != st.query_params.get("tool"):
    st.query_params["tool"] = _slug(choice)
st.divider()

PAGES[choice]()
