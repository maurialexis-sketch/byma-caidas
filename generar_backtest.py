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
import config, conector, generar, reloj

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


def resultado_json(res, universo, ajustes, fallidos, hoy, rel):
    p, lado = bt.PARAMS, bt.costo_lado()
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
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    clave = os.environ.get("CLAVE_ACCESO", "")
    if not a.solo_claro and len(clave) < generar.MIN_CLAVE:
        sys.exit(f"Falta CLAVE_ACCESO (mínimo {generar.MIN_CLAVE} caracteres). Sin clave no se publica nada.")

    rel = reloj.Reloj()
    conector.RELOJ = rel.epoch
    rel.sincronizar()
    hoy = rel.ahora().date()
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
    res = bt.correr(papeles, merval)
    if not res:
        sys.exit("El backtest no encontró ninguna señal.")
    log(f"Backtest listo en {time.time() - t0:.0f} s: {res['senales_total']} señales, "
        f"{res['base']['metricas']['trades']} operaciones cerradas.")
    out = resultado_json(res, {"papeles": papeles, "especies": len(especies)}, ajustes, fallidos, hoy, rel)

    if a.solo_claro:
        with open(a.solo_claro, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False)
        log(f"Resultado SIN cifrar escrito en {a.solo_claro} (no subir a ningún repositorio).")
    else:
        archivo = generar.guardar("backtest", out, generar.derivar(clave, generar.cargar_meta()))
        log(f"Guardado cifrado: docs/data/{archivo}")
    m = out["metricas"]
    print(f"BACKTEST {out['periodo']['inicio']} → {out['periodo']['fin']}: {m['trades']} operaciones, "
          f"ganancia {m['ganancia_total_pct']:+.1f}%, profit factor {m['profit_factor']}, "
          f"ganadoras {m['ganadores_pct']}%, max DD {m['max_drawdown']['pct']}%.")


if __name__ == "__main__":
    main()
