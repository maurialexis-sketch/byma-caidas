"""
informe.py — Informe diario de CANDIDATOS (no es un backtest ni una recomendación de compra: es un filtro objetivo para decidir mirando el gráfico).

Barre el universo líquido de acciones y CEDEARs en pesos y devuelve los papeles que HOY (última rueda cerrada) cumplen TODOS los filtros:
  1. Liquidez confirmada: monto promedio de las últimas 5 ruedas >= 1.000 M.
  2. Tendencia alcista: cierre por encima de su media de 200 ruedas (150 si el papel no tiene 200 de histórico).
  3. Señal de entrada, de dos tipos (se etiqueta cuál dispara):
       RUPTURA: el cierre superó una resistencia de 8 meses que el cierre anterior todavía no había superado.
       REBOTE : el mínimo de ayer u hoy tocó (±2%) un soporte de 8 meses y hoy cerró en verde (cierre > cierre anterior).
  4. Recorrido a la resistencia >= 10%: distancia a la resistencia más cercana por ENCIMA del precio. Si no hay ninguna (máximos de 8 meses), no hay recorrido
     que medir y NO pasa.
  5. Relación riesgo/beneficio >= 2: (resistencia - precio) / (precio - stop), con stop = soporte - 1%. En una RUPTURA el soporte es la resistencia que se
     acaba de romper (el nivel que tiene que aguantar); en un REBOTE, la zona de soporte tocada.
Niveles: los mismos del resto del proyecto (zonas de pivotes de 168 ruedas, 2+ toques, tolerancia 2%). Salida: hasta 5, ordenados por R/B.
No se baja la vara para llenar la lista: si nada cumple todo, el informe lo dice.
"""
import backtest as bt
import sectores

MAX_CANDIDATOS = 5
RECORRIDO_MIN = 0.10
RB_MIN = 2.0
BUFFER_STOP = 0.01          # stop = soporte - 1% (el mismo de la estrategia de rebote)
MENSAJE_NINGUNO = "Hoy ningún activo cumple las condiciones"
RECORDATORIO = ("En el backtest (unos 16 meses) la ruptura rindió mejor que el rebote, pero ninguna de las dos superó al índice y la muestra es corta; "
                "el rebote del backtest además exigía una caída previa. No es una recomendación.")


def _niveles_senal(c, soporte, techos):
    """Recorrido, R/B y riesgo para un soporte dado y las resistencias, con el precio c. None si no hay resistencia por encima."""
    arriba = [r for r in techos if r > c]
    if not arriba or soporte is None:
        return None
    r = min(arriba)
    stop = soporte * (1 - BUFFER_STOP)
    riesgo = c - stop
    return {"soporte": soporte, "resistencia": r, "recorrido_pct": (r / c - 1) * 100, "riesgo_pct": riesgo / c * 100,
            "rr": (r - c) / riesgo if riesgo > 0 else None}


def evaluar_papel(p, params=bt.PARAMS):
    """Todo lo que se mide de un papel en su última rueda. None si no hay histórico suficiente para la ventana de 8 meses."""
    i = len(p.c) - 1
    if i < params["ventana_ruedas"]:
        return None
    c = p.c[i]
    n_ma = params["ma_larga"] if i + 1 >= params["ma_larga"] else params["ma_corta"]
    ma = p.sma(i, n_ma)
    e = {"ticker": p.ticker, "tipo": p.tipo, "fecha": str(p.f[i]), "precio": c, "monto5": p.monto5[i],
         "liquido": p.monto5[i] >= params["piso_monto"], "ma_n": n_ma, "ma": ma,
         "alcista": ma is not None and c > ma, "dist_ma_pct": (c / ma - 1) * 100 if ma else None,
         "ruptura": None, "rebote": None, "cercano": None}
    pisos, techos = bt.niveles(p, i, params)
    # niveles más cercanos al precio (para medir los filtros de recorrido y R/B por separado)
    sop_cerca = max((z for z in pisos if z < c), default=None)
    e["cercano"] = _niveles_senal(c, sop_cerca, techos)
    # RUPTURA: cierre por encima de una zona que el cierre anterior no había superado (si se rompen varias, la más alta)
    rotas = [z for z in techos if p.c[i - 1] <= z < c]
    if rotas:
        z = max(rotas)
        e["ruptura"] = {"disparo": True, "nivel": z, **(_niveles_senal(c, z, techos) or {"soporte": z, "resistencia": None, "recorrido_pct": None, "riesgo_pct": None, "rr": None})}
    # REBOTE: el mínimo de ayer u hoy tocó un soporte (±tolerancia), cierre por encima de esa zona y en verde
    minimo = min(p.l[i - 1], p.l[i])
    tocados = [z for z in pisos if z <= c and z * (1 - params["tol_zona"]) <= minimo <= z * (1 + params["tol_zona"])]
    if tocados and c > p.c[i - 1]:
        z = max(tocados)
        e["rebote"] = {"disparo": True, "nivel": z, **(_niveles_senal(c, z, techos) or {"soporte": z, "resistencia": None, "recorrido_pct": None, "riesgo_pct": None, "rr": None})}
    return e


