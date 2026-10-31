"""
Analysis functions + the original Flask UI.

All market logic lives here so that both front-ends (Flask routes below and
../streamlit_app.py) use exactly the same calculations. The functions return
plain DataFrames / matplotlib Figures; each UI decides how to render them.
"""
import base64
import io
import math
import os
from datetime import datetime, timedelta, timezone

import matplotlib
matplotlib.use("Agg")                 # headless backend: no GUI, safe on servers
import matplotlib.pyplot as plt
import mplfinance as mpf
import numpy as np
import pandas as pd
import seaborn as sns
import yfinance as yf
from flask import Flask, render_template, request
from matplotlib.colors import LinearSegmentedColormap

HERE = os.path.dirname(os.path.abspath(__file__))
NIFTY50_CSV = os.path.join(HERE, "ind_nifty50list.csv")
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# ------------------------------------------------------------------ universes
NSE_INDICES = {
    '^NSEI': 'Nifty 50', '^CNXIT': 'Nifty IT', '^CNXREALTY': 'Nifty Realty',
    '^CNXINFRA': 'Nifty Infrastructure', '^CNXAUTO': 'Nifty Auto',
    '^CNXMETAL': 'Nifty Metal', '^CNXCMDT': 'Nifty Commodities',
    '^CNXPSUBANK': 'Nifty PSU Bank', '^NSEBANK': 'Nifty Bank',
    'NIFTY_PVT_BANK.NS': 'Nifty Private Bank', '^CNXPSE': 'Nifty PSE',
    '^CNXENERGY': 'Nifty Energy', '^CNXMNC': 'Nifty MNC', '^CNXFMCG': 'Nifty FMCG',
    'NIFTY_FIN_SERVICE.NS': 'Nifty Financial Services', '^CNXMEDIA': 'Nifty Media',
    '^CNXCONSUM': 'Nifty Consumption', '^CNXSERVICE': 'Nifty Services Sector',
    'NIFTY_MIDCAP_100.NS': 'Nifty Midcap 100', 'BSE-SMLCAP.BO': 'BSE SmallCap',
    '^CNXSC': 'Nifty Smallcap', '^CNXPHARMA': 'Nifty Pharma',
}
WORLD_INDICES = {
    '^NSEI': 'Nifty 50', '^HSI': 'Hang Seng', '^DJI': 'Dow Jones', '^IXIC': 'Nasdaq',
    '^FTSE': 'FTSE 100 UK', '^GDAXI': 'DAX Germany', '^FCHI': 'CAC 40 France',
    '^STOXX50E': 'EURO STOXX 50', '^N225': 'Nikkei 225 Japan',
    '^JKSE': 'JKSE Indonesia', '^KLSE': 'KLSE Malaysia', '^KS11': 'KOSPI South Korea',
    '^TWII': 'TSEC Taiwan', '^BVSP': 'BOVESPA Brazil', '^MXX': 'MXX Mexico',
    '^TA125.TA': 'TA125 Tel Aviv', '^STI': 'STI Singapore',
    'PSEI.PS': 'PSEI Philippines', '^BSESN': 'Sensex', '^GSPTSE': 'S&P/TSX Canada',
}


def nifty50_symbols():
    """Yahoo symbols for the constituents in ind_nifty50list.csv."""
    df = pd.read_csv(NIFTY50_CSV)
    return [f"{s.strip()}.NS" for s in df["Symbol"].dropna()]


# ------------------------------------------------------------- data helpers
def _naive_utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def flatten_columns(df):
    """yfinance >= 0.2.48 returns (Price, Ticker) MultiIndex columns even for
    one ticker; keep only the Price level."""
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    return df


def strip_tz(df):
    """Drop timezone info. Guarded: a failed download has a RangeIndex, which
    has no .tz attribute (this crashed the NSE page when a ticker was dead)."""
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
        df = df.copy()
        df.index = df.index.tz_localize(None)
    return df


def _to_date(d):
    return pd.Timestamp(d).strftime("%Y-%m-%d")


