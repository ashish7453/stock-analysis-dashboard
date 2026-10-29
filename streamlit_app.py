"""
Streamlit UI for the Analysis Dashboard.

The six original analyses live in `stock-chart-app-main/app.py` (Flask + matplotlib).
Rather than rewriting the strategy logic, this module imports that file's functions
and re-renders their matplotlib output natively in Streamlit.

Run locally:   streamlit run streamlit_app.py
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(HERE, "stock-chart-app-main")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
os.chdir(APP_DIR)                     # app.py reads ind_nifty50list.csv relatively

import pandas as pd
import streamlit as st

import app as core
from pretty_html_table import build_table

st.set_page_config(page_title="Analysis Dashboard",
                   page_icon="📈", layout="wide")

DATA_SOURCE = "Yahoo Finance. Not investment advice."


def show_html_table(html: str):
    """Style the pandas to_html() output the original app produced."""
    try:
        st.markdown(build_table(
            pd.read_html(io.StringIO(html))[0],
            color="blue_light",
        ), unsafe_allow_html=True)
    except Exception:
        st.markdown(html, unsafe_allow_html=True)


def decode_plot(plot_value):
    """analyze_indices returns a full 'data:image/png;base64,...' URI, which
    st.image cannot consume. Strip it down to raw PNG bytes."""
    if isinstance(plot_value, (bytes, bytearray)):
        return bytes(plot_value)
    if not isinstance(plot_value, str):
        return plot_value
    if plot_value.startswith("data:"):
        plot_value = plot_value.split(",", 1)[-1]
    import base64
    return base64.b64decode(plot_value)


# --------------------------------------------------------------------- pages
def page_home():
    st.title("Analysis Dashboard")
    st.caption("Pick a tool from the sidebar.")


def page_candle():
    st.header("Candlestick Chart Generator")
    c1, c2, c3 = st.columns([2, 1, 1])
    ticker = c1.text_input("Ticker", "TCS.NS", help="Yahoo symbol, e.g. RELIANCE.NS")
    start = c2.date_input("Start", pd.Timestamp.today() - pd.Timedelta(days=180))
    end = c3.date_input("End", pd.Timestamp.today())
    if st.button("Generate chart", type="primary"):
        with st.spinner("Fetching data..."):
            data = core.yf.download(ticker.upper(), start=str(start), end=str(end),
                                    progress=False)
        if data.empty:
            st.error(f"No data found for {ticker.upper()}")
            return
        data = data.reset_index()
        data["Date"] = core.mdates.date2num(data["Date"])
        ohlc = data[["Date", "Open", "High", "Low", "Close"]].values
        fig, ax = core.plt.subplots(figsize=(12, 6))
        core.candlestick_ohlc(ax, ohlc, width=0.6, colorup="g", colordown="r", alpha=0.8)
        ax.xaxis_date()
        ax.xaxis.set_major_formatter(core.mdates.DateFormatter("%Y-%m-%d"))
        ax.xaxis.set_major_locator(core.mdates.WeekdayLocator())
        core.plt.xticks(rotation=45)
        ax.set_title(f"{ticker.upper()} Candlestick Chart")
        ax.set_xlabel("Date")
        ax.set_ylabel("Price")
        core.plt.tight_layout()
        st.pyplot(fig)
        core.plt.close(fig)


def _indices_page(route, indices, names, title):
    st.header(title)
    if st.button("Run analysis", type="primary"):
        with st.spinner("Pulling 30/60/90-day returns..."):
            try:
                table_html, plot_url = core.analyze_indices(indices, names, route)
            except Exception as e:
                st.error(f"Error: {e}")
                return
        st.image(decode_plot(plot_url),
                 caption="Weakest three indices by summed rank")
        show_html_table(table_html)


def page_nse():
    _indices_page("nse",
                  ['^NSEI', '^CNXIT', '^CNXREALTY', '^CNXINFRA', '^CNXAUTO',
                   '^CNXMETAL', '^CNXCMDT', '^CNXPSUBANK', '^NSEBANK',
                   'NIFTY_PVT_BANK.NS', '^CNXPSE', '^CNXENERGY',
                   '^CNXMNC', '^CNXFMCG', 'NIFTY_FIN_SERVICE.NS', '^CNXMEDIA',
                   '^CNXCONSUM', '^CNXSERVICE', 'NIFTY_MIDCAP_100.NS',
                   'BSE-SMLCAP.BO', '^CNXSC', '^CNXPHARMA'],
                  {'^NSEI': 'Nifty 50', '^CNXIT': 'Nifty IT', '^CNXREALTY': 'Nifty Realty',
                   '^CNXINFRA': 'Nifty Infrastructure', '^CNXAUTO': 'Nifty Auto',
                   '^CNXMETAL': 'Nifty Metal', '^CNXCMDT': 'Nifty Commodities',
                   '^CNXPSUBANK': 'Nifty PSU Bank', '^NSEBANK': 'Nifty Bank',
                   'NIFTY_PVT_BANK.NS': 'Nifty Private Bank', '^CNXPSE': 'Nifty PSE',
                   '^CNXENERGY': 'Nifty Energy', '^CNXMNC': 'Nifty MNC',
                   '^CNXFMCG': 'Nifty FMCG',
                   'NIFTY_FIN_SERVICE.NS': 'Nifty Financial Services',
                   '^CNXMEDIA': 'Nifty Media', '^CNXCONSUM': 'Nifty Consumption',
                   '^CNXSERVICE': 'Nifty Services Sector',
                   'NIFTY_MIDCAP_100.NS': 'Nifty Midcap 100',
                   'BSE-SMLCAP.BO': 'BSE SmallCap', '^CNXSC': 'Nifty Smallcap',
                   '^CNXPHARMA': 'Nifty Pharma'},
                  "NSE Indices Performance")


def page_world():
    _indices_page("world",
                  ['^NSEI', '^HSI', '^DJI', '^IXIC', '^FTSE', '^GDAXI', '^FCHI',
                   '^STOXX50E', '^N225', '^JKSE', '^KLSE', '^KS11', '^TWII',
                   '^BVSP', '^MXX', '^TA125.TA', '^STI', 'PSEI.PS', '^BSESN',
                   '^GSPTSE'],
                  {'^NSEI': 'Nifty 50', '^HSI': 'Hang Seng', '^DJI': 'Dow Jones',
                   '^IXIC': 'Nasdaq', '^FTSE': 'FTSE 100 UK', '^GDAXI': 'DAX Germany',
                   '^FCHI': 'CAC 40 France', '^STOXX50E': 'EURO STOXX 50',
                   '^N225': 'Nikkei 225 Japan', '^JKSE': 'JKSE Indonesia',
                   '^KLSE': 'KLSE Malaysia', '^KS11': 'KOSPI South Korea',
                   '^TWII': 'TSEC Taiwan', '^BVSP': 'BOVESPA Brazil',
                   '^MXX': 'MXX Mexico', '^TA125.TA': 'TA125 Tel Aviv',
                   '^STI': 'STI Singapore', 'PSEI.PS': 'PSEI Philippines',
                   '^BSESN': 'Sensex', '^GSPTSE': 'S&P/TSX Canada'},
                  "World Indices Performance")


def page_seasonality():
    st.header("Monthly Seasonality Heatmap")
    c1, c2 = st.columns([2, 1])
    ticker = c1.text_input("Ticker", "RELIANCE.NS")
    years = c2.number_input("Lookback (years)", 1, 50, 10)
    if st.button("Run seasonality", type="primary"):
        from datetime import datetime, timedelta, timezone
        with st.spinner("Downloading monthly history..."):
            end_date = datetime.now(timezone.utc)
            start_date = end_date - timedelta(days=int(years) * 365)
            data = core.yf.download(ticker.upper(), start=start_date, end=end_date,
                                    interval="1mo", auto_adjust=True, progress=False)
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = [c[0] for c in data.columns]
        if data.empty or "Close" not in data.columns:
            st.error(f"No monthly data for {ticker.upper()}")
            return
        if data.index.tz is not None:
            data.index = data.index.tz_localize(None)
        data["Returns"] = data["Close"].pct_change()
        data = data.dropna(subset=["Returns"])
        if data.empty:
            st.error("Not enough history.")
            return
        data["Year"] = data.index.year
        data["Month"] = data.index.month

        monthly_avg = data.groupby(["Year", "Month"])["Returns"].mean().unstack()
        colors = ["#C71585", "#DB7093", "#FFFFFF", "#228B22", "#006400"]
        cmap = core.LinearSegmentedColormap.from_list("dark_cmap", colors, N=256)
        fig = core.plt.figure(figsize=(12, 10))
        core.sns.heatmap(monthly_avg, annot=True, fmt=".2%", cmap=cmap, center=0,
                         cbar_kws={"label": "Average Monthly Returns"})
        core.plt.title(f"Monthly Seasonality of {ticker.upper()} "
                       f"(Last {data['Year'].nunique()} Years)")
        core.plt.xlabel("Month")
        core.plt.ylabel("Year")
        core.plt.xticks(ticks=range(12),
                        labels=["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
                        rotation=45)
        core.plt.tight_layout()
        st.pyplot(fig)
        core.plt.close(fig)

        monthly_counts = data.groupby("Month")[["Returns"]].size()
        monthly_avg_total = data.groupby("Month")["Returns"].mean()
        summary = pd.DataFrame({
            "Month": ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
            "Observations": [int(monthly_counts.get(m, 0)) for m in range(1, 13)],
            "Avg Return": [f"{monthly_avg_total.get(m, float('nan')):.2%}"
                           if m in monthly_avg_total.index else "N/A"
                           for m in range(1, 13)],
        })
        st.dataframe(summary, width='stretch', hide_index=True)


def page_custom():
    st.header("Custom Date Range â€” Global Indices")
    c1, c2 = st.columns(2)
    start = c1.date_input("Start", pd.Timestamp("2026-01-01"))
    end = c2.date_input("End", pd.Timestamp.today())
    if st.button("Compare indices", type="primary"):
        from datetime import datetime, timedelta, timezone
        from flask import Flask
        names = {'^NSEI': 'Nifty 50', '^HSI': 'Hang Seng', '^DJI': 'Dow Jones',
                 '^IXIC': 'Nasdaq', '^FTSE': 'FTSE 100 UK', '^GDAXI': 'DAX Germany',
                 '^FCHI': 'CAC 40 France', '^STOXX50E': 'EURO STOXX 50',
                 '^N225': 'Nikkei 225 Japan', '^JKSE': 'JKSE Indonesia',
                 '^KLSE': 'KLSE Malaysia', '^KS11': 'KOSPI South Korea',
                 '^TWII': 'TSEC Taiwan', '^BVSP': 'BOVESPA Brazil', '^MXX': 'MXX Mexico',
                 '^TA125.TA': 'TA125 Tel Aviv', '^STI': 'STI Singapore',
                 'PSEI.PS': 'PSEI Philippines', '^BSESN': 'Sensex',
                 '^GSPTSE': 'S&P/TSX Canada'}
        end_yf = (pd.Timestamp(end) + timedelta(days=1)).strftime("%Y-%m-%d")
        rows = []
        prog = st.progress(0.0, text="Fetching...")
        for i, (sym, nm) in enumerate(names.items()):
            try:
                g = core.get_custom_date_range_gain(
                    sym, str(start), end_yf)
            except Exception:
                g = None
            rows.append({"Index": nm, "Gain (%)": None if g is None or pd.isna(g)
                         else round(float(g), 2)})
            prog.progress((i + 1) / len(names), text=f"{nm}...")
        prog.empty()
        df = pd.DataFrame(rows).sort_values("Gain (%)", ascending=False,
                                            na_position="last").reset_index(drop=True)
        valid = df.dropna(subset=["Gain (%)"])
        if not valid.empty:
            fig, ax = core.plt.subplots(figsize=(12, 7))
            colors = ["green" if g > 0 else "red" for g in valid["Gain (%)"]]
            bars = ax.bar(valid["Index"], valid["Gain (%)"], color=colors)
            for b, g in zip(bars, valid["Gain (%)"]):
                ax.text(b.get_x() + b.get_width() / 2, g, f"{g:.2f}%",
                        ha="center", va="bottom" if g > 0 else "top", fontsize=10)
            ax.set_ylabel("Gain (%)")
            ax.set_title(f"Equity indices {start} â†’ {end}")
            core.plt.xticks(rotation=45, ha="right")
            ax.grid(axis="y", linestyle="--", alpha=0.6)
            core.plt.tight_layout()
            st.pyplot(fig)
            core.plt.close(fig)
        st.dataframe(df, width='stretch', hide_index=True)


def page_nifty50():
    st.header("Nifty 50 Performance Heatmap")
    c1, c2 = st.columns(2)
    start = c1.date_input("Start", pd.Timestamp.today() - pd.Timedelta(days=30))
    end = c2.date_input("End", pd.Timestamp.today())
    if st.button("Run Nifty 50 scan", type="primary"):
        from datetime import timedelta
        df_csv = pd.read_csv("ind_nifty50list.csv")
        symbols = [f"{x}.NS" for x in df_csv["Symbol"].tolist()]
        end_yf = (pd.Timestamp(end) + timedelta(days=1)).strftime("%Y-%m-%d")
        rows = []
        prog = st.progress(0.0, text="Fetching 50 symbols...")
        for i, sym in enumerate(symbols):
            try:
                g = core.get_custom_date_range_gain(sym, str(start), end_yf)
            except Exception:
                g = None
            rows.append({"Stock": sym.replace(".NS", ""),
                         "Gain (%)": None if g is None or pd.isna(g) else round(float(g), 2)})
            prog.progress((i + 1) / len(symbols), text=sym)
        prog.empty()
        df = pd.DataFrame(rows).sort_values("Gain (%)", ascending=False,
                                            na_position="last").reset_index(drop=True)
        st.dataframe(df, width='stretch', hide_index=True)

        valid = df.dropna(subset=["Gain (%)"]).reset_index(drop=True)
        if valid.empty:
            st.warning("No valid data.")
            return
        while len(valid) < 50:
            valid.loc[len(valid)] = {"Stock": "", "Gain (%)": float("nan")}
        gains = valid["Gain (%)"].to_numpy(float).reshape(10, 5)
        annot = valid.apply(
            lambda r: f"{r['Stock']}\n{r['Gain (%)']:.1f}%"
            if isinstance(r["Stock"], str) and r["Stock"] else "",
            axis=1).to_numpy().reshape(10, 5)
        cmap = core.LinearSegmentedColormap.from_list("rg", ["red", "white", "green"], N=256)
        fig, ax = core.plt.subplots(figsize=(14, 16))
        core.sns.heatmap(gains, annot=annot, fmt="", cmap=cmap, center=0, ax=ax,
                         annot_kws={"fontsize": 11}, linewidths=0.5,
                         linecolor="white",
                         cbar_kws={"label": "Gain (%)", "shrink": 0.8})
        ax.set_title(f"Nifty 50 â€” {start} â†’ {end} (sorted by gain)")
        core.plt.tight_layout()
        st.pyplot(fig)
        core.plt.close(fig)


PAGES = {
    "Home": page_home,
    "Nifty 50 Heatmap": page_nifty50,
    "NSE Indices": page_nse,
    "World Indices": page_world,
    "Seasonality": page_seasonality,
    "Custom Date Range": page_custom,
    "Candlestick Chart": page_candle,
}

with st.sidebar:
    st.title("📈 Analysis")
    choice = st.radio("Tool", list(PAGES), label_visibility="collapsed")
    st.divider()
    st.caption(DATA_SOURCE)

PAGES[choice]()

