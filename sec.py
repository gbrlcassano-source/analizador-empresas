"""Datos de la SEC (EDGAR) -> tablas anual y trimestral. Solo empresas de EE.UU."""
import requests
import pandas as pd

CONCEPTS = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"],
    "gross_profit": ["GrossProfit"],
    "op_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
    "cfo": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "buybacks": ["PaymentsForRepurchaseOfCommonStock"],
    "dividends": ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],
    "assets": ["Assets"],
    "equity": ["StockholdersEquity"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "securities": ["MarketableSecuritiesCurrent"],
    "debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "debt_st": ["LongTermDebtCurrent", "ShortTermBorrowings"],
}
FLOWS = {"revenue", "gross_profit", "op_income", "net_income", "cfo", "capex", "buybacks", "dividends"}


def _get(url, email):
    r = requests.get(url, headers={"User-Agent": f"finanzas-tool {email}"}, timeout=30)
    r.raise_for_status()
    return r.json()


def get_facts(ticker, email):
    t = ticker.strip().upper()
    tickers = _get("https://www.sec.gov/files/company_tickers.json", email)
    m = next((v for v in tickers.values() if v["ticker"] == t), None)
    if not m:
        raise ValueError(f"No encontré '{t}' en la SEC (solo cubre empresas de EE.UU.).")
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(m['cik_str']):010d}.json"
    return m["title"], _get(url, email)


def _frames(facts, names):
    gaap = facts.get("facts", {}).get("us-gaap", {})
    out = []
    for n in names:
        rows = gaap.get(n, {}).get("units", {}).get("USD")
        if rows:
            df = pd.DataFrame(rows)
            out.append(df[df["form"].isin(["10-K", "10-K/A", "10-Q"])])
    return out


def _instant(facts, names):
    out = pd.Series(dtype=float)
    for df in _frames(facts, names):
        df = df.sort_values("filed").drop_duplicates("end", keep="last")
        out = out.combine_first(df.set_index("end")["val"].astype(float))
    return out


def _flow(facts, names, annual):
    """Flujos anuales, o trimestrales (los 10-Q traen acumulado del año: se diferencia)."""
    out = pd.Series(dtype=float)
    for df in _frames(facts, names):
        df = df[df["start"].notna()].sort_values("filed").drop_duplicates(["start", "end"], keep="last")
        df = df.assign(days=(pd.to_datetime(df["end"]) - pd.to_datetime(df["start"])).dt.days)
        if annual:
            y = df[(df["form"] != "10-Q") & df["days"].between(350, 380)]
            s = y.set_index("end")["val"].astype(float)
        else:
            parts = []
            for start, g in df[df["days"] <= 380].groupby("start"):
                v = g.sort_values("end").set_index("end")["val"].astype(float)
                ends = pd.DatetimeIndex(pd.to_datetime(v.index))
                prev = pd.DatetimeIndex([pd.to_datetime(start)] + list(ends[:-1]))
                span = (ends - prev).days
                q = v.diff().fillna(v)
                q[(span < 60) | (span > 130)] = float("nan")  # faltó un período: no inventar
                parts.append(q)
            s = pd.concat(parts) if parts else pd.Series(dtype=float)
            s = s[~s.index.duplicated()].dropna()
        out = out.combine_first(s)
    return out


def _metrics(d, k):
    """k = períodos por año (1 anual, 4 trimestral)."""
    d["fcf"] = d["cfo"] - d["capex"]
    d["net_debt"] = d[["debt", "debt_st"]].fillna(0).sum(axis=1) - d[["cash", "securities"]].fillna(0).sum(axis=1)
    for c in ["revenue", "gross_profit", "op_income", "net_income", "fcf"]:
        d[c + "_yoy"] = d[c].pct_change(k, fill_method=None)
        d["ttm_" + c] = d[c].rolling(k).sum() if k > 1 else d[c]
    d["gross_margin"] = d["gross_profit"] / d["revenue"]
    d["op_margin"] = d["op_income"] / d["revenue"]
    d["net_margin"] = d["net_income"] / d["revenue"]
    d["fcf_margin"] = d["fcf"] / d["revenue"]
    for name, col in [("roe", "equity"), ("roa", "assets")]:
        avg = ((d[col] + d[col].shift(k)) / 2).fillna(d[col])
        d[name] = d["ttm_net_income"] / avg
    return d


def _table(facts, annual):
    d = pd.DataFrame({k: (_flow(facts, v, annual) if k in FLOWS else _instant(facts, v)) for k, v in CONCEPTS.items()})
    d = d[d["revenue"].notna()].sort_index()
    d.index = pd.to_datetime(d.index)
    return _metrics(d, 1 if annual else 4)


def annual_table(facts):
    return _table(facts, True)


def quarterly_table(facts):
    return _table(facts, False)


def shares_outstanding(facts):
    """Acciones en circulación según la tapada de cada reporte (fecha de tapada)."""
    rows = facts.get("facts", {}).get("dei", {}).get("EntityCommonStockSharesOutstanding", {}).get("units", {}).get("shares", [])
    if not rows:
        return pd.Series(dtype=float)
    df = pd.DataFrame(rows).sort_values("filed").drop_duplicates("end", keep="last")
    return df.set_index(pd.to_datetime(df["end"]))["val"].astype(float).sort_index()