def download_ohlc(symbol, start, end, interval="1d"):
    """OHLCV for one symbol. `end` is INCLUSIVE here (yfinance's is exclusive)."""
    end_excl = _to_date(pd.Timestamp(end) + timedelta(days=1))
    data = yf.download(symbol, start=_to_date(start), end=end_excl,
                       interval=interval, auto_adjust=True, progress=False)
    data = strip_tz(flatten_columns(data))
    if data.empty or "Close" not in data.columns:
        return pd.DataFrame()
    return data.dropna(subset=["Close"])


def download_closes(symbols, start, end):
    """Closing prices for many symbols in ONE batched request
    (rows = dates, columns = symbols). `end` is inclusive.
    Symbols with no data come back as all-NaN columns."""
    symbols = list(symbols)
    end_excl = _to_date(pd.Timestamp(end) + timedelta(days=1))
    data = yf.download(symbols, start=_to_date(start), end=end_excl,
                       auto_adjust=True, progress=False, group_by="column")
    if data.empty:
        return pd.DataFrame(columns=symbols, dtype=float)
    if isinstance(data.columns, pd.MultiIndex):
        closes = data["Close"]
    else:                                  # very old yfinance, single symbol
        closes = data[["Close"]].set_axis(symbols[:1], axis=1)
    if isinstance(closes, pd.Series):
        closes = closes.to_frame(symbols[0])
    return strip_tz(closes.reindex(columns=symbols).astype(float))


def period_gain(closes):
    """% change from first to last available close in a series."""
    s = closes.dropna()
    if len(s) < 2 or s.iloc[0] == 0:
        return np.nan
    return (s.iloc[-1] / s.iloc[0] - 1) * 100


def range_gains(names, start, end):
    """DataFrame [Name, Gain (%)] sorted best -> worst, NaN rows last.
    `names` maps Yahoo symbol -> display name. Base price is the first trading
    day on/after `start`; `end` is inclusive."""
    closes = download_closes(list(names), start, end)
    rows = [{"Name": nm, "Gain (%)": period_gain(closes[sym])}
            for sym, nm in names.items()]
    df = pd.DataFrame(rows)
    df["Gain (%)"] = df["Gain (%)"].astype(float).round(2)
    return df.sort_values("Gain (%)", ascending=False,
                          na_position="last").reset_index(drop=True)


def get_valid_date(symbol, date_str, max_back=10):
    """Latest trading day on/before date_str. Returns None after `max_back`
    days instead of looping forever on a delisted symbol (old behaviour)."""
    date = datetime.strptime(date_str, '%Y-%m-%d')
    for _ in range(max_back):
        data = download_ohlc(symbol, date, date)
        if not data.empty:
            return date.strftime('%Y-%m-%d')
        date -= timedelta(days=1)
    return None


def get_custom_date_range_gain(symbol, start_date, end_date):
    """Kept for backward compatibility. end_date is EXCLUSIVE (yfinance style)."""
    end_incl = pd.Timestamp(end_date) - timedelta(days=1)
    data = download_ohlc(symbol, start_date, end_incl)
    return np.nan if data.empty else period_gain(data["Close"])


# ------------------------------------------------------- 30/60/90-day ranking
def compute_index_returns(names, durations=(30, 60, 90), reference_date=None):
    """Returns over each look-back window, ranked (rank 1 = best return).
    Rows sorted by Sum of Ranks ascending (strongest first); symbols with
    missing data are appended at the bottom."""
    durations = list(durations)
    ref = pd.Timestamp(reference_date or _naive_utc_now()).normalize()
    closes = download_closes(list(names), ref - timedelta(days=max(durations) + 5), ref)

    rows = {}
    for sym in names:
        s = closes[sym].dropna()
        rows[sym] = {f"{d}D %": period_gain(s[s.index >= ref - timedelta(days=d)])
                     for d in durations}
    df = pd.DataFrame.from_dict(rows, orient="index")
    df.insert(0, "Name", [names[s] for s in df.index])
    ret_cols = [f"{d}D %" for d in durations]

    ok = df.dropna(subset=ret_cols).copy()          # .copy(): no SettingWithCopy
    bad = df[df[ret_cols].isna().any(axis=1)]
    for c in ret_cols:
        ok[f"Rank {c.replace(' %', '')}"] = ok[c].rank(ascending=False, method="min")
    rank_cols = [c for c in ok.columns if c.startswith("Rank")]
    ok["Sum of Ranks"] = ok[rank_cols].sum(axis=1)
    ok = ok.sort_values("Sum of Ranks", kind="stable")

    out = pd.concat([ok, bad]) if not bad.empty else ok
    out[ret_cols] = out[ret_cols].round(2)
    out.index.name = "Symbol"
    return out


