"""Datos de la SEC (EDGAR) -> tablas anual y trimestral. Solo empresas de EE.UU."""
import requests
import pandas as pd

CONCEPTS = {  # primero nombres US-GAAP, después IFRS (empresas extranjeras con 20-F)
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "Revenue"],
    "gross_profit": ["GrossProfit"],
    "op_income": ["OperatingIncomeLoss", "ProfitLossFromOperatingActivities"],
    "pretax": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest", "ProfitLossBeforeTax"],
    "net_income": ["NetIncomeLoss", "ProfitLossAttributableToOwnersOfParent", "ProfitLoss"],
    "cfo": ["NetCashProvidedByUsedInOperatingActivities", "CashFlowsFromUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets", "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"],
    "buybacks": ["PaymentsForRepurchaseOfCommonStock", "PaymentsToAcquireOrRedeemEntitysShares"],
    "dividends": ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock", "DividendsPaidClassifiedAsFinancingActivities"],
    "assets": ["Assets"],
    "equity": ["StockholdersEquity", "EquityAttributableToOwnersOfParent", "Equity"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "CashAndCashEquivalents"],
    "securities": ["MarketableSecuritiesCurrent"],
    "debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "debt_st": ["LongTermDebtCurrent", "ShortTermBorrowings"],
    "loans": ["LoansAndLeasesReceivableNetReportedAmount", "LoansAndAdvancesToCustomers"],
    "deposits": ["Deposits", "DepositsFromCustomers"],
}
FLOWS = {"revenue", "gross_profit", "op_income", "pretax", "net_income", "cfo", "capex", "buybacks", "dividends"}


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


FORMS = ["10-K", "10-K/A", "10-Q", "20-F", "20-F/A"]
ANNUAL_FORMS = ["10-K", "10-K/A", "20-F", "20-F/A"]


def _frames(facts, names):
    out = []
    for tax in ("us-gaap", "ifrs-full"):
        items = facts.get("facts", {}).get(tax, {})
        for n in names:
            rows = items.get(n, {}).get("units", {}).get("USD")
            if rows:
                df = pd.DataFrame(rows)
                out.append(df[df["form"].isin(FORMS)])
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
            y = df[df["form"].isin(ANNUAL_FORMS) & df["days"].between(350, 380)]
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
    d["pretax_margin"] = d["pretax"] / d["revenue"]
    for name, col in [("roe", "equity"), ("roa", "assets")]:
        avg = ((d[col] + d[col].shift(k)) / 2).fillna(d[col])
        d[name] = d["ttm_net_income"] / avg
    return d


def _table(facts, annual):
    d = pd.DataFrame({k: (_flow(facts, v, annual) if k in FLOWS else _instant(facts, v)) for k, v in CONCEPTS.items()})
    key = "revenue" if d["revenue"].notna().any() else "net_income"  # IFRS: el nombre de ingresos puede variar
    d = d[d[key].notna()].sort_index()
    d.index = pd.to_datetime(d.index)
    return _metrics(d, 1 if annual else 4)


def annual_table(facts):
    return _table(facts, True)


def quarterly_table(facts):
    return _table(facts, False)


def shares_outstanding(facts):
    """Acciones en circulación según la tapada de cada reporte (suma las clases de acciones)."""
    rows = facts.get("facts", {}).get("dei", {}).get("EntityCommonStockSharesOutstanding", {}).get("units", {}).get("shares", [])
    if not rows:
        return pd.Series(dtype=float)
    s = pd.DataFrame(rows).drop_duplicates(["end", "val"]).groupby("end")["val"].sum().astype(float)
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


def concept_catalog(facts):
    """Lista de conceptos con datos anuales en USD: sirve para ubicar cifras que la herramienta no encuentra."""
    rows = []
    for tax, items in facts.get("facts", {}).items():
        for name, c in items.items():
            v = [x for x in c.get("units", {}).get("USD", []) if x["form"] in ANNUAL_FORMS]
            if v:
                last = max(v, key=lambda x: (x["end"], x["filed"]))
                rows.append({"taxonomía": tax, "concepto": name, "último cierre": last["end"], "valor (US$ M)": round(last["val"] / 1e6, 1)})
    return pd.DataFrame(rows, columns=["taxonomía", "concepto", "último cierre", "valor (US$ M)"])
