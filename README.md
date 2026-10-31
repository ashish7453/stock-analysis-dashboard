# Stock Analysis Dashboard

Six market-analysis views built on Yahoo Finance data, served with Streamlit.

| Page | What it does |
|---|---|
| Nifty 50 Performance | All 50 stocks over any date range — heatmap or ranked bars |
| NSE Sector Indices | 22 NSE indices ranked on 30/60/90-day returns; strongest or weakest N charted |
| Stock List Ranking | Upload any CSV with a `Symbol` column (NSE/BSE/US) and rank it on 30/60/90-day returns |
| World Indices | 20 global indices ranked on 30/60/90-day returns |
| Global Indices (Date Range) | 20 global indices over a date range you choose |
| Country ETFs (USA) | 44 US-listed single-country ETFs ranked on 30/60/90-day returns |
| Commodities | Gold, silver, platinum, palladium, copper, aluminium, WTI, Brent, natural gas over a date range |
| Currencies vs USD | 16 currencies' moves against the US dollar over a date range |
| Seasonality | Monthly return heatmap (year x month) plus win rate and averages per month |
| Candlestick Chart | OHLC candlestick chart with volume for any Yahoo ticker |

Every date-range tool shows advancers/decliners, median, best/worst, and per-symbol
base/last price, range high/low, distance from high, max drawdown, annualised
volatility and % up days. Date-range tools have a **Live auto-refresh** toggle
(every 60 s when the end date is today). All result tables download as CSV or Excel.

## Deploy

This repo is a Streamlit Community Cloud app. Entry point: `streamlit_app.py`.

1. Fork/clone, then on [share.streamlit.io](https://share.streamlit.io): New app → pick this repo → main file `streamlit_app.py` → Deploy.
2. No secrets or API keys required — `yfinance` reads public Yahoo data.

## Local run

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Then open http://localhost:8501.

## Project layout

```
streamlit_app.py            # Streamlit UI (the deployed app)
requirements.txt
stock-chart-app-main/
    app.py                  # original Flask app + all analysis functions
    ind_nifty50list.csv     # Nifty 50 constituent list
```

Note: the Flask templates (`templates/*.html`) are not in this repo, so the Flask
UI needs them restored before `python app.py` works. The Streamlit app does not use them.

`streamlit_app.py` imports the analysis functions from `stock-chart-app-main/app.py`
so the strategy logic lives in exactly one place. 

## Notes

- `BSE-SMLCAP.BO` was delisted on Yahoo; the BSE SmallCap row shows N/A.
- Charts are rendered server-side with matplotlib.
- Downloads are batched (one Yahoo request per page) and cached for 15 minutes.
- Seasonality skips the current, unfinished month unless you tick "Include current month".
- Data: Yahoo Finance, delayed. Not investment advice.