def plot_index_returns(df, which="strongest", n=3, title_prefix=""):
    """Grouped bar chart of the n strongest (lowest Sum of Ranks) or weakest
    indices. Returns a Figure, or None if no index has complete data."""
    ranked = df.dropna(subset=["Sum of Ranks"]) if "Sum of Ranks" in df else df.iloc[0:0]
    if ranked.empty:
        return None
    pick = ranked.head(n) if which == "strongest" else ranked.tail(n).iloc[::-1]
    ret_cols = [c for c in df.columns if c.endswith("D %")]

    fig, ax = plt.subplots(figsize=(10, 7))
    width = 0.8 / len(ret_cols)
    x = np.arange(len(pick))
    for i, c in enumerate(ret_cols):
        vals = pick[c].to_numpy(float)
        ax.bar(x + i * width, vals, width, label=f"{c[:-3]} days")
        for xi, v in zip(x, vals):
            ax.text(xi + i * width, v, f"{v:.2f}%", ha="center",
                    va="bottom" if v >= 0 else "top", fontsize=11)
    ax.axhline(0, color="grey", linewidth=0.8)
    ax.set_xticks(x + width * (len(ret_cols) - 1) / 2)
    ax.set_xticklabels(pick["Name"], fontsize=13, rotation=30, ha="right")
    ax.set_ylabel("Return (%)", fontsize=13)
    ax.set_title(f"{title_prefix}{which.title()} {len(pick)} by sum of 30/60/90-day ranks",
                 fontsize=16)
    ax.legend(title="Window")
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------- seasonality
def seasonality_tables(ticker, years, include_partial=False):
    """Returns (heatmap_df [Year x Jan..Dec], summary_df, n_years).
    Raises ValueError if there is not enough data."""
    end = _naive_utc_now()
    start = end - timedelta(days=int(years) * 366 + 62)   # extra months: first return
    data = download_ohlc(ticker, start, end, interval="1mo")
    if data.empty:
        raise ValueError(f"No monthly data for {ticker}")

    # Yahoo sometimes adds an extra mid-month row for the latest price:
    # collapse to one close per calendar month.
    close = data["Close"].groupby(data.index.to_period("M")).last()
    rets = close.pct_change().dropna()
    if not include_partial and len(rets) and rets.index[-1] == pd.Period(end, "M"):
        rets = rets.iloc[:-1]                               # month not finished yet
    rets = rets[rets.index >= pd.Period(end, "M") - 12 * int(years)]
    if rets.empty:
        raise ValueError("Not enough history.")

    frame = pd.DataFrame({"Year": rets.index.year, "Month": rets.index.month,
                          "Ret": rets.to_numpy()})
    heat = (frame.pivot_table(index="Year", columns="Month", values="Ret")
                 .reindex(columns=range(1, 13)))            # always 12 columns
    heat.columns = MONTHS

    g = frame.groupby("Month")["Ret"]
    summary = pd.DataFrame({
        "Month": MONTHS,
        "Positive": g.apply(lambda r: int((r > 0).sum())).reindex(range(1, 13)).fillna(0).astype(int).to_numpy(),
        "Negative": g.apply(lambda r: int((r < 0).sum())).reindex(range(1, 13)).fillna(0).astype(int).to_numpy(),
        "Avg Return": g.mean().reindex(range(1, 13)).to_numpy(),
        "Avg Positive Return": frame[frame.Ret > 0].groupby("Month")["Ret"].mean().reindex(range(1, 13)).to_numpy(),
        "Geo Mean Return": g.apply(lambda r: np.prod(1 + r) ** (1 / len(r)) - 1).reindex(range(1, 13)).to_numpy(),
    })
    total = summary["Positive"] + summary["Negative"]
    summary.insert(3, "Win Rate", np.where(total > 0, summary["Positive"] / total.replace(0, 1), np.nan))
    return heat, summary, int(frame["Year"].nunique())


