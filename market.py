"""Precios (Yahoo Finance via yfinance) y múltiplos históricos."""
import pandas as pd
import yfinance as yf


def _try(fn):
    try:
        return fn()
    except Exception:
        return None


def market_data(ticker, shares):
    """Devuelve (precios, splits, datos actuales). Cada dato tiene respaldos si Yahoo no lo entrega."""
    t = yf.Ticker(ticker.strip().upper())
    info = _try(lambda: t.info) or {}
    px = t.history(period="max", auto_adjust=False)["Close"]  # ajustado por splits, no por dividendos
    sp = t.splits
    px.index = px.index.tz_localize(None)
    if len(sp):
        sp.index = sp.index.tz_localize(None)
    else:
        sp = pd.Series(dtype=float, index=pd.DatetimeIndex([]))  # sin splits
    price = info.get("currentPrice") or info.get("regularMarketPrice") or _try(lambda: t.fast_info["last_price"])
    if not price and len(px):
        price = float(px.iloc[-1])
    cap = info.get("marketCap") or _try(lambda: t.fast_info["market_cap"])
    if not cap and price and len(shares):  # respaldo: acciones de la SEC llevadas a base actual
        cap = price * shares.iloc[-1] * sp[sp.index > shares.index[-1]].prod()
    fwd = info.get("forwardPE")
    if not fwd and price:
        eps = info.get("forwardEps") or _try(lambda: float(t.earnings_estimate.loc["+1y", "avg"]))
        fwd = price / eps if eps and eps > 0 else None
    return px, sp, {"price": price, "cap": cap, "fwd_pe": fwd, "pe": info.get("trailingPE"), "debt": info.get("totalDebt"), "cash": info.get("totalCash")}


def multiples(q, shares, px, splits, fallback=None):
    """Múltiplos al cierre de cada período: precio x acciones / métricas de 12 meses.
    Si la SEC no informa acciones, usa `fallback` (acciones actuales, aproximado)."""
    rows = {}
    for end, r in q.iterrows():
        p = px[:end]
        if p.empty:
            continue
        nxt = shares[(shares.index >= end) & (shares.index <= end + pd.Timedelta(days=90))] if len(shares) else shares
        if len(nxt):
            sh = nxt.iloc[0] * splits[splits.index > end].prod()  # lleva acciones a base actual
        elif fallback and not len(shares):
            sh = fallback
        else:
            continue
        cap = p.iloc[-1] * sh
        pos = lambda v: cap / v if pd.notna(v) and v > 0 else None
        rows[end] = {"P/E": pos(r["ttm_net_income"]), "P/S": pos(r["ttm_revenue"]),
                     "P/FCF": pos(r["ttm_fcf"]), "P/B": pos(r["equity"])}
    return pd.DataFrame.from_dict(rows, orient="index", columns=["P/E", "P/S", "P/FCF", "P/B"]).astype(float)
