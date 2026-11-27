"""
fuente_ny.py — Datos de SAINT MARINO DÓLAR: el universo (los CEDEARs en dólares de Bull Market, cedears_dolar.json) y el gráfico de la bolsa de Nueva York de cada uno, de Yahoo Finance.

  universo()                       -> [{'yahoo', 'nombre', 'simbolos'}]  los tickers de Nueva York a evaluar (un CEDEAR puede tener más de una línea D: se evalúa una vez)
  get_daily_ohlc(yahoo, dias, corte_ts)
                                   -> [{'t','o','h','l','c','v'}] velas diarias en DÓLARES de la bolsa de Nueva York (Yahoo ya las ajusta por splits; no por dividendos)
  liquidez_cedears(items)          -> {yahoo: {...}} monto del día, en US$, de la línea D del CEDEAR en BYMA (data912, foto del día; sin historial): sirve para marcar «operable»
  hora_ny / sesion_cerrada_ny / rueda_esperada_ny / corte_de_datos_ny      el calendario de Nueva York (horario de verano de EE.UU. incluido)

No importa conector ni backtest (import circular). Las fechas de las velas se pasan a la medianoche de Argentina de ese día (t) como en el resto de la herramienta.
"""
import json, os, time
from datetime import date, datetime, timedelta, timezone

import requests

import fuente_respaldo as fr

RUTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cedears_dolar.json")
YAHOO = "https://{host}.finance.yahoo.com/v8/finance/chart/{simbolo}"
NOMBRE = "Yahoo Finance (bolsa de Nueva York, en dólares)"
REINTENTOS = 4
HORA_APERTURA_NY = (9, 30)
HORA_CIERRE_NY = (16, 30)          # el cierre es a las 16:00; media hora de margen para que Yahoo publique la vela completa
_http = requests.Session()


def universo(ruta=None):
    """Los tickers a evaluar, del archivo cedears_dolar.json (validado: tickers únicos, líneas D)."""
    with open(ruta or RUTA, encoding="utf-8") as f:
        doc = json.load(f)
    items = doc["items"]
    vistos = set()
    for e in items:
        if not e.get("yahoo") or not e.get("simbolos") or e["yahoo"] in vistos:
            raise ValueError(f"cedears_dolar.json: entrada inválida o repetida: {e}")
        vistos.add(e["yahoo"])
    return items


def _rango(dias):
    return fr._rango_yahoo(dias)


def _filas(simbolo, dias):
    """Filas {date, o, h, l, c, v} de Yahoo para un ticker de Nueva York; [] si Yahoo no lo tiene; ConnectionError si no responde."""
    for intento in range(REINTENTOS):
        for host in ("query1", "query2"):
            try:
                r = _http.get(YAHOO.format(host=host, simbolo=requests.utils.quote(simbolo)), params={"range": _rango(dias), "interval": "1d"}, timeout=30,
                              headers={"User-Agent": "Mozilla/5.0 (compatible; caidas-ny/1.0)"})
                if r.status_code == 404:
                    return []
                if r.status_code != 200:
                    continue
                res = r.json()["chart"]["result"]
                if not res or not res[0].get("timestamp"):
                    return []
                j = res[0]
                off = j["meta"].get("gmtoffset", -18000)
                q = j["indicators"]["quote"][0]
                filas = []
                for i, ts in enumerate(j["timestamp"]):
                    if None in (q["open"][i], q["high"][i], q["low"][i], q["close"][i]):
                        continue
                    filas.append({"date": datetime.fromtimestamp(ts + off, timezone.utc).date().isoformat(), "o": q["open"][i], "h": q["high"][i], "l": q["low"][i],
                                  "c": q["close"][i], "v": (q.get("volume") or [0] * len(q["close"]))[i] or 0})
                return filas
            except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
                pass
        time.sleep(2 ** intento)
    raise requests.ConnectionError(f"{simbolo}: Yahoo Finance no respondió")


def get_daily_ohlc(simbolo, dias=400, corte_ts=None):
    """Velas diarias de la bolsa de Nueva York (USD). Lista vacía si Yahoo no tiene el ticker."""
    return fr._velas(_filas(simbolo, dias), dias, corte_ts)


def liquidez_cedears(items):
    """{yahoo: {'monto_dia': US$ operados hoy en la línea D del CEDEAR (la de más monto si hay varias), 'volumen_dia': unidades, 'linea': símbolo D}} según data912 (foto del día en BYMA).
    {} si data912 no responde: sin dato no se marca «operable». No hay historial: es lo de un día, no un promedio."""
    try:
        filas = fr._get("/live/arg_cedears")
    except (requests.RequestException, ValueError):
        return {}
    if not isinstance(filas, list):
        return {}
    por = {f["symbol"]: f for f in filas if f.get("symbol")}
    out = {}
    for e in items:
        mejor = None
        for s in e["simbolos"]:
            f = por.get(s)
            if not f:
                continue
            monto = float(f.get("c") or 0) * float(f.get("v") or 0)
            if mejor is None or monto > mejor["monto_dia"]:
                mejor = {"monto_dia": monto, "volumen_dia": float(f.get("v") or 0), "linea": s}
        if mejor:
            out[e["yahoo"]] = mejor
    return out


# ---------------------------------------------------------------- calendario de Nueva York

def _domingo(anio, mes, n):
    """El n-ésimo domingo del mes (n=1 es el primero)."""
    d = date(anio, mes, 1)
    d += timedelta(days=(6 - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def en_horario_de_verano(utc):
    """Horario de verano de EE.UU.: del 2.º domingo de marzo (2:00 hora local, 07:00 UTC) al 1.er domingo de noviembre (2:00 hora local de verano, 06:00 UTC)."""
    ini = datetime.combine(_domingo(utc.year, 3, 2), datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=7)
    fin = datetime.combine(_domingo(utc.year, 11, 1), datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=6)
    return ini <= utc < fin


def hora_ny(dt):
    """La misma hora de 'dt' (con zona) en Nueva York."""
    utc = dt.astimezone(timezone.utc)
    return utc.astimezone(timezone(timedelta(hours=-4 if en_horario_de_verano(utc) else -5)))


def sesion_cerrada_ny(ahora_ny):
    """Día hábil con la rueda de Nueva York ya terminada (la vela de hoy está completa)."""
    return ahora_ny.weekday() < 5 and (ahora_ny.hour, ahora_ny.minute) >= HORA_CIERRE_NY


def rueda_esperada_ny(ahora_ny):
    """La rueda que debe reflejar una corrida PROGRAMADA que arranca en 'ahora_ny' (hora de Nueva York), o None si no corresponde generar informe. Igual criterio que generar_informe.rueda_esperada:
    GitHub atrasa las corridas horas, a veces pasada la medianoche. Día hábil con la rueda cerrada: la de hoy; antes de la apertura (9:30): la última rueda hábil anterior; otro momento: None."""
    if sesion_cerrada_ny(ahora_ny):
        return ahora_ny.date()
    if (ahora_ny.hour, ahora_ny.minute) < HORA_APERTURA_NY:
        d = ahora_ny.date() - timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        return d
    return None


def corte_de_datos_ny(ahora_ny):
    """Fecha desde la cual se descartan velas: hoy si la rueda no cerró (la vela de hoy puede estar a medias); mañana si ya cerró o es fin de semana."""
    cerrada = ahora_ny.weekday() >= 5 or (ahora_ny.hour, ahora_ny.minute) >= HORA_CIERRE_NY
    return ahora_ny.date() + timedelta(days=1) if cerrada else ahora_ny.date()