def plot_seasonality(heat, ticker, n_years):
    colors = ["#C71585", "#DB7093", "#FFFFFF", "#228B22", "#006400"]
    cmap = LinearSegmentedColormap.from_list("dark_cmap", colors, N=256)
    fig, ax = plt.subplots(figsize=(12, max(4, 0.45 * len(heat) + 2)))
    sns.heatmap(heat, annot=True, fmt=".2%", cmap=cmap, center=0, ax=ax,
                cbar_kws={"label": "Monthly return"})
    # Labels come from the DataFrame columns, so they sit centred on the
    # correct cells (old code put them on cell edges at 0..11).
    span = f"{heat.index.min()}" if heat.index.min() == heat.index.max() \
        else f"{heat.index.min()}-{heat.index.max()}"
    ax.set_title(f"Monthly Seasonality of {ticker} ({span})")
    ax.set_xlabel("Month")
    ax.set_ylabel("Year")
    ax.tick_params(axis="x", rotation=45)
    ax.tick_params(axis="y", rotation=0)
    fig.tight_layout()
    return fig


# --------------------------------------------------------------- other charts
def plot_gain_bars(df, title):
    """Bar chart for a [Name, Gain (%)] frame. None if nothing to plot."""
    valid = df.dropna(subset=["Gain (%)"])
    if valid.empty:
        return None
    fig, ax = plt.subplots(figsize=(12, 7))
    gains = valid["Gain (%)"].to_numpy(float)
    bars = ax.bar(valid["Name"], gains, color=["green" if g > 0 else "red" for g in gains])
    for b, g in zip(bars, gains):
        ax.text(b.get_x() + b.get_width() / 2, g, f"{g:.2f}%", ha="center",
                va="bottom" if g > 0 else "top", fontsize=10)
    ax.axhline(0, color="grey", linewidth=0.8)
    ax.set_ylabel("Gain (%)")
    ax.set_title(title)
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
    ax.grid(axis="y", linestyle="--", alpha=0.6)
    fig.tight_layout()
    return fig


def plot_gain_grid(df, title, ncols=5):
    """Heatmap grid of [Name, Gain (%)] sorted best -> worst (row 1 = best).
    Grid height adapts to the number of stocks (was hard-coded 10x5)."""
    valid = df.dropna(subset=["Gain (%)"]).reset_index(drop=True)
    if valid.empty:
        return None
    nrows = math.ceil(len(valid) / ncols)
    pad = nrows * ncols - len(valid)
    gains = np.append(valid["Gain (%)"].to_numpy(float), [np.nan] * pad).reshape(nrows, ncols)
    labels = [f"{n}\n{g:.1f}%" for n, g in zip(valid["Name"], valid["Gain (%)"])]
    annot = np.array(labels + [""] * pad, dtype=object).reshape(nrows, ncols)

    cmap = LinearSegmentedColormap.from_list("rg", ["red", "white", "green"], N=256)
    fig, ax = plt.subplots(figsize=(14, 1.4 * nrows + 2))
    sns.heatmap(gains, annot=annot, fmt="", cmap=cmap, center=0, ax=ax,
                annot_kws={"fontsize": 11}, linewidths=0.5, linecolor="white",
                xticklabels=False, yticklabels=range(1, nrows + 1),
                cbar_kws={"label": "Gain (%)", "shrink": 0.8})
    ax.set_ylabel("Row (1 = top performers)")
    ax.tick_params(axis="y", rotation=0)
    ax.set_title(title)
    fig.tight_layout()
    return fig


def plot_candles(ticker, data):
    """Candlestick (+ volume when available) without weekend/holiday gaps."""
    has_vol = bool("Volume" in data.columns and data["Volume"].fillna(0).sum() > 0)
    fig, _ = mpf.plot(data, type="candle", style="yahoo", volume=has_vol,
                      title=f"{ticker} Candlestick Chart", ylabel="Price",
                      figsize=(12, 7), returnfig=True, tight_layout=True)
    return fig


