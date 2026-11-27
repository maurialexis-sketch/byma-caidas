"""
generar_sanmarino_dolar.py — Informe de la pestaña SAINT MARINO DÓLAR: lo mismo que SAN MARINO (listado 1 «a punto de cruzar» y listado 2 «despegó», con el MACD y el Vortex; macd.py explica las reglas)
pero sobre los CEDEARs que Bull Market ofrece EN DÓLARES (cedears_dolar.json, del PDF del dueño) y evaluando el GRÁFICO DE LA BOLSA DE NUEVA YORK, en dólares, de Yahoo Finance (no el precio del CEDEAR en BYMA).
Publica el resultado CIFRADO en docs/data (funcion = «sanmarinodolar»). No es un backtest ni una recomendación. No usa BYMA para los precios: no le afecta que BYMA esté caído.

    python generar_sanmarino_dolar.py                      CLAVE_ACCESO en el entorno (en GitHub: un "secret")
    python generar_sanmarino_dolar.py --programado         corrida automática: si Nueva York no tuvo rueda o faltan datos, saltea y avisa (no falla)
    python generar_sanmarino_dolar.py --dist 0,8 --dias 3  cambia parámetros (quedan guardados en parametros_macd_dolar.json)
    python generar_sanmarino_dolar.py --cache c.json       guarda/usa el histórico bajado (desarrollo local)
    python generar_sanmarino_dolar.py --solo-claro r.json  escribe el resultado SIN cifrar y no publica (desarrollo local)
"""
import argparse, json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import requests

import backtest as bt
import fuente_ny as ny
import generar, generar_backtest as gb, generar_informe as gi, indices, macd, parametros_macd_dolar as pd, reloj, sectores

FUNCION = "sanmarinodolar"
AVISO = "Filtro objetivo para decidir mirando el gráfico. No es una recomendación de compra."
NOTA = ("Las señales salen del gráfico de la bolsa de Nueva York (Yahoo Finance, en dólares) del activo que respalda cada CEDEAR, no del precio del CEDEAR en BYMA: no incluyen el efecto del tipo de cambio ni del ratio. "
        "«Operable» se mide sobre la línea en dólares (D) del CEDEAR en BYMA, con lo operado en el día. Es una señal de aviso, no una predicción: el cruce puede no ocurrir.")
WORKERS = 4
MIN_RESPUESTAS = 0.5          # corrida programada: si Yahoo devolvió datos para menos de esta fracción de los tickers, se saltea


def anotar(texto, nivel="warning"):
    """Aviso visible en la corrida de GitHub Actions (anotación y resumen) sin hacerla fallar."""
    print(f"::{nivel} title=Saint Marino Dólar::{texto}")
    resumen = os.environ.get("GITHUB_STEP_SUMMARY")
    if resumen:
        with open(resumen, "a", encoding="utf-8") as f:
            f.write(f"### Saint Marino Dólar\n\n{texto}\n")


def armar_salteado(motivo, rel, valores, ref=None, datos=None):
    """Registro (cifrado como cualquier informe) que avisa en la página que ese día no se generó informe, y por qué."""
    ahora = rel.ahora().isoformat(timespec="seconds")
    return {"funcion": FUNCION, "moneda": "USD", "salteado": True, "motivo": motivo, "generado": ahora, "fecha_datos": str(ref) if ref else None,
            "parametros": pd.descripcion(valores), "datos": datos or {},
            "contexto": {"hora_mercado": ahora, "fuente_hora": rel.fuente, "origen": "programada", "advertencias": []}}


