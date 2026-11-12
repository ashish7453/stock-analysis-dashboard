"""
Analysis functions + the original Flask UI.

All market logic lives here so that both front-ends (Flask routes below and
../streamlit_app.py) use exactly the same calculations. The functions return
plain DataFrames / matplotlib Figures; each UI decides how to render them.
"""
import base64
import io
import re
import math
import os
import time
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
CALC_VERSION = 10   # bump when calculations change: invalidates Streamlit's cache
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

COMMODITIES = {
    'GC=F': 'Gold', 'SI=F': 'Silver', 'PL=F': 'Platinum', 'PA=F': 'Palladium',
    'HG=F': 'Copper', 'ALI=F': 'Aluminium', 'CL=F': 'Crude Oil (WTI)',
    'BZ=F': 'Crude Oil (Brent)', 'NG=F': 'Natural Gas',
}
# Quoted as USD per 1 unit of the currency, so a positive gain means that
# currency STRENGTHENED against the US dollar.
CURRENCIES = {
    'INRUSD=X': 'Rupee (India)', 'JPYUSD=X': 'Yen (Japan)', 'GBPUSD=X': 'Pound (UK)',
    'EURUSD=X': 'Euro (Eurozone)', 'CNYUSD=X': 'Yuan (China)', 'CADUSD=X': 'Dollar (Canada)',
    'AUDUSD=X': 'Dollar (Australia)', 'BRLUSD=X': 'Real (Brazil)',
    'ZARUSD=X': 'Rand (South Africa)', 'MYRUSD=X': 'Ringgit (Malaysia)',
    'SGDUSD=X': 'Dollar (Singapore)', 'NZDUSD=X': 'Dollar (New Zealand)',
    'IDRUSD=X': 'Rupiah (Indonesia)', 'KRWUSD=X': 'Won (South Korea)',
    'MXNUSD=X': 'Peso (Mexico)', 'THBUSD=X': 'Baht (Thailand)',
}
COUNTRY_ETFS = {sym: f"{country} ({sym})" for sym, country in [
    ("EWA", "Australia"), ("EWO", "Austria"), ("EWK", "Belgium"), ("EWZ", "Brazil"),
    ("EWC", "Canada"), ("ECH", "Chile"), ("FXI", "China"), ("GXG", "Colombia"),
    ("EDEN", "Denmark"), ("EFNL", "Finland"), ("EWQ", "France"), ("EWG", "Germany"),
    ("GREK", "Greece"), ("EWH", "Hong Kong"), ("INDA", "India"), ("EPI", "India"),
    ("EIDO", "Indonesia"), ("EIRL", "Ireland"), ("EIS", "Israel"), ("EWI", "Italy"),
    ("EWJ", "Japan"), ("EWY", "South Korea"), ("KWT", "Kuwait"), ("EWM", "Malaysia"),
    ("EWW", "Mexico"), ("EWN", "Netherlands"), ("ENZL", "New Zealand"), ("NORW", "Norway"),
    ("EPHE", "Philippines"), ("EPOL", "Poland"), ("QAT", "Qatar"), ("KSA", "Saudi Arabia"),
    ("EWS", "Singapore"), ("EZA", "South Africa"), ("EWP", "Spain"), ("EWD", "Sweden"),
    ("EWL", "Switzerland"), ("EWT", "Taiwan"), ("THD", "Thailand"), ("TUR", "Turkey"),
    ("UAE", "UAE"), ("EWU", "United Kingdom"), ("VNM", "Vietnam"), ("ARGT", "Argentina"),
]}


def nifty50_symbols():
    """Yahoo symbols for the constituents in ind_nifty50list.csv."""
    df = pd.read_csv(NIFTY50_CSV)
    return [f"{s.strip()}.NS" for s in df["Symbol"].dropna()]


def symbols_from_csv(df, suffix=".NS", limit=500):
    """{yahoo_symbol: display_name} from an uploaded CSV. Uses a 'Symbol' /
    'Ticker' column (any case), or the first column. Symbols that already carry
    an exchange suffix or are indices/futures ('TCS.BO', '^NSEI', 'GC=F') are
    kept as-is."""
    cols = {str(c).lower().strip(): c for c in df.columns}
    col = cols.get("symbol") or cols.get("ticker") or df.columns[0]
    names = {}
    for raw in df[col].dropna().astype(str).str.strip().str.upper():
        if not raw or raw in ("SYMBOL", "TICKER"):
            continue
        sym = raw if ("." in raw or raw.startswith("^") or "=" in raw) else raw + suffix
        names[sym] = raw.split(".")[0]
    return dict(list(names.items())[:limit])


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


def _request_end(end):
    """yfinance `end` to send Yahoo. Asking for exactly the day after `end`
    sometimes makes Yahoo leave out the last daily bar (seen live: an end
    date of Fri 6-Nov returned data only up to Thu 5-Nov). So ask for 4 extra
    days and trim to `end` ourselves with _trim_to()."""
    return _to_date(pd.Timestamp(end) + timedelta(days=4))


def _trim_to(df, end):
    """Keep rows dated on or before `end` (inclusive)."""
    if df.empty or not isinstance(df.index, pd.DatetimeIndex):
        return df
    return df[df.index < pd.Timestamp(end).normalize() + timedelta(days=1)]


def download_ohlc(symbol, start, end, interval="1d"):
    """OHLCV for one symbol. `end` is INCLUSIVE here (yfinance's is exclusive)."""
    data = yf.download(symbol, start=_to_date(start), end=_request_end(end),
                       interval=interval, auto_adjust=True, progress=False)
    data = _trim_to(strip_tz(flatten_columns(data)), end)
    if data.empty or "Close" not in data.columns:
        return pd.DataFrame()
    return data.dropna(subset=["Close"])


class DataUnavailable(RuntimeError):
    """Yahoo returned no prices at all (rate limit, outage or blocked IP).
    Raised instead of returning an empty table so callers (and Streamlit's
    cache) never treat a failed download as a real, cacheable result."""


def _yahoo_errors():
    try:
        import yfinance.shared as shared
        return dict(getattr(shared, "_ERRORS", {}) or {})
    except Exception:
        return {}