def umbrales(params=bt.PARAMS):
    """(recorrido mínimo en %, R/B mínimo) del parámetro; los de fábrica si no vienen."""
    return params.get("recorrido_min", RECORRIDO_MIN) * 100, params.get("rb_min", RB_MIN)


def _cumple_recorrido(s, params=bt.PARAMS):
    return bool(s and s.get("resistencia") and s["recorrido_pct"] >= umbrales(params)[0] - 1e-9)


def _cumple_rb(s, params=bt.PARAMS):
    return bool(s and s.get("rr") is not None and s["rr"] >= umbrales(params)[1] - 1e-9)


def _pasa(s, params=bt.PARAMS):
    """¿La señal cumple el recorrido mínimo y el R/B mínimo?"""
    return _cumple_recorrido(s, params) and _cumple_rb(s, params)


def mejor_senal(e, params=bt.PARAMS):
    """Entre las señales que disparan hoy y cumplen recorrido y R/B, la de mayor R/B. (tipo, señal) o None."""
    cand = [(t, e[k]) for t, k in (("RUPTURA", "ruptura"), ("REBOTE", "rebote")) if _pasa(e[k], params)]
    return max(cand, key=lambda x: x[1]["rr"]) if cand else None


def _numero(x):
    return f"{x:g}".replace(".", ",")


def nombres_filtros(params=bt.PARAMS):
    """Los textos de los filtros con los valores con que se corre (no los de fábrica fijos)."""
    rmin, rbmin = umbrales(params)
    piso = f"{params['piso_monto'] / 1e6:,.0f}".replace(",", ".")
    return [("liquidez", f"Liquidez confirmada (monto ≥ {piso} M)"), ("tendencia", f"Tendencia alcista (cierre > media de {params['ma_larga']})"),
            ("senal", "Señal de entrada hoy (ruptura o rebote)"), ("ruptura", "   · de ellas, RUPTURA"), ("rebote", "   · de ellas, REBOTE"),
            ("recorrido", f"Recorrido a la resistencia ≥ {_numero(rmin)}%"), ("rr", f"R/B ≥ {_numero(rbmin)}")]


