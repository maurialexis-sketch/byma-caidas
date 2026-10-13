"""
generar_informe.py — Informe diario de candidatos (a demanda): baja el universo líquido de BYMA, aplica los filtros de informe.py y publica el resultado
CIFRADO en docs/data (lo lee la misma página, pestaña CANDIDATOS). No es un backtest ni una recomendación.

    python generar_informe.py                       CLAVE_ACCESO en el entorno (en GitHub: un "secret")
    python generar_informe.py --cache c.json        guarda/usa el histórico bajado (desarrollo local)
    python generar_informe.py --solo-claro r.json   escribe el resultado SIN cifrar y no publica (desarrollo local)
"""
import argparse, collections, json, os, sys
from datetime import date, datetime, timedelta

import backtest as bt
import config, conector, generar, generar_backtest as gb, indices, informe, reloj, sectores

HORA_CIERRE_COMPLETO = (17, 30)   # a partir de esta hora la vela del día ya está completa; antes, la de hoy puede venir a medias y no se usa


MIN_COHERENTES = 0.8              # para armar la vela de hoy con el panel, al menos esta fracción de los papeles tiene que ser coherente con el histórico
TOLERANCIA_PREVIO = 0.005         # el cierre previo del panel tiene que coincidir (±0,5%) con el último cierre del histórico
VOLUMEN_MIN = 0.5                 # si el volumen mediano de la última rueda es menos de esta fracción del normal, se avisa que parece incompleta


def sesion_cerrada(ahora):
    """Día hábil con la rueda ya terminada (la vela de hoy ya debería estar completa)."""
    return ahora.weekday() < 5 and (ahora.hour, ahora.minute) >= HORA_CIERRE_COMPLETO


def filas_panel():
    """{ticker: fila} de los paneles de BYMA (líder, general y CEDEARs), solo especies en pesos."""
    filas = {}
    for panel in config.PANELES:
        pagina, paginas = 1, 1
        while pagina <= paginas:
            d = conector._post(config.PANEL_BASE + panel, {"excludeZeroPxAndQty": False, "T1": True, "T0": False, "page_number": pagina}).json()
            for f in (d if isinstance(d, list) else d.get("data", [])):
                if f.get("denominationCcy") == "ARS":
                    filas.setdefault(f["symbol"], f)
            if isinstance(d, dict):
                paginas = d.get("content", {}).get("page_count", 1) or 1
            pagina += 1
    return filas


def _fecha(vela):
    return datetime.fromtimestamp(vela["t"], bt.AR).date()


def completar_con_panel(barras, filas, hoy):
    """Si el histórico de BYMA todavía no trae la rueda de hoy, arma la vela de hoy con el panel (apertura, máximo, mínimo, cierre y volumen del día).
    Solo se usa si el panel es COHERENTE con el histórico: su 'cierre previo' tiene que coincidir con el último cierre del histórico en al menos
    MIN_COHERENTES de los papeles que operaron hoy (si hoy fue feriado o no hubo rueda, no coincide y no se arma nada). La vela se agrega solo a los
    papeles coherentes. Devuelve (barras, info); 'barras' queda modificado en el lugar."""
    ts = int(datetime(hoy.year, hoy.month, hoy.day, tzinfo=bt.AR).timestamp())
    cand = []
    for t, b in barras.items():
        f = filas.get(t)
        if not b or not f or _fecha(b[-1]) >= hoy:
            continue
        precio = f.get("trade") or f.get("closingPrice") or 0
        if precio <= 0 or not (f.get("tradeVolume") or 0) > 0:
            continue                                      # no operó hoy
        previo = f.get("previousClosingPrice") or 0
        cand.append((t, f, precio, bool(previo) and abs(previo / b[-1]["c"] - 1) <= TOLERANCIA_PREVIO))
    coherentes = [x for x in cand if x[3]]
    info = {"revisados": len(cand), "coherentes": len(coherentes), "agregadas": 0, "usada": False}
    if len(cand) < 20 or len(coherentes) < MIN_COHERENTES * len(cand):
        info["motivo"] = "el panel no es coherente con el histórico (o no hubo rueda hoy): no se arma la vela de hoy"
        return barras, info
    for t, f, precio, _ in coherentes:
        o = f.get("openingPrice") or precio
        hi = max(f.get("tradingHighPrice") or 0, precio, o)
        lo = min(x for x in (f.get("tradingLowPrice") or precio, precio, o) if x > 0)
        barras[t].append({"t": ts, "o": o, "h": hi, "l": lo, "c": precio, "v": f["tradeVolume"]})
        info["agregadas"] += 1
    info["usada"] = True
    return barras, info