def _download_close_table(symbols, start, end_req, threads=True):
    # auto_adjust=False -> real exchange closing prices (split-adjusted only),
    # so Base/Last Price match NSE's published closes. Dividend-adjusted
    # prices (auto_adjust=True) lowered the base price of any stock that went
    # ex-dividend inside the range, so its gain did not match NSE.
    data = yf.download(symbols, start=start, end=end_req, auto_adjust=False,
                       progress=False, group_by="column", threads=threads)
    if data is None or data.empty:
        return pd.DataFrame(columns=symbols, dtype=float)
    if isinstance(data.columns, pd.MultiIndex):
        closes = data["Close"]
    else:                                  # very old yfinance, single symbol
        closes = data[["Close"]].set_axis(symbols[:1], axis=1)
    if isinstance(closes, pd.Series):
        closes = closes.to_frame(symbols[0])
    return strip_tz(closes.reindex(columns=symbols).astype(float))


def download_closes(symbols, start, end, retry_wait=2.0):
    """Closing prices for many symbols in ONE batched request
    (rows = dates, columns = symbols). `end` is inclusive.

    Symbols Yahoo skipped (rate limit / hiccup) are retried once, one at a
    time. Symbols that still have no data come back as all-NaN columns.
    If NO symbol has data, raises DataUnavailable with Yahoo's message."""
    symbols = list(symbols)
    start_s = _to_date(start)
    end_req = _request_end(end)
    closes = _trim_to(_download_close_table(symbols, start_s, end_req), end)

    missing = [s for s in symbols if closes[s].dropna().empty]
    if missing:
        time.sleep(retry_wait)
        again = _trim_to(_download_close_table(missing, start_s, end_req, threads=False), end)
        got = [s for s in missing if not again[s].dropna().empty]
        if got:
            closes = closes.combine_first(again[got]).reindex(columns=symbols)

    if all(closes[s].dropna().empty for s in symbols):
        errs = _yahoo_errors()
        detail = next(iter(errs.values()), "") if errs else ""
        raise DataUnavailable(
            "Yahoo Finance returned no prices for any symbol "
            f"({start_s} to {_to_date(end)}). This is usually a temporary "
            "rate limit on the hosting server; wait a minute and run again."
            + (f" Yahoo said: {str(detail)[:200]}" if detail else ""))
    return closes


def base_window(closes, start, include_start=True):
    """Closes from the base close to the end.

    include_start=True  -> base = close ON `start` (or the last trading day
                           before it). Used by the 30/60/90-day rankings.
    include_start=False -> base = close of the last trading day BEFORE
                           `start`, so the start day's own move is counted.
                           Used wherever the user picks a start date.

    Falls back to the first available close for symbols with no earlier data
    (new listings)."""
    s = closes.dropna()
    start = pd.Timestamp(start).normalize()
    if include_start:
        base, after = s[s.index <= start], s[s.index > start]
    else:
        base, after = s[s.index < start], s[s.index >= start]
    return pd.concat([base.iloc[-1:], after]) if len(base) else after


def period_gain(closes):
    """% change from first to last available close in a series."""
    s = closes.dropna()
    if len(s) < 2 or s.iloc[0] == 0:
        return np.nan
    return (s.iloc[-1] / s.iloc[0] - 1) * 100


RANGE_COLUMNS = ["Name", "Symbol", "Gain (%)", "Base Date", "Base Price", "Last Date",
                 "Last Price", "Range High", "Range Low", "Off High (%)",
                 "Max Drawdown (%)", "Volatility (%)", "Up Days (%)"]


def range_stats(names, start, end):
    """Performance of each symbol from `start` to `end` (inclusive), sorted
    best -> worst, missing symbols last.

    Base price = close of the last trading day BEFORE the start date, so the
    start day's own move is included. E.g. start 30-Oct / end 30-Oct gives the
    30th's one-day move (close 29 -> close 30); start Mon 2-Nov uses Friday
    30-Oct's close. Falls back to the first close on/after `start` for
    symbols listed later.
    Extra columns: range high/low, distance from the high, max drawdown,
    annualised volatility and % of up days."""
    start_ts = pd.Timestamp(start).normalize()
    closes = download_closes(list(names), start_ts - timedelta(days=14), end)
    return stats_from_closes(closes, names, start_ts)


def stats_from_closes(closes, names, start):
    """range_stats() maths on an already-downloaded close table
    (rows = dates, columns = keys of `names`). Shared by Yahoo and NSE tools."""
    start_ts = pd.Timestamp(start).normalize()
    rows = []
    for sym, nm in names.items():
        w = base_window(closes[sym], start_ts, include_start=False)
        if len(w) < 2 or w.index[-1] < start_ts:
            rows.append({"Name": nm, "Symbol": sym})
            continue
        r = w.pct_change().dropna()
        rows.append({
            "Name": nm, "Symbol": sym,
            "Gain (%)": (w.iloc[-1] / w.iloc[0] - 1) * 100,
            "Base Date": w.index[0].date(), "Base Price": w.iloc[0],
            "Last Date": w.index[-1].date(), "Last Price": w.iloc[-1],
            "Range High": w.max(), "Range Low": w.min(),
            "Off High (%)": (w.iloc[-1] / w.max() - 1) * 100,
            "Max Drawdown (%)": (w / w.cummax() - 1).min() * 100,
            "Volatility (%)": r.std() * np.sqrt(252) * 100 if len(r) > 1 else np.nan,
            "Up Days (%)": (r > 0).mean() * 100,
        })
    df = pd.DataFrame(rows).reindex(columns=RANGE_COLUMNS)
    pct = [c for c in df.columns if c.endswith("(%)")]
    df[pct] = df[pct].astype(float).round(2)
    return df.sort_values("Gain (%)", ascending=False,
                          na_position="last").reset_index(drop=True)


