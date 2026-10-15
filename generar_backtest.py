"""
generar_backtest.py — Baja el histórico de BYMA (acciones y CEDEARs en pesos), corre el backtest de la estrategia base
(backtest.py), lo compara contra el Merval y publica el resultado CIFRADO en docs/data (lo lee la misma página).

    python generar_backtest.py                       CLAVE_ACCESO en el entorno (en GitHub: un "secret")
    python generar_backtest.py --cache c.json        guarda/usa el histórico bajado (solo para desarrollo local)
    python generar_backtest.py --solo-claro r.json   escribe el resultado SIN cifrar en r.json y no publica (desarrollo local)

Fuentes: BYMA Data (precios; la fuente ya validada) y Yahoo Finance ^MERV (referencia: BYMA no publica el histórico
del S&P MERVAL; el último valor de Yahoo coincidió exacto con el que informa BYMA).
"""
import argparse, collections, json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

import backtest as bt
import bollinger, config, conector, escalonada, generar, grilla, indices, parametros, reloj, ruptura, sectores

DIAS = 740            # BYMA entrega como máximo 2 años de velas diarias (probado: pedir más no trae más)


def log(msg):
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- datos

def bajar_historico(especies, cache=None):
    """{ticker: velas} con 3 pedidos en paralelo y reintentos; devuelve también los que no respondieron."""
    if cache and os.path.exists(cache):
        with open(cache, encoding="utf-8") as f:
            c = json.load(f)
        log(f"Histórico leído de la caché ({len(c['barras'])} papeles).")
        return c["barras"], c["fallidos"]

    def uno(t):
        try:
            return conector.get_daily_ohlc(t, DIAS)
        except Exception as e:
            return e
    tickers = sorted(especies)
    t0 = time.time()
    with ThreadPoolExecutor(config.WORKERS) as ex:
        res = list(ex.map(uno, tickers))
    res = [uno(t) if isinstance(r, Exception) else r for t, r in zip(tickers, res)]    # 2º pase, de a uno
    barras = {t: r for t, r in zip(tickers, res) if not isinstance(r, Exception) and r}
    fallidos = [t for t, r in zip(tickers, res) if isinstance(r, Exception)]
    log(f"Histórico: {len(barras)} papeles con datos, {len(fallidos)} sin respuesta, {time.time() - t0:.0f} s.")
    if cache:
        with open(cache, "w", encoding="utf-8") as f:
            json.dump({"barras": barras, "fallidos": fallidos}, f)
    return barras, fallidos


# ---------------------------------------------------------------- salida

def r2(x, d=2):
    return None if x is None else round(x, d)


def operacion(t, lado):
    """Fila de la lista de operaciones. Las abiertas (sin salida todavía) se valúan al último cierre."""
    abierta = t["motivo"] == "abierta"
    bruto = t["acciones"] * t["px_salida"] * (1 - lado)
    pnl = t["pnl"] if not abierta else bruto - t["costo_total"]
    fila = {"ticker": t["papel"].ticker, "tipo": t["papel"].tipo, "fecha_entrada": str(t["fecha"]),
            "precio_entrada": r2(t["precio"], 4), "fecha_salida": str(t["f_salida"]), "precio_salida": r2(t["px_salida"], 4),
            "resultado": r2(pnl), "resultado_pct": r2(pnl / t["costo_total"] * 100), "motivo": t["motivo"],
            "acciones": t["acciones"], "invertido": r2(t["costo_total"]), "soporte": r2(t["soporte"], 4),
            "resistencia": r2(t["resistencia"], 4), "ruedas": t["j"] - t["i"], "dias": (t["f_salida"] - t["fecha"]).days,
            "caida_pct": r2(t["caida_pct"], 1), "caida_dias": t["caida_dias"], "ajustado": bool(t["papel"].ajustes)}
    if "tramos" in t:   # salida escalonada: cada venta parcial con su fecha, precio y porcentaje de la posición original
        fila["tramos"] = [{"fecha": x["fecha"], "precio": r2(x["px"], 4), "acciones": x["acciones"], "pct_posicion": r2(x["pct_posicion"], 1), "motivo": x["motivo"]}
                          for x in t["tramos"]]
        fila["costos_pagados"] = r2(t["costo_compra"] + t["costo_ventas"])
    return fila


def concentracion(cerradas, capital):
    """¿La ganancia se reparte o depende de pocas operaciones? (en pesos y como % del capital inicial)."""
    pnl = sorted((t["pnl"] for t in cerradas), reverse=True)
    total = sum(pnl)
    top1, top3 = sum(pnl[:1]), sum(pnl[:3])
    return {"ganancia_neta": r2(total, 0), "n": len(pnl), "n_ganadoras": sum(x > 0 for x in pnl),
            "top1_pct": r2(top1 / total * 100) if total > 0 else None, "top3_pct": r2(top3 / total * 100) if total > 0 else None,
            "sin_top1": r2(total - top1, 0), "sin_top3": r2(total - top3, 0),
            "sin_top3_pct_capital": r2((total - top3) / capital * 100)}