def fig_to_data_uri(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def analyze_indices(indices, index_names, route_name):
    """Backward-compatible wrapper for the Flask routes: (table_html, plot_uri)."""
    names = {s: index_names.get(s, s) for s in indices}
    df = compute_index_returns(names)
    prefix = "NSE Indices: " if route_name == "nse" else "World Indices: "
    fig = plot_index_returns(df, "strongest", title_prefix=prefix)
    table_html = df.to_html(classes="table table-striped table-bordered", na_rep="N/A")
    return table_html, (fig_to_data_uri(fig) if fig else None)


# ======================================================================= Flask
# NOTE: the templates/ folder referenced below is not in the repo, so these
# routes need it restored before the Flask UI works. Streamlit does not use them.
app = Flask(__name__)


@app.after_request
def add_no_cache(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/')
def home():
    return render_template('home.html')


@app.route('/candle', methods=['GET', 'POST'])
def candle():
    if request.method == 'POST':
        ticker = request.form['ticker'].strip().upper()
        data = download_ohlc(ticker, request.form['start_date'], request.form['end_date'])
        if data.empty:
            return render_template('candle.html', error=f"No data found for {ticker}")
        return render_template('candle.html', ticker=ticker,
                               plot_url=fig_to_data_uri(plot_candles(ticker, data)))
    return render_template('candle.html')


@app.route('/nse', methods=['GET', 'POST'])
def nse():
    if request.method == 'POST':
        try:
            table_html, plot_url = analyze_indices(list(NSE_INDICES), NSE_INDICES, 'nse')
            return render_template('nse.html', table=table_html, plot_url=plot_url)
        except Exception as e:
            return render_template('nse.html', error=f"Error generating NSE Indices analysis: {e}")
    return render_template('nse.html', message="Click 'Run NSE Analysis' to generate results.")


@app.route('/world', methods=['GET', 'POST'])
def world():
    if request.method == 'POST':
        try:
            table_html, plot_url = analyze_indices(list(WORLD_INDICES), WORLD_INDICES, 'world')
            return render_template('world.html', table=table_html, plot_url=plot_url)
        except Exception as e:
            return render_template('world.html', error=f"Error generating World Indices analysis: {e}")
    return render_template('world.html', message="Click 'Run World Indices Analysis' to generate results.")


@app.route('/seasonality', methods=['GET', 'POST'])
def seasonality():
    if request.method == 'POST':
        ticker = request.form['ticker'].strip().upper()
        try:
            years = int(request.form.get('year', 30))
            heat, summary, n_years = seasonality_tables(ticker, years)
            fmt = {c: "{:.2%}".format for c in summary.columns
                   if c not in ("Month", "Positive", "Negative")}
            summary_html = summary.to_html(classes='table table-striped table-bordered',
                                           index=False, formatters=fmt, na_rep='N/A')
            return render_template('seasonality.html', summary_table=summary_html, ticker=ticker,
                                   plot_url=fig_to_data_uri(plot_seasonality(heat, ticker, n_years)),
                                   actual_year=n_years)
        except Exception as e:
            return render_template('seasonality.html',
                                   error=f"Error generating seasonality analysis for {ticker}: {e}")
    return render_template('seasonality.html')


def _range_page(template, names, title_fmt, plotter):
    start_str, end_str = request.form['start_date'], request.form['end_date']
    try:
        if start_str >= end_str:
            raise ValueError("Start date must be before end date.")
        df = range_gains(names, start_str, end_str)
        fig = plotter(df, title_fmt.format(start=start_str, end=end_str))
        if fig is None:
            raise ValueError("No valid data for plotting")
        table_html = df.to_html(classes='table table-striped table-bordered',
                                na_rep='N/A', float_format='%.2f')
        return render_template(template, plot_url=fig_to_data_uri(fig), table=table_html,
                               start_date=start_str, end_date=end_str)
    except Exception as e:
        return render_template(template, error=f"Error generating analysis: {e}")


@app.route('/custom', methods=['GET', 'POST'])
def custom():
    if request.method == 'POST':
        return _range_page('custom.html', WORLD_INDICES,
                           "Equity indices {start} to {end}", plot_gain_bars)
    return render_template('custom.html')


@app.route('/nifty50', methods=['GET', 'POST'])
def nifty50():
    if request.method == 'POST':
        names = {s: s[:-3] for s in nifty50_symbols()}
        return _range_page('nifty50.html', names,
                           "Nifty 50 {start} to {end} (sorted by gain)", plot_gain_grid)
    return render_template('nifty50.html')


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False, threaded=True)