# ------------------------------------------------- NSE all-indices (EOD file)
# NSE publishes one CSV per trading day with the close of EVERY NSE index
# (sectoral, thematic, strategy, broad market, bond). Yahoo only carries a
# handful of them, so this tool reads NSE's own file instead.
NSE_INDEX_URLS = [
    "https://nsearchives.nseindia.com/content/indices/ind_close_all_{}.csv",
    "https://archives.nseindia.com/content/indices/ind_close_all_{}.csv",   # mirror
]
NSE_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "text/csv,*/*", "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/all-reports",
}
NSE_MAX_FULL_DAYS = 100      # longer ranges: fetch only the two end points
NSE_TIMEOUT = (5, 12)        # seconds: connect, read (per request)
NSE_BUDGET = 40              # seconds: hard limit for one batch of downloads
_NSE_BLOCKED = {}            # "NSE:archive" / "BSE:live" ... -> time until which we skip it
_NSE_DAY_CACHE = {}          # (exchange, date) -> (fetched_at, DataFrame | None)
_NSE_NUM_COLS = {"Open Index Value": "Open", "High Index Value": "High",
                 "Low Index Value": "Low", "Closing Index Value": "Close",
                 "Change(%)": "Day Chg (%)", "P/E": "P/E", "P/B": "P/B",
                 "Div Yield": "Div Yield"}

NSE_CATEGORIES = ["Sectoral", "Thematic", "Strategy", "Broad market", "Bond / G-Sec", "Volatility"]
_SECTOR_WORDS = re.compile(
    r"\b(auto|bank|financial services|fmcg|it|media|metal|pharma|realty|healthcare|"
    r"consumer durables|oil (?:&|and) gas|chemicals|it & telecom)\b", re.I)
_BOND_WORDS = re.compile(r"g-?sec|sdl|bond|t-?bill|gilt|\bcorporate\b|\baaa\b|1d rate|"
                         r"\bgsec\b|\byr\b|\byear\b|money market|overnight", re.I)
_STRATEGY_WORDS = re.compile(
    r"alpha|beta|quality|value|momentum|low[ -]?vol|equal weight|dividend|growth|"
    r"multi.?factor|\bfactor\b|shariah|top \d+|\btri\b|leverage|inverse|arbitrage|"
    r"\bmq\b|\bqvlv\b|liquid \d+", re.I)
_BROAD_WORDS = re.compile(
    r"^nifty ?(50|next 50|100|200|500|midcap|smallcap|microcap|total market|"
    r"largemidcap|midsmallcap|mid ?small|large ?mid|india 500)|^nifty(100|200|500)?$|"
    r"midcap|smallcap|microcap|total market", re.I)


def nse_category(name):
    n = str(name)
    if "vix" in n.lower():
        return "Volatility"
    if _BOND_WORDS.search(n):
        return "Bond / G-Sec"
    if _STRATEGY_WORDS.search(n):
        return "Strategy"
    if _SECTOR_WORDS.search(n) and not re.search(r"midcap|smallcap|next 50", n, re.I) \
            or re.search(r"midsmall (healthcare|financial services|it & telecom)", n, re.I):
        return "Sectoral"
    if _BROAD_WORDS.search(n):
        return "Broad market"
    return "Thematic"


def _parse_nse_csv(text):
    # index_col=False: a row with a stray extra field must not shift columns
    df = pd.read_csv(io.StringIO(text.lstrip("\ufeff")), index_col=False)
    df.columns = [str(c).strip() for c in df.columns]
    if "Index Name" not in df.columns or "Closing Index Value" not in df.columns:
        raise ValueError("unexpected file format")
    df["Index Name"] = df["Index Name"].astype(str).str.strip()
    df = df[df["Index Name"].ne("") & df["Index Name"].ne("nan")]
    out = pd.DataFrame(index=pd.Index(df["Index Name"], name="Index Name"))
    for src, dst in _NSE_NUM_COLS.items():
        if src in df.columns:
            out[dst] = pd.to_numeric(df[src].astype(str).str.replace(",", "").str.strip(),
                                     errors="coerce").to_numpy()
    return out[~out.index.duplicated()]


def nse_index_day(day, session=None, ex="NSE"):
    """All indices of exchange `ex` for one trading day: DataFrame indexed by
    index name, None when there is no file for that day (holiday, or not
    published yet). Raises ConnectionError if the exchange refused us."""
    import requests
    src = INDEX_SOURCES[ex]
    day = pd.Timestamp(day).normalize()
    now = time.time()
    hit = _NSE_DAY_CACHE.get((ex, day))
    if hit is not None:
        fetched_at, df = hit
        old_day = (pd.Timestamp(_naive_utc_now()).normalize() - day).days > 4
        if df is not None or old_day or now - fetched_at < 600:
            return df
    if day.weekday() >= 5:                       # weekend: no file, no request
        _NSE_DAY_CACHE[(ex, day)] = (now, None)
        return None
    http = session or requests
    last_err = None
    for url in src["urls"]:
        try:
            r = http.get(url.format(day.strftime("%d%m%Y")), headers=src["headers"],
                         timeout=NSE_TIMEOUT)
        except Exception as e:                   # network error: try the mirror
            last_err = e
            continue
        if r.status_code == 404:
            _NSE_DAY_CACHE[(ex, day)] = (now, None)
            return None
        if r.status_code == 200 and src["marker"] in r.text[:300]:
            df = src["parse"](r.text)
            _NSE_DAY_CACHE[(ex, day)] = (now, df)
            return df
        if r.status_code == 200 and src["html_is_holiday"]:
            # BSE answers non-trading days with a placeholder page, not a 404
            _NSE_DAY_CACHE[(ex, day)] = (now, None)
            return None
        last_err = f"HTTP {r.status_code}"
    raise ConnectionError(f"{ex} archives unreachable ({last_err})")


