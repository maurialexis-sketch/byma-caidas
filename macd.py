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

LISTADO 2 — «DESPEGÓ» (el MACD ya cruzó hacia arriba la señal, y recién): última rueda cerrada, todo a la vez:
  1. arriba     : histograma > 0 (el MACD está por encima de la señal).
  2. reciente   : el cruce fue hace 'cruce2_ruedas' ruedas o menos (0 = cruzó hoy). Si no hubo cruce a la vista (siempre estuvo arriba), no entra.
  3. se separa  : el histograma de hoy es mayor que el de ayer (las líneas se abren; si se está cerrando de nuevo, no «despegó»).
  4. pegado     : la separación, en % del precio, es de 'cruce2_distancia_max_pct' (0,15 de fábrica) o menos: todavía no se fue lejos del cruce.
  5. Vortex     : VI+ > VI− (opcional, prendido de fábrica): el indicador Vortex confirma la fuerza alcista.

INDICADOR VORTEX (Botes y Siepman, 2010), período 'vortex_periodo' (14), sobre máximos, mínimos y cierres ajustados:
  VM+ = |máx(t) − mín(t−1)|     VM− = |mín(t) − máx(t−1)|     TR = máx(máx−mín, |máx − cierre(t−1)|, |mín − cierre(t−1)|)
  VI+ = Σ VM+ / Σ TR     VI− = Σ VM− / Σ TR      (sumas de las últimas n ruedas)      Alcista: VI+ > VI−.
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
        for k in ("cruce2_ruedas", "vortex_periodo"):
            if not isinstance(c.get(k), int) or isinstance(c.get(k), bool) or c[k] < 1:
                raise ValueError(f"{nombre}: '{k}' tiene que ser un entero >= 1")
        if not isinstance(c.get("cruce2_distancia_max_pct"), (int, float)) or c["cruce2_distancia_max_pct"] <= 0:
            raise ValueError(f"{nombre}: 'cruce2_distancia_max_pct' tiene que ser un número > 0")
        if not isinstance(c.get("vortex_exigir"), bool):
            raise ValueError(f"{nombre}: 'vortex_exigir' tiene que ser true o false")
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
            "bajo_cero": bool(v["macd_bajo_cero"]), "piso_millones": v["macd_piso_millones"],
            "dist2_pct": float(v["macd2_dist_pct"]), "ruedas_cruce": v["macd2_ruedas"], "vortex_exigir": bool(v["vortex_exigir"]), "vortex_periodo": cargar()["vortex_periodo"]}


def ruedas_minimas(p):
    """Ruedas de histórico que hacen falta para poder evaluar un papel (la señal necesita 'lento + señal − 1' ruedas, y además los días de histograma subiendo)."""
    return p["lento"] + p["senal"] - 1 + p["dias"]


def vortex_serie(altos, bajos, cierres, n):
    """VI+ y VI− por rueda: {'mas': [...], 'menos': [...]} (None donde faltan n+1 velas o donde el rango verdadero de las n ruedas suma 0: papel sin movimiento; no se aproxima)."""
    m = len(cierres)
    mas, menos = [None] * m, [None] * m
    if m < n + 1 or not (len(altos) == len(bajos) == m):
        return {"mas": mas, "menos": menos}
    vmp, vmm, tr = [0.0] * m, [0.0] * m, [0.0] * m
    for i in range(1, m):
        vmp[i] = abs(altos[i] - bajos[i - 1])
        vmm[i] = abs(bajos[i] - altos[i - 1])
        tr[i] = max(altos[i] - bajos[i], abs(altos[i] - cierres[i - 1]), abs(bajos[i] - cierres[i - 1]))
    for t in range(n, m):                                              # (VI+, VI−) con las n ruedas que terminan en t
        den = sum(tr[t - n + 1:t + 1])
        if den > 0:
            mas[t], menos[t] = sum(vmp[t - n + 1:t + 1]) / den, sum(vmm[t - n + 1:t + 1]) / den
    return {"mas": mas, "menos": menos}


def vortex_en(vs, t):
    """El Vortex en la rueda t (de un vortex_serie): {'mas': VI+, 'menos': VI−, 'alcista': VI+ > VI−, 'ruedas': ruedas seguidas, terminando en t, con VI+ > VI−}, o None si no se puede calcular."""
    if vs["mas"][t] is None:
        return None
    racha = 0
    while t - racha >= 0 and vs["mas"][t - racha] is not None and vs["mas"][t - racha] > vs["menos"][t - racha]:
        racha += 1
    return {"mas": vs["mas"][t], "menos": vs["menos"][t], "alcista": vs["mas"][t] > vs["menos"][t], "ruedas": racha}


def vortex(altos, bajos, cierres, n):
    """El indicador Vortex en la última rueda: {'mas': VI+, 'menos': VI−, 'alcista': VI+ > VI−, 'ruedas': ruedas seguidas, terminando hoy, con VI+ > VI−}.
    None si hay menos de n+1 velas o si en esas n ruedas el rango verdadero suma 0 (papel sin movimiento): no se aproxima."""
    return vortex_en(vortex_serie(altos, bajos, cierres, n), len(cierres) - 1) if cierres else None


