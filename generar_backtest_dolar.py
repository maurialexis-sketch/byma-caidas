"""
generar_backtest_dolar.py — BACKTEST del listado 2 de SAINT MARINO DÓLAR: el mismo del listado 2 de San Marino (sanmarino_bt.py: entra cuando el papel entra al listado 2, sale al cierre del cruce del MACD hacia abajo,
3 posiciones de 1/3, costos de siempre) pero sobre el gráfico de la bolsa de Nueva York en dólares (Yahoo Finance) de los CEDEARs en dólares de Bull Market (cedears_dolar.json), contra el S&P 500 en dólares.
Publica el resultado CIFRADO en docs/data (pestaña BACKTEST, el mismo panel que los demás backtests).

    python generar_backtest_dolar.py                      CLAVE_ACCESO en el entorno (en GitHub: un "secret")
    python generar_backtest_dolar.py --cache c.json       guarda/usa el histórico bajado (desarrollo local)
    python generar_backtest_dolar.py --solo-claro r.json  escribe el resultado SIN cifrar y no publica (desarrollo local)

Usa los parámetros GUARDADOS de Saint Marino Dólar (parametros_macd_dolar.json): los de la pestaña, no se cambian acá. SIN filtro de liquidez (no hay historial de lo operado en las líneas D de BYMA); como dato
informativo se corre también solo con los papeles que HOY operaron al menos el piso en su línea D (mira el presente: tiene sesgo, y se dice).
"""
import argparse, json, os, sys, time
from datetime import date

import backtest as bt
import fuente_ny as ny
import generar, generar_backtest as gb, generar_sanmarino_dolar as gd, indices, parametros_macd_dolar as pd, reloj, sanmarino_bt

ETIQUETA = "Saint Marino Dólar · Listado 2 (despegó) · 3 posiciones (1/3 c/u)"


def solo_operables_hoy(papeles, items, p, merval):
    """Informativo: la misma estrategia con solo los papeles que HOY operaron al menos el piso en su línea D de BYMA (data912). Mira el presente, no la liquidez que tenían en cada rueda: sesgo de selección."""
    liq = ny.liquidez_cedears(items)
    piso_usd = p["sm"]["piso_millones"] * 1e6
    ok = {t for t, l in liq.items() if l["monto_dia"] >= piso_usd}
    elegidos = [pa for pa in papeles if pa.ticker in ok]
    if not liq or not elegidos:
        return None
    res = bt.correr(elegidos, merval, p, generar=sanmarino_bt.senales_sanmarino2)
    if not res:
        return {"n_papeles": len(elegidos), "piso_usd": piso_usd, "resumen": None}
    return {"n_papeles": len(elegidos), "piso_usd": piso_usd, "resumen": gb.resumen(res, "base", p)}