def _fetch_nse_days(days, session, workers=6, budget=NSE_BUDGET, max_fails=3, ex="NSE"):
    """Download many days in parallel with a hard time limit, so a slow or
    hanging exchange server can never keep the page 'Running' for minutes.
    Returns {day: frame}. Raises ConnectionError if it is not answering."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from concurrent.futures import TimeoutError as FuturesTimeout
    frames, fails = {}, 0
    pool = ThreadPoolExecutor(max_workers=workers)
    futures = {pool.submit(nse_index_day, d, session, ex): d for d in days}
    try:
        for fut in as_completed(futures, timeout=budget):
            try:
                df = fut.result()
            except ConnectionError as e:
                fails += 1
                if fails >= max_fails:
                    raise ConnectionError(f"{fails} downloads failed: {e}") from None
                continue
            if df is not None:
                frames[futures[fut]] = df
    except FuturesTimeout:
        raise ConnectionError(f"{ex} did not answer within {budget} seconds") from None
    finally:
        pool.shutdown(wait=False, cancel_futures=True)   # never wait for stragglers
    return frames


def _with_deadline(fn, budget=NSE_BUDGET + 5):
    """Run fn() but give up after `budget` seconds (ConnectionError)."""
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as FuturesTimeout
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(fn).result(timeout=budget)
    except FuturesTimeout:
        raise ConnectionError(f"no answer within {budget} seconds") from None
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _check_archive_block(ex="NSE"):
    wait = _NSE_BLOCKED.get(f"{ex}:archive", 0) - time.time()
    if wait > 0:
        raise ConnectionError(f"{ex} did not answer a moment ago; trying again in {wait:.0f}s")


def _blocked_message(ex, err):
    src = INDEX_SOURCES[ex]
    return (f"Could not download {ex}'s index file from {src['host']} ({err}). "
            f"{ex} sometimes blocks cloud servers for a few minutes; wait a minute and run again.")


def _nse_walk_back(day, limit=12, session=None, ex="NSE"):
    """(date, frame) of the latest trading day on or before `day`."""
    day = pd.Timestamp(day).normalize()
    for back in range(limit):
        d = day - timedelta(days=back)
        df = nse_index_day(d, session, ex)
        if df is not None:
            return d, df
    return None, None


# ------------------------------------------------------ today's live values
NSE_LIVE_URL = "https://www.nseindia.com/api/allIndices"
# Yahoo symbols for NSE indices, used only if NSE's live feed is blocked.
YAHOO_FOR_NSE = {
    "Nifty 50": "^NSEI", "Nifty Bank": "^NSEBANK", "Nifty IT": "^CNXIT",
    "Nifty Auto": "^CNXAUTO", "Nifty Pharma": "^CNXPHARMA", "Nifty FMCG": "^CNXFMCG",
    "Nifty Metal": "^CNXMETAL", "Nifty Realty": "^CNXREALTY", "Nifty Media": "^CNXMEDIA",
    "Nifty Energy": "^CNXENERGY", "Nifty PSU Bank": "^CNXPSUBANK", "Nifty Infrastructure": "^CNXINFRA",
    "Nifty Commodities": "^CNXCMDT", "Nifty PSE": "^CNXPSE", "Nifty MNC": "^CNXMNC",
    "Nifty India Consumption": "^CNXCONSUM", "Nifty Services Sector": "^CNXSERVICE",
    "Nifty Private Bank": "NIFTY_PVT_BANK.NS", "Nifty Financial Services": "NIFTY_FIN_SERVICE.NS",
    "Nifty Midcap 100": "NIFTY_MIDCAP_100.NS", "Nifty Consumer Durables": "NIFTY_CONSR_DURBL.NS",
}


def _today_ist():
    return datetime.now(timezone(timedelta(hours=5, minutes=30))).date()


def _norm_index_name(n):
    """'NIFTY FINANCIAL SERVICES 25/50' and 'Nifty Financial Services 25/50' -> same key."""
    return re.sub(r"[^a-z0-9]", "", str(n).lower())


def _num(v):
    try:
        f = float(str(v).replace(",", "").strip())
        return f if f > 0 else np.nan
    except (TypeError, ValueError):
        return np.nan


def _browser_session():
    """A session that looks like Chrome at the TLS level (curl_cffi, which
    yfinance already installs). NSE/BSE's bot protection rejects plain
    Python requests by that fingerprint. Falls back to requests."""
    try:
        from curl_cffi import requests as creq
        return creq.Session(impersonate="chrome"), "curl_cffi"
    except Exception:
        import requests
        return requests.Session(), "requests"


def nse_live_snapshot(today=None):
    """Today's live/latest value of every NSE index.

    Returns (frame, info). `frame` is indexed by normalised index name with
    Close (= last traded value), P/E, P/B, Div Yield; None if nothing usable.
    `info` = {"source": "NSE live"|"Yahoo"|None, "as_of": str, "count": n, "error": str}.
    1) NSE's own live feed (all indices; often blocked from cloud servers).
    2) Yahoo for the ~20 indices it carries.
    Values are used only if they are stamped with today's date."""
    import requests
    today = today or _today_ist()
    info = {"source": None, "as_of": "", "count": 0, "error": ""}
    # 1) NSE live feed: needs cookies from the home page first
    try:
        if time.time() < _NSE_BLOCKED.get("NSE:live", 0):
            raise ConnectionError("skipped: it did not answer in the last 10 minutes")
        sess, _kind = _browser_session()
        with sess:
            sess.headers.update({"Accept": "application/json, text/plain, */*",
                                 "Accept-Language": "en-US,en;q=0.9",
                                 "Referer": "https://www.nseindia.com/market-data/live-market-indices"})
            sess.get("https://www.nseindia.com", timeout=8)
            r = sess.get(NSE_LIVE_URL, timeout=10)
        if r.status_code != 200:
            _NSE_BLOCKED["NSE:live"] = time.time() + 600
            raise ConnectionError(f"HTTP {r.status_code}")
        payload = r.json()
        stamp = pd.to_datetime(payload.get("timestamp", ""), format="%d-%b-%Y %H:%M", errors="coerce")
        if pd.isna(stamp) or stamp.date() != today:
            info["error"] = f"NSE live feed is not for today (stamped {payload.get('timestamp')})"
        else:
            rows = {}
            for row in payload.get("data", []):
                close = _num(row.get("last"))
                if np.isnan(close):
                    continue
                rows[_norm_index_name(row.get("index") or row.get("indexSymbol"))] = {
                    "Close": close, "P/E": _num(row.get("pe")), "P/B": _num(row.get("pb")),
                    "Div Yield": _num(row.get("dy"))}
            if rows:
                info.update(source="NSE live", as_of=f"{stamp:%H:%M} IST", count=len(rows))
                return pd.DataFrame.from_dict(rows, orient="index"), info
            info["error"] = "NSE live feed returned no index values"
    except Exception as e:                       # blocked / timeout / not JSON
        if not str(e).startswith("skipped"):
            _NSE_BLOCKED["NSE:live"] = time.time() + 600
        info["error"] = f"NSE live feed unavailable ({str(e)[:80]})"
    # 2) Yahoo fallback for the indices it carries
    return _yahoo_live(YAHOO_FOR_NSE, today, info)


