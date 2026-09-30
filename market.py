"""Precios y datos de mercado desde Yahoo Finance (via yfinance)."""
import yfinance as yf


def market_data(ticker):
    t = yf.Ticker(ticker.strip().upper())
    info = t.info or {}
    hist = t.history(period="10y", interval="1mo")["Close"]
    return info, hist
