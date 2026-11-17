"""
generar_sanmarino.py — Informe de la pestaña SAN MARINO: los CEDEARs donde la línea MACD está por debajo de la señal y a punto de cruzarla hacia arriba (macd.py explica las reglas).
Baja el mismo universo de BYMA que el informe de candidatos, y publica el resultado CIFRADO en docs/data (funcion = «sanmarino»). No es un backtest ni una recomendación.
Funciona igual que el informe de candidatos: parámetros editables que quedan guardados (parametros_macd.json), corrida a demanda y programada, y si hoy no hubo rueda lo saltea y avisa.

    python generar_sanmarino.py                      CLAVE_ACCESO en el entorno (en GitHub: un "secret")
    python generar_sanmarino.py --programado         corrida automática: si hoy no hubo rueda o faltan datos, saltea y avisa (no falla)
    python generar_sanmarino.py --dist 0,8 --dias 3  cambia parámetros (quedan guardados en parametros_macd.json)
    python generar_sanmarino.py --cache c.json       guarda/usa el histórico bajado (desarrollo local)
    python generar_sanmarino.py --solo-claro r.json  escribe el resultado SIN cifrar y no publica (desarrollo local)
"""
import argparse, json, os, sys
from datetime import date, timedelta

import requests

import backtest as bt
import conector, generar, generar_backtest as gb, generar_informe as gi, indices, macd, parametros_macd as pm, reloj, sectores

AVISO = "Filtro objetivo para decidir mirando el gráfico. No es una recomendación de compra."
NOTA_PESOS = ("El MACD se calcula sobre el precio del CEDEAR en pesos: mezcla el movimiento del activo con el del dólar. "
              "Es una señal de aviso, no una predicción: el cruce puede no ocurrir.")


def anotar(texto, nivel="warning"):
    """Aviso visible en la corrida de GitHub Actions (anotación y resumen) sin hacerla fallar."""
    print(f"::{nivel} title=San Marino::{texto}")
    resumen = os.environ.get("GITHUB_STEP_SUMMARY")
    if resumen:
        with open(resumen, "a", encoding="utf-8") as f:
            f.write(f"### San Marino\n\n{texto}\n")


def armar_salteado(motivo, rel, valores, ref=None, datos=None):
    """Registro (cifrado como cualquier informe) que avisa en la página que ese día no se generó informe, y por qué."""
    ahora = rel.ahora().isoformat(timespec="seconds")
    return {"funcion": "sanmarino", "salteado": True, "motivo": motivo, "generado": ahora, "fecha_datos": str(ref) if ref else None,
            "parametros": pm.descripcion(valores), "datos": datos or {},
            "contexto": {"hora_mercado": ahora, "fuente_hora": rel.fuente, "origen": "programada", "advertencias": []}}


def armar(res, vara, fecha_datos, universo, rel, avisos, datos, valores, origen, cambios):
    """Diccionario del informe a partir del resultado de macd.listado y la vara."""
    p = macd.de_params(valores)
    r2 = lambda x: None if x is None else round(x, 4)
    filas = [{k: (r2(v) if isinstance(v, float) else ([r2(x) for x in v] if k == "hist_pct_ult" else v)) for k, v in f.items()} for f in res["lista"]]
    for f in filas:                                                                    # (los montos y el precio se muestran con pocos decimales)
        f["ruedas_al_cruce"] = None if f["ruedas_al_cruce"] is None else round(f["ruedas_al_cruce"], 1)
    return {"funcion": "sanmarino", "generado": rel.ahora().isoformat(timespec="seconds"), "fecha_datos": str(fecha_datos), "aviso": AVISO, "nota": NOTA_PESOS,
            "universo": {**universo, "evaluados": res["evaluados"]}, "vara": vara, "lista": filas, "embudo": res["embudo"], "resumen": res["resumen"], "piso_millones": res["piso_millones"],
            "mensaje": None if filas else "Hoy ningún CEDEAR está a punto de cruzar", "avisos": avisos, "datos": datos,
            "parametros": {**pm.descripcion(valores), "cambios": cambios},
            "criterios": {"macd": f"EMA {p['rapido']} − EMA {p['lento']}", "senal": f"EMA {p['senal']} del MACD", "dias": p["dias"], "dist_pct": p["dist_pct"], "bajo_cero": p["bajo_cero"],
                          "ruedas_minimas": macd.ruedas_minimas(p)},
            "contexto": {"hora_mercado": rel.ahora().isoformat(timespec="seconds"), "fuente_hora": rel.fuente, "origen": origen, "advertencias": []}}


