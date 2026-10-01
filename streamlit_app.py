import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from market import market_data, multiples
from sec import annual_table, get_facts, quarterly_table, shares_outstanding

st.set_page_config(page_title="Analizador de empresas", layout="wide")
st.title("Analizador de empresas")
ticker = st.sidebar.text_input("Ticker (EE.UU.)", "NVDA")
email = st.sidebar.text_input("Tu email (la SEC exige identificar el acceso)")
freq = st.sidebar.radio("Frecuencia", ["Anual", "Trimestral"])
n = st.sidebar.slider("Períodos a mostrar", 4, 40, 12)


@st.cache_data(ttl=6 * 3600, show_spinner="Bajando datos de la SEC...")
def load(t, e):
    name, facts = get_facts(t, e)
    return name, annual_table(facts), quarterly_table(facts), shares_outstanding(facts)


@st.cache_data(ttl=15 * 60, show_spinner="Bajando precios...")
def load_market(t, q, sh):
    info, px, sp = market_data(t)
    return info, px, multiples(q, sh, px, sp)


if not email:
    st.info("Ingresá tu email en la barra lateral para empezar.")
    st.stop()
try:
    name, a, q, sh = load(ticker, email)
except Exception as ex:
    st.error(str(ex))
    st.stop()

d = (a if freq == "Anual" else q).tail(n)
x = d.index.year.astype(str) if freq == "Anual" else d.index.strftime("%Y-%m")
st.subheader(f"{name} ({ticker.upper()}) · {freq.lower()}")


def bars(cols, names, title, scale=1e9, unit=" (US$ mil millones)"):
    f = go.Figure([go.Bar(x=x, y=d[c] / scale, name=nm) for c, nm in zip(cols, names)])
    f.update_layout(title=title + unit, barmode="group", legend_orientation="h")
    return f


def lines(cols, names, title):
    f = go.Figure([go.Scatter(x=x, y=d[c] * 100, name=nm, mode="lines+markers") for c, nm in zip(cols, names)])
    f.update_layout(title=title + " (%)", legend_orientation="h")
    return f


def show(col, fig):
    col.plotly_chart(fig, use_container_width=True)


c1, c2 = st.columns(2)
show(c1, bars(["revenue", "net_income", "fcf"], ["Ingresos", "Utilidad neta", "FCF"], "Ingresos, utilidad y FCF"))
show(c2, lines(["gross_margin", "op_margin", "net_margin", "fcf_margin"], ["Bruto", "Operativo", "Neto", "FCF"], "Márgenes"))
c3, c4 = st.columns(2)
yoy = bars(["revenue_yoy", "op_income_yoy", "net_income_yoy", "fcf_yoy"], ["Ingresos", "Res. operativo", "Utilidad neta", "FCF"], "Variación interanual", 0.01, " (%)")
yoy.update_layout(title="Variación " + ("año contra año" if freq == "Anual" else "contra el mismo trimestre del año anterior") + " (%)")
show(c3, yoy)
show(c4, lines(["roe", "roa"], ["ROE", "ROA"], "ROE y ROA (utilidad 12M / promedio)"))
show(st.columns(1)[0], bars(["buybacks", "dividends"], ["Recompras", "Dividendos"], "Retorno al accionista"))

st.subheader("Valuación y precio")
try:
    info, px, mult = load_market(ticker, q, sh)
    lq = q.iloc[-1]
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    cap = info.get("marketCap")
    ev = cap + (info.get("totalDebt") or 0) - (info.get("totalCash") or 0) if cap else None

    def ratio(a_, b_):
        ok = a_ is not None and pd.notna(a_) and pd.notna(b_) and b_ > 0
        return f"{a_ / b_:,.1f}x" if ok else "n/d"

    m = st.columns(7)
    m[0].metric("Precio", f"{price:,.2f}" if price else "n/d")
    m[1].metric("Capitalización", f"US${cap / 1e9:,.0f} mil M" if cap else "n/d")
    m[2].metric("P/E (12M)", ratio(cap, lq["ttm_net_income"]))
    m[3].metric("P/E forward", f"{info['forwardPE']:.1f}x" if info.get("forwardPE") else "n/d")
    m[4].metric("EV/Ventas", ratio(ev, lq["ttm_revenue"]))
    m[5].metric("EV/EBIT", ratio(ev, lq["ttm_op_income"]))
    m[6].metric("Rend. FCF", f"{lq['ttm_fcf'] / cap:.1%}" if cap and pd.notna(lq["ttm_fcf"]) else "n/d")
    st.caption("Múltiplos actuales con los últimos 12 meses reportados. El P/E forward es solo el dato actual: no hay historia gratuita de estimaciones de analistas.")

    if not mult.empty:
        opts = st.multiselect("Múltiplos históricos", ["P/E", "P/S", "P/FCF", "P/B"], ["P/E", "P/S", "P/FCF"])
        f = go.Figure([go.Scatter(x=mult.index, y=mult[o], name=o, mode="lines+markers") for o in opts])
        f.update_layout(title="Múltiplos al cierre de cada trimestre (veces)", legend_orientation="h")
        st.plotly_chart(f, use_container_width=True)

    labels = {"ttm_fcf": "FCF 12M", "ttm_revenue": "Ingresos 12M", "ttm_net_income": "Utilidad neta 12M", "ttm_op_income": "Res. operativo 12M"}
    key = st.selectbox("Comparar la cotización con", list(labels), format_func=labels.get)
    f = make_subplots(specs=[[{"secondary_y": True}]])
    f.add_trace(go.Scatter(x=px.index, y=px.values, name="Precio (US$)", mode="lines"), secondary_y=False)
    f.add_trace(go.Scatter(x=q.index, y=q[key] / 1e9, name=labels[key] + " (US$ mil M)", line_shape="hv"), secondary_y=True)
    f.update_xaxes(range=[q.index.min(), px.index.max()])
    f.update_yaxes(title_text="Precio (US$)", secondary_y=False)
    f.update_yaxes(title_text=labels[key] + " (US$ mil M)", secondary_y=True)
    f.update_layout(title="Cotización vs " + labels[key], legend_orientation="h")
    st.plotly_chart(f, use_container_width=True)
except Exception as ex:
    st.warning(f"No pude traer precios de Yahoo Finance ({ex}). El resto del análisis sigue funcionando.")

with st.expander("Ver tabla de datos"):
    st.dataframe(d)
    st.download_button("Descargar CSV", d.to_csv(), f"{ticker.upper()}_{freq.lower()}.csv")
st.caption("Fuente: SEC EDGAR (reportes 10-K y 10-Q, cifras GAAP) y Yahoo Finance. Solo informativo, no es una recomendación.")