def aviso_vela_de_hoy(info):
    """Texto para el informe sobre la vela de hoy, o None si no hay nada que avisar (el histórico ya la traía)."""
    if info["revisados"] == 0:
        return None                                   # ningún papel que operó hoy le faltaba la vela: el histórico estaba completo
    if info["usada"]:
        return (f"El histórico de BYMA todavía no traía la rueda de hoy para todos los papeles: la vela de hoy se armó con el panel de BYMA para "
                f"{info['agregadas']} papeles (coherente con el histórico en {info['coherentes']} de {info['revisados']}).")
    return "El histórico de BYMA todavía no trae la rueda de hoy y el panel no permitió armarla: el informe se refiere a la última rueda con datos."


def fecha_de_referencia(papeles):
    """La fecha en que cotizó la mayoría de los papeles (la más reciente si hay empate): todo papel se evalúa en esa fecha."""
    cont = collections.Counter(p.f[-1] for p in papeles if p.f)
    if not cont:
        return None
    return max(cont, key=lambda d: (cont[d], d))


def volumen_relativo(papeles, piso):
    """Mediana, entre los papeles líquidos, de (monto de la última vela) / (mediana del monto de las 5 anteriores). 1 = normal."""
    r = []
    for p in papeles:
        if len(p.monto) > 6 and p.monto5[-1] >= piso:
            previos = sorted(p.monto[-6:-1])
            if previos[2] > 0:
                r.append(p.monto[-1] / previos[2])
    r.sort()
    return r[len(r) // 2] if r else None


def corte_de_datos(ahora):
    """Fecha a partir de la cual se descartan velas: hoy si la rueda no cerró (la vela de hoy no es confiable); mañana si ya cerró o es fin de semana."""
    cerrada = ahora.weekday() >= 5 or (ahora.hour, ahora.minute) >= HORA_CIERRE_COMPLETO
    return ahora.date() + timedelta(days=1) if cerrada else ahora.date()


def vara_12m(refs, fecha_fin):
    """Retorno de los últimos 12 meses de cada índice de referencia: {clave: {...}} (solo los que hay)."""
    out = {}
    for k, serie in refs.items():
        r = informe.retorno_12m(serie, fecha_fin) if serie else None
        if r:
            out[k] = {"nombre": indices.INDICES[k]["nombre"], "moneda": indices.INDICES[k]["moneda"], "retorno_12m_pct": round(r[0], 2),
                      "desde": str(r[1]), "hasta": str(r[2])}
    return out


def armar(res, refs, fecha_datos, universo, rel, hoy_corte, avisos=None, datos=None):
    """Diccionario del informe a partir del resultado de informe.candidatos y las referencias."""
    vara = vara_12m(refs, fecha_datos)
    r1 = lambda x: None if x is None else round(x, 2)
    cands = []
    for c in res["candidatos"]:
        k = "sp500_ars" if c["especie"] == "cedear" else "merval"
        cands.append({**{kk: (r1(v) if isinstance(v, float) else v) for kk, v in c.items()},
                      "vara_clave": k, "vara_nombre": vara.get(k, {}).get("nombre"), "vara_12m_pct": vara.get(k, {}).get("retorno_12m_pct")})
    embudo = [{**f} for f in res["embudo"]]
    return {
        "funcion": "informe", "generado": rel.ahora().isoformat(timespec="seconds"), "fecha_datos": str(fecha_datos),
        "aviso": "Filtro objetivo para decidir mirando el gráfico. No es una recomendación de compra.",
        "universo": {**universo, "evaluados": res["evaluados"], "liquidos": res["liquidos"]},
        "vara": vara, "filtros": embudo, "candidatos": cands, "total_candidatos": res["total_candidatos"], "mas_candidatos": res["mas_candidatos"],
        "mensaje": None if cands else informe.MENSAJE_NINGUNO, "recordatorio": informe.RECORDATORIO,
        "avisos": avisos or [], "datos": datos or {},
        "cercanos": [{**x, "recorrido_pct": r1(x["recorrido_pct"]), "rr": r1(x["rr"])} for x in res["cercanos"]],
        "criterios": {"recorrido_min_pct": informe.RECORRIDO_MIN * 100, "rr_min": informe.RB_MIN, "stop": "soporte − 1%", "piso_monto_millones": bt.PARAMS["piso_monto"] / 1e6,
                      "media": "200 ruedas (150 si el papel no tiene 200 de histórico)", "ventana_niveles": "8 meses (168 ruedas), zonas con 2+ toques, tolerancia 2%"},
        "contexto": {"hora_mercado": rel.ahora().isoformat(timespec="seconds"), "fuente_hora": rel.fuente, "origen": "manual", "advertencias": []},
    }


def main():
    ap = argparse.ArgumentParser(description="Informe diario de candidatos (cifrado y publicado en docs/data)")
    ap.add_argument("--cache", help="archivo JSON para guardar/leer el histórico (desarrollo local)")
    ap.add_argument("--solo-claro", metavar="ARCHIVO", help="escribe el resultado sin cifrar y no publica (desarrollo local)")
    ap.add_argument("--hoy", metavar="AAAA-MM-DD", help="solo desarrollo: fija la fecha de corte (se descartan las velas desde ese día)")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    clave = os.environ.get("CLAVE_ACCESO", "")
    if not a.solo_claro and len(clave) < generar.MIN_CLAVE:
        sys.exit(f"Falta CLAVE_ACCESO (mínimo {generar.MIN_CLAVE} caracteres). Sin clave no se publica nada.")

    rel = reloj.Reloj()
    conector.RELOJ = rel.epoch
    rel.sincronizar()
    corte = date.fromisoformat(a.hoy) if a.hoy else corte_de_datos(rel.ahora())
    gb.log(f"Hora de mercado: {rel.ahora().isoformat(timespec='seconds')} — {rel.fuente}. Se usan velas anteriores al {corte}.")

    especies = conector.universo()
    gb.log(f"Universo: {len(especies)} especies en pesos.")
    barras, fallidos = gb.bajar_historico(especies, a.cache)
    ahora = rel.ahora()
    avisos, datos = [], {}
    if not a.hoy and sesion_cerrada(ahora):
        # la rueda de hoy ya terminó: si el histórico todavía no la trae, se arma con el panel (solo si es coherente)
        barras, datos["vela_de_hoy"] = completar_con_panel(barras, filas_panel(), ahora.date())
        aviso = aviso_vela_de_hoy(datos["vela_de_hoy"])
        if aviso:
            avisos.append(aviso)
    papeles = [bt.Papel(t, especies.get(t, "accion"), b, corte) for t, b in barras.items()]
    papeles = [p for p in papeles if p.f]
    ref = fecha_de_referencia(papeles)
    if ref is None:
        sys.exit("No hay datos para evaluar.")
    sin_fecha = [p.ticker for p in papeles if p.f[-1] != ref]
    papeles = [bt.Papel(p.ticker, p.tipo, barras[p.ticker], ref + timedelta(days=1)) for p in papeles if p.f[-1] == ref]   # todos, en la misma fecha
    datos["fecha_referencia"] = str(ref)
    datos["sin_cotizacion_en_la_fecha"] = len(sin_fecha)
    if sesion_cerrada(ahora) and ref < ahora.date() and not a.hoy:
        avisos.append(f"Los datos llegan hasta la rueda del {ref:%d/%m/%Y}. Si hoy hubo rueda, BYMA todavía no la publicó y el informe se refiere a la rueda anterior.")
    vol = volumen_relativo(papeles, bt.PARAMS["piso_monto"])
    datos["volumen_relativo_ultima_rueda"] = None if vol is None else round(vol, 2)
    if vol is not None and vol < VOLUMEN_MIN:
        avisos.append(f"La última rueda parece incompleta: el monto mediano de los papeles líquidos es el {vol * 100:.0f}% del normal.")
    assert not any(indices.es_indice(p.ticker) for p in papeles), "un índice no puede ser un papel operable"
    refs = indices.bajar_todos(barras, ref + timedelta(days=1))

    res = informe.candidatos(papeles, sectores.cargar())
    fecha_datos = ref
    universo = {"especies": len(especies), "con_datos": len(papeles), "sin_respuesta": fallidos, "sin_cotizacion_en_la_fecha": len(sin_fecha)}
    out = armar(res, refs, fecha_datos, universo, rel, corte, avisos, datos)

    if a.solo_claro:
        with open(a.solo_claro, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        gb.log(f"Resultado SIN cifrar escrito en {a.solo_claro} (no subir a ningún repositorio).")
    else:
        archivo = generar.guardar("informe", out, generar.derivar(clave, generar.cargar_meta()))
        gb.log(f"Guardado cifrado: docs/data/{archivo}")
    print(f"INFORME datos al {fecha_datos}: {res['liquidos']} líquidos, " + " → ".join(f"{f['nombre'].split(' (')[0]} {f['acumulado']}" for f in res["embudo"][1:]) +
          f". Candidatos: {res['total_candidatos']}" + ("" if res["candidatos"] else f". {informe.MENSAJE_NINGUNO}."))
    for c in out["candidatos"]:
        print(f"  {c['ticker']:6} {c['senal']:8} R/B {c['rr']} recorrido {c['recorrido_pct']}% precio {c['precio']}")


if __name__ == "__main__":
    main()
