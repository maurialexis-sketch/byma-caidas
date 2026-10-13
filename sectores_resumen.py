"""
sectores_resumen.py — ¿Cuántos papeles líquidos hay en cada sector? (para saber si el análisis por sector tiene sentido)

    python sectores_resumen.py                       baja el universo de BYMA y cuenta
    python sectores_resumen.py --cache c.json        usa/guarda el histórico bajado (desarrollo local)

Cuenta, por sector: especies (cada línea cotizada) y empresas distintas (AAPL y AAPLB son una), líquidas HOY (monto promedio de las
últimas 5 ruedas >= 1.000 M, la definición de la app) y líquidas en ALGÚN MOMENTO del período (lo que puede entrar a un backtest).
También lista los líquidos que todavía están 'sin_clasificar' para completarlos en datos/sectores.json.
"""
import argparse, json, sys
from datetime import date

import backtest as bt
import conector, generar_backtest as gb, sectores

# Con cuántas empresas líquidas por día conviene hacer análisis por sector (criterio mío, no estadístico): con menos, el resultado depende de
# una o dos empresas. >= 8 'sí', de 4 a 8 'justo', menos de 4 'NO'. Se mide con el promedio diario del período, no con 'alguna vez'.
MINIMO_ANALISIS = 8


def main():
    ap = argparse.ArgumentParser(description="Conteo de papeles líquidos por sector")
    ap.add_argument("--cache", help="archivo JSON para guardar/leer el histórico (desarrollo local)")
    ap.add_argument("--hoy", metavar="AAAA-MM-DD", help="fecha de corte (por defecto, hoy)")
    ap.add_argument("--desde", metavar="AAAA-MM-DD", help="inicio del período para el promedio diario (en el backtest, el inicio operable)")
    ap.add_argument("--json", metavar="ARCHIVO", help="además escribe el conteo en un JSON")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    hoy = date.fromisoformat(a.hoy) if a.hoy else date.today()
    especies = conector.universo()
    barras, _ = gb.bajar_historico(especies, a.cache)
    papeles = [bt.Papel(t, especies.get(t, "accion"), b, hoy) for t, b in barras.items()]
    papeles = [p for p in papeles if len(p.c) > 0]
    datos = sectores.cargar()
    piso = bt.PARAMS["piso_monto"]
    desde = date.fromisoformat(a.desde) if a.desde else None
    filas = sectores.contar(papeles, piso, datos, desde)

    print(f"Universo con datos: {len(papeles)} especies | líquidas hoy: {sum(1 for p in papeles if p.monto5[-1] >= piso)} | "
          f"líquidas alguna vez en el período: {sum(1 for p in papeles if max(p.monto5) >= piso)} | piso {piso / 1e6:,.0f} M\n")
    print(f"{'grupo':8}{'sector':15}{'subsector':14}{'líquidas hoy':>14}{'(empresas)':>11}{'alguna vez':>12}{'(empresas)':>11}{'prom. diario':>13}   ¿alcanza?")
    for f in filas:
        if not (f["especies"] or f["liquidas_alguna_vez"]) and f["sector"] == "sin_clasificar":
            continue
        d = f["promedio_diario"]
        ok = "sí" if d >= MINIMO_ANALISIS else ("justo" if d >= 4 else "NO")
        print(f"{f['grupo']:8}{f['sector']:15}{str(f['subsector'] or '—'):14}{f['liquidas_hoy']:>14}{f['empresas_liquidas_hoy']:>11}"
              f"{f['liquidas_alguna_vez']:>12}{f['empresas_liquidas_alguna_vez']:>11}{d:>13.1f}   {ok}")
    sin = [p.ticker for p in papeles if not sectores.etiquetar(p.ticker, p.tipo, datos)["clasificado"] and max(p.monto5) >= piso]
    print(f"\nLíquidos en algún momento y sin clasificar ({len(sin)}): {' '.join(sorted(sin)) or 'ninguno'}")
    if a.json:
        json.dump({"fecha": str(hoy), "piso": piso, "minimo_para_analisis": MINIMO_ANALISIS, "sectores": filas, "liquidos_sin_clasificar": sorted(sin)},
                  open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