def motivo_de_salteo(ahora_ny, ref, n_items, n_con_datos):
    """Para la corrida PROGRAMADA: por qué no corresponde publicar el informe (texto), o None si está todo para publicarlo. Igual criterio que generar_informe.motivo_de_salteo, con el calendario de Nueva York."""
    esperada = ny.rueda_esperada_ny(ahora_ny)
    if esperada is None:
        return f"La corrida programada arrancó con la rueda de Nueva York en curso o en un día no hábil ({ahora_ny:%d/%m/%Y %H:%M} hora de Nueva York): no se genera el informe."
    if ref is None:
        return "Yahoo Finance no devolvió datos de precios: no se puede generar el informe."
    if ref < esperada:
        cuando = f"Hoy ({ahora_ny:%d/%m/%Y})" if esperada == ahora_ny.date() else f"El {esperada:%d/%m/%Y}"
        return (f"{cuando} no hay datos de la rueda de Nueva York: pudo ser feriado o un día sin operaciones, o Yahoo todavía no publicó el cierre. "
                f"La última rueda con datos es la del {ref:%d/%m/%Y}.")
    if n_items and n_con_datos < MIN_RESPUESTAS * n_items:
        return f"Yahoo Finance respondió con datos para solo {n_con_datos} de {n_items} papeles: el informe saldría incompleto."
    return None


def aviso_de_atraso(ahora_ny):
    """Aviso para el informe de una corrida programada que llegó con atraso (la rueda que informa no es la de hoy); lista vacía si llegó a su hora."""
    esperada = ny.rueda_esperada_ny(ahora_ny)
    if esperada is None or esperada == ahora_ny.date():
        return []
    return [f"La corrida programada llegó con atraso (GitHub la lanzó el {ahora_ny:%d/%m/%Y} a las {ahora_ny:%H:%M}, hora de Nueva York): el informe es de la rueda del {esperada:%d/%m/%Y}."]


def bajar_historico(items, cache=None):
    """{yahoo: velas} con pedidos en paralelo y un segundo pase de a uno; devuelve también los que no respondieron (Yahoo caído o error), no los que Yahoo no tiene."""
    if cache and os.path.exists(cache):
        with open(cache, encoding="utf-8") as f:
            c = json.load(f)
        gb.log(f"Histórico leído de la caché ({len(c['barras'])} papeles).")
        return c["barras"], c["fallidos"]

    def uno(t):
        try:
            return ny.get_daily_ohlc(t, gb.DIAS)
        except Exception as e:
            return e
    tickers = [e["yahoo"] for e in items]
    t0 = time.time()
    with ThreadPoolExecutor(WORKERS) as ex:
        res = list(ex.map(uno, tickers))
    res = [uno(t) if isinstance(r, Exception) else r for t, r in zip(tickers, res)]
    barras = {t: r for t, r in zip(tickers, res) if not isinstance(r, Exception) and r}
    fallidos = [t for t, r in zip(tickers, res) if isinstance(r, Exception)]
    gb.log(f"Histórico de Nueva York: {len(barras)} papeles con datos, {len(fallidos)} sin respuesta, {len(tickers) - len(barras) - len(fallidos)} que Yahoo no tiene, {time.time() - t0:.0f} s.")
    if cache:
        with open(cache, "w", encoding="utf-8") as f:
            json.dump({"barras": barras, "fallidos": fallidos}, f)
    return barras, fallidos


def _filas(lista):
    """Las filas de una lista redondeadas para publicar."""
    r2 = lambda x: None if x is None else round(x, 4)
    filas = [{k: (r2(v) if isinstance(v, float) else ([r2(x) for x in v] if k == "hist_pct_ult" else v)) for k, v in f.items()} for f in lista]
    for f in filas:
        f["ruedas_al_cruce"] = None if f["ruedas_al_cruce"] is None else round(f["ruedas_al_cruce"], 1)
    return filas


