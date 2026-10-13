"""
indices.py — Índices de REFERENCIA (Merval, S&P 500). Solo se leen para comparar: NO son activos operables.

REGLA FIJA DE LA HERRAMIENTA: en todo backtest, el índice del mercado correspondiente es la VARA A SUPERAR. Si la estrategia no le gana
(retorno total menor o igual que el del índice en el mismo período), el resultado se marca en rojo.

  Vara por grupo de papeles:  Merval -> S&P MERVAL | CEDEAR -> S&P 500 en pesos | mixto (acciones y CEDEARs) -> el MAYOR de los dos.
  (Un universo mixto se compara contra el índice que más rindió: es la vara más exigente.)

Por qué el S&P 500 "en pesos": los CEDEARs cotizan en pesos, así que compararlos con el índice en dólares ignoraría el tipo de cambio. BYMA no publica
el histórico de ningún índice, así que el S&P 500 en pesos se aproxima con el CEDEAR SPY (precio en pesos de un ETF que replica el índice). Es un proxy:
sigue al índice y al dólar, pero no es el índice. El S&P 500 en dólares (Yahoo, ^GSPC) se informa aparte, solo como dato.

Los índices viven como series de precios sueltas; nunca se convierten en 'Papel' ni entran al generador de señales.
"""
import time
from datetime import datetime

import requests

import backtest as bt

INDICES = {
    "merval": {"nombre": "S&P MERVAL", "moneda": "ARS", "fuente": "Yahoo Finance (^MERV)", "operable": False},
    "sp500_ars": {"nombre": "S&P 500 en pesos (proxy: CEDEAR SPY)", "moneda": "ARS", "fuente": "BYMA, CEDEAR SPY", "operable": False},
    "sp500_usd": {"nombre": "S&P 500 (USD)", "moneda": "USD", "fuente": "Yahoo Finance (^GSPC)", "operable": False},
}
YAHOO_SIMBOLO = {"merval": "^MERV", "sp500_usd": "^GSPC"}
YAHOO = "https://{host}.finance.yahoo.com/v8/finance/chart/{simbolo}"
VARA_POR_GRUPO = {"Merval": ["merval"], "CEDEAR": ["sp500_ars"], "mixto": ["merval", "sp500_ars"]}
TICKERS_DE_INDICES = {"^MERV", "^GSPC", "MERV", "MERVAL", "SPX", "S&P MERVAL", "S&P500"}   # nombres que nunca deben aparecer como papel operable


def es_indice(ticker):
    """True si el nombre es el de un índice (que nunca puede entrar al universo operable)."""
    return str(ticker).upper() in TICKERS_DE_INDICES or str(ticker).startswith("^")


def claves_vara(grupo=None):
    """Claves de los índices que forman la vara para un grupo ('Merval', 'CEDEAR') o para uno mixto (por defecto)."""
    return list(VARA_POR_GRUPO.get(grupo, VARA_POR_GRUPO["mixto"]))


def grupo_de_universo(papeles):
    """'Merval', 'CEDEAR' o 'mixto' según los papeles que componen el universo (objetos con .tipo)."""
    tipos = {p.tipo for p in papeles}
    if tipos == {"accion"}:
        return "Merval"
    if tipos == {"cedear"}:
        return "CEDEAR"
    return "mixto"


def bajar_yahoo(simbolo):
    """[(fecha, cierre)] de un índice desde Yahoo Finance, o None si no responde (la corrida sigue sin esa referencia)."""
    for intento in range(4):
        for host in ("query1", "query2"):
            try:
                r = requests.get(YAHOO.format(host=host, simbolo=requests.utils.quote(simbolo)), params={"range": "2y", "interval": "1d"},
                                 timeout=25, headers={"User-Agent": "Mozilla/5.0 (compatible; caidas-benchmark/1.0)"})
                if r.status_code != 200:
                    continue
                j = r.json()["chart"]["result"][0]
                serie = [(datetime.fromtimestamp(t, bt.AR).date(), c) for t, c in
                         zip(j["timestamp"], j["indicators"]["quote"][0]["close"]) if c]
                if len(serie) > 100:
                    return serie
            except Exception:
                pass
        time.sleep(2 ** intento)
    return None


def sp500_en_pesos(barras_spy, hoy=None):
    """Serie del CEDEAR SPY (pesos), ajustada por cambios de ratio, como proxy del S&P 500 en pesos. barras_spy: velas de BYMA."""
    if not barras_spy:
        return None
    p = bt.Papel("SPY", "cedear", barras_spy, hoy)
    return list(zip(p.f, p.c)) if len(p.c) > 100 else None


def bajar_todos(barras, hoy=None):
    """{clave: serie o None} de los tres índices. 'barras' = las velas de BYMA ya bajadas (de ahí sale SPY, sin pedirlo otra vez)."""
    return {"merval": bajar_yahoo(YAHOO_SIMBOLO["merval"]), "sp500_usd": bajar_yahoo(YAHOO_SIMBOLO["sp500_usd"]),
            "sp500_ars": sp500_en_pesos(barras.get("SPY"), hoy)}


def evaluar(retorno_pct, retornos_indices, claves):
    """¿Supera la estrategia la vara? retornos_indices: {clave: retorno % del índice en el mismo período}. La vara es el mayor de 'claves'.
    Devuelve None si no hay ninguna referencia disponible (no se puede decir que supera ni que no)."""
    cand = [(k, retornos_indices[k]) for k in claves if retornos_indices.get(k) is not None]
    if not cand:
        return None
    k, v = max(cand, key=lambda x: x[1])
    return {"clave": k, "nombre": INDICES[k]["nombre"], "retorno_pct": v, "supera": retorno_pct > v, "diferencia_pp": retorno_pct - v}