def main():
    ap = argparse.ArgumentParser(description="Informe SAN MARINO (MACD a punto de cruzar), cifrado y publicado en docs/data")
    ap.add_argument("--cache", help="archivo JSON para guardar/leer el histórico (desarrollo local)")
    ap.add_argument("--solo-claro", metavar="ARCHIVO", help="escribe el resultado sin cifrar y no publica (desarrollo local)")
    ap.add_argument("--hoy", metavar="AAAA-MM-DD", help="solo desarrollo: fija la fecha de corte (se descartan las velas desde ese día)")
    ap.add_argument("--programado", action="store_true", help="corrida automática: si hoy no hubo rueda o faltan datos, la saltea y lo avisa (no falla)")
    ap.add_argument("--parametros", default=pm.ARCHIVO, help="archivo donde quedan guardados los parámetros editables")
    for c, ayuda in (("rapido", "período de la EMA rápida"), ("lento", "período de la EMA lenta"), ("senal", "período de la señal"), ("dias", "ruedas con el histograma subiendo"),
                     ("dist", "distancia máxima a la señal, en %% del precio"), ("bajo-cero", "1 = exigir MACD bajo cero, 0 = no"), ("piso", "piso de liquidez para «operable», en millones de $")):
        ap.add_argument("--" + c, default="", help=f"{ayuda}; vacío = el valor guardado")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    contrasena = os.environ.get("CLAVE_ACCESO", "")           # (la contraseña de cifrado: no reasignar este nombre en ningún bucle)
    if not a.solo_claro and len(contrasena) < generar.MIN_CLAVE:
        sys.exit(f"Falta CLAVE_ACCESO (mínimo {generar.MIN_CLAVE} caracteres). Sin clave no se publica nada.")

    try:
        guardados = pm.cargar(a.parametros)
        valores, cambios = pm.combinar(guardados, {"macd_rapido": a.rapido, "macd_lento": a.lento, "macd_senal": a.senal, "macd_dias": a.dias, "macd_dist_pct": a.dist,
                                                   "macd_bajo_cero": getattr(a, "bajo_cero"), "macd_piso_millones": a.piso})
        pm.validar(valores)
    except pm.ErrorParametro as ex:
        sys.exit(f"Parámetros inválidos, no se generó nada: {ex}")
    params = macd.de_params(valores)
    textos_cambios = [f"{pm.POR_CLAVE[c]['nombre']}: {v0:g} → {v1:g}" for c, (v0, v1) in cambios.items()]
    gb.log("Parámetros: " + ", ".join(f"{c}={v:g}" for c, v in valores.items()) + (" (cambiados en esta corrida: " + "; ".join(textos_cambios) + ")" if cambios else " (los guardados)"))
    origen = "programada" if a.programado else "manual"

    def publicar_salteo(motivo, rel, ref=None, datos=None):
        out = armar_salteado(motivo, rel, guardados, ref, datos)      # un salteo no aplica ni guarda lo que se pidió en esta corrida
        anotar("SALTEADO: " + motivo)
        if a.solo_claro:
            with open(a.solo_claro, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=1)
        else:
            gb.log("Guardado cifrado (aviso de informe salteado): docs/data/" + generar.guardar("sanmarino", out, generar.derivar(contrasena, generar.cargar_meta()), etiqueta="SALTEADO"))

    rel = reloj.Reloj()
    conector.RELOJ = rel.epoch
    try:
        rel.sincronizar()
    except reloj.RelojError as ex:
        if not a.programado:
            raise
        rel = gi.RelojServidor()
        conector.RELOJ = lambda: rel.ahora().timestamp()
        gb.log(f"AVISO: {ex}; se usa el reloj del servidor.")
    corte = date.fromisoformat(a.hoy) if a.hoy else gi.corte_de_datos(rel.ahora())
    gb.log(f"Hora de mercado: {rel.ahora().isoformat(timespec='seconds')} — {rel.fuente}. Se usan velas anteriores al {corte}.")

    try:
        especies = conector.universo()
        if not especies and a.programado:
            raise RuntimeError("BYMA devolvió un universo vacío")
    except (requests.RequestException, RuntimeError, ValueError) as ex:
        if not a.programado:
            raise
        return publicar_salteo(f"No se pudo obtener el universo de papeles de BYMA ({type(ex).__name__}): {ex}", rel)
    gb.log(f"Universo: {len(especies)} especies en pesos.")
    barras, fallidos = gb.bajar_historico(especies, a.cache)
    ahora = rel.ahora()
    avisos, datos = [], {}
    avisos += gi.avisos_de_fuente(datos)
    if not a.hoy and gi.sesion_cerrada(ahora) and conector.FUENTE != "respaldo":   # con la fuente de respaldo no hay panel de BYMA con qué armar la vela de hoy
        try:
            barras, datos["vela_de_hoy"] = gi.completar_con_panel(barras, gi.filas_panel(), ahora.date())
        except (requests.RequestException, RuntimeError, ValueError) as ex:
            if not a.programado:
                raise
            datos["vela_de_hoy"] = {"revisados": 0, "coherentes": 0, "agregadas": 0, "usada": False, "motivo": f"el panel de BYMA no respondió ({type(ex).__name__})"}
            avisos.append("El panel de BYMA no respondió: no se pudo completar la vela de hoy.")
        aviso = gi.aviso_vela_de_hoy(datos["vela_de_hoy"])
        if aviso:
            avisos.append(aviso)
    papeles = [bt.Papel(t, especies.get(t, "accion"), b, corte) for t, b in barras.items()]
    papeles = [p for p in papeles if p.f]
    ref = gi.fecha_de_referencia(papeles)
    if ref is None:
        if a.programado:
            return publicar_salteo("BYMA no devolvió datos de precios: no se puede generar el informe.", rel, None, datos)
        sys.exit("No hay datos para evaluar.")
    sin_fecha = [p.ticker for p in papeles if p.f[-1] != ref]
    papeles = [bt.Papel(p.ticker, p.tipo, barras[p.ticker], ref + timedelta(days=1)) for p in papeles if p.f[-1] == ref]   # todos, en la misma fecha
    datos["fecha_referencia"] = str(ref)
    datos["sin_cotizacion_en_la_fecha"] = len(sin_fecha)
    vol = gi.volumen_relativo(papeles, params["piso_millones"] * 1e6)
    datos["volumen_relativo_ultima_rueda"] = None if vol is None else round(vol, 2)
    if a.programado:
        motivo = gi.motivo_de_salteo(ahora, ref, len(especies), len(papeles) + len(sin_fecha), vol)
        if motivo:
            return publicar_salteo(motivo, rel, ref, datos)
    else:
        if gi.sesion_cerrada(ahora) and ref < ahora.date() and not a.hoy:
            avisos.append(f"Los datos llegan hasta la rueda del {ref:%d/%m/%Y}. Si hoy hubo rueda, BYMA todavía no la publicó y el informe se refiere a la rueda anterior.")
        if vol is not None and vol < gi.VOLUMEN_MIN:
            avisos.append(f"La última rueda parece incompleta: el monto mediano de los papeles líquidos es el {vol * 100:.0f}% del normal.")
    assert not any(indices.es_indice(p.ticker) for p in papeles), "un índice no puede ser un papel operable"

    try:                                                              # la vara (S&P 500 en pesos) es contexto: si Yahoo no responde, el informe sale igual y lo dice
        vara = gi.vara_12m(indices.bajar_todos(barras, ref + timedelta(days=1)), ref)
    except Exception as ex:
        vara = {}
        avisos.append(f"No se pudo obtener el índice de referencia ({type(ex).__name__}): el informe sale sin la vara.")

    datos_sectores = sectores.cargar()
    por_ticker = {p.ticker: p for p in papeles}
    etiquetar = lambda t: sectores.etiquetar(t, por_ticker[t].tipo, datos_sectores)["subyacente"]
    res = macd.listado(papeles, params, datos_sectores, etiquetar)
    for f in res["lista"]:
        et = sectores.etiquetar(f["ticker"], "cedear", datos_sectores)
        f["grupo"], f["sector"], f["subsector"] = et["grupo"], et["sector"], et["subsector"]
    universo = {"especies": len(especies), "con_datos": len(papeles), "sin_respuesta": fallidos, "sin_cotizacion_en_la_fecha": len(sin_fecha)}
    gb.log(f"San Marino (CEDEARs, datos al {ref}): {res['evaluados']} evaluados, {res['embudo']['debajo']} con el MACD bajo la señal, {res['embudo']['subiendo']} con el histograma subiendo, "
           f"{res['resumen']['total']} a punto de cruzar ({res['resumen']['operables']} operables).")
    out = armar(res, vara, ref, universo, rel, avisos, datos, valores, origen, textos_cambios)

    if a.solo_claro:
        with open(a.solo_claro, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        gb.log(f"Resultado SIN cifrar escrito en {a.solo_claro} (no subir a ningún repositorio).")
    else:
        archivo = generar.guardar("sanmarino", out, generar.derivar(contrasena, generar.cargar_meta()))
        gb.log(f"Guardado cifrado: docs/data/{archivo}")
        if cambios or not os.path.exists(a.parametros):
            pm.guardar(valores, a.parametros)
            gb.log(f"Parámetros guardados para la próxima corrida en {os.path.basename(a.parametros)}.")
    print(f"SAN MARINO datos al {ref}: {res['evaluados']} CEDEARs evaluados → {res['resumen']['total']} a punto de cruzar"
          + ("" if out["lista"] else f". {out['mensaje']}"))


if __name__ == "__main__":
    main()