def vara_resumen(res, retorno_pct):
    """La vara a superar de esta corrida (índice del mercado correspondiente) y si la estrategia la supera. None si no hay referencia."""
    v = bt.vara_de(res)
    if v is None:
        return None
    return {"clave": v["clave"], "nombre": indices.INDICES[v["clave"]]["nombre"], "retorno_pct": r2(v["retorno_pct"]),
            "supera": retorno_pct > v["retorno_pct"], "diferencia_pp": r2(retorno_pct - v["retorno_pct"])}


def resumen(res, clave="base"):
    """Las métricas que se comparan lado a lado entre estrategias o variantes. `clave`: 'base' (la corrida principal) o 'variante'
    (la misma estrategia con el otro criterio de tamaño de posición)."""
    b = res[clave]
    m, lado = b["metricas"], bt.costo_lado()
    abiertas = [(t["acciones"] * t["px_salida"] * (1 - lado) - t["costo_total"], t) for t in b["abiertas"]]
    pcts = [t["pnl_pct"] for t in b["cerradas"]]
    calendario = [d for d, _ in b["serie"]]
    posiciones = b["cerradas"] + b["abiertas"]
    ocupacion = sum(1 for d in calendario for t in posiciones if t["fecha"] <= d <= t["f_salida"]) / len(calendario)
    return {"ganancia_total": r2(m["ganancia_total"], 0), "ganancia_total_pct": r2(m["ganancia_total_pct"]),
            "profit_factor": r2(m["profit_factor"], 3), "payoff_ratio": r2(m["payoff_ratio"], 3),
            "ganadores_pct": r2(m["ganadores_pct"]), "trades": m["trades"],
            "max_drawdown": {"pct": r2(m["max_drawdown"]["pct"]), "monto": r2(m["max_drawdown"]["monto"], 0)},
            "ganancia_media_trade_pct": r2(m["ganancia_media_trade_pct"], 3), "cagr_pct": r2(m["cagr_pct"]),
            "duracion_media_dias": r2(m["duracion_media_dias"], 1), "mejor_trade_pct": r2(max(pcts), 1) if pcts else None,
            "peor_trade_pct": r2(min(pcts), 1) if pcts else None,
            "concentracion": concentracion(b["cerradas"], bt.PARAMS["capital"]),
            "abiertas": {"n": len(abiertas), "no_realizado": r2(sum(x for x, _ in abiertas), 0)},
            "descartes_cartera": b["desc"], "ocupacion_media": r2(ocupacion, 2),
            "vara": vara_resumen(res, m["ganancia_total_pct"]),
            "senales": res["senales_total"], "descartes_senal": res["descartes_senal"]}