def armar(res, res2, vara, fecha_datos, universo, rel, avisos, datos, valores, origen, cambios):
    """Diccionario del informe a partir de los resultados de macd.listado (listado 1) y macd.listado2 (listado 2) y la vara."""
    p = pd.de_params(valores)
    filas, filas2 = _filas(res["lista"]), _filas(res2["lista"])
    return {"funcion": FUNCION, "moneda": "USD", "generado": rel.ahora().isoformat(timespec="seconds"), "fecha_datos": str(fecha_datos), "aviso": AVISO, "nota": NOTA,
            "universo": {**universo, "evaluados": res["evaluados"]}, "vara": vara, "lista": filas, "embudo": res["embudo"], "resumen": res["resumen"], "piso_millones": res["piso_millones"],
            "mensaje": None if filas else "Hoy ningún CEDEAR está a punto de cruzar", "avisos": avisos, "datos": datos,
            "lista2": filas2, "embudo2": res2["embudo"], "resumen2": res2["resumen"],
            "mensaje2": None if filas2 else "Hoy ningún CEDEAR despegó por encima de la señal con estas condiciones",
            "parametros": {**pd.descripcion(valores), "cambios": cambios},
            "criterios": {"macd": f"EMA {p['rapido']} − EMA {p['lento']}", "senal": f"EMA {p['senal']} del MACD", "dias": p["dias"], "dist_pct": p["dist_pct"], "bajo_cero": p["bajo_cero"],
                          "ruedas_minimas": macd.ruedas_minimas(p), "dist2_pct": p["dist2_pct"], "ruedas_cruce": p["ruedas_cruce"], "vortex_exigir": p["vortex_exigir"], "vortex_periodo": p["vortex_periodo"]},
            "contexto": {"hora_mercado": rel.ahora().isoformat(timespec="seconds"), "fuente_hora": rel.fuente, "origen": origen, "advertencias": []}}