def main():
    ap = argparse.ArgumentParser(description="Backtest del listado 2 de Saint Marino Dólar (cifrado y publicado en docs/data)")
    ap.add_argument("--cache", help="archivo JSON para guardar/leer el histórico (desarrollo local)")
    ap.add_argument("--solo-claro", metavar="ARCHIVO", help="escribe el resultado sin cifrar y no publica (desarrollo local)")
    ap.add_argument("--hoy", metavar="AAAA-MM-DD", help="solo desarrollo: fija 'hoy' (las velas desde esa fecha se descartan)")
    ap.add_argument("--parametros", default=pd.ARCHIVO, help="archivo con los parámetros guardados de Saint Marino Dólar")
    ap.add_argument("--universo", default=None, help="solo desarrollo: otro archivo de universo")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    contrasena = os.environ.get("CLAVE_ACCESO", "")           # (la contraseña de cifrado: no reasignar este nombre en ningún bucle)
    if not a.solo_claro and len(contrasena) < generar.MIN_CLAVE:
        sys.exit(f"Falta CLAVE_ACCESO (mínimo {generar.MIN_CLAVE} caracteres). Sin clave no se publica nada.")
    try:
        p = sanmarino_bt.parametros(pd.cargar(a.parametros), dolar=True)
    except pd.ErrorParametro as ex:
        sys.exit(f"Parámetros de Saint Marino Dólar inválidos, no se generó nada: {ex}")
    gb.log("Parámetros de Saint Marino Dólar: " + ", ".join(f"{k}={v:g}" for k, v in pd.cargar(a.parametros).items()) + " (los guardados)")

    rel = reloj.Reloj()
    rel.sincronizar()
    ahora_ny = ny.hora_ny(rel.ahora())
    hoy = date.fromisoformat(a.hoy) if a.hoy else ny.corte_de_datos_ny(ahora_ny)         # nunca se usa una vela de hoy (puede estar a medias)
    gb.log(f"Hora de mercado: {rel.ahora().isoformat(timespec='seconds')} — {rel.fuente} (Nueva York: {ahora_ny:%d/%m/%Y %H:%M}). Se usan velas anteriores al {hoy}.")

    items = ny.universo(a.universo)
    barras, fallidos = gd.bajar_historico(items, a.cache)
    papeles = [bt.Papel(t, "cedear", b, hoy) for t, b in barras.items()]
    papeles = [pa for pa in papeles if len(pa.c) > 0]
    ajustes = [x for pa in papeles for x in pa.ajustes]
    gb.log(f"{len(papeles)} papeles utilizables de {len(items)}; {len(ajustes)} ajustes por split/contrasplit.")
    serie = indices.bajar_yahoo(indices.YAHOO_SIMBOLO["sp500_usd"])                       # la vara: el S&P 500 en dólares
    if not serie:
        gb.log("AVISO: no se pudo bajar el S&P 500: el backtest sale sin vara.")
    serie = [(d, v) for d, v in (serie or []) if d < hoy]
    bt.fijar_referencias({"sp500_usd": serie}, ["sp500_usd"])
    gb.log("Vara a superar (CEDEARs en dólares): " + indices.INDICES["sp500_usd"]["nombre"])

    t0 = time.time()
    res = bt.correr(papeles, None, p, generar=sanmarino_bt.senales_sanmarino2)
    if not res:
        sys.exit("El listado 2 de Saint Marino Dólar no encontró ninguna señal en este universo y período.")
    gb.log(f"Backtest listo en {time.time() - t0:.0f} s: {res['senales_total']} señales, {res['base']['metricas']['trades']} operaciones cerradas.")
    out = gb.resultado_json(res, {"papeles": papeles, "especies": len(items)}, ajustes, fallidos, hoy, rel, p)
    out["etiqueta"], out["estrategia"], out["moneda"] = ETIQUETA, "sanmarino", "USD"
    out["comparacion_sanmarino"] = gb.comparacion_sanmarino(res, papeles, p, None, out["merval"])
    out["comparacion_sanmarino"]["solo_operables_hoy"] = solo_operables_hoy(papeles, items, p, None)
    out["equity"]["nombre_base"] = "Listado 2 de Saint Marino Dólar"
    out["fuente_datos"] = ny.NOMBRE

    if a.solo_claro:
        with open(a.solo_claro, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False)
        gb.log(f"Resultado SIN cifrar escrito en {a.solo_claro} (no subir a ningún repositorio).")
    else:
        archivo = generar.guardar("backtest", out, generar.derivar(contrasena, generar.cargar_meta()), etiqueta=out["etiqueta"])
        gb.log(f"Guardado cifrado: docs/data/{archivo}")
    m = out["metricas"]
    print(f"BACKTEST [{out['etiqueta']}] {out['periodo']['inicio']} → {out['periodo']['fin']}: {m['trades']} operaciones, ganancia {m['ganancia_total_pct']:+.1f}%, "
          f"profit factor {m['profit_factor']}, ganadoras {m['ganadores_pct']}%, max DD {m['max_drawdown']['pct']}%.")


if __name__ == "__main__":
    main()
