"""
Interactive Plotly charts for the Streamlit dashboard.

Every function returns a plotly Figure (or None when there is nothing to plot).
Charts use fixed pixel heights that fit a laptop screen, stretch to the full
width, and inherit Streamlit's light/dark theme when shown with
st.plotly_chart(theme="streamlit"). The Flask UI keeps the matplotlib charts
in app.py.
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Finviz-style diverging scale: red -> slate -> green
GAIN_SCALE = [[0.0, "#f63538"], [0.3, "#bf4045"], [0.45, "#8b444e"], [0.5, "#414554"],
              [0.55, "#35764e"], [0.7, "#2f9e4f"], [1.0, "#30cc5a"]]
UP, DOWN = "#22a35a", "#e5484d"
WINDOW_COLORS = ["#3b82f6", "#f59e0b", "#10b981", "#a855f7"]
FONT = "Source Sans, Source Sans Pro, Segoe UI, Roboto, sans-serif"


def _limit(values, pct=90, floor=0.5):
    """Colour-scale limit: ignore a few outliers so normal moves still show colour."""
    v = np.abs(np.asarray(values, dtype=float))
    v = v[np.isfinite(v)]
    return max(float(np.percentile(v, pct)) if len(v) else floor, floor)


def _hover_details(row):
    parts = []
    for base, last in (("Base Price", "Last Price"), ("Base Value", "Last Value")):
        if base in row and pd.notna(row.get(base)) and pd.notna(row.get(last)):
            parts.append(f"{row['Base Date']}: {row[base]:,.2f}<br>{row['Last Date']}: {row[last]:,.2f}")
    for col, label in (("Max Drawdown (%)", "Max drawdown"), ("Off High (%)", "Off range high"),
                       ("Volatility (%)", "Volatility")):
        if col in row and pd.notna(row.get(col)):
            parts.append(f"{label}: {row[col]:.2f}%")
    return "<br>".join(parts)


def _base_layout(fig, title, height):
    fig.update_layout(
        title=dict(text=title, x=0.01, xanchor="left", font=dict(size=18)),
        height=height, margin=dict(l=10, r=10, t=56, b=10), font=dict(family=FONT),
        hoverlabel=dict(font=dict(family=FONT, size=13)))
    return fig


# --------------------------------------------------------------- market map
def _wrap(text, width=14):
    """Break a long tile label into lines of about `width` characters so it
    fits narrow tiles (e.g. 'India Manufacturing' -> 'India<br>Manufacturing')."""
    if len(text) <= width:
        return text
    lines, cur = [], ""
    for w in text.split():
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur); cur = w
        else:
            cur = f"{cur} {w}".strip()
    lines.append(cur)
    return "<br>".join(lines)


def market_map(df, title, group_col=None, value_col="Gain (%)", height=620):
    """Finviz-style treemap: one tile per row, coloured red -> green by gain,
    optionally grouped (e.g. by industry or category). Group tiles show the
    average gain of their members."""
    d = df.dropna(subset=[value_col]).reset_index(drop=True)
    if d.empty:
        return None
    lim = _limit(d[value_col])
    ids, labels, parents, values, colors, texts, hovers = [], [], [], [], [], [], []
    grouped = bool(group_col and group_col in d and d[group_col].notna().any())
    if grouped:
        d[group_col] = d[group_col].fillna("Other")
        for g, members in d.groupby(group_col, sort=False):
            avg = members[value_col].mean()
            ids.append(f"g::{g}"); labels.append(str(g)); parents.append("")
            values.append(len(members)); colors.append(float(np.clip(avg, -lim, lim)))
            texts.append(f"avg {avg:+.2f}%")
            hovers.append(f"{len(members)} members · average {avg:+.2f}%<br>"
                          f"best {members[value_col].max():+.2f}% · worst {members[value_col].min():+.2f}%")
    for _, r in d.iterrows():
        ids.append(f"l::{r['Name']}"); labels.append(_wrap(str(r["Name"])))
        parents.append(f"g::{r[group_col]}" if grouped else "")
        values.append(1); colors.append(float(np.clip(r[value_col], -lim, lim)))
        texts.append(f"{r[value_col]:+.2f}%")
        hovers.append(f"Gain {r[value_col]:+.2f}%<br>{_hover_details(r)}")

    fig = go.Figure(go.Treemap(
        ids=ids, labels=labels, parents=parents, values=values, branchvalues="total",
        text=texts, customdata=hovers,
        texttemplate="<b>%{label}</b><br>%{text}",
        hovertemplate="<b>%{label}</b><br>%{customdata}<extra></extra>",
        marker=dict(colors=colors, colorscale=GAIN_SCALE, cmin=-lim, cmid=0, cmax=lim,
                    line=dict(width=1.5, color="rgba(20,20,25,0.85)"),
                    colorbar=dict(title="Gain %", ticksuffix="%", thickness=12, len=0.75)),
        textfont=dict(color="white", family=FONT), insidetextfont=dict(color="white"),
        tiling=dict(pad=2), pathbar=dict(visible=grouped), maxdepth=3,
        sort=False,
    ))
    # No "hide" mode: Plotly then shrinks a label to fit its tile instead of
    # leaving the tile blank. Long names are wrapped so they stay readable.
    return _base_layout(fig, title, height)


# --------------------------------------------------------------- ranked bars
def ranked_bars(df, title, value_col="Gain (%)", height=540):
    """Bars sorted best -> worst, green/red, value on each bar, details on hover."""
    d = df.dropna(subset=[value_col]).reset_index(drop=True)
    if d.empty:
        return None
    g = d[value_col].astype(float)
    many = len(d) > 15
    fig = go.Figure(go.Bar(
        x=d["Name"], y=g, marker_color=[UP if v >= 0 else DOWN for v in g],
        marker_line_width=0, text=[f"{v:+.2f}%" for v in g],
        textposition="outside", textangle=-90 if many else 0, cliponaxis=False,
        textfont=dict(size=11 if many else 13),
        customdata=[_hover_details(r) for _, r in d.iterrows()],
        hovertemplate="<b>%{x}</b><br>Gain %{y:+.2f}%<br>%{customdata}<extra></extra>",
    ))
    fig.update_yaxes(ticksuffix="%", zeroline=True, zerolinewidth=1.5,
                     range=_range(min(0, g.min()), max(0, g.max()), 0.28 if many else 0.15))
    fig.update_xaxes(tickangle=-90 if many else -30, tickfont=dict(size=11 if many else 15))
    fig.update_layout(bargap=0.18, showlegend=False)
    return _base_layout(fig, title, height)


# ------------------------------------------------------- 30/60/90-day windows
def window_bars(df, which="strongest", n=3, title_prefix="", height=520):
    """Grouped bars of each window's return for the n strongest/weakest rows
    (ranked by Sum of Ranks). Returns None if nothing is ranked."""
    ranked = df.dropna(subset=["Sum of Ranks"]) if "Sum of Ranks" in df else df.iloc[0:0]
    if ranked.empty:
        return None
    pick = ranked.head(n) if which == "strongest" else ranked.tail(n).iloc[::-1]
    ret_cols = [c for c in df.columns if c.endswith("D %") and not c.startswith("Off")]
    fig = go.Figure()
    for i, c in enumerate(ret_cols):
        vals = pick[c].astype(float)
        fig.add_bar(name=c.replace(" %", "ays").replace("D", " d", 1), x=pick["Name"], y=vals,
                    marker_color=WINDOW_COLORS[i % len(WINDOW_COLORS)],
                    text=[f"{v:+.2f}%" for v in vals], textposition="outside", cliponaxis=False,
                    textfont=dict(size=14),
                    hovertemplate="<b>%{x}</b><br>" + c.replace(" %", "") + ": %{y:+.2f}%<extra></extra>")
    allv = pick[ret_cols].to_numpy(float)
    fig.update_yaxes(ticksuffix="%", zeroline=True, zerolinewidth=1.5,
                     range=_range(min(0, np.nanmin(allv)), max(0, np.nanmax(allv)), 0.15))
    fig.update_xaxes(tickfont=dict(size=17), tickprefix="<b>", ticksuffix="</b>")
    fig.update_layout(barmode="group", bargap=0.25, bargroupgap=0.06,
                      legend=dict(orientation="h", y=1.02, x=1, xanchor="right", yanchor="bottom"))
    title = f"{title_prefix}{which.title()} {len(pick)} by sum of 30/60/90-day ranks"
    return _base_layout(fig, title, height)


# ------------------------------------------------------------- seasonality
def seasonality_heatmap(heat, ticker, n_years, summary=None):
    """Year x month heatmap of monthly returns, with an 'Average' row."""
    z = heat.to_numpy(float) * 100
    years = [str(y) for y in heat.index]
    avg = np.nanmean(z, axis=0) if len(z) else np.full(12, np.nan)
    z = np.vstack([z, avg]) if len(z) else z
    years = years + ["Average"]
    lim = _limit(z, pct=95, floor=1.0)
    text = [[("" if not np.isfinite(v) else f"{v:+.1f}%") for v in row] for row in z]
    fig = go.Figure(go.Heatmap(
        z=np.clip(z, -lim, lim), x=list(heat.columns), y=years, text=text,
        customdata=z, texttemplate="%{text}", textfont=dict(size=12),
        colorscale=GAIN_SCALE, zmid=0, zmin=-lim, zmax=lim, xgap=2, ygap=2,
        hovertemplate="<b>%{x} %{y}</b>: %{customdata:+.2f}%<extra></extra>",
        colorbar=dict(title="Return", ticksuffix="%", thickness=12)))
    fig.update_yaxes(autorange="reversed", type="category")
    fig.update_xaxes(side="bottom", type="category")
    span = f"{heat.index.min()}" if heat.index.min() == heat.index.max() else f"{heat.index.min()}-{heat.index.max()}"
    return _base_layout(fig, f"Monthly seasonality of {ticker} ({span})", max(320, 34 * len(years) + 140))


# ---------------------------------------------------------------- candles
def candles(ticker, data, height=640):
    """Candlestick + volume with 20/50-day moving averages; no gaps for
    weekends/holidays (category axis)."""
    if data is None or data.empty:
        return None
    d = data.copy()
    x = d.index.strftime("%d %b %Y")
    has_vol = "Volume" in d and d["Volume"].fillna(0).sum() > 0
    fig = make_subplots(rows=2 if has_vol else 1, cols=1, shared_xaxes=True,
                        row_heights=[0.76, 0.24] if has_vol else [1.0], vertical_spacing=0.03)
    fig.add_trace(go.Candlestick(
        x=x, open=d["Open"], high=d["High"], low=d["Low"], close=d["Close"], name=ticker,
        increasing=dict(line=dict(color="#26a69a"), fillcolor="#26a69a"),
        decreasing=dict(line=dict(color="#ef5350"), fillcolor="#ef5350")), row=1, col=1)
    for win, color in ((20, "#f59e0b"), (50, "#3b82f6")):
        if len(d) >= win:
            fig.add_trace(go.Scatter(x=x, y=d["Close"].rolling(win).mean(), name=f"{win}-day avg",
                                     line=dict(color=color, width=1.6), hoverinfo="skip"), row=1, col=1)
    if has_vol:
        up = d["Close"] >= d["Open"]
        fig.add_trace(go.Bar(x=x, y=d["Volume"], name="Volume", showlegend=False,
                             marker_color=np.where(up, "rgba(38,166,154,0.55)", "rgba(239,83,80,0.55)"),
                             hovertemplate="Volume %{y:,.0f}<extra></extra>"), row=2, col=1)
    fig.update_xaxes(type="category", nticks=10, rangeslider_visible=False, showgrid=False)
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_layout(hovermode="x unified",
                      legend=dict(orientation="h", y=1.02, x=1, xanchor="right", yanchor="bottom"))
    first, last = d.index[0], d.index[-1]
    chg = (d["Close"].iloc[-1] / d["Close"].iloc[0] - 1) * 100 if len(d) > 1 else 0.0
    return _base_layout(fig, f"{ticker}  ·  {first:%d %b %Y} – {last:%d %b %Y}  ·  {chg:+.2f}%", height)


def apply_ink(fig, ink):
    """Make chart text solid black (light theme) or white (dark theme): titles,
    axis labels, legend, colour-bar labels and the value labels above bars.
    Text drawn on coloured tiles (market map, heatmap) stays white."""
    fig.update_layout(font_color=ink, title_font_color=ink, legend_font_color=ink)
    fig.update_xaxes(tickfont_color=ink, title_font_color=ink)
    fig.update_yaxes(tickfont_color=ink, title_font_color=ink)
    for tr in fig.data:
        if tr.type == "bar" and tr.text is not None:
            tr.textfont.color = ink
        if tr.type == "treemap":
            tr.marker.colorbar.tickfont.color = ink
            tr.marker.colorbar.title.font.color = ink
            tr.pathbar.textfont.color = ink
        if tr.type == "heatmap":
            tr.colorbar.tickfont.color = ink
            tr.colorbar.title.font.color = ink
    return fig


def _range(lo, hi, pad):
    """Y-axis range with room for value labels; only extends below 0 when a
    value is negative (so labels sit close to the bars)."""
    span = max(abs(lo), abs(hi)) or 1.0
    return [lo - span * pad if lo < 0 else 0, hi + span * pad if hi > 0 else 0]