def main():
    ap = argparse.ArgumentParser(description="Informe SAINT MARINO DÓLAR (MACD sobre el gráfico de Nueva York de los CEDEARs en dólares), cifrado y publicado en docs/data")
    ap.add_argument("--cache", help="archivo JSON para guardar/leer el histórico (desarrollo local)")
    ap.add_argument("--solo-claro", metavar="ARCHIVO", help="escribe el resultado sin cifrar y no publica (desarrollo local)")
    ap.add_argument("--hoy", metavar="AAAA-MM-DD", help="solo desarrollo: fija la fecha de corte (se descartan las velas desde ese día)")
    ap.add_argument("--programado", action="store_true", help="corrida automática: si Nueva York no tuvo rueda o faltan datos, la saltea y lo avisa (no falla)")
    ap.add_argument("--parametros", default=pd.ARCHIVO, help="archivo donde quedan guardados los parámetros editables")
    ap.add_argument("--universo", default=None, help="solo desarrollo: otro archivo de universo")
    for c, ayuda in (("rapido", "período de la EMA rápida"), ("lento", "período de la EMA lenta"), ("senal", "período de la señal"), ("dias", "ruedas con el histograma subiendo"),
                     ("dist", "distancia máxima a la señal, en %% del precio"), ("bajo-cero", "1 = exigir MACD bajo cero, 0 = no"), ("piso", "piso de liquidez para «operable», en miles de US$"),
                     ("dist2", "listado 2: separación máxima sobre la señal, en %% del precio"), ("ruedas-cruce", "listado 2: ruedas desde el cruce, como máximo"),
                     ("vortex", "listado 2: 1 = exigir la confirmación del Vortex (VI+ > VI−), 0 = no")):
        ap.add_argument("--" + c, default="", help=f"{ayuda}; vacío = el valor guardado")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    contrasena = os.environ.get("CLAVE_ACCESO", "")           # (la contraseña de cifrado: no reasignar este nombre en ningún bucle)
    if not a.solo_claro and len(contrasena) < generar.MIN_CLAVE:
        sys.exit(f"Falta CLAVE_ACCESO (mínimo {generar.MIN_CLAVE} caracteres). Sin clave no se publica nada.")

    try:
        guardados = pd.cargar(a.parametros)
        valores, cambios = pd.combinar(guardados, {"macd_rapido": a.rapido, "macd_lento": a.lento, "macd_senal": a.senal, "macd_dias": a.dias, "macd_dist_pct": a.dist,
                                                   "macd_bajo_cero": getattr(a, "bajo_cero"), "dolar_piso_miles": a.piso,
                                                   "macd2_dist_pct": a.dist2, "macd2_ruedas": getattr(a, "ruedas_cruce"), "vortex_exigir": a.vortex})
        pd.validar(valores)
    except pd.ErrorParametro as ex:
        sys.exit(f"Parámetros inválidos, no se generó nada: {ex}")
    params = pd.de_params(valores)
    textos_cambios = [f"{pd.POR_CLAVE[c]['nombre']}: {v0:g} → {v1:g}" for c, (v0, v1) in cambios.items()]
    gb.log("Parámetros: " + ", ".join(f"{c}={v:g}" for c, v in valores.items()) + (" (cambiados en esta corrida: " + "; ".join(textos_cambios) + ")" if cambios else " (los guardados)"))
    origen = "programada" if a.programado else "manual"

    def publicar_salteo(motivo, rel, ref=None, datos=None):
        out = armar_salteado(motivo, rel, guardados, ref, datos)      # un salteo no aplica ni guarda lo que se pidió en esta corrida
        anotar("SALTEADO: " + motivo)
        if a.solo_claro:
            with open(a.solo_claro, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=1)
        else:
            gb.log("Guardado cifrado (aviso de informe salteado): docs/data/" + generar.guardar(FUNCION, out, generar.derivar(contrasena, generar.cargar_meta()), etiqueta="SALTEADO"))

    rel = reloj.Reloj()
    try:
        rel.sincronizar()
    except reloj.RelojError as ex:
        if not a.programado:
            raise
        rel = gi.RelojServidor()
        gb.log(f"AVISO: {ex}; se usa el reloj del servidor.")
    ahora = rel.ahora()
    ahora_ny = ny.hora_ny(ahora)
    corte = date.fromisoformat(a.hoy) if a.hoy else ny.corte_de_datos_ny(ahora_ny)
    gb.log(f"Hora de mercado: {ahora.isoformat(timespec='seconds')} — {rel.fuente} (Nueva York: {ahora_ny:%d/%m/%Y %H:%M}). Se usan velas anteriores al {corte}.")

    items = ny.universo(a.universo)
    gb.log(f"Universo: {len(items)} CEDEARs en dólares ({sum(len(e['simbolos']) for e in items)} líneas D) → gráficos de Nueva York.")
    barras, fallidos = bajar_historico(items, a.cache)
    avisos, datos = [], {"fuente": ny.NOMBRE}
    if a.programado:
        avisos += aviso_de_atraso(ahora_ny)
    papeles = [bt.Papel(t, "cedear", b, corte) for t, b in barras.items()]
    papeles = [p for p in papeles if p.f]
    ref = gi.fecha_de_referencia(papeles)
    if ref is None:
        if a.programado:
            return publicar_salteo("Yahoo Finance no devolvió datos de precios: no se puede generar el informe.", rel, None, datos)
        sys.exit("No hay datos para evaluar.")
    sin_fecha = [p.ticker for p in papeles if p.f[-1] != ref]
    papeles = [bt.Papel(p.ticker, p.tipo, barras[p.ticker], ref + timedelta(days=1)) for p in papeles if p.f[-1] == ref]       # todos, en la misma fecha
    datos["fecha_referencia"] = str(ref)
    datos["sin_cotizacion_en_la_fecha"] = len(sin_fecha)
    if a.programado:
        motivo = motivo_de_salteo(ahora_ny, ref, len(items), len(papeles) + len(sin_fecha))
        if motivo:
            return publicar_salteo(motivo, rel, ref, datos)
    elif sesion_incompleta(ahora_ny, ref, a.hoy):
        avisos.append(f"Los datos llegan hasta la rueda del {ref:%d/%m/%Y}. Si hoy hubo rueda en Nueva York, Yahoo todavía no la publicó y el informe se refiere a la rueda anterior.")

    try:                                                              # la vara (S&P 500 en dólares) es contexto: si Yahoo no responde, el informe sale igual y lo dice
        serie = indices.bajar_yahoo(indices.YAHOO_SIMBOLO["sp500_usd"])
        vara = gi.vara_12m({"sp500_usd": serie}, ref) if serie else {}
        if not serie:
            avisos.append("No se pudo obtener el índice de referencia (S&P 500): el informe sale sin la vara.")
    except Exception as ex:
        vara = {}
        avisos.append(f"No se pudo obtener el índice de referencia ({type(ex).__name__}): el informe sale sin la vara.")

    liq = ny.liquidez_cedears(items)
    if not liq:
        avisos.append("No se pudo consultar lo operado hoy en las líneas en dólares de BYMA: ningún papel se marca «operable» (todos quedan «solo señal»).")
    piso_usd = params["piso_millones"] * 1e6
    nombre = {e["yahoo"]: e["nombre"] for e in items}
    linea = {e["yahoo"]: e["simbolos"] for e in items}

    def liquidez(pa):
        l = liq.get(pa.ticker)
        extra = {"nombre": nombre.get(pa.ticker), "lineas_d": linea.get(pa.ticker, [])}
        if not l:
            return {"monto_dia": None, "volumen_dia": None, "operable": False, "extra": {**extra, "sin_dato_liquidez": True}}
        return {"monto_dia": l["monto_dia"], "volumen_dia": l["volumen_dia"], "operable": l["monto_dia"] >= piso_usd, "extra": {**extra, "linea_d": l["linea"]}}

    datos_sectores = sectores.cargar()
    etiquetar = lambda t: nombre.get(t, t)
    res = macd.listado(papeles, params, datos_sectores, etiquetar, liquidez)
    res2 = macd.listado2(papeles, params, datos_sectores, etiquetar, liquidez)
    for f in res["lista"] + res2["lista"]:
        et = sectores.etiquetar(f["ticker"], "cedear", datos_sectores)
        f["grupo"], f["sector"], f["subsector"] = et["grupo"], et["sector"], et["subsector"]
    universo = {"especies": len(items), "con_datos": len(papeles), "sin_respuesta": fallidos, "sin_cotizacion_en_la_fecha": len(sin_fecha)}
    gb.log(f"Saint Marino Dólar (datos al {ref}): {res['evaluados']} evaluados, {res['embudo']['debajo']} con el MACD bajo la señal, {res['embudo']['subiendo']} con el histograma subiendo, "
           f"{res['resumen']['total']} a punto de cruzar ({res['resumen']['operables']} operables).")
    e2 = res2["embudo"]
    gb.log(f"Saint Marino Dólar, listado 2 (despegó): {e2['arriba']} con el MACD sobre la señal, {e2['reciente']} con cruce reciente, {e2['se_separa']} separándose, {e2['pegado']} con poca separación, "
           f"{res2['resumen']['total']} con la confirmación del Vortex ({res2['resumen']['operables']} operables).")
    out = armar(res, res2, vara, ref, universo, rel, avisos, datos, valores, origen, textos_cambios)

    if a.solo_claro:
        with open(a.solo_claro, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        gb.log(f"Resultado SIN cifrar escrito en {a.solo_claro} (no subir a ningún repositorio).")
    else:
        archivo = generar.guardar(FUNCION, out, generar.derivar(contrasena, generar.cargar_meta()))
        gb.log(f"Guardado cifrado: docs/data/{archivo}")
        if cambios or not os.path.exists(a.parametros):
            pd.guardar(valores, a.parametros)
            gb.log(f"Parámetros guardados para la próxima corrida en {os.path.basename(a.parametros)}.")
    print(f"SAINT MARINO DÓLAR datos al {ref}: {res['evaluados']} papeles evaluados → {res['resumen']['total']} a punto de cruzar, {res2['resumen']['total']} despegaron"
          + ("" if out["lista"] else f". {out['mensaje']}"))


def sesion_incompleta(ahora_ny, ref, hoy_fijado):
    """Corrida manual: ¿la rueda de Nueva York de hoy ya terminó pero los datos llegan hasta una fecha anterior?"""
    return (not hoy_fijado) and ny.sesion_cerrada_ny(ahora_ny) and ref < ahora_ny.date()


if __name__ == "__main__":
    main()