def estado(cierres, p):
    """El estado del MACD en la última rueda de 'cierres', o None si no hay ruedas suficientes (no se aproxima). Ver estado_en."""
    if len(cierres) < ruedas_minimas(p):
        return None
    return estado_en(serie(cierres, p["rapido"], p["lento"], p["senal"]), cierres, len(cierres) - 1, p)


def estado_en(s, cierres, t, p):
    """El estado del MACD en la rueda t, con la serie 's' (de macd.serie) ya calculada sobre TODOS los cierres: el MACD solo usa datos hasta t, así que el valor en t es el mismo que
    se calcularía con cierres[:t+1] (el backtest lo usa para recorrer todo el historial de un papel sin recalcular en cada rueda). None si en t no hay ruedas suficientes.
    Devuelve {macd, senal, hist, hist_pct, dias_subiendo, ruedas_al_cruce, debajo, subiendo, cerca, bajo_cero, cumple, hist_pct_ult, arriba, ruedas_desde_cruce, se_separa}."""
    if t + 1 < ruedas_minimas(p):
        return None
    h = s["hist"]
    precio = cierres[t]
    racha = 0                                                         # ruedas seguidas con el histograma subiendo, terminando en t
    while t - racha - 1 >= 0 and h[t - racha - 1] is not None and h[t - racha] > h[t - racha - 1]:
        racha += 1
    arriba = h[t] > EPS * precio
    racha_arriba = 0                                                   # ruedas seguidas con el MACD por encima de la señal, terminando en t
    while t - racha_arriba >= 0 and h[t - racha_arriba] is not None and h[t - racha_arriba] > EPS * cierres[t - racha_arriba]:
        racha_arriba += 1
    previa = t - racha_arriba                                          # la rueda anterior a la racha: si tiene histograma, hubo un cruce a la vista (si no, siempre estuvo arriba)
    cruzo = arriba and previa >= 0 and h[previa] is not None
    debajo = h[t] < -EPS * precio                                      # un histograma de «cero» con ruido de punto flotante (precio en línea recta) no es estar debajo de la señal
    subiendo = racha >= p["dias"]
    pct = h[t] / precio * 100
    cerca = abs(pct) <= p["dist_pct"]
    bajo_cero = s["macd"][t] < 0
    sube_hoy = h[t] - h[t - 1] if h[t - 1] is not None else 0
    return {"precio": precio, "macd": s["macd"][t], "senal": s["senal"][t], "hist": h[t], "hist_pct": pct, "dias_subiendo": racha,
            "ruedas_al_cruce": (-h[t] / sube_hoy) if (debajo and sube_hoy > 0) else None,
            "debajo": debajo, "subiendo": subiendo, "cerca": cerca, "bajo_cero": bool(bajo_cero),
            "arriba": arriba, "ruedas_desde_cruce": (racha_arriba - 1) if cruzo else None, "se_separa": bool(h[t - 1] is not None and h[t] > h[t - 1]),
            "cumple": bool(debajo and subiendo and cerca and (bajo_cero or not p["bajo_cero"])),
            "hist_pct_ult": [None if x is None else x / c * 100 for x, c in zip(h[t - 3:t + 1], cierres[t - 3:t + 1])]}


def etapas_listado2(e, v, p):
    """Las condiciones del LISTADO 2 para un papel en una rueda, en orden, cada una como bool: [arriba, reciente, se_separa, pegado, vortex]. 'e' = estado(), 'v' = Vortex de esa rueda (o None).
    La usan el listado y el backtest: así la regla de entrada es una sola. El papel entra si TODAS son True."""
    return [bool(e["arriba"]),
            e["ruedas_desde_cruce"] is not None and e["ruedas_desde_cruce"] <= p["ruedas_cruce"],
            bool(e["se_separa"]),
            e["hist_pct"] <= p["dist2_pct"],
            (not p["vortex_exigir"]) or bool(v and v["alcista"])]


OCULTAS = ("debajo", "subiendo", "cerca", "cumple", "arriba", "se_separa")      # campos de estado() que no van a la fila de la lista


def _recientes(papeles):
    """Los CEDEARs con cotización reciente (la última rueda de la mayoría): solo esos se evalúan."""
    ultima = max((x.f[-1] for x in papeles if x.f), default=None)
    return [pa for pa in papeles if pa.tipo == "cedear" and pa.f and (ultima - pa.f[-1]).days <= 5]


