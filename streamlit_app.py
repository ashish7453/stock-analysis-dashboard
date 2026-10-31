"""
Streamlit UI for the Analysis Dashboard.

All calculations live in `stock-chart-app-main/app.py` (shared with the Flask UI);
this file only handles inputs, caching and rendering.

Run locally:   streamlit run streamlit_app.py
"""
import os
import sys
from datetime import date, timedelta

import streamlit as st

HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(HERE, "stock-chart-app-main")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
# (No os.chdir any more: app.py resolves its CSV path from its own location.)

import app as core            # noqa: E402  (needs the sys.path tweak above)
import matplotlib.pyplot as plt  # noqa: E402

st.set_page_config(page_title="Analysis Dashboard", page_icon="📈", layout="wide")

DATA_SOURCE = "Data: Yahoo Finance (delayed). Not investment advice."
CACHE_TTL = 15 * 60           # seconds; repeat runs within 15 min are instant
PCT = st.column_config.NumberColumn(format="%.2f%%")


# --------------------------------------------------------------- cached data
@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def cached_range_gains(names: dict, start: str, end: str):
    return core.range_gains(names, start, end)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def cached_index_returns(names: dict, today: str):
    return core.compute_index_returns(names, reference_date=today)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def cached_seasonality(ticker: str, years: int, include_partial: bool):
    return core.seasonality_tables(ticker, years, include_partial)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def cached_ohlc(ticker: str, start: str, end: str):
    return core.download_ohlc(ticker, start, end)


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


# --------------------------------------------------------------------- pages
def page_home():
    st.title("Analysis Dashboard")
    st.caption("Pick a tool from the sidebar.")


def page_candle():
    st.header("Candlestick Chart Generator")
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


def _indices_page(names, title):
    st.header(title)
    which = st.radio("Chart", ["Strongest", "Weakest"], horizontal=True,
                     help="Ranked by the sum of 30/60/90-day return ranks")
    if st.button("Run analysis", type="primary"):
        with st.spinner("Pulling 30/60/90-day returns..."):
            try:
                df = cached_index_returns(names, str(date.today()))
            except Exception as e:
                st.error(f"Error: {e}")
                return
        fig = core.plot_index_returns(df, which.lower())
        if fig is None:
            st.warning("No index returned complete data.")
        else:
            show_fig(fig)
        st.dataframe(df, width="stretch",
                     column_config={c: PCT for c in df.columns if c.endswith("D %")})
        missing = df[df["Sum of Ranks"].isna()]["Name"].tolist() if "Sum of Ranks" in df else []
        if missing:
            st.caption("No data from Yahoo for: " + ", ".join(missing))


def page_nse():
    _indices_page(core.NSE_INDICES, "NSE Indices Performance")


def page_world():
    _indices_page(core.WORLD_INDICES, "World Indices Performance")


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


def _range_page(header, names, default_start, plotter, label):
    st.header(header)
    c1, c2 = st.columns(2)
    start = c1.date_input("Start", default_start)
    end = c2.date_input("End", date.today())
    if st.button(label, type="primary") and valid_range(start, end):
        with st.spinner(f"Fetching {len(names)} symbols..."):
            df = cached_range_gains(names, str(start), str(end))
        fig = plotter(df, f"{header}: {start:%d-%m-%Y} to {end:%d-%m-%Y}")
        if fig is None:
            st.warning("No valid data for this range.")
        else:
            show_fig(fig)
        st.dataframe(df, width="stretch", hide_index=True, column_config={"Gain (%)": PCT})


def page_custom():
    _range_page("Custom Date Range Global Indices", core.WORLD_INDICES,
                date(date.today().year, 1, 1), core.plot_gain_bars, "Compare indices")


def page_nifty50():
    names = {s: s[:-3] for s in core.nifty50_symbols()}
    _range_page("Nifty 50 Performance Heatmap", names,
                date.today() - timedelta(days=30), core.plot_gain_grid, "Run Nifty 50 scan")


PAGES = {
    "Home": page_home,
    "Nifty 50 Heatmap": page_nifty50,
    "NSE Indices": page_nse,
    "World Indices": page_world,
    "Seasonality": page_seasonality,
    "Custom Date Range Global Indices": page_custom,
    "Candlestick Chart": page_candle,
}

with st.sidebar:
    st.title("📈 Analysis")
    choice = st.radio("Tool", list(PAGES), label_visibility="collapsed")
    st.divider()
    st.caption(DATA_SOURCE)

PAGES[choice]()
