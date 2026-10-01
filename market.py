"""Precios (Yahoo Finance via yfinance) y múltiplos históricos."""
import pandas as pd
import yfinance as yf


def market_data(ticker):
    t = yf.Ticker(ticker.strip().upper())
    info = t.info or {}
    px = t.history(period="max", auto_adjust=False)["Close"]  # ajustado por splits, no por dividendos
    sp = t.splits
    px.index = px.index.tz_localize(None)
    sp.index = sp.index.tz_localize(None)
    return info, px, sp


def multiples(q, shares, px, splits):
    """Múltiplos al cierre de cada trimestre: precio x acciones / métricas de 12 meses."""
    rows = {}
    for end, r in q.iterrows():
        nxt = shares[(shares.index > end) & (shares.index <= end + pd.Timedelta(days=90))]
        p = px[:end]
        if nxt.empty or p.empty:
            continue
        cap = p.iloc[-1] * nxt.iloc[0] * splits[splits.index > end].prod()  # lleva acciones a base actual
        pos = lambda v: cap / v if pd.notna(v) and v > 0 else None
        rows[end] = {"P/E": pos(r["ttm_net_income"]), "P/S": pos(r["ttm_revenue"]),
                     "P/FCF": pos(r["ttm_fcf"]), "P/B": pos(r["equity"])}
    return pd.DataFrame.from_dict(rows, orient="index", columns=["P/E", "P/S", "P/FCF", "P/B"]).astype(float)