def _fila(pa, e, v, p, etiquetar, piso, liquidez=None):
    """La fila de un papel en una lista: su estado del MACD, el Vortex 'v' (informativo en el listado 1, condición en el 2), el monto y si es operable.
    'liquidez' (opcional, SAINT MARINO DÓLAR): función papel -> dict que reemplaza lo que sale del propio papel; claves opcionales: 'monto_dia', 'volumen_dia', 'operable' y 'extra' (campos que se agregan a la fila)."""
    l = liquidez(pa) if liquidez else {}
    return {"ticker": pa.ticker, "empresa": etiquetar(pa.ticker) if etiquetar else pa.ticker, **{k: x for k, x in e.items() if k not in OCULTAS}, "fecha": str(pa.f[-1]),
            "vi_mas": v["mas"] if v else None, "vi_menos": v["menos"] if v else None, "vortex_alcista": bool(v and v["alcista"]), "vortex_ruedas": v["ruedas"] if v else None,
            "monto5_millones": pa.monto5[-1] / 1e6, "monto_dia_millones": (l["monto_dia"] / 1e6 if l["monto_dia"] is not None else None) if "monto_dia" in l else pa.monto[-1] / 1e6,
            "volumen_dia": l["volumen_dia"] if "volumen_dia" in l else pa.vol[-1], "operable": bool(l["operable"]) if "operable" in l else pa.monto5[-1] >= piso, **l.get("extra", {})}


def _por_empresa(filas):
    """Una empresa una vez: se queda la línea más líquida y las otras quedan anotadas en 'otras_lineas'."""
    out = {}
    for fila in filas:
        previa = out.get(fila["empresa"])
        if previa is None or fila["monto5_millones"] > previa["monto5_millones"]:
            fila["otras_lineas"] = sorted(([previa["ticker"]] + previa.get("otras_lineas", [])) if previa else [])
            out[fila["empresa"]] = fila
        else:
            previa["otras_lineas"] = sorted(previa.get("otras_lineas", []) + [fila["ticker"]])
    return list(out.values())


def listado(papeles, p, datos_sectores, etiquetar, liquidez=None):
    """El listado de SAN MARINO: CEDEARs en pesos con cotización reciente que cumplen las condiciones. SIN filtro de liquidez (como los listados de Bollinger): cada papel lleva su monto
    promedio de 5 ruedas y si es 'operable' (>= el piso de liquidez) o 'solo señal'. Una empresa una vez (la línea más líquida). Orden: operables primero y, dentro de cada grupo,
    el más cerca del cruce primero (|histograma| en % del precio, de menor a mayor). Devuelve también cuántos pasan cada condición (acumulado)."""
    piso = p["piso_millones"] * 1e6
    embudo = {"evaluados": 0, "debajo": 0, "subiendo": 0, "cerca": 0, "bajo_cero": 0, "sin_historia": 0}
    filas = []
    for pa in _recientes(papeles):
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
        filas.append(_fila(pa, e, vortex(pa.h, pa.l, pa.c, p["vortex_periodo"]), p, etiquetar, piso, liquidez))
    filas = sorted(_por_empresa(filas), key=lambda f: (not f["operable"], abs(f["hist_pct"])))
    return {"evaluados": embudo["evaluados"], "piso_millones": p["piso_millones"], "lista": filas, "embudo": embudo,
            "resumen": {"total": len(filas), "operables": sum(f["operable"] for f in filas)}}


def listado2(papeles, p, datos_sectores, etiquetar, liquidez=None):
    """El LISTADO 2 de SAN MARINO: CEDEARs donde el MACD ya cruzó hacia arriba la señal y «despegó» (ver el docstring del módulo): está arriba, el cruce fue hace pocas ruedas, las líneas
    se siguen abriendo, la separación es chica y (si se pide) el Vortex confirma. Mismo criterio de liquidez y de «una empresa una vez» que el listado 1. Orden: operables primero y, dentro
    de cada grupo, el cruce más reciente primero y, a igual antigüedad, el menos separado. Devuelve también cuántos pasan cada condición (acumulado)."""
    piso = p["piso_millones"] * 1e6
    embudo = {"evaluados": 0, "arriba": 0, "reciente": 0, "se_separa": 0, "pegado": 0, "vortex": 0, "sin_historia": 0}
    filas = []
    for pa in _recientes(papeles):
        e = estado(pa.c, p)
        if e is None:
            embudo["sin_historia"] += 1
            continue
        embudo["evaluados"] += 1
        v = vortex(pa.h, pa.l, pa.c, p["vortex_periodo"])
        etapas = etapas_listado2(e, v, p)
        for clave, ok in zip(("arriba", "reciente", "se_separa", "pegado", "vortex"), etapas):       # acumulado: cada paso cuenta solo si pasaron todos los anteriores
            if not ok:
                break
            embudo[clave] += 1
        if all(etapas):
            filas.append(_fila(pa, e, v, p, etiquetar, piso, liquidez))
    filas = sorted(_por_empresa(filas), key=lambda f: (not f["operable"], f["ruedas_desde_cruce"], f["hist_pct"]))
    return {"evaluados": embudo["evaluados"], "piso_millones": p["piso_millones"], "lista": filas, "embudo": embudo,
            "resumen": {"total": len(filas), "operables": sum(f["operable"] for f in filas), "con_vortex": sum(f["vortex_alcista"] for f in filas)}}