def resultado_json(res, universo, ajustes, fallidos, hoy, rel, p=None):
    p = p or bt.PARAMS
    lado = bt.costo_lado(p)
    base, var = res["base"], res["variante"]
    ops = sorted([operacion(t, lado) for t in base["cerradas"] + base["abiertas"]], key=lambda o: o["fecha_entrada"])
    fechas = [d for d, _ in base["serie"]]
    merval = dict(res["merval"]) if res["merval"] else {}
    mdd = lambda m: {**m["max_drawdown"], "pct": r2(m["max_drawdown"]["pct"]), "monto": r2(m["max_drawdown"]["monto"], 0)}

    def met(m):
        o = {k: (r2(v, 4) if isinstance(v, float) else v) for k, v in m.items() if k != "max_drawdown"}
        o["max_drawdown"] = mdd(m)
        return o
    n_cerr = len(base["cerradas"])
    if p.get("estrategia") == "bollinger":
        primera = (f"BYMA entrega como máximo 2 años de histórico y las bandas necesitan {p['ventana_ruedas']} ruedas previas: "
                   f"el período operable es de {res['calendario'][0]} a {res['calendario'][1]}, no 2 años completos.")
    else:
        primera = ("BYMA entrega como máximo 2 años de histórico y la estrategia necesita 8 meses previos para calcular soportes: "
                   f"el período operable es de {res['calendario'][0]} a {res['calendario'][1]}, no 2 años completos.")
    advertencias = [
        primera,
        "Sesgo de supervivencia: el universo son los papeles que cotizan HOY en BYMA; los que dejaron de cotizar no están.",
        "El umbral de 1.000 millones es nominal en pesos de cada época: con la inflación es más fácil de superar en fechas recientes.",
    ]
    if n_cerr < 30:
        advertencias.append(f"Pocas operaciones cerradas ({n_cerr}): con tan pocas, las métricas son estadísticamente débiles.")
    if not res["merval"]:
        advertencias.append("No se pudo bajar el Merval en esta corrida: sin curva de referencia.")
    pnl = sorted((t["pnl"] for t in base["cerradas"]), reverse=True)
    if pnl and sum(pnl) > 0 and sum(pnl[:3]) >= 0.5 * sum(pnl):
        advertencias.append(f"El resultado depende de pocas operaciones: las 3 mejores suman {sum(pnl[:3]) / sum(pnl) * 100:.0f}% de la "
                            f"ganancia neta; sin ellas el resultado sería {sum(pnl) - sum(pnl[:3]):+,.0f} pesos.")
    if base["abiertas"]:
        advertencias.append(f"Hay {len(base['abiertas'])} posición(es) abierta(s) al final; cuentan en la curva de capital pero no en las métricas de operaciones.")
    salida = {
        "funcion": "backtest", "generado": rel.ahora().isoformat(timespec="seconds"),
        "periodo": {"inicio": str(res["calendario"][0]), "fin": str(res["calendario"][1]), "ruedas": len(fechas),
                    "anios": r2(base["metricas"]["anios"], 2), "historico_desde": str(min(pa.f[0] for pa in universo["papeles"]))},
        "parametros": {k: v for k, v in p.items()}, "costo_por_lado_pct": r2(lado * 100, 4),
        "metricas": met(base["metricas"]), "metricas_variante": met(var["metricas"]),
        "metricas_sin_costos": met(res["sin_costos"]),
        "merval": ({"retorno_total_pct": r2(res["merval_metricas"]["retorno_total_pct"]),
                    "cagr_pct": r2(res["merval_metricas"]["cagr_pct"]), "max_drawdown": mdd(res["merval_metricas"])}
                   if res["merval_metricas"] else None),
        "anios": [{**a, "retorno_pct": r2(a["retorno_pct"]), "ganancia": r2(a["ganancia"], 0), "ganadores_pct": r2(a["ganadores_pct"]),
                   "merval_pct": r2(a["merval_pct"])} for a in res["anios"]],
        "operaciones": ops,
        "equity": {"fechas": [str(d) for d in fechas], "base": [r2(e, 0) for _, e in base["serie"]],
                   "variante": [r2(e, 0) for _, e in var["serie"]],
                   "merval": [r2(merval.get(d), 0) for d in fechas] if merval else None},
        "universo": {"especies": universo["especies"], "con_datos": len(universo["papeles"]),
                     "sin_respuesta": fallidos, "papeles_con_senal": res["papeles_con_senal"],
                     "senales": res["senales_total"], "descartes_senal": res["descartes_senal"],
                     "descartes_cartera": base["desc"], "descartes_cartera_variante": var["desc"]},
        "ajustes": ajustes, "advertencias": advertencias,
        "contexto": {"hora_mercado": rel.ahora().isoformat(timespec="seconds"), "fuente_hora": rel.fuente,
                     "origen": "manual", "advertencias": []},
    }
    # REGLA FIJA: la vara a superar es el índice del mercado correspondiente. Los índices son solo referencia (no operables).
    salida["referencias"] = {k: {**{kk: indices.INDICES[k][kk] for kk in ("nombre", "moneda", "fuente", "operable")},
                                 "retorno_pct": r2(v["metricas"]["retorno_total_pct"]), "cagr_pct": r2(v["metricas"]["cagr_pct"]),
                                 "max_drawdown": mdd(v["metricas"]), "es_vara": k in bt.VARA}
                             for k, v in res.get("referencias", {}).items()}
    salida["vara"] = vara_resumen(res, base["metricas"]["ganancia_total_pct"])
    v_ = bt.vara_de(res)
    if v_:
        ser_ = dict(res["referencias"][v_["clave"]]["serie"])
        salida["equity"]["vara"] = {"clave": v_["clave"], "nombre": indices.INDICES[v_["clave"]]["nombre"], "v": [r2(ser_.get(d), 0) for d in fechas]}
    if salida["vara"] is None:
        salida["advertencias"].append("No hay índice de referencia disponible en esta corrida: no se puede decir si la estrategia supera la vara.")
    elif not salida["vara"]["supera"]:
        salida["advertencias"].insert(0, f"NO SUPERA LA VARA: la estrategia rindió {r2(base['metricas']['ganancia_total_pct'])}% y {salida['vara']['nombre']} "
                                         f"{salida['vara']['retorno_pct']}% en el mismo período.")
    return salida