def _yahoo_live(mapping, today, info):
    """Today's Yahoo value for {index name or alias: yahoo symbol}."""
    try:
        syms = sorted(set(mapping.values()))
        closes = download_closes(syms, pd.Timestamp(today) - timedelta(days=6), today,
                                 retry_wait=1.0)
        today_rows = closes[closes.index.normalize() == pd.Timestamp(today)]
        if not today_rows.empty:
            last = today_rows.iloc[-1]
            rows = {_norm_index_name(nm): {"Close": last[sym]}
                    for nm, sym in mapping.items() if pd.notna(last[sym])}
            if rows:
                info.update(source="Yahoo", as_of="delayed ~15 min",
                            count=len({sym for sym in mapping.values() if pd.notna(last[sym])}))
                return pd.DataFrame.from_dict(rows, orient="index"), info
        info["error"] = (info["error"] + "; " if info["error"] else "") + "Yahoo has no values for today yet"
    except Exception as e:
        info["error"] = (info["error"] + "; " if info["error"] else "") + f"Yahoo fallback failed ({str(e)[:60]})"
    return None, info


def _add_live_today(frames, columns, end_day, ex="NSE"):
    """If `end_day` is today (a weekday) and NSE's file for today is not out yet,
    add a frame of today's live values for the matching index names.
    Returns info dict (empty when live data was not needed)."""
    today = pd.Timestamp(_today_ist())
    if pd.Timestamp(end_day).normalize() < today or today.weekday() >= 5 or today in frames:
        return {}
    live, info = INDEX_SOURCES[ex]["live"](today.date())
    if live is None:
        return info
    key_of = {_norm_index_name(c): c for c in columns}
    live = live[live.index.isin(key_of)].rename(index=key_of)
    # Sanity guard: drop values more than 20% away from the last published
    # close (wrong/stale symbol); real one-day index moves are far smaller.
    prev_day = max((d for d in frames if d < today), default=None)
    if prev_day is not None and not live.empty:
        prev = frames[prev_day]["Close"].reindex(live.index)
        ratio = live["Close"] / prev
        matched = len(live)
        live = live[ratio.isna() | ratio.between(0.8, 1.2)]
        if matched and live.empty:
            info.update(source=None, error=f"{info['source']} values looked wrong "
                        "(over 20% away from the last close), so they were ignored")
            return info
    if live.empty:
        info["error"] = "live index names did not match NSE's file"
        info["source"] = None
        return info
    info["count"], info["total"] = len(live), len(columns)
    info["names"] = sorted(live.index)
    frames[today] = live
    return info


def _fundamentals(frames, names):
    """Latest P/E, P/B, Div Yield per index (live values when present,
    otherwise the latest end-of-day file that has them)."""
    out = pd.DataFrame(index=names, columns=["P/E", "P/B", "Div Yield"], dtype=float)
    for d in sorted(frames):                       # later days overwrite earlier
        f = frames[d]
        for c in out.columns:
            if c in f:
                vals = f[c].reindex(names)
                out[c] = vals.where(vals.notna(), out[c])
    return out


def nse_index_stats(start, end, max_full_days=NSE_MAX_FULL_DAYS, workers=6, ex="NSE"):
    """range_stats() for EVERY NSE index, from NSE's daily all-indices file.

    Same base rule as the other tools: base = close of the last trading day
    before `start`. Ranges longer than `max_full_days` weekdays fetch only the
    base and end days (gain is exact; range high/low, drawdown and volatility
    are left blank). Adds Category and the latest P/E, P/B and dividend yield."""
    import requests
    start_ts, end_ts = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    session = requests.Session()
    days = [d for d in pd.bdate_range(start_ts, end_ts)]
    quick = len(days) > max_full_days

    def download():
        frames = {}
        base_day, base_df = _nse_walk_back(start_ts - timedelta(days=1), session=session, ex=ex)
        if base_df is not None:
            frames[base_day] = base_df
        if quick:
            d, df = _nse_walk_back(end_ts, session=session, ex=ex)
            if df is not None and d >= start_ts:
                frames[d] = df
        else:
            frames.update(_fetch_nse_days(days, session, workers, ex=ex))
        return frames

    try:
        _check_archive_block(ex)
        frames = _with_deadline(download)
    except ConnectionError as e:
        _NSE_BLOCKED[f"{ex}:archive"] = time.time() + 120
        raise DataUnavailable(_blocked_message(ex, e)) from None
    finally:
        session.close()

    if not frames:
        return (pd.DataFrame(columns=RANGE_COLUMNS + ["Category", "P/E", "P/B", "Div Yield"]),
                {"quick": quick, "live": {},
                 "note": (f"{ex} has no index files for this range."
                          + (" BSE keeps only about the last 18 months of index files."
                             if ex == "BSE" else ""))})
    all_names = sorted(set().union(*[f.index for f in frames.values()]))
    note = ""
    if not any(d < start_ts for d in frames):       # no base close found
        note = (f"{ex} has no index file for the trading day before "
                f"{start_ts:%d-%b-%Y}, so gains could not be measured from your start date."
                + (" BSE keeps only about the last 18 months of index files." if ex == "BSE" else ""))
    live_info = _add_live_today(frames, all_names, end_ts, ex)
    closes = pd.DataFrame({d: f["Close"] for d, f in sorted(frames.items())}).T
    closes.index = pd.DatetimeIndex(closes.index)
    names = {c: c for c in closes.columns}
    out = stats_from_closes(closes, names, start_ts)
    if quick:
        out[["Range High", "Range Low", "Off High (%)", "Max Drawdown (%)",
             "Volatility (%)", "Up Days (%)"]] = np.nan
    fund = _fundamentals(frames, list(out["Name"]))
    out["Category"] = [INDEX_SOURCES[ex]["category"](n) for n in out["Name"]]
    for c in ("P/E", "P/B", "Div Yield"):
        out[c] = out["Name"].map(fund[c])
    out = out.drop(columns=["Symbol"]).rename(columns={"Base Price": "Base Value",
                                                       "Last Price": "Last Value"})
    out = out[["Name", "Category"] + [c for c in out.columns if c not in ("Name", "Category")]]
    return out, {"quick": quick, "live": live_info, "note": note}


