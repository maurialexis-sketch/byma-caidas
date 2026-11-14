"""
macd.py — MACD (línea negra), línea de señal (roja) e histograma, sobre el CIERRE AJUSTADO, y el listado de la pestaña SAN MARINO: los CEDEARs donde la línea MACD está
POR DEBAJO de la señal y A PUNTO de cruzarla hacia arriba (esa es la señal de compra del MACD). Es un filtro, no una recomendación.

Cálculo (el estándar, el mismo de Yahoo Finance / TradingView):
  EMA(n)  : media móvil exponencial con k = 2 / (n + 1); la primera EMA es la media simple de los primeros n cierres (hasta entonces vale None: no se rellena).
  MACD    = EMA(rápida) − EMA(lenta)                          (12 y 26 de fábrica)
  señal   = EMA(n_señal) del MACD                             (9 de fábrica)
  histograma = MACD − señal                                   (negativo = la negra está debajo de la roja)
Los períodos y los demás valores de fábrica están en config_macd.json (no en el código); los editables se guardan en parametros_macd.json.

«A PUNTO DE CRUZAR HACIA ARRIBA» (la última rueda cerrada; todas las condiciones a la vez):
  1. debajo   : histograma < 0 (el MACD está por debajo de la señal; si ya la cruzó, o la toca justo, no entra).
  2. subiendo : el histograma subió 'macd_dias' ruedas seguidas terminando hoy (las dos líneas se están acercando).
  3. cerca    : la distancia entre las dos líneas, |MACD − señal|, es como máximo 'macd_dist_pct' % del precio (en % para que sirva igual en papeles de precios distintos).
  4. bajo cero (opcional, apagado de fábrica): el MACD también está por debajo de cero.
Informativo (no filtra): ruedas estimadas hasta el cruce, = |histograma| ÷ (cuánto subió el histograma hoy), suponiendo que siga igual. Es una extrapolación, no una predicción.
"""
import json, os

RUTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config_macd.json")
_CACHE = {}
EPS = 1e-9


def cargar(ruta=None):
    """La configuración de fábrica (validada). Sin ruta, la del repositorio."""
    ruta = ruta or RUTA
    if ruta not in _CACHE:
        with open(ruta, encoding="utf-8") as f:
            c = json.load(f)
        nombre = os.path.basename(ruta)
        for k in ("rapido", "lento", "senal", "dias_subiendo", "piso_millones"):
            if not isinstance(c.get(k), int) or isinstance(c.get(k), bool) or c[k] < 1:
                raise ValueError(f"{nombre}: '{k}' tiene que ser un entero >= 1")
        if c["rapido"] >= c["lento"]:
            raise ValueError(f"{nombre}: el período rápido ({c['rapido']}) tiene que ser menor que el lento ({c['lento']})")
        if not isinstance(c.get("distancia_max_pct"), (int, float)) or c["distancia_max_pct"] <= 0:
            raise ValueError(f"{nombre}: 'distancia_max_pct' tiene que ser un número > 0")
        if not isinstance(c.get("exigir_bajo_cero"), bool):
            raise ValueError(f"{nombre}: 'exigir_bajo_cero' tiene que ser true o false")
        _CACHE[ruta] = c
    return _CACHE[ruta]


def ema(valores, n):
    """EMA de n por rueda; None hasta tener n valores (la primera es la media simple de esos n). 'valores' puede empezar con None (se ignora ese tramo inicial)."""
    out = [None] * len(valores)
    ini = next((i for i, v in enumerate(valores) if v is not None), None)
    if ini is None or len(valores) - ini < n:
        return out
    k = 2.0 / (n + 1)
    e = sum(valores[ini:ini + n]) / n
    out[ini + n - 1] = e
    for i in range(ini + n, len(valores)):
        e = valores[i] * k + e * (1 - k)
        out[i] = e
    return out


def serie(cierres, rapido, lento, senal):
    """{'macd': [...], 'senal': [...], 'hist': [...]} por rueda (None donde todavía no se puede calcular)."""
    r, l = ema(cierres, rapido), ema(cierres, lento)
    macd = [None if a is None or b is None else a - b for a, b in zip(r, l)]
    sen = ema(macd, senal)
    hist = [None if m is None or s is None else m - s for m, s in zip(macd, sen)]
    return {"macd": macd, "senal": sen, "hist": hist}


def de_params(v):
    """Los parámetros (los valores guardados de parametros_macd.py) con el nombre que usa este módulo."""
    return {"rapido": v["macd_rapido"], "lento": v["macd_lento"], "senal": v["macd_senal"], "dias": v["macd_dias"], "dist_pct": float(v["macd_dist_pct"]),
            "bajo_cero": bool(v["macd_bajo_cero"]), "piso_millones": v["macd_piso_millones"]}


