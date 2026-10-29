# Stock Analysis Dashboard

Six market-analysis views built on Yahoo Finance data, served with Streamlit.

| Page | What it does |
|---|---|
| Nifty 50 Heatmap | 10x5 heatmap of Nifty 50 constituents' gains over any date range, sorted best→worst |
| NSE Indices | 30/60/90-day performance of 22 NSE sectoral indices, ranked, weakest three charted |
| World Indices | Same 30/60/90-day ranking across 20 global indices |
| Seasonality | Monthly return heatmap (year x month) for any ticker with up to 50 years of history |
| Custom Date Range | Bar chart comparing 20 global indices over a user-chosen window |
| Candlestick Chart | OHLC candlestick chart for any Yahoo ticker |

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
    templates/              # original Flask templates (kept for reference)
```

`streamlit_app.py` imports the analysis functions from `stock-chart-app-main/app.py`
so the strategy logic lives in exactly one place. The Flask app can still be run
standalone (`python app.py` → port 5000) if you want the original UI.

## Notes

- `BSE-SMLCAP.BO` was delisted on Yahoo; the BSE SmallCap row shows N/A.
- Charts are rendered server-side with matplotlib.
- Data: Yahoo Finance, delayed. Not investment advice.
