"""Datos de la SEC (EDGAR) -> tabla anual de métricas. Solo empresas de EE.UU."""
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


def _series(facts, names, flow):
    gaap = facts.get("facts", {}).get("us-gaap", {})
    out = pd.Series(dtype=float)
    for n in names:  # los primeros nombres tienen prioridad; los demás rellenan huecos
        rows = gaap.get(n, {}).get("units", {}).get("USD")
        if not rows:
            continue
        df = pd.DataFrame(rows)
        df = df[df["form"].isin(["10-K", "10-K/A"])]
        if flow:
            df = df[df["start"].notna()]
            days = (pd.to_datetime(df["end"]) - pd.to_datetime(df["start"])).dt.days
            df = df[days.between(350, 380)]  # solo períodos anuales
        if df.empty:
            continue
        df = df.sort_values("filed").drop_duplicates("end", keep="last")
        out = out.combine_first(df.set_index("end")["val"].astype(float))
    return out


def annual_table(facts):
    d = pd.DataFrame({k: _series(facts, v, k in FLOWS) for k, v in CONCEPTS.items()})
    d = d[d["revenue"].notna()].sort_index()
    d.index = pd.to_datetime(d.index)
    d["fcf"] = d["cfo"] - d["capex"]
    d["rev_growth"] = d["revenue"].pct_change()
    d["gross_margin"] = d["gross_profit"] / d["revenue"]
    d["op_margin"] = d["op_income"] / d["revenue"]
    d["net_margin"] = d["net_income"] / d["revenue"]
    d["fcf_margin"] = d["fcf"] / d["revenue"]
    for name, col in [("roe", "equity"), ("roa", "assets")]:
        avg = ((d[col] + d[col].shift()) / 2).fillna(d[col])  # promedio; el 1er año usa el cierre
        d[name] = d["net_income"] / avg
    return d