def ruedas_minimas(p):
    """Ruedas de histórico que hacen falta para poder evaluar un papel (la señal necesita 'lento + señal − 1' ruedas, y además los días de histograma subiendo)."""
    return p["lento"] + p["senal"] - 1 + p["dias"]


def estado(cierres, p):
    """El estado del MACD en la última rueda de 'cierres', o None si no hay ruedas suficientes (no se aproxima).
    Devuelve {macd, senal, hist, hist_pct, dias_subiendo, ruedas_al_cruce, debajo, subiendo, cerca, bajo_cero, cumple, hist_pct_ult}."""
    if len(cierres) < ruedas_minimas(p):
        return None
    s = serie(cierres, p["rapido"], p["lento"], p["senal"])
    t = len(cierres) - 1
    h = s["hist"]
    precio = cierres[t]
    racha = 0                                                         # ruedas seguidas con el histograma subiendo, terminando hoy
    while t - racha - 1 >= 0 and h[t - racha - 1] is not None and h[t - racha] > h[t - racha - 1]:
        racha += 1
    debajo = h[t] < -EPS * precio                                      # un histograma de «cero» con ruido de punto flotante (precio en línea recta) no es estar debajo de la señal
    subiendo = racha >= p["dias"]
    pct = h[t] / precio * 100
    cerca = abs(pct) <= p["dist_pct"]
    bajo_cero = s["macd"][t] < 0
    sube_hoy = h[t] - h[t - 1] if h[t - 1] is not None else 0
    return {"precio": precio, "macd": s["macd"][t], "senal": s["senal"][t], "hist": h[t], "hist_pct": pct, "dias_subiendo": racha,
            "ruedas_al_cruce": (-h[t] / sube_hoy) if (debajo and sube_hoy > 0) else None,
            "debajo": debajo, "subiendo": subiendo, "cerca": cerca, "bajo_cero": bool(bajo_cero),
            "cumple": bool(debajo and subiendo and cerca and (bajo_cero or not p["bajo_cero"])),
            "hist_pct_ult": [None if x is None else x / c * 100 for x, c in zip(h[-4:], cierres[-4:])]}


def listado(papeles, p, datos_sectores, etiquetar):
    """El listado de SAN MARINO: CEDEARs en pesos con cotización reciente que cumplen las condiciones. SIN filtro de liquidez (como los listados de Bollinger): cada papel lleva su monto
    promedio de 5 ruedas y si es 'operable' (>= el piso de liquidez) o 'solo señal'. Una empresa una vez (la línea más líquida). Orden: operables primero y, dentro de cada grupo,
    el más cerca del cruce primero (|histograma| en % del precio, de menor a mayor). Devuelve también cuántos pasan cada condición (acumulado)."""
    piso = p["piso_millones"] * 1e6
    ultima = max((x.f[-1] for x in papeles if x.f), default=None)
    embudo = {"evaluados": 0, "debajo": 0, "subiendo": 0, "cerca": 0, "bajo_cero": 0, "sin_historia": 0}
    por_empresa = {}
    for pa in papeles:
        if pa.tipo != "cedear" or not pa.f or (ultima - pa.f[-1]).days > 5:             # solo CEDEARs con cotización reciente
            continue
        e = estado(pa.c, p)
        if e is None:
            embudo["sin_historia"] += 1
            continue
        embudo["evaluados"] += 1
        if not e["debajo"]:
            continue
        embudo["debajo"] += 1
        if not e["subiendo"]:
            continue
        embudo["subiendo"] += 1
        if not e["cerca"]:
            continue
        embudo["cerca"] += 1
        if p["bajo_cero"] and not e["bajo_cero"]:
            continue
        embudo["bajo_cero"] += 1
        emp = etiquetar(pa.ticker) if etiquetar else pa.ticker
        fila = {"ticker": pa.ticker, "empresa": emp, **{k: v for k, v in e.items() if k not in ("debajo", "subiendo", "cerca", "cumple")}, "fecha": str(pa.f[-1]),
                "monto5_millones": pa.monto5[-1] / 1e6, "monto_dia_millones": pa.monto[-1] / 1e6, "volumen_dia": pa.vol[-1], "operable": pa.monto5[-1] >= piso}
        previa = por_empresa.get(emp)
        if previa is None or fila["monto5_millones"] > previa["monto5_millones"]:
            fila["otras_lineas"] = sorted(([previa["ticker"]] + previa.get("otras_lineas", [])) if previa else [])
            por_empresa[emp] = fila
        else:
            previa["otras_lineas"] = sorted(previa.get("otras_lineas", []) + [fila["ticker"]])
    filas = sorted(por_empresa.values(), key=lambda f: (not f["operable"], abs(f["hist_pct"])))
    return {"evaluados": embudo["evaluados"], "piso_millones": p["piso_millones"], "lista": filas, "embudo": embudo,
            "resumen": {"total": len(filas), "operables": sum(f["operable"] for f in filas)}}