def candidatos(papeles, datos_sectores=None, params=bt.PARAMS, max_candidatos=MAX_CANDIDATOS):
    """Aplica los filtros a todo el universo. Devuelve {'embudo','candidatos','mas_candidatos','cercanos','evaluados'}.
    'embudo' trae, por filtro, cuántos pasan solos (contra el universo líquido) y cuántos pasan acumulando los anteriores."""
    datos = datos_sectores or sectores.cargar()
    ev = []
    ultima = max((p.f[-1] for p in papeles if p.f), default=None)
    for p in papeles:
        if not p.f or (ultima - p.f[-1]).days > 5:          # sin cotización reciente: no se evalúa
            continue
        e = evaluar_papel(p, params)
        if e:
            ev.append(e)
    liq = [e for e in ev if e["liquido"]]
    alc = [e for e in liq if e["alcista"]]
    con_senal = [e for e in alc if e["ruptura"] or e["rebote"]]
    con_reco = [e for e in con_senal if any(_cumple_recorrido(s, params) for s in (e["ruptura"], e["rebote"]))]
    pasan = [e for e in alc if mejor_senal(e, params)]
    tk = lambda L: sorted(e["ticker"] for e in L)
    solos = {
        "liquidez": liq, "tendencia": [e for e in liq if e["alcista"]], "senal": [e for e in liq if e["ruptura"] or e["rebote"]],
        "ruptura": [e for e in liq if e["ruptura"]], "rebote": [e for e in liq if e["rebote"]],
        "recorrido": [e for e in liq if _cumple_recorrido(e["cercano"], params)],
        "rr": [e for e in liq if _cumple_rb(e["cercano"], params)]}
    nombres = nombres_filtros(params)
    acumulado = {"liquidez": liq, "tendencia": alc, "senal": con_senal, "ruptura": [e for e in alc if e["ruptura"]], "rebote": [e for e in alc if e["rebote"]],
                 "recorrido": con_reco, "rr": pasan}
    embudo = [{"clave": k, "nombre": n, "pasan_solos": len(solos[k]), "tickers_solos": tk(solos[k]),
               "acumulado": len(acumulado[k]), "tickers_acumulado": tk(acumulado[k])} for k, n in nombres]
    embudo.append({"clave": "todos", "nombre": "Cumplen TODOS los filtros", "pasan_solos": None, "tickers_solos": [], "acumulado": len(pasan),
                   "tickers_acumulado": tk(pasan)})

    def ficha(e, tipo, s):
        et = sectores.etiquetar(e["ticker"], e["tipo"], datos)
        return {"ticker": e["ticker"], "especie": e["tipo"], "grupo": et["grupo"], "sector": et["sector"], "subsector": et["subsector"], "empresa": et["subyacente"],
                "fecha": e["fecha"], "precio": e["precio"], "monto_millones": e["monto5"] / 1e6, "tendencia": "alcista", "ma_n": e["ma_n"], "ma": e["ma"],
                "dist_ma_pct": e["dist_ma_pct"], "senal": tipo,
                "senales_hoy": [t for t, k in (("RUPTURA", "ruptura"), ("REBOTE", "rebote")) if e[k]],
                "soporte": s["soporte"], "soporte_nota": "resistencia rota (ahora soporte)" if tipo == "RUPTURA" else "zona de soporte tocada",
                "resistencia": s["resistencia"], "recorrido_pct": s["recorrido_pct"], "riesgo_pct": s["riesgo_pct"], "rr": s["rr"]}
    todas = []
    for e in alc:
        m = mejor_senal(e, params)
        if m:
            todas.append(ficha(e, m[0], m[1]))
    # una empresa, una vez: entre las líneas de la misma empresa (AAPL, AAPLB) queda la más líquida
    por_empresa = {}
    for f in todas:
        v = por_empresa.setdefault(f["empresa"], [])
        v.append(f)
    unicas = []
    for empresa, L in por_empresa.items():
        mejor = max(L, key=lambda f: f["monto_millones"])
        mejor["otras_lineas"] = sorted(f["ticker"] for f in L if f is not mejor)
        unicas.append(mejor)
    unicas.sort(key=lambda f: (-f["rr"], -f["monto_millones"]))
    # con señal hoy pero sin recorrido o R/B suficientes: SOLO informativo, nunca entran a la lista
    cercanos = []
    for e in con_senal:
        if mejor_senal(e, params):
            continue
        for tipo, k in (("RUPTURA", "ruptura"), ("REBOTE", "rebote")):
            s = e[k]
            if s:
                rmin, rbmin = umbrales(params)
                motivo = ("sin resistencia por encima" if not s.get("resistencia") else
                          f"recorrido menor a {_numero(rmin)}%" if not _cumple_recorrido(s, params) else f"R/B menor a {_numero(rbmin)}")
                cercanos.append({"ticker": e["ticker"], "senal": tipo, "motivo": motivo, "recorrido_pct": s.get("recorrido_pct"), "rr": s.get("rr")})
    cercanos.sort(key=lambda x: (-(x["rr"] or 0)))
    return {"embudo": embudo, "candidatos": unicas[:max_candidatos], "mas_candidatos": max(0, len(unicas) - max_candidatos),
            "total_candidatos": len(unicas), "cercanos": cercanos[:15], "evaluados": len(ev), "liquidos": len(liq)}


def retorno_12m(serie, hasta=None):
    """Retorno % de una serie [(fecha, valor)] en los últimos 12 meses (365 días) hasta su último dato (o hasta 'hasta'). None si no alcanza el histórico.
    Devuelve (retorno, fecha_inicio, fecha_fin)."""
    if not serie:
        return None
    pts = [(d, v) for d, v in serie if hasta is None or d <= hasta]
    fin_d, fin_v = pts[-1]
    previos = [(d, v) for d, v in pts if (fin_d - d).days >= 365]
    if not previos:
        return None
    ini_d, ini_v = previos[-1]
    return (fin_v / ini_v - 1) * 100, ini_d, fin_d