def nse_index_returns(reference_date=None, durations=(30, 60, 90), workers=6, ex="NSE"):
    """Unranked 30/60/90-day returns for EVERY NSE index from NSE's daily file
    (rank with rank_returns() after filtering). Downloads each weekday in the
    90-day window (cached per day) so 'Off 90D High' is exact.
    Returns (DataFrame, latest_trading_day)."""
    import requests
    durations = list(durations)
    ref = pd.Timestamp(reference_date or _naive_utc_now()).normalize()
    days = list(pd.bdate_range(ref - timedelta(days=max(durations) + 14), ref))
    session = requests.Session()
    try:
        _check_archive_block(ex)
        frames = _with_deadline(lambda: _fetch_nse_days(days, session, workers, ex=ex))
    except ConnectionError as e:
        _NSE_BLOCKED[f"{ex}:archive"] = time.time() + 120
        raise DataUnavailable(_blocked_message(ex, e)) from None
    finally:
        session.close()
    if not frames:
        raise DataUnavailable(f"{ex} returned no index files for the last "
                              f"{max(durations)} days; try again later.")
    all_names = sorted(set().union(*[f.index for f in frames.values()]))
    latest_day = max(frames)                       # last PUBLISHED close (before live)
    live_info = _add_live_today(frames, all_names, ref, ex)
    closes = pd.DataFrame({d: f["Close"] for d, f in sorted(frames.items())}).T
    closes.index = pd.DatetimeIndex(closes.index)
    df = window_returns(closes, ref, durations)
    df = df.rename(columns={"Last Price": "Last Value"})
    df.insert(0, "Name", df.index)
    df.insert(1, "Category", [INDEX_SOURCES[ex]["category"](n) for n in df.index])
    fund = _fundamentals(frames, list(df["Name"]))
    for c in ("P/E", "P/B", "Div Yield"):
        df[c] = df["Name"].map(fund[c])
    df.index.name = "Index"
    return df, {"last_day": latest_day.date(), "live": live_info}


# ------------------------------------------------ BSE all-indices (EOD file)
# BSE's JSON API has blocked scripts since Sept 2026, but its daily
# "Index Bhavcopy" CSV on www.bseindia.com is a plain static file with every
# BSE index (open/high/low/close). BSE keeps roughly the last 18 months.
BSE_INDEX_URLS = ["https://www.bseindia.com/bsedata/Index_Bhavcopy/INDEXSummary_{}.csv"]
BSE_HEADERS = {**NSE_HEADERS, "Referer": "https://www.bseindia.com/",
               "Origin": "https://www.bseindia.com"}
BSE_CATEGORIES = ["Sectoral", "Thematic", "Strategy", "Broad market", "Other"]
_BSE_SECTOR = re.compile(
    r"\b(auto|bankex|banks?|capital goods|consumer discretionary|consumer durables|energy|"
    r"fmcg|finance|financial services|healthcare|it|industrials|metal|oil (?:&|and) gas|"
    r"power|private banks|realty|teck|telecom(?:munication)?|utilities|commodities|"
    r"basic materials|services|fast moving consumer goods|information technology)\b", re.I)
_BSE_STRATEGY = re.compile(
    r"momentum|quality|value|low vol|volatility|dividend|esg|alpha|equal weight|shariah|"
    r"enhanced|factor|leverage|inverse|\btri\b", re.I)
_BSE_BROAD = re.compile(
    r"sensex|\b(100|150|200|250|400|500|1000)\b|allcap|largecap|large ?cap|midcap|mid ?cap|"
    r"smallcap|small ?cap|microcap|large ?mid|mid ?small|total market", re.I)
_BSE_OTHER = re.compile(r"dollex|bond|gilt|g-?sec|t-?bill|sovereign|liquid rate|\bsdl\b", re.I)


def bse_category(name):
    n = re.sub(r"^(s&p\s+)?bse\s*", "", str(name).strip(), flags=re.I)
    if _BSE_OTHER.search(n):
        return "Other"
    if _BSE_STRATEGY.search(n):
        return "Strategy"
    if _BSE_SECTOR.search(n) and not re.search(r"\b(100|150|200|250|400|500)\b", n):
        return "Sectoral"
    if _BSE_BROAD.search(n):
        return "Broad market"
    return "Thematic"


def _parse_bse_csv(text):
    df = pd.read_csv(io.StringIO(text.lstrip("\ufeff")), index_col=False)
    df.columns = [str(c).strip() for c in df.columns]
    if "ClosePrice" not in df.columns:
        raise ValueError("unexpected BSE file format")
    name_col = "IndexName" if "IndexName" in df.columns else "IndexID"
    names = df[name_col].astype(str).str.strip()
    if "IndexID" in df.columns:                    # fall back to the ID if a name is blank
        names = names.where(names.ne("") & names.ne("nan"), df["IndexID"].astype(str).str.strip())
    out = pd.DataFrame(index=pd.Index(names, name="Index Name"))
    for src, dst in {"OpenPrice": "Open", "HighPrice": "High", "LowPrice": "Low",
                     "ClosePrice": "Close", "PE": "P/E", "PB": "P/B", "DivYield": "Div Yield"}.items():
        if src in df.columns:
            vals = pd.to_numeric(df[src].astype(str).str.replace(",", "").str.strip(),
                                 errors="coerce").to_numpy()
            out[dst] = np.where(vals > 0, vals, np.nan)
    out = out[(out.index.str.len() > 0) & (out.index != "nan")]
    return out[~out.index.duplicated()]