def main():
    ap = argparse.ArgumentParser(description="Backtest de la estrategia base (cifrado y publicado en docs/data)")
    ap.add_argument("--cache", help="archivo JSON para guardar/leer el histórico (desarrollo local)")
    ap.add_argument("--solo-claro", metavar="ARCHIVO", help="escribe el resultado sin cifrar y no publica (desarrollo local)")
    ap.add_argument("--variante", choices=["base", "filtro_tendencia", "ruptura", "ruptura_trailing", "ruptura_5pos", "grilla_ruptura", "ruptura_escalonada", "bollinger"], default="base",
                    help="base = estrategia de caídas; filtro_tendencia = caídas + cierre sobre la media de 200 ruedas (150 si no hay 200); "
                         "ruptura = estrategia NUEVA de ruptura al alza (se compara contra la de caídas); "
                         "ruptura_trailing = ruptura con trailing stop del 15%% en vez de las 20 ruedas (dos versiones, contra la de tiempo); "
                         "ruptura_5pos = ruptura con solo trailing 15%%, cartera de 5 posiciones de 20%% contra la de 2 posiciones; "
                         "grilla_ruptura = grilla de la ruptura con solo trailing: 2/3/5 posiciones x trailing 15%%/20%%, con estabilidad por día de arranque; "
                         "ruptura_escalonada = ruptura con salida escalonada (40%% a +10%%, 40%% a +15%%, 20%% a +20%%; stop 8%% y luego trailing 8%%), 3 posiciones, "
                         "contra la ruptura con solo trailing 15%% (3 posiciones); "
                         "bollinger = estrategia de Bandas de Bollinger (giro de la línea central en U; salida por tramos en las bandas), 3 posiciones, contra la ruptura con solo trailing 15%%")
    for c, ayuda in (("periodo", "período de la media central"), ("desvios", "desvíos de las bandas"), ("dias", "días de pendiente positiva que confirman el giro"),
                     ("ventana", "ventana de detección del patrón (ruedas)"), ("magnitud", "magnitud mínima del giro (%%)"),
                     ("salida", "salida: 'peso1,peso2,peso3,stop' (por defecto 1,1,1,1)")):
        ap.add_argument("--bb-" + c, default="", help=f"solo variante bollinger: {ayuda}; vacío = el valor guardado en parametros.json")
    ap.add_argument("--parametros", default=parametros.ARCHIVO, help="archivo donde quedan guardados los parámetros editables")
    ap.add_argument("--grupo", help="solo papeles de este grupo: Merval o CEDEAR (ver sectores.py)")
    ap.add_argument("--sector", help="solo papeles de este sector: energeticas, bancos, tecnologicas, ETF, alimentarias, otros")
    ap.add_argument("--subsector", help="solo para tecnologicas: IA, computadoras, satelites, otras")
    ap.add_argument("--hoy", metavar="AAAA-MM-DD", help="solo desarrollo: fija 'hoy' para reproducir una corrida (las velas desde esa fecha se descartan)")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    clave = os.environ.get("CLAVE_ACCESO", "")
    if not a.solo_claro and len(clave) < generar.MIN_CLAVE:
        sys.exit(f"Falta CLAVE_ACCESO (mínimo {generar.MIN_CLAVE} caracteres). Sin clave no se publica nada.")

    valores_bb = cambios_bb = None
    if a.variante == "bollinger":
        # parámetros de Bollinger: los guardados, con los pedidos en esta corrida por encima; si algo no es válido no se corre ni se guarda nada
        try:
            pedidos = {"bb_periodo": a.bb_periodo, "bb_desvios": a.bb_desvios, "bb_dias": a.bb_dias, "bb_ventana": a.bb_ventana, "bb_magnitud_pct": a.bb_magnitud,
                       **parametros.parsear_salida(a.bb_salida)}
            valores_bb, cambios_bb = parametros.combinar(parametros.cargar(a.parametros), pedidos)
            parametros.validar(valores_bb)
        except parametros.ErrorParametro as ex:
            sys.exit(f"Parámetros inválidos, no se generó nada: {ex}")
        log("Parámetros de Bollinger: " + ", ".join(f"{k}={v:g}" for k, v in valores_bb.items() if k.startswith("bb_")) +
            (" (cambiados en esta corrida)" if cambios_bb else " (los guardados)"))

    rel = reloj.Reloj()
    conector.RELOJ = rel.epoch
    rel.sincronizar()
    hoy = date.fromisoformat(a.hoy) if a.hoy else rel.ahora().date()
    log(f"Hora de mercado: {rel.ahora().isoformat(timespec='seconds')} — {rel.fuente}")

    especies = conector.universo()                      # panel líder + general + CEDEARs, solo pesos
    log(f"Universo: {len(especies)} especies en pesos ({sum(v == 'accion' for v in especies.values())} acciones, "
        f"{sum(v == 'cedear' for v in especies.values())} CEDEARs).")
    barras, fallidos = bajar_historico(especies, a.cache)
    papeles = [bt.Papel(t, especies.get(t, "accion"), b, hoy) for t, b in barras.items()]
    papeles = [pa for pa in papeles if len(pa.c) > 0]
    ajustes = [x for pa in papeles for x in pa.ajustes]
    log(f"{len(papeles)} papeles utilizables; {len(ajustes)} ajustes por split/contrasplit.")
    assert not any(indices.es_indice(p.ticker) for p in papeles), "un índice no puede ser un papel operable"
    refs = indices.bajar_todos(barras, hoy)                      # índices de referencia: series sueltas, nunca papeles
    merval = refs["merval"]
    for k, v in refs.items():
        log(f"Referencia {indices.INDICES[k]['nombre']}: " + (f"{len(v)} velas, último {v[-1][1]:,.1f}" if v else "NO disponible"))
    filtro = {k: getattr(a, k) for k in ("grupo", "sector", "subsector") if getattr(a, k)}
    if filtro:
        papeles = sectores.filtrar(papeles, datos=sectores.cargar(), **filtro)
        if not papeles:
            sys.exit(f"Ningún papel cumple el filtro {filtro}.")
        log(f"Filtro por sector {filtro}: {len(papeles)} papeles.")
    grupo_vara = indices.grupo_de_universo(papeles)
    bt.fijar_referencias(refs, indices.claves_vara(grupo_vara))
    log(f"Vara a superar ({grupo_vara}): " + " / ".join(indices.INDICES[k]["nombre"] for k in bt.VARA) + " (el mayor retorno manda)")

    t0 = time.time()
    res_base = bt.correr(papeles, merval, bt.PARAMS)          # la estrategia base: siempre se corre, con los mismos datos
    if not res_base:
        sys.exit("El backtest no encontró ninguna señal.")
    p = bt.PARAMS
    res = res_base
    if a.variante == "filtro_tendencia":
        p = dict(bt.PARAMS, filtro_tendencia=True)             # ÚNICO cambio: el filtro de tendencia en la entrada
        res = bt.correr(papeles, merval, p)
        if not res:
            sys.exit("Con el filtro de tendencia no queda ninguna señal.")
    if a.variante == "ruptura":
        p = ruptura.PARAMS_RUPTURA                              # estrategia NUEVA y separada; la de caídas queda como res_base
        res = bt.correr(papeles, merval, p, generar=ruptura.senales_ruptura)
        if not res:
            sys.exit("La estrategia de ruptura no encontró ninguna señal.")
    if a.variante == "ruptura_trailing":
        p = ruptura.PARAMS_TRAILING
        res = bt.correr(papeles, merval, p, generar=ruptura.senales_ruptura)
        if not res:
            sys.exit("La ruptura con trailing no encontró ninguna señal.")
    if a.variante == "ruptura_5pos":
        p = ruptura.PARAMS_TRAILING_5POS
        res = bt.correr(papeles, merval, p, generar=ruptura.senales_ruptura)
        if not res:
            sys.exit("La ruptura con 5 posiciones no encontró ninguna señal.")
    if a.variante == "grilla_ruptura":
        celdas = grilla.correr_grilla(papeles, merval)
        if not celdas:
            sys.exit("La grilla no encontró ninguna señal.")
        elegida = next(c for c in celdas if c["clave"] == grilla.mas_estable(celdas))
        p, res = elegida["params"], elegida["res"]
    if a.variante == "ruptura_escalonada":
        p = escalonada.PARAMS_ESCALONADA                        # estrategia NUEVA y separada (salida por tramos); las anteriores no cambian
        res = bt.correr(papeles, merval, p, generar=escalonada.senales_escalonada, simulador=escalonada.simular_escalonada)
        if not res:
            sys.exit("La ruptura escalonada no encontró ninguna señal.")
    if a.variante == "bollinger":
        p = bollinger.con_bollinger(bollinger.PARAMS_BOLLINGER, parametros.bollinger_de(valores_bb))   # estrategia NUEVA y separada; entra por su propio generador y simulador
        res = bt.correr(papeles, merval, p, generar=bollinger.senales_bollinger, simulador=escalonada.simular_escalonada)
        if not res:
            sys.exit("La estrategia de Bollinger no encontró ninguna señal.")
    log(f"Backtest listo en {time.time() - t0:.0f} s: {res['senales_total']} señales, "
        f"{res['base']['metricas']['trades']} operaciones cerradas.")
    universo = {"papeles": papeles, "especies": len(especies)}
    salidas = []
    if a.variante == "ruptura_trailing":
        # Misma entrada, mismos datos, gestión y costos; solo cambia la SALIDA. Se publican dos informes (uno por versión del trailing),
        # y los dos traen la misma comparación contra la ruptura con salida por tiempo y contra el Merval.
        nombres = {"tiempo": "Tiempo 20 ruedas (original)", "trailing_stop": "Trailing 15% + stop de ruptura",
                   "trailing_solo": "Solo trailing 15%"}
        params_sal = {"tiempo": ruptura.PARAMS_RUPTURA, "trailing_stop": ruptura.PARAMS_TRAILING, "trailing_solo": ruptura.PARAMS_TRAILING_SOLO}
        corridas = {k: bt.correr(papeles, merval, pk, generar=ruptura.senales_ruptura) for k, pk in params_sal.items()}
        for k, rk in corridas.items():
            assert [d for d, _ in rk["base"]["serie"]] == [d for d, _ in corridas["tiempo"]["base"]["serie"]], "los calendarios deben ser idénticos"
        una_por_una = {k: {kk: r2(v, 3) for kk, v in bt.estadistica_senales(papeles, ruptura.senales_ruptura, pk).items()}
                       for k, pk in params_sal.items()}
        for k in ("trailing_stop", "trailing_solo"):
            out = resultado_json(corridas[k], universo, ajustes, fallidos, hoy, rel, params_sal[k])
            out["etiqueta"] = "Ruptura · " + nombres[k]
            out["estrategia"] = "ruptura"
            out["comparacion_salidas"] = {
                "principal": k, "nombres": nombres, **{kk: resumen(corridas[kk]) for kk in nombres}, "merval": out["merval"],
                "senales_una_por_una": una_por_una,
                "sensibilidad_inicio": {kk: [{k2: r2(v2, 2) if isinstance(v2, float) else v2 for k2, v2 in fila.items()}
                                             for fila in bt.sensibilidad_inicio(papeles, params_sal[kk], ruptura.senales_ruptura, merval)]
                                        for kk in nombres},
                "regla": "Único cambio sobre la ruptura: la salida por tiempo (20 ruedas) se reemplaza por un trailing stop del 15%, sin límite de "
                         "días. El stop arranca 15% bajo la entrada, sube a 15% bajo el máximo cierre desde la compra y nunca baja; se vende "
                         "cuando el cierre lo toca. Mismas entradas, gestión y costos."}
            out["equity"]["extras"] = [{"n": nombres[kk], "v": [r2(e, 0) for _, e in corridas[kk]["base"]["serie"]]} for kk in nombres if kk != k]
            out["equity"]["nombre_base"] = nombres[k]
            salidas.append(out)
    else:
        out = resultado_json(res, universo, ajustes, fallidos, hoy, rel, p)
        out["etiqueta"] = {"base": "Base", "filtro_tendencia": "Con filtro de tendencia", "ruptura": "Ruptura al alza",
                           "ruptura_5pos": "Ruptura · Solo trailing 15% · 5 posiciones (20% c/u)",
                           "grilla_ruptura": "Ruptura · Grilla 2/3/5 posiciones x trailing 15/20%",
                           "ruptura_escalonada": "Ruptura · Salida escalonada · 3 posiciones (1/3 c/u)",
                           "bollinger": "Bollinger · 3 posiciones (1/3 c/u)"}[a.variante]
        out["estrategia"] = ("ruptura" if a.variante in ("ruptura", "ruptura_5pos", "grilla_ruptura", "ruptura_escalonada") else "bollinger" if a.variante == "bollinger" else "caidas")
        if a.variante == "bollinger":
            p_comun = dict(p, ventana_ruedas=bt.PARAMS["ventana_ruedas"])         # la MISMA estrategia, pero operando solo desde donde empieza la ruptura (8 meses de arranque)
            res_comun = bt.correr(papeles, merval, p_comun, generar=bollinger.senales_bollinger, simulador=escalonada.simular_escalonada)
            p2 = grilla.parametros(3, 15)                                         # la comparación: ruptura con SOLO trailing 15%, 3 posiciones de 1/3 y los mismos costos
            res2 = bt.correr(papeles, merval, p2, generar=ruptura.senales_ruptura)
            assert [d for d, _ in res_comun["base"]["serie"]] == [d for d, _ in res2["base"]["serie"]], "el período común debe ser idéntico al de la ruptura"
            fila = lambda f: {k2: r2(v2, 2) if isinstance(v2, float) else v2 for k2, v2 in f.items()}
            una = lambda gen, pk: {k: r2(v, 3) for k, v in bt.estadistica_senales(papeles, gen, pk).items()}
            vc = bt.vara_de(res_comun)
            vref = res_comun["referencias"][vc["clave"]]["metricas"] if vc else None
            out["comparacion_bollinger"] = {
                "bollinger": {**resumen(res), "costos": fila(escalonada.resumen_costos(res, p))},
                "bollinger_comun": {**resumen(res_comun), "costos": fila(escalonada.resumen_costos(res_comun, p_comun))},
                "trailing": {**resumen(res2), "costos": fila(escalonada.resumen_costos(res2, p2))},
                "periodos": {"bollinger": [str(res["calendario"][0]), str(res["calendario"][1])], "comun": [str(res2["calendario"][0]), str(res2["calendario"][1])]},
                "vara_comun": None if not vc else {"clave": vc["clave"], "nombre": indices.INDICES[vc["clave"]]["nombre"], "retorno_pct": r2(vc["retorno_pct"]),
                                                   "cagr_pct": r2(vref["cagr_pct"]), "max_drawdown": {"pct": r2(vref["max_drawdown"]["pct"])}},
                "merval": out["merval"],
                "sensibilidad_inicio": {
                    "bollinger_comun": [fila(f) for f in bt.sensibilidad_inicio(papeles, p_comun, bollinger.senales_bollinger, merval, simulador=escalonada.simular_escalonada)],
                    "trailing": [fila(f) for f in bt.sensibilidad_inicio(papeles, p2, ruptura.senales_ruptura, merval)]},
                "senales_una_por_una": {"bollinger": una(bollinger.senales_bollinger, p), "trailing": una(ruptura.senales_ruptura, p2)},
                "diagnostico_patron": bollinger.diagnostico_patron(papeles, p),
                "salidas": {k: {"trades": len(rk["base"]["cerradas"]), "por_motivo": dict(collections.Counter(t["motivo"] for t in rk["base"]["cerradas"])),
                                "con_algun_toque": sum(any(x["motivo"].startswith("banda") for x in t["tramos"]) for t in rk["base"]["cerradas"])}
                            for k, rk in (("bollinger", res), ("bollinger_comun", res_comun))},
                "regla": "Bollinger recorre TODO el historial disponible (a partir de las ruedas que necesitan las bandas) y toma el patrón cada vez que aparece. Para comparar contra la "
                         "ruptura (que necesita 8 meses de arranque para sus soportes) se muestra también la misma Bollinger operando solo en el período de la ruptura. Misma cartera "
                         "(3 posiciones de 1/3 del patrimonio) y costos en todas.",
                "cambios": [f"{parametros.POR_CLAVE[k]['nombre']}: {v0:g} → {v1:g}" for k, (v0, v1) in (cambios_bb or {}).items()]}
            fechas_ = [d for d, _ in res["base"]["serie"]]
            serie2 = dict(res2["base"]["serie"])
            serie_c = dict(res_comun["base"]["serie"])
            out["equity"]["extras"] = [{"n": "Bollinger · período de la ruptura", "v": [r2(serie_c.get(d), 0) for d in fechas_]},
                                       {"n": "Ruptura · solo trailing 15% (3 pos)", "v": [r2(serie2.get(d), 0) for d in fechas_]}]
            out["equity"]["nombre_base"] = "Bollinger (todo el historial)"
        if a.variante == "ruptura_escalonada":
            p2 = grilla.parametros(3, 15)                       # la comparación: ruptura con SOLO trailing 15%, misma cartera (3 posiciones, 1/3 c/u) y costos
            res2 = bt.correr(papeles, merval, p2, generar=ruptura.senales_ruptura)
            assert [d for d, _ in res["base"]["serie"]] == [d for d, _ in res2["base"]["serie"]], "los calendarios deben ser idénticos"
            entradas = lambda gen, pk: [(pa.ticker, x["i"], x["precio"]) for pa in papeles if len(pa.c) > pk["ventana_ruedas"] for x in gen(pa, p=pk)[0]]
            assert entradas(escalonada.senales_escalonada, p) == entradas(ruptura.senales_ruptura, p2), "las entradas de las dos estrategias deben ser las mismas"
            fila = lambda f: {k2: r2(v2, 2) if isinstance(v2, float) else v2 for k2, v2 in f.items()}
            una = lambda gen, pk: {k: r2(v, 3) for k, v in bt.estadistica_senales(papeles, gen, pk).items()}
            out["comparacion_escalonada"] = {
                "escalonada": {**resumen(res), "costos": fila(escalonada.resumen_costos(res, p))},
                "trailing": {**resumen(res2), "costos": fila(escalonada.resumen_costos(res2, p2))},
                "merval": out["merval"],
                "sensibilidad_inicio": {
                    "escalonada": [fila(f) for f in bt.sensibilidad_inicio(papeles, p, escalonada.senales_escalonada, merval, simulador=escalonada.simular_escalonada)],
                    "trailing": [fila(f) for f in bt.sensibilidad_inicio(papeles, p2, ruptura.senales_ruptura, merval)]},
                "senales_una_por_una": {"escalonada": una(escalonada.senales_escalonada, p), "trailing": una(ruptura.senales_ruptura, p2)},
                "regla": "Misma entrada de ruptura, mismos datos, período, cartera (3 posiciones de 1/3 del patrimonio) y costos en las dos. Cambia solo la salida: la "
                         "escalonada vende 40% a +10%, 40% a +15% y 20% a +20% sobre el precio de compra (stop inicial −8%; desde el +10%, trailing 8% bajo el máximo "
                         "cierre); la otra sale solo por un trailing del 15%. Todo se evalúa con cierres."}
            out["equity"]["extras"] = [{"n": "Ruptura · solo trailing 15% (3 pos)", "v": [r2(e, 0) for _, e in res2["base"]["serie"]]}]
            out["equity"]["nombre_base"] = "Escalonada (3 pos)"
        if a.variante == "grilla_ruptura":
            for c in celdas:
                assert [d for d, _ in c["res"]["base"]["serie"]] == [d for d, _ in celdas[0]["res"]["base"]["serie"]], "los calendarios deben ser idénticos"
            redondeo = lambda d: {k2: r2(v2, 2) if isinstance(v2, float) else v2 for k2, v2 in d.items()}
            out["comparacion_grilla"] = {
                "celdas": [{"clave": c["clave"], "posiciones": c["posiciones"], "trailing": c["trailing"], "resumen": resumen(c["res"]),
                            "estabilidad": redondeo(c["estabilidad"]), "arranques": [redondeo(f) for f in c["arranques"]]} for c in celdas],
                "mas_estable": elegida["clave"], "merval": out["merval"],
                "criterio": "Más estable = menor amplitud (mejor menos peor retorno) entre 17 días de arranque, uno por semana (semanas 0 a 16); "
                            "a igual amplitud, el mejor peor arranque. No es la de mayor ganancia.",
                "regla": "Misma entrada, datos y costos en las 6 celdas; solo cambian las posiciones simultáneas (2/3/5, cada una 1/N del patrimonio "
                         "al entrar) y el trailing (15%/20%). Salida solo por trailing, sin stop de ruptura y sin límite de ruedas."}
        if a.variante == "ruptura_5pos":
            p2 = ruptura.PARAMS_TRAILING_SOLO                   # la versión de 2 posiciones (50% del efectivo): la referencia
            res2 = bt.correr(papeles, merval, p2, generar=ruptura.senales_ruptura)
            assert [d for d, _ in res["base"]["serie"]] == [d for d, _ in res2["base"]["serie"]], "los calendarios deben ser idénticos"
            fila = lambda f: {k2: r2(v2, 2) if isinstance(v2, float) else v2 for k2, v2 in f.items()}
            out["comparacion_posiciones"] = {
                "dos": resumen(res2), "cinco": resumen(res), "dos_patrimonio": resumen(res2, "variante"), "merval": out["merval"],
                "sensibilidad_inicio": {
                    "dos": [fila(f) for f in bt.sensibilidad_inicio(papeles, p2, ruptura.senales_ruptura, merval)],
                    "cinco": [fila(f) for f in bt.sensibilidad_inicio(papeles, p, ruptura.senales_ruptura, merval)]},
                "regla": "Único cambio sobre 'ruptura con solo trailing 15%': la cartera pasa de 2 a 5 posiciones simultáneas, cada una con el 20% del "
                         "patrimonio al entrar (con tope en el efectivo libre). Misma entrada, mismo trailing y mismos costos. La tercera columna "
                         "es una referencia: 2 posiciones con el 50% del patrimonio, para separar el efecto de la cantidad de posiciones del del tamaño."}
            out["equity"]["extras"] = [{"n": "2 posiciones (50% del efectivo)", "v": [r2(e, 0) for _, e in res2["base"]["serie"]]},
                                       {"n": "2 posiciones (50% del patrimonio)", "v": [r2(e, 0) for _, e in res2["variante"]["serie"]]}]
            out["equity"]["nombre_base"] = "5 posiciones (20% c/u)"
        if a.variante == "ruptura":
            assert [d for d, _ in res["base"]["serie"]] == [d for d, _ in res_base["base"]["serie"]], "los calendarios deben ser idénticos"
            out["comparacion_estrategias"] = {
                "ruptura": resumen(res), "caidas": resumen(res_base), "merval": out["merval"],
                "senales_una_por_una": {
                    "ruptura": {k: r2(v, 3) for k, v in bt.estadistica_senales(papeles, ruptura.senales_ruptura, p).items()},
                    "caidas": {k: r2(v, 3) for k, v in bt.estadistica_senales(papeles, bt.señales, bt.PARAMS).items()}},
                "regla": "Ruptura al alza contra la estrategia de caídas (base), con los mismos datos, período, gestión y costos."}
            out["equity"]["otra"] = [r2(e, 0) for _, e in res_base["base"]["serie"]]
            out["equity"]["nombre_base"], out["equity"]["nombre_otra"] = "Ruptura", "Caídas (base)"
        if a.variante == "filtro_tendencia":
            out["comparacion"] = {"base": resumen(res_base), "filtro": resumen(res),
                                  "diagnostico": {k: {kk: r2(vv, 2) for kk, vv in v.items()} for k, v in bt.diagnostico_filtro(papeles, p).items()},
                                  "regla": "Único cambio: la entrada exige cierre por encima de la media móvil de 200 ruedas "
                                           "(de 150 si el papel no tiene 200 de histórico). Todo lo demás es idéntico."}
        salidas.append(out)

    clave_aes = None if a.solo_claro else generar.derivar(clave, generar.cargar_meta())
    for k, out in enumerate(salidas):
        if filtro:
            out["filtro_sector"] = filtro
            out["etiqueta"] += " · " + " ".join(str(v) for v in filtro.values())
        if a.solo_claro:
            ruta = a.solo_claro if len(salidas) == 1 else a.solo_claro.replace(".json", f"_{k}.json")
            with open(ruta, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False)
            log(f"Resultado SIN cifrar escrito en {ruta} (no subir a ningún repositorio).")
        else:
            archivo = generar.guardar("backtest", out, clave_aes, etiqueta=out["etiqueta"])
            log(f"Guardado cifrado: docs/data/{archivo}")
            if valores_bb is not None and (cambios_bb or not os.path.exists(a.parametros)):
                parametros.guardar(valores_bb, a.parametros)
                log(f"Parámetros guardados para las próximas corridas en {os.path.basename(a.parametros)}.")
        m = out["metricas"]
        print(f"BACKTEST [{out['etiqueta']}] {out['periodo']['inicio']} → {out['periodo']['fin']}: {m['trades']} operaciones, "
              f"ganancia {m['ganancia_total_pct']:+.1f}%, profit factor {m['profit_factor']}, "
              f"ganadoras {m['ganadores_pct']}%, max DD {m['max_drawdown']['pct']}%.")


if __name__ == "__main__":
    main()
