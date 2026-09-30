import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from market import market_data
from sec import annual_table, get_facts

st.set_page_config(page_title="Analizador de empresas", layout="wide")
st.title("Analizador de empresas")
ticker = st.sidebar.text_input("Ticker (EE.UU.)", "NVDA")
email = st.sidebar.text_input("Tu email (la SEC exige identificar el acceso)")
years = st.sidebar.slider("Años a mostrar", 3, 15, 8)


@st.cache_data(ttl=6 * 3600, show_spinner="Bajando datos de la SEC...")
def load(t, e):
    name, facts = get_facts(t, e)
    return name, annual_table(facts)



@st.cache_data(ttl=15 * 60, show_spinner="Bajando precios...")
def load_market(t):
    return market_data(t)


if not email:
    st.info("Ingresá tu email en la barra lateral para empezar.")
    st.stop()
try:
    name, d = load(ticker, email)
except Exception as ex:
    st.error(str(ex))
    st.stop()

d = d.tail(years)
x = d.index.year.astype(str)  # año de cierre del ejercicio fiscal
st.subheader(f"{name} ({ticker.upper()})")


def bars(cols, names, title):
    f = go.Figure([go.Bar(x=x, y=d[c] / 1e9, name=n) for c, n in zip(cols, names)])
    f.update_layout(title=title + " (US$ mil millones)", barmode="group", legend_orientation="h")
    return f


def lines(cols, names, title):
    f = go.Figure([go.Scatter(x=x, y=d[c] * 100, name=n, mode="lines+markers") for c, n in zip(cols, names)])
    f.update_layout(title=title + " (%)", legend_orientation="h")
    return f


a, b = st.columns(2)
a.plotly_chart(bars(["revenue", "net_income", "fcf"], ["Ingresos", "Utilidad neta", "FCF"], "Ingresos, utilidad y FCF"), use_container_width=True)
b.plotly_chart(lines(["gross_margin", "op_margin", "net_margin", "fcf_margin"], ["Bruto", "Operativo", "Neto", "FCF"], "Márgenes"), use_container_width=True)
c, e = st.columns(2)
c.plotly_chart(lines(["roe", "roa"], ["ROE", "ROA"], "ROE y ROA (sobre promedios)"), use_container_width=True)
e.plotly_chart(bars(["buybacks", "dividends"], ["Recompras", "Dividendos"], "Retorno al accionista"), use_container_width=True)

st.subheader("Valuación")
try:
    info, hist = load_market(ticker)
    last = d.iloc[-1]
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    cap = info.get("marketCap")
    ev = cap + (info.get("totalDebt") or 0) - (info.get("totalCash") or 0) if cap else None

    def ratio(a, b):
        ok = a is not None and pd.notna(a) and pd.notna(b) and b > 0
        return f"{a / b:,.1f}x" if ok else "n/d"

    m = st.columns(6)
    m[0].metric("Precio", f"{price:,.2f}" if price else "n/d")
    m[1].metric("Capitalización", f"US${cap / 1e9:,.0f} mil M" if cap else "n/d")
    m[2].metric("P/E", ratio(cap, last["net_income"]))
    m[3].metric("EV/Ventas", ratio(ev, last["revenue"]))
    m[4].metric("EV/EBIT", ratio(ev, last["op_income"]))
    m[5].metric("Rend. FCF", f"{last['fcf'] / cap:.1%}" if cap and pd.notna(last["fcf"]) else "n/d")
    f = go.Figure(go.Scatter(x=hist.index, y=hist.values, mode="lines"))
    f.update_layout(title="Precio (cierre mensual, 10 años)")
    st.plotly_chart(f, use_container_width=True)
    st.caption("Múltiplos calculados con el último año fiscal reportado (no últimos 12 meses) y el precio actual de Yahoo Finance.")
except Exception as ex:
    st.warning(f"No pude traer precios de Yahoo Finance ({ex}). El resto del análisis sigue funcionando.")

with st.expander("Ver tabla de datos"):
    st.dataframe(d)
    st.download_button("Descargar CSV", d.to_csv(), f"{ticker.upper()}_anual.csv")
st.caption("Fuente: SEC EDGAR (reportes 10-K, cifras GAAP). Solo informativo, no es una recomendación.")
