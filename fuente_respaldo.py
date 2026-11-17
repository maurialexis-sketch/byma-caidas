"""
fuente_respaldo.py — Fuente de datos de RESPALDO (data912.com) para cuando el servidor de datos de BYMA no responde.

Solo se usa si BYMA falla al pedir el universo de papeles (ver conector.universo); si BYMA responde, esto no se toca. Mismo contrato que el conector:
  universo()                      -> {ticker: 'accion' | 'cedear'}  solo especies en PESOS (se descartan las líneas en dólares MEP y cable)
  get_daily_ohlc(ticker, dias)    -> [{'t','o','h','l','c','v'}] velas diarias SIN ajustar (igual que BYMA: los splits los trata backtest.Papel)

Dos niveles: 1) data912.com (universo y histórico); 2) Yahoo Finance (.BA) para los papeles que data912 no tiene en su histórico (cubre ~40% del universo: faltan varios líquidos).
Lo que se sabe (data912 comparada contra Yahoo .BA en 6 papeles, 2 años): los cierres coinciden con una diferencia mediana de ~0,1% (máxima ~1,9%) y el volumen coincide exacto.
Son fuentes gratuitas y de terceros, sin garantía de servicio, y no son BYMA. Por eso todo informe armado con ellas lo dice.
"""
import threading, time
from datetime import date, datetime, timedelta, timezone

import requests

AR = timezone(timedelta(hours=-3))      # hora de Argentina (sin horario de verano)
BASE = "https://data912.com"
RUTA_VIVO = {"accion": "/live/arg_stocks", "cedear": "/live/arg_cedears"}
RUTA_HISTORICO = {"accion": "/historical/stocks/", "cedear": "/historical/cedears/"}
NOMBRE = "data912.com (fuente de respaldo; BYMA no respondió)"
FACTOR_USD = 0.2          # una línea «XXXC»/«XXXD» cuyo precio es menos de esta fracción del de «XXX» es la versión en dólares, no la de pesos (el cociente real es ~1/1.400)
REINTENTOS = 4
YAHOO = "https://{host}.finance.yahoo.com/v8/finance/chart/{simbolo}.BA"
ORIGEN = {"data912": 0, "yahoo": 0}     # de dónde salió el histórico de cada papel en esta corrida
_candado = threading.Lock()

TIPOS = {}                # {ticker: tipo}, lo llena universo()
_http = requests.Session()


def _get(ruta):
    for intento in range(REINTENTOS):
        try:
            r = _http.get(BASE + ruta, timeout=30, headers={"User-Agent": "Mozilla/5.0 (compatible; caidas-respaldo/1.0)"})
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError):
            if intento == REINTENTOS - 1:
                raise
            time.sleep(2 ** intento)


def es_linea_en_dolares(simbolo, precios):
    """True si 'simbolo' (terminado en C o D) es la versión en dólares de otro papel de la lista. precios = {simbolo: último precio}."""
    if len(simbolo) < 2 or simbolo[-1] not in "CD" or simbolo[:-1] not in precios:
        return False
    base = precios[simbolo[:-1]] or 0
    return base <= 0 or (precios[simbolo] or 0) < FACTOR_USD * base


def universo():
    """{ticker: tipo} de las especies en pesos de acciones y CEDEARs."""
    out = {}
    for tipo, ruta in RUTA_VIVO.items():
        filas = _get(ruta)
        if not isinstance(filas, list):
            raise ValueError(f"{BASE}{ruta} no devolvió una lista")
        precios = {f["symbol"]: f.get("c") or 0 for f in filas if f.get("symbol")}
        for s in sorted(precios):
            if not es_linea_en_dolares(s, precios):
                out.setdefault(s, tipo)
    if not out:
        raise ValueError("la fuente de respaldo devolvió un universo vacío")
    TIPOS.clear()
    TIPOS.update(out)
    return out


def _velas(filas, dias, corte_ts):
    """Pasa las filas de data912 al formato del conector (t = medianoche de Argentina de ese día, como las fecha BYMA) y se queda con las últimas 'dias' jornadas."""
    bars = []
    for x in filas:
        try:
            d = date.fromisoformat(x["date"])
            o, h, l, c = float(x["o"]), float(x["h"]), float(x["l"]), float(x["c"])
        except (KeyError, TypeError, ValueError):
            continue
        if min(o, h, l, c) <= 0:                                    # vela en 0 = sin operar
            continue
        t = int(datetime(d.year, d.month, d.day, tzinfo=AR).timestamp())
        if corte_ts is not None and t >= corte_ts:
            continue
        bars.append({"t": t, "o": o, "h": h, "l": l, "c": c, "v": x.get("v") or 0})
    bars.sort(key=lambda b: b["t"])
    if bars:
        bars = [b for b in bars if b["t"] >= bars[-1]["t"] - dias * 24 * 3600]
    return bars


def _rango_yahoo(dias):
    """El rango de Yahoo que cubre 'dias' días corridos (después se recorta)."""
    for tope, rango in ((30, "1mo"), (95, "3mo"), (190, "6mo"), (370, "1y"), (740, "2y")):
        if dias <= tope:
            return rango
    return "5y"


def _yahoo(ticker, dias):
    """Filas {date, o, h, l, c, v} del papel (línea en pesos, '.BA') según Yahoo Finance. Lista vacía si Yahoo no lo tiene."""
    simbolo = requests.utils.quote(ticker)
    for intento in range(REINTENTOS):
        for host in ("query1", "query2"):
            try:
                r = _http.get(YAHOO.format(host=host, simbolo=simbolo), params={"range": _rango_yahoo(dias), "interval": "1d"}, timeout=30,
                              headers={"User-Agent": "Mozilla/5.0 (compatible; caidas-respaldo/1.0)"})
                if r.status_code == 404:
                    return []
                if r.status_code != 200:
                    continue
                res = r.json()["chart"]["result"]
                if not res or not res[0].get("timestamp"):
                    return []
                j = res[0]
                q = j["indicators"]["quote"][0]
                filas = []
                for i, ts in enumerate(j["timestamp"]):
                    if None in (q["open"][i], q["high"][i], q["low"][i], q["close"][i]):
                        continue
                    filas.append({"date": datetime.fromtimestamp(ts, AR).date().isoformat(), "o": q["open"][i], "h": q["high"][i], "l": q["low"][i], "c": q["close"][i],
                                  "v": (q.get("volume") or [0] * len(q["close"]))[i] or 0})
                return filas
            except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
                pass
        time.sleep(2 ** intento)
    raise requests.ConnectionError(f"{ticker}: Yahoo Finance no respondió")


def get_daily_ohlc(ticker, dias=400, corte_ts=None):
    """Velas diarias del papel (en pesos): de data912 si lo tiene; si no, de Yahoo Finance. Lista vacía si ninguna lo tiene; si no responde ninguna, la excepción sale."""
    tipo = TIPOS.get(ticker)
    if tipo is None:
        raise KeyError(f"{ticker}: no está en el universo de la fuente de respaldo")
    try:
        filas = _get(RUTA_HISTORICO[tipo] + requests.utils.quote(ticker))
    except (requests.RequestException, ValueError):
        filas = None
    if isinstance(filas, list) and filas:                          # data912 sin ese papel contesta 200 con {"Error": ...}
        velas = _velas(filas, dias, corte_ts)
        if velas:
            with _candado:
                ORIGEN["data912"] += 1
            return velas
    velas = _velas(_yahoo(ticker, dias), dias, corte_ts)
    with _candado:
        ORIGEN["yahoo"] += 1 if velas else 0
    return velas