# Yahoo tickers for BSE indices, with the names BSE's file may use for them.
# Some Yahoo BSE tickers are stale; only values stamped with TODAY's date are
# used, and values >20% from the last close are rejected, so dead ones are harmless.
_YAHOO_BSE = {
    "^BSESN": ["BSE SENSEX", "SENSEX", "S&P BSE SENSEX"],
    "BSE-BANK.BO": ["BSE BANKEX", "BANKEX", "S&P BSE BANKEX"],
    "BSE-AUTO.BO": ["BSE Auto"],
    "BSE-IT.BO": ["BSE IT", "BSE Information Technology"],
    "BSE-FMCG.BO": ["BSE FMCG", "BSE Fast Moving Consumer Goods"],
    "BSE-HC.BO": ["BSE Healthcare"],
    "BSE-METAL.BO": ["BSE Metal"],
    "BSE-POWER.BO": ["BSE Power"],
    "BSE-CG.BO": ["BSE Capital Goods"],
    "BSE-CD.BO": ["BSE Consumer Durables"],
    "BSE-OILGAS.BO": ["BSE Oil & Gas"],
    "BSE-REALTY.BO": ["BSE Realty"],
    "BSE-TECK.BO": ["BSE Teck", "BSE TECk"],
    "BSE-PSU.BO": ["BSE PSU"],
    "BSE-100.BO": ["BSE 100"],
    "BSE-200.BO": ["BSE 200"],
    "BSE-500.BO": ["BSE 500"],
    "BSE-MIDCAP.BO": ["BSE MidCap"],
    "BSE-SMLCAP.BO": ["BSE SmallCap"],
}
YAHOO_FOR_BSE = {alias: sym for sym, names in _YAHOO_BSE.items() for alias in names}
for _alias in list(YAHOO_FOR_BSE):            # also match the 'S&P BSE ...' spelling
    YAHOO_FOR_BSE.setdefault("S&P " + _alias, YAHOO_FOR_BSE[_alias])


def bse_live_snapshot(today=None):
    """BSE's live API blocks scripts, so today's BSE values come from Yahoo,
    for the BSE indices Yahoo still updates."""
    today = today or _today_ist()
    info = {"source": None, "as_of": "", "count": 0,
            "error": "BSE's live feed blocks automated requests"}
    return _yahoo_live(YAHOO_FOR_BSE, today, info)


def bse_index_stats(start, end, **kw):
    return nse_index_stats(start, end, ex="BSE", **kw)


def bse_index_returns(reference_date=None, **kw):
    return nse_index_returns(reference_date, ex="BSE", **kw)


INDEX_SOURCES = {
    "NSE": {"urls": NSE_INDEX_URLS, "headers": NSE_HEADERS, "marker": "Index Name",
            "parse": _parse_nse_csv, "category": nse_category, "live": nse_live_snapshot,
            "html_is_holiday": False, "host": "nsearchives.nseindia.com",
            "categories": NSE_CATEGORIES},
    "BSE": {"urls": BSE_INDEX_URLS, "headers": BSE_HEADERS, "marker": "ClosePrice",
            "parse": _parse_bse_csv, "category": bse_category, "live": bse_live_snapshot,
            "html_is_holiday": True, "host": "www.bseindia.com",
            "categories": BSE_CATEGORIES},
}


def range_gains(names, start, end):
    """[Name, Gain (%)] only (used by the Flask routes)."""
    return range_stats(names, start, end)[["Name", "Gain (%)"]]


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
    """Kept for backward compatibility. end_date is EXCLUSIVE (yfinance style).
    Same base rule as range_stats (last close before start_date)."""
    end_incl = pd.Timestamp(end_date) - timedelta(days=1)
    data = download_ohlc(symbol, pd.Timestamp(start_date) - timedelta(days=14), end_incl)
    return np.nan if data.empty else period_gain(base_window(data["Close"], start_date, include_start=False))


# ------------------------------------------------------- 30/60/90-day ranking
def compute_index_returns(names, durations=(30, 60, 90), reference_date=None):
    """Returns over each look-back window, ranked (rank 1 = best return).
    Rows sorted by Sum of Ranks ascending (strongest first); symbols with
    missing data are appended at the bottom."""
    durations = list(durations)
    ref = pd.Timestamp(reference_date or _naive_utc_now()).normalize()
    # 14 extra days so the base close exists even after long holidays
    closes = download_closes(list(names), ref - timedelta(days=max(durations) + 14), ref)

    df = window_returns(closes, ref, durations).drop(columns=["Last Date"])
    df.insert(0, "Name", [names[s] for s in df.index])
    df.index.name = "Symbol"
    return rank_returns(df, durations)


def window_returns(closes, ref, durations=(30, 60, 90)):
    """Unranked 30/60/90-day returns for every column of a close table.
    Base for each window = close on (ref - d days), or the last trading day
    before it. Columns: d D %, Last Price, Off <max>D High %."""
    ref = pd.Timestamp(ref).normalize()
    hi_col = f"Off {max(durations)}D High %"
    rows = {}
    for col in closes.columns:
        s = closes[col].dropna()
        s = s[s.index < ref + timedelta(days=1)]
        row = {f"{d}D %": period_gain(base_window(s, ref - timedelta(days=d)))
               for d in durations}
        win = base_window(s, ref - timedelta(days=max(durations)))
        row["Last Price"] = win.iloc[-1] if len(win) else np.nan
        row["Last Date"] = win.index[-1].date() if len(win) else None
        row[hi_col] = (win.iloc[-1] / win.max() - 1) * 100 if len(win) else np.nan
        rows[col] = row
    return pd.DataFrame.from_dict(rows, orient="index")


def rank_returns(df, durations=(30, 60, 90)):
    """Rank each window (1 = best), add Sum of Ranks, sort strongest first;
    rows with a missing window go to the bottom. Ranks are relative to the
    rows passed in, so filter BEFORE ranking."""
    durations = list(durations)
    hi_col = f"Off {max(durations)}D High %"
    ret_cols = [f"{d}D %" for d in durations]
    df = df.drop(columns=[c for c in df.columns if c.startswith("Rank") or c == "Sum of Ranks"])

    ok = df.dropna(subset=ret_cols).copy()          # .copy(): no SettingWithCopy
    bad = df[df[ret_cols].isna().any(axis=1)]
    for c in ret_cols:
        ok[f"Rank {c.replace(' %', '')}"] = ok[c].rank(ascending=False, method="min")
    rank_cols = [c for c in ok.columns if c.startswith("Rank")]
    ok["Sum of Ranks"] = ok[rank_cols].sum(axis=1)
    ok = ok.sort_values("Sum of Ranks", kind="stable")

    out = pd.concat([ok, bad]) if not bad.empty else ok
    out[ret_cols + [hi_col]] = out[ret_cols + [hi_col]].round(2)
    order = (["Name", "Category"] + ret_cols + [c for c in out.columns if c.startswith("Rank")]
             + ["Sum of Ranks", "Last Price", "Last Value", hi_col])
    extra = [c for c in out.columns if c not in order]
    out = out[[c for c in order if c in out.columns] + extra]
    return out


