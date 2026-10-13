"""
generar_informe.py — Informe diario de candidatos (a demanda): baja el universo líquido de BYMA, aplica los filtros de informe.py y publica el resultado
CIFRADO en docs/data (lo lee la misma página, pestaña CANDIDATOS). No es un backtest ni una recomendación.

    python generar_informe.py                       CLAVE_ACCESO en el entorno (en GitHub: un "secret")
    python generar_informe.py --cache c.json        guarda/usa el histórico bajado (desarrollo local)
    python generar_informe.py --solo-claro r.json   escribe el resultado SIN cifrar y no publica (desarrollo local)
"""
import argparse, json, os, sys
from datetime import date, timedelta

import backtest as bt
import conector, generar, generar_backtest as gb, indices, informe, reloj, sectores

HORA_CIERRE_COMPLETO = (17, 30)   # a partir de esta hora la vela del día ya está completa; antes, la de hoy puede venir a medias y no se usa


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


def armar(res, refs, fecha_datos, universo, rel, hoy_corte):
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
    papeles = [bt.Papel(t, especies.get(t, "accion"), b, corte) for t, b in barras.items()]
    papeles = [p for p in papeles if p.f]
    assert not any(indices.es_indice(p.ticker) for p in papeles), "un índice no puede ser un papel operable"
    refs = indices.bajar_todos(barras, corte)

    res = informe.candidatos(papeles, sectores.cargar())
    fecha_datos = max(p.f[-1] for p in papeles)
    universo = {"especies": len(especies), "con_datos": len(papeles), "sin_respuesta": fallidos}
    out = armar(res, refs, fecha_datos, universo, rel, corte)

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
