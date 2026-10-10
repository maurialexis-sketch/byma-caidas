"""
generar_backtest.py — Baja el histórico de BYMA (acciones y CEDEARs en pesos), corre el backtest de la estrategia base
(backtest.py), lo compara contra el Merval y publica el resultado CIFRADO en docs/data (lo lee la misma página).

    python generar_backtest.py                       CLAVE_ACCESO en el entorno (en GitHub: un "secret")
    python generar_backtest.py --cache c.json        guarda/usa el histórico bajado (solo para desarrollo local)
    python generar_backtest.py --solo-claro r.json   escribe el resultado SIN cifrar en r.json y no publica (desarrollo local)

Fuentes: BYMA Data (precios; la fuente ya validada) y Yahoo Finance ^MERV (referencia: BYMA no publica el histórico
del S&P MERVAL; el último valor de Yahoo coincidió exacto con el que informa BYMA).
"""
import argparse, json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

import requests

import backtest as bt
import config, conector, generar, reloj, ruptura

DIAS = 740            # BYMA entrega como máximo 2 años de velas diarias (probado: pedir más no trae más)
YAHOO = "https://{host}.finance.yahoo.com/v8/finance/chart/%5EMERV"


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


def bajar_merval():
    """[(fecha, cierre)] del S&P MERVAL en pesos desde Yahoo, o None si no responde (el backtest sigue sin la referencia)."""
    for intento in range(4):
        for host in ("query1", "query2"):
            try:
                r = requests.get(YAHOO.format(host=host), params={"range": "2y", "interval": "1d"}, timeout=25,
                                 headers={"User-Agent": "Mozilla/5.0 (compatible; caidas-benchmark/1.0)"})
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


# ---------------------------------------------------------------- salida

def r2(x, d=2):
    return None if x is None else round(x, d)


def operacion(t, lado):
    """Fila de la lista de operaciones. Las abiertas (sin salida todavía) se valúan al último cierre."""
    abierta = t["motivo"] == "abierta"
    bruto = t["acciones"] * t["px_salida"] * (1 - lado)
    pnl = t["pnl"] if not abierta else bruto - t["costo_total"]
    return {"ticker": t["papel"].ticker, "tipo": t["papel"].tipo, "fecha_entrada": str(t["fecha"]),
            "precio_entrada": r2(t["precio"], 4), "fecha_salida": str(t["f_salida"]), "precio_salida": r2(t["px_salida"], 4),
            "resultado": r2(pnl), "resultado_pct": r2(pnl / t["costo_total"] * 100), "motivo": t["motivo"],
            "acciones": t["acciones"], "invertido": r2(t["costo_total"]), "soporte": r2(t["soporte"], 4),
            "resistencia": r2(t["resistencia"], 4), "ruedas": t["j"] - t["i"], "dias": (t["f_salida"] - t["fecha"]).days,
            "caida_pct": r2(t["caida_pct"], 1), "caida_dias": t["caida_dias"], "ajustado": bool(t["papel"].ajustes)}


def concentracion(cerradas, capital):
    """¿La ganancia se reparte o depende de pocas operaciones? (en pesos y como % del capital inicial)."""
    pnl = sorted((t["pnl"] for t in cerradas), reverse=True)
    total = sum(pnl)
    top1, top3 = sum(pnl[:1]), sum(pnl[:3])
    return {"ganancia_neta": r2(total, 0), "n": len(pnl), "n_ganadoras": sum(x > 0 for x in pnl),
            "top1_pct": r2(top1 / total * 100) if total > 0 else None, "top3_pct": r2(top3 / total * 100) if total > 0 else None,
            "sin_top1": r2(total - top1, 0), "sin_top3": r2(total - top3, 0),
            "sin_top3_pct_capital": r2((total - top3) / capital * 100)}


