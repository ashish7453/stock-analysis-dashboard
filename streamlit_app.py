"""
Streamlit UI for the Analysis Dashboard.

All calculations live in `stock-chart-app-main/app.py` (shared with the Flask UI);
this file only handles inputs, caching and rendering.

Run locally:   streamlit run streamlit_app.py
"""
import io
import os
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
import matplotlib.pyplot as plt  # noqa: E402

st.set_page_config(page_title="Analysis Dashboard", page_icon="📈", layout="wide")

DATA_SOURCE = ("Data: Yahoo Finance (delayed) and NSE end-of-day files. "
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
def show_fig(fig):
    st.pyplot(fig, clear_figure=True)
    plt.close(fig)


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
        show_fig(fig)

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
    fig = core.plot_index_returns(name_fmt(df) if name_fmt else df, which.lower(), n=n,
                                  title_prefix=f"{chart_title}: ")
    if fig is None:
        st.warning("No symbol returned complete data.")
    else:
        show_fig(fig)
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


# ============================================== NSE all-indices (NSE EOD file)
@st.cache_data(ttl=600, show_spinner=False)
def cached_nse_stats(start: str, end: str, version: int = core.CALC_VERSION):
    return core.nse_index_stats(start, end)


@st.cache_data(ttl=60, show_spinner=False)          # includes today: refresh each minute
def live_nse_stats(start: str, end: str, version: int = core.CALC_VERSION):
    return core.nse_index_stats(start, end)


def live_badge(live):
    """One line saying where today's numbers came from."""
    if not live:
        return
    total = live.get("total")
    if live.get("source") == "NSE live":
        st.success(f"🔴 Live: today's values from NSE's live feed as of {live['as_of']} "
                   f"({live['count']} indices). Final closes replace these once NSE publishes "
                   "the evening file.", icon="📡")
    elif live.get("source") == "Yahoo":
        st.warning(f"🟡 NSE's live feed is unavailable from this server, so today's values "
                   f"come from Yahoo ({live['as_of']}) for {live['count']} of {total} indices. "
                   "The rest show the previous close; see the Last Date column.", icon="📡")
    else:
        st.caption(f"⚠️ Today's live values could not be loaded: {live.get('error', '')}. "
                   "Showing the latest published closes.")


def _short_names(df):
    """'Nifty Financial Services 25/50' -> 'Financial Services 25/50' for charts."""
    d = df.copy()
    d["Name"] = d["Name"].str.replace(r"^Nifty\s*", "", regex=True).str.strip().replace("", "Nifty")
    return d


def page_nse_all():
    key, title = "nseall", "NSE Indices (All, Date Range)"
    st.header(title)
    st.caption("Every NSE index: sectoral, thematic, strategy and broad market, from "
               "NSE's own end-of-day file (nsearchives.nseindia.com), not Yahoo. When the "
               "end date is today, today's values come from NSE's live feed (Yahoo as a "
               "fallback) until NSE publishes the evening file. Live values refresh every "
               "minute: click Run again.")
    c1, c2, c3 = st.columns([1, 1, 2])
    start = c1.date_input("Start", today_ist(), key=f"{key}_start")
    end = c2.date_input("End", today_ist(), key=f"{key}_end")
    cats = c3.multiselect("Categories", core.NSE_CATEGORIES, ["Sectoral"], key=f"{key}_cats",
                          help="Leave empty to show every index")
    if st.button("Run NSE indices scan", type="primary", key=f"{key}_go") and valid_range(start, end):
        st.session_state[key] = {"start": str(start), "end": str(end), "live": False}
    p = st.session_state.get(key)
    if not p:
        return
    with st.spinner("Downloading NSE index files..."):
        try:
            fetch = live_nse_stats if pd.Timestamp(p["end"]).date() >= today_ist() else cached_nse_stats
            df, info = fetch(p["start"], p["end"], version=core.CALC_VERSION)
            quick = info["quick"]
        except core.DataUnavailable as e:          # not cached: next click retries
            st.error(str(e))
            return
    if quick:
        st.info(f"Long range (over {core.NSE_MAX_FULL_DAYS} trading days): gains use the "
                "base and end closes only, so range high/low, drawdown and volatility are "
                "left blank. Use a shorter range for those.", icon="ℹ️")
    live_badge(info.get("live"))
    shown = df[df["Category"].isin(cats)] if cats else df
    shown = shown.reset_index(drop=True)

    if len(cats) != 1 and not shown.dropna(subset=["Gain (%)"]).empty:
        by = (shown.dropna(subset=["Gain (%)"]).groupby("Category")["Gain (%)"]
                   .agg(["count", "median", "max", "min"]).round(2)
                   .rename(columns={"count": "Indices", "median": "Median gain (%)",
                                    "max": "Best (%)", "min": "Worst (%)"})
                   .sort_values("Median gain (%)", ascending=False))
        with st.expander("By category", expanded=True):
            st.dataframe(by, width="stretch")

    views = {"Heatmap": lambda d, t: core.plot_gain_grid(_short_names(d), t),
             "Ranked bars": lambda d, t: core.plot_gain_bars(_short_names(d), t)}
    show_range_results(shown, key, f"NSE {', '.join(cats) or 'all'} indices", p, views,
                       source="NSE", name_fmt=_short_names, live=info.get("live"))


# ===================================================================== pages
def page_home():
    st.title("Analysis Dashboard")
    st.caption("Pick a tool from the sidebar.")
    st.dataframe(pd.DataFrame([
        ("🇮🇳 Nifty 50 Performance", "All 50 stocks over any date range — heatmap or ranked bars, with drawdown and volatility"),
        ("🇮🇳 NSE Indices (All, Date Range)", "Every NSE sectoral, thematic, strategy and broad-market index over any date range, from NSE's own data"),
        ("🇮🇳 NSE Sector Indices", "Every NSE sectoral index ranked on 30/60/90-day returns, from NSE's own data (thematic/strategy/broad optional)"),
        ("🇮🇳 Stock List Ranking", "Upload any CSV of symbols (Nifty Infra, Media, your watchlist…) and rank them on 30/60/90-day returns"),
        ("🌍 World Indices", "20 global indices ranked on 30/60/90-day returns"),
        ("🌍 Global Indices (Date Range)", "20 global indices over a date range you choose"),
        ("🌍 Country ETFs (USA)", "44 US-listed single-country ETFs ranked on 30/60/90-day returns"),
        ("🛢️ Commodities", "Gold, silver, oil, gas, base metals over a date range, with optional live refresh"),
        ("💱 Currencies vs USD", "16 currencies' moves against the US dollar over a date range"),
        ("📅 Seasonality", "Month-by-month return heatmap and win rates for any ticker"),
        ("🕯️ Candlestick Chart", "OHLC chart with volume for any Yahoo ticker"),
    ], columns=["Tool", "What it shows"]), hide_index=True, width="stretch")


def page_nifty50():
    names = {s: s[:-3] for s in core.nifty50_symbols()}
    range_tool("nifty50", "Nifty 50 Performance", names,
               {"Heatmap": core.plot_gain_grid, "Ranked bars": core.plot_gain_bars},
               "Run Nifty 50 scan")


@st.cache_data(ttl=60, show_spinner=False)           # includes today's live values
def cached_nse_returns(today: str, version: int = core.CALC_VERSION):
    return core.nse_index_returns(today)


def page_nse():
    key = "nse"
    st.header("NSE Sector Indices")
    st.caption("Every NSE sectoral index (and, if you choose, thematic, strategy and "
               "broad-market indices) ranked on 30/60/90-day returns, from NSE's own "
               "end-of-day file, plus today's live values from NSE's live feed until the "
               "evening file is out. Click Run again to refresh (every minute).")
    c1, c2 = st.columns([3, 1])
    cats = c1.multiselect("Categories", core.NSE_CATEGORIES, ["Sectoral"], key=f"{key}_cats",
                          help="Ranks are worked out within the categories you pick. "
                               "Leave empty for every index.")
    c2.write("")
    if c2.button("Run analysis", type="primary", key=f"{key}_go", width="stretch"):
        st.session_state[key] = True
    if not st.session_state.get(key):
        return
    with st.spinner("Downloading 90 days of NSE index files (first run takes a few seconds)..."):
        try:
            raw, info = cached_nse_returns(str(today_ist()), version=core.CALC_VERSION)
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
    live_badge(live)
    if last_day < today_ist() and today_ist().weekday() < 5 and not live.get("source"):
        st.caption(f"⚠️ NSE has not published {today_ist():%a %d-%b} yet "
                   "(holiday, or before the evening update).")
    show_ranking_results(df.reset_index(drop=True), key, "NSE " + (", ".join(cats) or "all"),
                         name_fmt=_short_names, index=False)


def page_world():
    ranking_tool("world", "World Indices", core.WORLD_INDICES, "World Indices")


def page_custom():
    range_tool("custom", "Global Indices (Date Range)", core.WORLD_INDICES,
               {"Bars": core.plot_gain_bars},
               "Compare indices",
               unit_note="Returns are in each index's local currency.")


def page_etfs():
    ranking_tool("etfs", "Country ETFs (USA)", core.COUNTRY_ETFS, "Country ETFs")
    st.caption("US-listed ETFs priced in USD, so returns include the currency move "
               "against the dollar.")


def page_commodities():
    range_tool("commod", "Commodities", core.COMMODITIES,
               {"Bars": core.plot_gain_bars},
               "Compare commodities",
               extra="Front-month futures on US/LME-linked exchanges, priced in USD.",
               unit_note="Futures roll each month, so a long range can include "
                         "small jumps at contract roll dates.")


def page_currencies():
    range_tool("fx", "Currencies vs USD", core.CURRENCIES,
               {"Bars": core.plot_gain_bars},
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
        show_fig(core.plot_seasonality(heat, ticker, n_years))
        ratio = st.column_config.NumberColumn(format="percent")
        st.dataframe(summary, width="stretch", hide_index=True,
                     column_config={c: ratio for c in summary.columns
                                    if c not in ("Month", "Positive", "Negative")})


def page_candle():
    st.header("Candlestick Chart")
    c1, c2, c3 = st.columns([2, 1, 1])
    ticker = c1.text_input("Ticker", "TCS.NS", help="Yahoo symbol, e.g. RELIANCE.NS").strip().upper()
    start = c2.date_input("Start", today_ist())
    end = c3.date_input("End", today_ist())
    if st.button("Generate chart", type="primary") and ticker and valid_range(start, end):
        with st.spinner("Fetching data..."):
            data = cached_ohlc(ticker, str(start), str(end))
        if data.empty:
            st.error(f"No data found for {ticker}")
            return
        show_fig(core.plot_candles(ticker, data))



# ============================================================ Diwali theme
# Pure CSS (no scripts): a banner with string lights, fireworks, a rotating
# rangoli and flickering diyas. pointer-events:none on all decoration, and
# animations stop for users who ask their OS for reduced motion.
DIWALI = {   # Diwali (Lakshmi Puja) date -> market notes shown on the banner
    date(2026, 11, 8): ["🪔 Muhurat trading: Sun 08-Nov",
                        "🔒 Market holiday: Tue 10-Nov (Balipratipada)"],
    date(2027, 10, 29): [],
    date(2028, 10, 17): [],
}


def diwali_season(today=None):
    """(diwali_date, notes) if today is within 5 days before / 7 days after."""
    today = today or datetime.now(IST).date()
    for d, notes in DIWALI.items():
        if -5 <= (today - d).days <= 7:
            return d, notes
    return None, []


def _lights_html(n_scallops=10, per=4, sag=9):
    """Bulbs hanging on a draped wire (quadratic curves, same maths for both)."""
    colors = ["#ffd54a", "#ff5c8a", "#4fe3c1", "#ff9f1c", "#b388ff"]
    path, bulbs, k = "M0,3", [], 0
    for i in range(n_scallops):
        x0, x1 = i * 100 / n_scallops, (i + 1) * 100 / n_scallops
        path += f" Q{(x0 + x1) / 2 * 10:.1f},{3 + 2 * sag} {x1 * 10:.1f},3"
        for j in range(1, per + 1):
            t = j / (per + 1)
            x, y = x0 + t * (x1 - x0), 3 + 4 * sag * t * (1 - t)
            c = colors[k % len(colors)]
            bulbs.append(f'<i class="dw-bulb" style="left:{x:.2f}%;top:{y:.1f}px;'
                         f'--c:{c};animation-delay:{(k * 0.37) % 2.2:.2f}s"></i>')
            k += 1
    wire = (f'<svg class="dw-wire" viewBox="0 0 1000 30" preserveAspectRatio="none">'
            f'<path d="{path}" fill="none" stroke="#6b4a1f" stroke-width="1.6" '
            f'vector-effect="non-scaling-stroke"/></svg>')
    return f'<div class="dw-lights">{wire}{"".join(bulbs)}</div>'


def _firework_html(left, top, size, delay, palette):
    import math
    dots = []
    for ring, (count, r) in enumerate([(18, size), (12, size * 0.58)]):
        for i in range(count):
            a = 2 * math.pi * i / count + ring * 0.26
            dots.append(f"{r * math.cos(a):.0f}px {r * math.sin(a):.0f}px 0 "
                        f"{1.6 if ring else 1.2}px {palette[(i + ring) % len(palette)]}")
    return (f'<i class="dw-fw" style="left:{left}%;top:{top}%;'
            f'box-shadow:{",".join(dots)};animation-delay:{delay}s"></i>')


def _diya(scale=1.0, delay=0.0):
    return (f'<div class="dw-diya" style="transform:scale({scale});'
            f'--d:{delay}s"><i class="dw-glow"></i><i class="dw-flame"></i>'
            f'<i class="dw-bowl"></i></div>')


DIWALI_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Yatra+One&display=swap');
.dw-banner{position:relative;overflow:hidden;border-radius:16px;margin:0 0 1.2rem;
  min-height:150px;padding:38px 24px 18px;color:#ffe9b0;
  background:radial-gradient(120% 140% at 50% 0%,#3b1159 0%,#2a0b3c 45%,#14061f 100%);
  box-shadow:0 8px 28px rgba(60,10,80,.35), inset 0 0 0 1px rgba(255,200,90,.25);
  display:flex;align-items:center;gap:22px;flex-wrap:wrap}
.dw-banner *{pointer-events:none}
.dw-lights{position:absolute;left:0;right:0;top:0;height:34px}
.dw-wire{position:absolute;inset:0;width:100%;height:30px}
.dw-bulb{position:absolute;width:9px;height:12px;margin-left:-4.5px;
  border-radius:50% 50% 50% 50%/60% 60% 40% 40%;background:var(--c);
  box-shadow:0 0 6px 2px var(--c),0 0 14px 4px color-mix(in srgb,var(--c) 45%,transparent);
  animation:dw-twinkle 2.2s ease-in-out infinite}
.dw-bulb::before{content:"";position:absolute;left:2.5px;top:-3px;width:4px;height:4px;
  background:#5a4320;border-radius:1px}
@keyframes dw-twinkle{0%,100%{opacity:1;filter:brightness(1.15)}50%{opacity:.35;filter:brightness(.7)}}
.dw-fw{position:absolute;width:3px;height:3px;border-radius:50%;opacity:0;
  transform:scale(.08);animation:dw-burst 3.2s cubic-bezier(.15,.7,.3,1) infinite}
@keyframes dw-burst{0%{opacity:0;transform:scale(.08)}8%{opacity:1}
  65%{opacity:.85}100%{opacity:0;transform:scale(1) translateY(10px)}}
.dw-rangoli{flex:0 0 auto;width:92px;height:92px;border-radius:50%;position:relative;
  background:
   radial-gradient(circle,#fff3c4 0 9%,#ff9f1c 10% 17%,transparent 18%),
   repeating-conic-gradient(from 0deg,#ff2e63 0 15deg,#ffd54a 15deg 30deg,#08d9d6 30deg 45deg,#ff9f1c 45deg 60deg);
  -webkit-mask:radial-gradient(circle,#000 0 46%,transparent 47% 52%,#000 53% 70%,transparent 71%);
          mask:radial-gradient(circle,#000 0 46%,transparent 47% 52%,#000 53% 70%,transparent 71%);
  animation:dw-spin 40s linear infinite;filter:drop-shadow(0 0 8px rgba(255,190,80,.5))}
@keyframes dw-spin{to{transform:rotate(360deg)}}
.dw-text,.dw-chips,.dw-diyas,.dw-rangoli{position:relative;z-index:2}
.dw-fw{z-index:1}
.dw-text{flex:1 1 260px}
.dw-banner .dw-title{font-family:'Yatra One','Tiro Devanagari Hindi',serif;font-size:2.3rem;
  font-weight:400;line-height:1.15;margin:0;padding:0;
  background:linear-gradient(90deg,#ffd27a,#fff6d8,#ffb347,#ffd27a);background-size:200% 100%;
  -webkit-background-clip:text;background-clip:text;color:transparent;
  animation:dw-shine 5s linear infinite;text-shadow:0 0 22px rgba(255,190,90,.25)}
@keyframes dw-shine{to{background-position:200% 0}}
.dw-banner .dw-title2{margin:.1rem 0 0;font-size:.95rem;font-weight:600;letter-spacing:.32em;
  text-transform:uppercase;color:#ffcf73}
.dw-banner .dw-sub{margin:.3rem 0 0;padding:0;font-size:1rem;line-height:1.4;color:#f5dcae;
  text-shadow:0 1px 6px rgba(20,6,31,.9)}
.dw-chips{display:flex;flex-direction:column;gap:8px}
.dw-chip{background:#2c0f40;border:1px solid rgba(255,210,122,.5);
  color:#ffe2a6;border-radius:999px;padding:5px 12px;font-size:.88rem;white-space:nowrap}
.dw-diyas{display:flex;align-items:flex-end;gap:4px}
.dw-diya{position:relative;width:46px;height:52px;transform-origin:bottom center}
.dw-bowl{position:absolute;bottom:0;left:3px;width:40px;height:18px;
  border-radius:0 0 40px 40px/0 0 26px 26px;
  background:linear-gradient(180deg,#e0752d,#a33d12 70%,#6e2508);
  box-shadow:inset 0 3px 0 #f2a65a}
.dw-flame{position:absolute;bottom:15px;left:16px;width:14px;height:24px;
  border-radius:50% 50% 50% 50%/65% 65% 35% 35%;
  background:radial-gradient(circle at 50% 75%,#fffbe6 0 22%,#ffd54a 40%,#ff8c1a 70%,rgba(255,80,0,0) 72%);
  transform-origin:50% 90%;animation:dw-flicker 1.3s ease-in-out infinite alternate;
  animation-delay:var(--d)}
.dw-glow{position:absolute;bottom:6px;left:-12px;width:70px;height:56px;border-radius:50%;
  background:radial-gradient(circle,rgba(255,180,60,.45),rgba(255,140,30,0) 65%);
  animation:dw-pulse 2.6s ease-in-out infinite;animation-delay:var(--d)}
@keyframes dw-flicker{0%{transform:scale(1,1) rotate(-2deg)}35%{transform:scale(.92,1.08) rotate(2deg)}
  70%{transform:scale(1.05,.95) rotate(-1deg)}100%{transform:scale(.97,1.04) rotate(1.5deg)}}
@keyframes dw-pulse{0%,100%{opacity:.75}50%{opacity:1}}
.dw-side{display:flex;justify-content:center;gap:2px;margin:.2rem 0 .4rem}
.dw-side .dw-diya{width:40px;height:46px}
@media (max-width:640px){.dw-banner .dw-title{font-size:1.7rem}.dw-rangoli{width:64px;height:64px}
  .dw-chips{flex-direction:row;flex-wrap:wrap}}
@media (prefers-reduced-motion:reduce){.dw-banner *,.dw-side *{animation:none!important}
  .dw-fw{opacity:.7;transform:scale(1)}}
</style>
"""


def diwali_banner(notes):
    pal1 = ["#ffd54a", "#ff9f1c", "#fff3c4"]
    pal2 = ["#ff5c8a", "#ffd54a", "#b388ff"]
    pal3 = ["#4fe3c1", "#fff3c4", "#ff9f1c"]
    fireworks = "".join([
        _firework_html(24, 34, 30, 0.0, pal1), _firework_html(62, 30, 34, 1.1, pal2),
        _firework_html(98, 70, 26, 2.0, pal3), _firework_html(21, 84, 20, 2.6, pal3),
        _firework_html(64, 86, 22, 1.6, pal1), _firework_html(85, 22, 22, 0.6, pal2),
    ])
    chips = "".join(f'<span class="dw-chip">{n}</span>' for n in notes)
    st.markdown(
        DIWALI_CSS
        + '<div class="dw-banner">' + _lights_html() + fireworks
        + '<div class="dw-rangoli"></div>'
        + '<div class="dw-diyas">' + _diya(0.9, 0) + _diya(1.1, .4) + _diya(0.9, .8) + "</div>"
        + '<div class="dw-text"><div class="dw-title">शुभ दीपावली</div>'
          '<div class="dw-title2">Happy Diwali</div>'
          '<div class="dw-sub">May your year be as bright as the diyas, and your portfolio '
          'greener than the market. ✨</div></div>'
        + (f'<div class="dw-chips">{chips}</div>' if chips else "")
        + "</div>", unsafe_allow_html=True)


PAGES = {
    "Home": page_home,
    "🇮🇳 Nifty 50 Performance": page_nifty50,
    "🇮🇳 NSE Indices (All, Date Range)": page_nse_all,
    "🇮🇳 NSE Sector Indices": page_nse,
    "🇮🇳 Stock List Ranking": page_stock_list,
    "🌍 World Indices": page_world,
    "🌍 Global Indices (Date Range)": page_custom,
    "🌍 Country ETFs (USA)": page_etfs,
    "🛢️ Commodities": page_commodities,
    "💱 Currencies vs USD": page_currencies,
    "📅 Seasonality": page_seasonality,
    "🕯️ Candlestick Chart": page_candle,
}

_diwali_day, _diwali_notes = diwali_season()

with st.sidebar:
    st.title("📈 Analysis")
    choice = st.radio("Tool", list(PAGES), label_visibility="collapsed")
    st.divider()
    festive = st.toggle("🪔 Diwali lights", value=_diwali_day is not None,
                        help="Festive banner with lights, fireworks and diyas")
    if festive:
        st.markdown('<div class="dw-side">' + _diya(0.8, 0) + _diya(0.8, .5)
                    + _diya(0.8, 1) + "</div>", unsafe_allow_html=True)
    st.caption(DATA_SOURCE)

if festive:
    diwali_banner(_diwali_notes if _diwali_day is not None else [])
PAGES[choice]()
