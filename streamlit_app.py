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

import app as core               # noqa: E402  (needs the sys.path tweak above)
import matplotlib.pyplot as plt  # noqa: E402

st.set_page_config(page_title="Analysis Dashboard", page_icon="📈", layout="wide")

DATA_SOURCE = "Data: Yahoo Finance (delayed). Not investment advice."
CACHE_TTL = 15 * 60          # normal runs: reuse results for 15 minutes
LIVE_TTL = 55                # live mode: refetch roughly every minute
LIVE_EVERY = 60              # live mode refresh interval (seconds)
IST = ZoneInfo("Asia/Kolkata")
PCT = st.column_config.NumberColumn(format="%.2f%%")


# --------------------------------------------------------------- cached data
@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def cached_range_stats(names: dict, start: str, end: str):
    return core.range_stats(names, start, end)


@st.cache_data(ttl=LIVE_TTL, show_spinner=False)
def live_range_stats(names: dict, start: str, end: str):
    return core.range_stats(names, start, end)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def cached_index_returns(names: dict, today: str):
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
    if start >= end:
        st.error("Start date must be before the end date.")
        return False
    if end > date.today():
        st.warning("End date is in the future; data runs up to the latest close.")
    return True


def column_config(df, price_fmt="%.2f"):
    cfg = {}
    for c in df.columns:
        if c.endswith("(%)") or c.endswith("D %") or c.endswith("High %"):
            cfg[c] = PCT
        elif "Price" in c or c in ("Range High", "Range Low"):
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


def summary_metrics(df, col="Gain (%)"):
    """Breadth + best/worst row of st.metric cards."""
    v = df.dropna(subset=[col])
    if v.empty:
        return
    best, worst = v.iloc[0], v.iloc[-1]
    m = st.columns(5)
    m[0].metric("Advancing", int((v[col] > 0).sum()))
    m[1].metric("Declining", int((v[col] < 0).sum()))
    m[2].metric("Median", f"{v[col].median():.2f}%")
    m[3].metric("Best", best["Name"], f"{best[col]:.2f}%")
    m[4].metric("Worst", worst["Name"], f"{worst[col]:.2f}%")


def missing_note(df, col):
    missing = df[df[col].isna()]["Name"].tolist() if col in df else []
    if missing:
        st.caption("No data from Yahoo for: " + ", ".join(missing))


# ======================================================= date-range tool body
def _range_body(key, title, names, p, views, price_fmt, unit_note):
    fetch = live_range_stats if p["live"] else cached_range_stats
    with st.spinner(f"Fetching {len(names)} symbols..."):
        df = fetch(names, p["start"], p["end"])
    if p["live"]:
        st.caption(f"🔴 Live · refreshes every {LIVE_EVERY}s · last update "
                   f"{datetime.now(IST):%H:%M:%S} IST")
    if unit_note:
        st.info(unit_note, icon="ℹ️")
    summary_metrics(df)

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
    st.caption("Base price = last close before the start date. Volatility is "
               "annualised from daily returns. Max drawdown = worst fall from a "
               "peak inside the range.")
    download_buttons(df, f"{key}_{p['start']}_{p['end']}", key)
    missing_note(df, "Gain (%)")


_range_static = st.fragment(_range_body)
_range_live = st.fragment(run_every=LIVE_EVERY)(_range_body)


def range_tool(key, title, names, default_start, views, button,
               price_fmt="%.2f", unit_note=None, extra=None):
    """Generic 'performance between two dates' page."""
    st.header(title)
    if extra:
        st.caption(extra)
    c1, c2, c3 = st.columns([1, 1, 1])
    start = c1.date_input("Start", default_start, key=f"{key}_start")
    end = c2.date_input("End", date.today(), key=f"{key}_end")
    c3.write("")
    live = c3.toggle("Live auto-refresh", False, key=f"{key}_live",
                     help=f"Re-fetches every {LIVE_EVERY}s. Only used when the end date is today.")
    if st.button(button, type="primary", key=f"{key}_go") and valid_range(start, end):
        st.session_state[key] = {"start": str(start), "end": str(end),
                                 "live": bool(live and end >= date.today())}
    p = st.session_state.get(key)
    if p:
        (_range_live if p["live"] else _range_static)(
            key, title, names, p, views, price_fmt, unit_note)