def resumen(res):
    """Las métricas que se comparan lado a lado entre estrategias o variantes de una misma estrategia."""
    m, b, lado = res["base"]["metricas"], res["base"], bt.costo_lado()
    abiertas = [(t["acciones"] * t["px_salida"] * (1 - lado) - t["costo_total"], t) for t in b["abiertas"]]
    pcts = [t["pnl_pct"] for t in b["cerradas"]]
    return {"ganancia_total": r2(m["ganancia_total"], 0), "ganancia_total_pct": r2(m["ganancia_total_pct"]),
            "profit_factor": r2(m["profit_factor"], 3), "payoff_ratio": r2(m["payoff_ratio"], 3),
            "ganadores_pct": r2(m["ganadores_pct"]), "trades": m["trades"],
            "max_drawdown": {"pct": r2(m["max_drawdown"]["pct"]), "monto": r2(m["max_drawdown"]["monto"], 0)},
            "ganancia_media_trade_pct": r2(m["ganancia_media_trade_pct"], 3), "cagr_pct": r2(m["cagr_pct"]),
            "duracion_media_dias": r2(m["duracion_media_dias"], 1), "mejor_trade_pct": r2(max(pcts), 1) if pcts else None,
            "peor_trade_pct": r2(min(pcts), 1) if pcts else None,
            "concentracion": concentracion(b["cerradas"], bt.PARAMS["capital"]),
            "abiertas": {"n": len(abiertas), "no_realizado": r2(sum(x for x, _ in abiertas), 0)},
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
    advertencias = [
        "BYMA entrega como máximo 2 años de histórico y la estrategia necesita 8 meses previos para calcular soportes: "
        f"el período operable es de {res['calendario'][0]} a {res['calendario'][1]}, no 2 años completos.",
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
    return {
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


def main():
    ap = argparse.ArgumentParser(description="Backtest de la estrategia base (cifrado y publicado en docs/data)")
    ap.add_argument("--cache", help="archivo JSON para guardar/leer el histórico (desarrollo local)")
    ap.add_argument("--solo-claro", metavar="ARCHIVO", help="escribe el resultado sin cifrar y no publica (desarrollo local)")
    ap.add_argument("--variante", choices=["base", "filtro_tendencia", "ruptura", "ruptura_trailing"], default="base",
                    help="base = estrategia de caídas; filtro_tendencia = caídas + cierre sobre la media de 200 ruedas (150 si no hay 200); "
                         "ruptura = estrategia NUEVA de ruptura al alza (se compara contra la de caídas); "
                         "ruptura_trailing = ruptura con trailing stop del 15%% en vez de las 20 ruedas (dos versiones, contra la de tiempo)")
    ap.add_argument("--hoy", metavar="AAAA-MM-DD", help="solo desarrollo: fija 'hoy' para reproducir una corrida (las velas desde esa fecha se descartan)")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    clave = os.environ.get("CLAVE_ACCESO", "")
    if not a.solo_claro and len(clave) < generar.MIN_CLAVE:
        sys.exit(f"Falta CLAVE_ACCESO (mínimo {generar.MIN_CLAVE} caracteres). Sin clave no se publica nada.")

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
    merval = bajar_merval()
    log("Merval: " + (f"{len(merval)} velas, último {merval[-1][1]:,.1f}" if merval else "NO disponible"))

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
    log(f"Backtest listo en {time.time() - t0:.0f} s: {res['senales_total']} señales, "
        f"{res['base']['metricas']['trades']} operaciones cerradas.")
    universo = {"papeles": papeles, "especies": len(especies)}
    salidas = []
    if a.variante == "ruptura_trailing":
        # Misma entrada, mismos datos, gestión y costos; solo cambia la SALIDA. Se publican dos informes (uno por versión del trailing),
        # y los dos traen la misma comparación contra la ruptura con salida por tiempo y contra el Merval.
        nombres = {"tiempo": "Tiempo 20 ruedas (original)", "trailing_stop": "Trailing 15% + stop de ruptura",
                   "trailing_solo": "Solo trailing 15%"}
        parametros = {"tiempo": ruptura.PARAMS_RUPTURA, "trailing_stop": ruptura.PARAMS_TRAILING, "trailing_solo": ruptura.PARAMS_TRAILING_SOLO}
        corridas = {k: bt.correr(papeles, merval, pk, generar=ruptura.senales_ruptura) for k, pk in parametros.items()}
        for k, rk in corridas.items():
            assert [d for d, _ in rk["base"]["serie"]] == [d for d, _ in corridas["tiempo"]["base"]["serie"]], "los calendarios deben ser idénticos"
        una_por_una = {k: {kk: r2(v, 3) for kk, v in bt.estadistica_senales(papeles, ruptura.senales_ruptura, pk).items()}
                       for k, pk in parametros.items()}
        for k in ("trailing_stop", "trailing_solo"):
            out = resultado_json(corridas[k], universo, ajustes, fallidos, hoy, rel, parametros[k])
            out["etiqueta"] = "Ruptura · " + nombres[k]
            out["estrategia"] = "ruptura"
            out["comparacion_salidas"] = {
                "principal": k, "nombres": nombres, **{kk: resumen(corridas[kk]) for kk in nombres}, "merval": out["merval"],
                "senales_una_por_una": una_por_una,
                "sensibilidad_inicio": {kk: [{k2: r2(v2, 2) if isinstance(v2, float) else v2 for k2, v2 in fila.items()}
                                             for fila in bt.sensibilidad_inicio(papeles, parametros[kk], ruptura.senales_ruptura, merval)]
                                        for kk in nombres},
                "regla": "Único cambio sobre la ruptura: la salida por tiempo (20 ruedas) se reemplaza por un trailing stop del 15%, sin límite de "
                         "días. El stop arranca 15% bajo la entrada, sube a 15% bajo el máximo cierre desde la compra y nunca baja; se vende "
                         "cuando el cierre lo toca. Mismas entradas, gestión y costos."}
            out["equity"]["extras"] = [{"n": nombres[kk], "v": [r2(e, 0) for _, e in corridas[kk]["base"]["serie"]]} for kk in nombres if kk != k]
            out["equity"]["nombre_base"] = nombres[k]
            salidas.append(out)
    else:
        out = resultado_json(res, universo, ajustes, fallidos, hoy, rel, p)
        out["etiqueta"] = {"base": "Base", "filtro_tendencia": "Con filtro de tendencia", "ruptura": "Ruptura al alza"}[a.variante]
        out["estrategia"] = "ruptura" if a.variante == "ruptura" else "caidas"
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
        if a.solo_claro:
            ruta = a.solo_claro if len(salidas) == 1 else a.solo_claro.replace(".json", f"_{k}.json")
            with open(ruta, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False)
            log(f"Resultado SIN cifrar escrito en {ruta} (no subir a ningún repositorio).")
        else:
            archivo = generar.guardar("backtest", out, clave_aes, etiqueta=out["etiqueta"])
            log(f"Guardado cifrado: docs/data/{archivo}")
        m = out["metricas"]
        print(f"BACKTEST [{out['etiqueta']}] {out['periodo']['inicio']} → {out['periodo']['fin']}: {m['trades']} operaciones, "
              f"ganancia {m['ganancia_total_pct']:+.1f}%, profit factor {m['profit_factor']}, "
              f"ganadoras {m['ganadores_pct']}%, max DD {m['max_drawdown']['pct']}%.")


if __name__ == "__main__":
    main()