def plot_index_returns(df, which="strongest", n=3, title_prefix=""):
    """Grouped bar chart of the n strongest (lowest Sum of Ranks) or weakest
    indices. Returns a Figure, or None if no index has complete data."""
    ranked = df.dropna(subset=["Sum of Ranks"]) if "Sum of Ranks" in df else df.iloc[0:0]
    if ranked.empty:
        return None
    pick = ranked.head(n) if which == "strongest" else ranked.tail(n).iloc[::-1]
    ret_cols = [c for c in df.columns if c.endswith("D %") and not c.startswith("Off")]

    fig, ax = plt.subplots(figsize=(max(14, 2.4 * len(pick)), 6.2))
    width = 0.8 / len(ret_cols)
    x = np.arange(len(pick))
    for i, c in enumerate(ret_cols):
        vals = pick[c].to_numpy(float)
        ax.bar(x + i * width, vals, width, label=f"{c[:-3]} days")
        for xi, v in zip(x, vals):
            ax.text(xi + i * width, v, f"{v:.1f}%" if len(pick) > 3 else f"{v:.2f}%",
                    ha="center", va="bottom" if v >= 0 else "top",
                    fontsize=11 if len(pick) <= 3 else 8)
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
    fig, ax = plt.subplots(figsize=(15, max(4, 0.45 * len(heat) + 2)))
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
def plot_gain_bars(df, title, value_col="Gain (%)"):
    """Bar chart for a [Name, Gain (%)] frame sorted best -> worst. Uses
    horizontal bars when there are many items so names stay readable.
    Returns None if nothing to plot."""
    valid = df.dropna(subset=[value_col])
    if valid.empty:
        return None
    names, gains = valid["Name"].tolist(), valid[value_col].to_numpy(float)
    colors = ["#2e7d32" if g > 0 else "#c62828" for g in gains]
    span = max(float(np.abs(gains).max()), 1e-9)

    if len(valid) > 60:
        fig, ax = plt.subplots(figsize=(14, 0.3 * len(valid) + 2))
        y = np.arange(len(valid))
        ax.barh(y, gains, color=colors)
        ax.set_yticks(y)
        ax.set_yticklabels(names, fontsize=9)
        ax.invert_yaxis()                                  # best on top
        for yi, g in zip(y, gains):
            ax.text(g + (0.01 if g >= 0 else -0.01) * span, yi, f"{g:.2f}%",
                    va="center", ha="left" if g >= 0 else "right", fontsize=8)
        ax.axvline(0, color="grey", linewidth=0.8)
        ax.set_xlabel(value_col)
        ax.grid(axis="x", linestyle="--", alpha=0.5)
        ax.set_xlim(min(0, gains.min()) - 0.15 * span, max(0, gains.max()) + 0.15 * span)
    else:
        many = len(valid) > 15
        # Wide, short shape so the whole chart fits on screen at full width.
        fig, ax = plt.subplots(figsize=(max(16, 0.34 * len(valid)), 7 if many else 6.2))
        bars = ax.bar(names, gains, color=colors)
        for b, g in zip(bars, gains):
            ax.text(b.get_x() + b.get_width() / 2, g, f" {g:.2f}% " if many else f"{g:.2f}%",
                    ha="center", va="bottom" if g >= 0 else "top",
                    fontsize=8 if many else 11, rotation=90 if many else 0)
        ax.axhline(0, color="grey", linewidth=0.8)
        ax.set_ylabel(value_col)
        ax.margins(y=0.18 if many else 0.1)            # room for the value labels
        if many:
            plt.setp(ax.get_xticklabels(), rotation=90, ha="center", fontsize=9)
        else:
            plt.setp(ax.get_xticklabels(), rotation=30, ha="right", fontsize=11)
        ax.grid(axis="y", linestyle="--", alpha=0.6)
    ax.set_title(title)
    fig.tight_layout()
    return fig


def plot_gain_grid(df, title, ncols=None):
    """Heatmap grid of [Name, Gain (%)] sorted best -> worst (row 1 = best).
    Grid height adapts to the number of stocks (was hard-coded 10x5)."""
    valid = df.dropna(subset=["Gain (%)"]).reset_index(drop=True)
    if valid.empty:
        return None
    ncols = ncols or (10 if len(valid) > 30 else 5)   # wide grid fits the screen
    nrows = math.ceil(len(valid) / ncols)
    pad = nrows * ncols - len(valid)
    gains = np.append(valid["Gain (%)"].to_numpy(float), [np.nan] * pad).reshape(nrows, ncols)
    import textwrap
    labels = [f"{textwrap.fill(str(n), 16, break_long_words=False)}\n{g:.1f}%"
              for n, g in zip(valid["Name"], valid["Gain (%)"])]
    annot = np.array(labels + [""] * pad, dtype=object).reshape(nrows, ncols)

    cmap = LinearSegmentedColormap.from_list("rg", ["red", "white", "green"], N=256)
    fig, ax = plt.subplots(figsize=(18 if ncols > 5 else 16, 1.25 * nrows + 1.6))
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
                      figsize=(16, 7), returnfig=True, tight_layout=True)
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


def _running_under_streamlit():
    try:
        from streamlit.runtime import exists
        return exists()
    except Exception:
        return False


if __name__ == '__main__':
    if _running_under_streamlit():
        # This file was started by Streamlit (e.g. uploaded as streamlit_app.py).
        # Starting Flask here would block forever and leave a blank page.
        import streamlit as st
        st.error("This is the calculation module (stock-chart-app-main/app.py), not the "
                 "dashboard. Upload the dashboard file as streamlit_app.py in the repo root "
                 "and put this file back in stock-chart-app-main/.")
    else:
        app.run(host='127.0.0.1', port=5000, debug=False, threaded=True)