# ================================================== 30/60/90-day ranking body
@st.fragment
def _ranking_body(key, title, names, chart_title):
    with st.spinner(f"Pulling 30/60/90-day returns for {len(names)} symbols..."):
        try:
            df = cached_index_returns(names, str(date.today()))
        except Exception as e:
            st.error(f"Error: {e}")
            return
    ok = df.dropna(subset=["Sum of Ranks"])
    if not ok.empty:
        m = st.columns(4)
        m[0].metric("Ranked", len(ok))
        m[1].metric("Strongest", ok.iloc[0]["Name"], f"{ok.iloc[0]['30D %']:.2f}% (30D)")
        m[2].metric("Weakest", ok.iloc[-1]["Name"], f"{ok.iloc[-1]['30D %']:.2f}% (30D)")
        m[3].metric("Positive over 90D", f"{int((ok['90D %'] > 0).sum())} / {len(ok)}")

    c1, c2 = st.columns([2, 1])
    which = c1.radio("Chart", ["Strongest", "Weakest"], horizontal=True, key=f"{key}_which",
                     help="Ranked by the sum of 30/60/90-day return ranks (lower = stronger)")
    n = c2.slider("How many", 3, 10, 3, key=f"{key}_n")
    fig = core.plot_index_returns(df, which.lower(), n=n, title_prefix=f"{chart_title}: ")
    if fig is None:
        st.warning("No symbol returned complete data.")
    else:
        show_fig(fig)
    st.dataframe(df, width="stretch", column_config=column_config(df))
    st.caption("Rank 1 = best return in that window. 'Off 90D High' = how far the "
               "last close is below the highest close of the last 90 days.")
    download_buttons(df, f"{key}_{date.today()}", key, index=True)
    missing_note(df, "Sum of Ranks")


def ranking_tool(key, title, names, chart_title=None, show_header=True):
    if show_header:
        st.header(title)
    if st.button("Run analysis", type="primary", key=f"{key}_go"):
        st.session_state[key] = names
    if st.session_state.get(key) is not None:
        _ranking_body(key, title, st.session_state[key], chart_title or title)


# ===================================================================== pages
def page_home():
    st.title("Analysis Dashboard")
    st.caption("Pick a tool from the sidebar.")
    st.dataframe(pd.DataFrame([
        ("🇮🇳 Nifty 50 Performance", "All 50 stocks over any date range — heatmap or ranked bars, with drawdown and volatility"),
        ("🇮🇳 NSE Sector Indices", "22 NSE indices ranked on 30/60/90-day returns"),
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
               date.today() - timedelta(days=30),
               {"Heatmap": core.plot_gain_grid, "Ranked bars": core.plot_gain_bars},
               "Run Nifty 50 scan")


def page_nse():
    ranking_tool("nse", "NSE Sector Indices", core.NSE_INDICES, "NSE Indices")


def page_world():
    ranking_tool("world", "World Indices", core.WORLD_INDICES, "World Indices")


def page_custom():
    range_tool("custom", "Global Indices (Date Range)", core.WORLD_INDICES,
               date(date.today().year, 1, 1), {"Bars": core.plot_gain_bars},
               "Compare indices",
               unit_note="Returns are in each index's local currency.")


def page_etfs():
    ranking_tool("etfs", "Country ETFs (USA)", core.COUNTRY_ETFS, "Country ETFs")
    st.caption("US-listed ETFs priced in USD, so returns include the currency move "
               "against the dollar.")


def page_commodities():
    range_tool("commod", "Commodities", core.COMMODITIES,
               date.today() - timedelta(days=30), {"Bars": core.plot_gain_bars},
               "Compare commodities",
               extra="Front-month futures on US/LME-linked exchanges, priced in USD.",
               unit_note="Futures roll each month, so a long range can include "
                         "small jumps at contract roll dates.")


def page_currencies():
    range_tool("fx", "Currencies vs USD", core.CURRENCIES,
               date.today() - timedelta(days=30), {"Bars": core.plot_gain_bars},
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
    start = c2.date_input("Start", date.today() - timedelta(days=180))
    end = c3.date_input("End", date.today())
    if st.button("Generate chart", type="primary") and ticker and valid_range(start, end):
        with st.spinner("Fetching data..."):
            data = cached_ohlc(ticker, str(start), str(end))
        if data.empty:
            st.error(f"No data found for {ticker}")
            return
        show_fig(core.plot_candles(ticker, data))


PAGES = {
    "Home": page_home,
    "🇮🇳 Nifty 50 Performance": page_nifty50,
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

with st.sidebar:
    st.title("📈 Analysis")
    choice = st.radio("Tool", list(PAGES), label_visibility="collapsed")
    st.divider()
    st.caption(DATA_SOURCE)

PAGES[choice]()
