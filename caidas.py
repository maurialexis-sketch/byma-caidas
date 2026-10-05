"""
caidas.py — Caídas acumuladas del panel líder de BYMA (en pesos, monto > 1.000 M).

Uso:   python caidas.py compra          -> FUNCIÓN COMPRA (pensada para las 12:00)
       python caidas.py venta           -> FUNCIÓN VENTA  (15:50; gancho listo, lógica pendiente)
       python caidas.py                 -> elige sola según la hora (antes de las 14:00 = compra)
Opciones: --paneles lider,general   universo (default: solo panel líder)
          --piso 2000               piso de liquidez en MILLONES de pesos (default: config.PISO_MONTO)
          --cerca 3                 % máximo al soporte para considerarlo "cerca" (default 3)
          --sin-color               sin colores ANSI en la consola

FUNCIÓN COMPRA — caída acumulada contra el cierre de la rueda previa a la ventana, con el
precio de este momento (último operado del panel):
    2 días = 1 rueda cerrada + hoy   -> precio hoy vs cierre de hace 2 ruedas   (umbral -3,5%)
    3 días = 2 ruedas cerradas + hoy -> precio hoy vs cierre de hace 3 ruedas   (umbral -5%)
    4 días = 3 ruedas cerradas + hoy -> precio hoy vs cierre de hace 4 ruedas   (umbral -7%)
Se muestran TODOS los papeles que cumplen alguna ventana; nada se descarta. La señal ordena, no filtra:
    VERDE     alcista y a <= CERCA_SOPORTE% de un soporte  (comprable)
    AMARILLO  alcista pero lejos del soporte / sin soporte (vigilar). También lateral (ver señal()).
    ROJO      bajista (riesgoso, solo estudio)
Tendencia y soportes salen de las MISMAS reglas que conector.py (medias 50/200, pivotes ±3 ruedas,
zonas con 2+ toques en 8 meses), calculadas con las ruedas cerradas y el precio de ahora.
Calcula datos; NO decide ni opera.
"""
import argparse, html, json, os, sys, time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import conector, config

AR = timezone(timedelta(hours=-3))

# ---- Parámetros de la función COMPRA ----
VENTANAS = [(2, 3.5), (3, 5.0), (4, 7.0)]   # (días de la ventana, caída mínima en %)
CERCA_SOPORTE = 3.0                          # % del precio: a esta distancia o menos = "cerca"
MAX_CAIDA_SOSPECHOSA = 25.0                  # una caída mayor a esto se marca (posible split/ajuste)
MAX_DIF_CIERRE_PREVIO = 1.0                  # % de diferencia tolerada panel vs histórico
PANELES = {"lider": "leading-equity", "general": "general-equity"}
ORDEN_SENAL = {"VERDE": 0, "AMARILLO": 1, "ROJO": 2}


def fecha(barra):
    return datetime.fromtimestamp(barra["t"], AR).date()


# ---------------------------------------------------------------- datos

def panel(nombres):
    """{ticker: fila del panel} de las especies en pesos a 24hs de los paneles pedidos."""
    filas = {}
    for nombre in nombres:
        pagina, paginas = 1, 1
        while pagina <= paginas:
            d = conector._post(config.PANEL_BASE + PANELES[nombre],
                               {"excludeZeroPxAndQty": False, "T1": True, "T0": False,
                                "page_number": pagina}).json()
            for f in (d if isinstance(d, list) else d.get("data", [])):
                if f.get("denominationCcy") == "ARS":   # afuera USD (MEP) y EXT (cable)
                    filas.setdefault(f["symbol"], f)
            if isinstance(d, dict):
                paginas = d.get("content", {}).get("page_count", 1) or 1
            pagina += 1
    return filas


def cargar_papel(ticker, fila, hoy):
    """Ruedas cerradas (histórico) + precio de ahora (panel) de un papel."""
    barras = conector.get_daily_ohlc(ticker)
    cerradas = [b for b in barras if fecha(b) < hoy]
    vela_hoy = next((b for b in barras if fecha(b) == hoy), None)
    ult = [b for b in cerradas if b["v"]][-config.RUEDAS_LIQUIDEZ:]
    monto = sum(b["c"] * b["v"] for b in ult) / len(ult) if ult else 0
    px = fila.get("trade") or fila.get("closingPrice") or 0
    fuente = f"panel {fila.get('tradeHour', '')}".strip()
    if not px and vela_hoy:              # rueda ya cerrada: el panel vuelve a 0, queda la vela de hoy
        px, fuente = vela_hoy["c"], "cierre de hoy (vela)"
    return {"ticker": ticker, "cerradas": cerradas, "precio": px or None, "fuente_precio": fuente,
            "cierre_previo_panel": fila.get("previousClosingPrice") or None, "monto": monto}


def cargar_datos(paneles, piso, ahora=None):
    """Carga todo el universo una sola vez; lo usan COMPRA y VENTA. Devuelve (datos, meta).
    `ahora` = hora de mercado (datetime con zona AR); en la nube viene de reloj.py, no del servidor."""
    ahora = ahora or datetime.now(AR)
    hoy = ahora.date()
    filas = panel(paneles)
    log(f"Universo: {len(filas)} especies en pesos ({', '.join(paneles)}). Bajando histórico...")

    def seguro(t):
        try:
            return cargar_papel(t, filas[t], hoy)
        except Exception as e:
            return e
    tickers = sorted(filas)
    with ThreadPoolExecutor(config.WORKERS) as ex:
        res = list(ex.map(seguro, tickers))
    res = [seguro(t) if isinstance(r, Exception) else r for t, r in zip(tickers, res)]   # 2º pase
    fallidos = {t: str(r) for t, r in zip(tickers, res) if isinstance(r, Exception)}
    todos = [r for r in res if not isinstance(r, Exception)]

    liquidos = [d for d in todos if d["monto"] >= piso]
    # Calendario de referencia: las últimas 4 ruedas cerradas que ven la mayoría de los papeles.
    cont = Counter(fecha(b) for d in liquidos for b in d["cerradas"][-6:])
    ref = sorted(f for f, n in cont.items() if n >= len(liquidos) / 2)[-4:]
    for d in liquidos:
        d["alertas"] = alertas_datos(d, ref, hoy)
    meta = {"hoy": hoy, "universo": len(filas), "liquidos": len(liquidos),
            "bajo_piso": [d["ticker"] for d in todos if d["monto"] < piso], "fallidos": fallidos,
            "piso": piso, "paneles": paneles, "ahora": ahora, "calendario_ref": [str(f) for f in ref]}
    return liquidos, meta


def alertas_datos(d, ref, hoy):
    a = []
    c = d["cerradas"]
    if len(c) < 60:
        a.append(f"pocos datos ({len(c)} ruedas)")
        return a
    if [fecha(b) for b in c[-len(ref):]] != ref:
        a.append("ruedas cerradas no coinciden con el resto del mercado (hueco/dato viejo): la ventana puede estar corrida")
    prev = d["cierre_previo_panel"]
    if prev and abs(prev / c[-1]["c"] - 1) * 100 > MAX_DIF_CIERRE_PREVIO:
        a.append(f"cierre previo panel {prev} vs histórico {c[-1]['c']}")
    if hoy.weekday() >= 5:
        a.append("hoy no es día hábil")
    return a


# ---------------------------------------------------------------- análisis

def niveles(cerradas, precio):
    """Tendencia y soporte más cercano bajo el precio actual (mismas reglas que conector.analizar)."""
    closes = [b["c"] for b in cerradas]
    s50, s200 = conector.sma(closes, 50), conector.sma(closes, 200)
    tendencia = ("alcista" if s50 and precio > s50 and (not s200 or s50 > s200)
                 else "bajista" if s50 and precio < s50 else "lateral")
    lows, _ = conector.pivots(cerradas[-conector.VENTANA_RUEDAS:])
    pisos = [(z, n) for z, n in conector.zonas(lows) if n >= conector.MIN_TOQUES and z < precio]
    sop = max(pisos) if pisos else None   # sin descartar por lejanía: la distancia es un dato a estudiar
    return tendencia, (sop[0] if sop else None), (sop[1] if sop else None)


def senal(tendencia, dist_soporte, cerca):
    if tendencia == "bajista":
        return "ROJO"
    # Lateral (arriba de la media 50 pero con la 50 bajo la 200) no está definido en el pedido:
    # ni comprable ni bajista -> AMARILLO. Cambiar acá si se quiere otro criterio.
    if tendencia == "alcista" and dist_soporte is not None and dist_soporte <= cerca:
        return "VERDE"
    return "AMARILLO"


def evaluar(d, cerca):
    """Fila de resultado de un papel, o None si no hay precio/datos para medirlo."""
    c, px = d["cerradas"], d["precio"]
    if not px or len(c) < max(n for n, _ in VENTANAS) or len(c) < 60:
        return None
    caidas = {n: (px / c[-n]["c"] - 1) * 100 for n, _ in VENTANAS}
    disparan = [n for n, umbral in VENTANAS if caidas[n] <= -umbral]
    tendencia, sop, toques = niveles(c, px)
    dist = (px - sop) / px * 100 if sop else None
    alertas = list(d["alertas"])
    if disparan and min(caidas.values()) < -MAX_CAIDA_SOSPECHOSA:
        alertas.append(f"caída de {min(caidas.values()):.0f}%: ¿split o ajuste de ratio?")
    fila = {"ticker": d["ticker"], "precio": round(px, 2), "fuente_precio": d["fuente_precio"],
            "monto_millones": round(d["monto"] / 1e6),
            "caidas_pct": {str(n): round(v, 2) for n, v in caidas.items()},
            "ventanas_que_disparan": disparan, "tendencia": tendencia,
            "soporte": round(sop, 2) if sop else None, "soporte_toques": toques,
            "dist_soporte_pct": round(dist, 2) if dist is not None else None, "alertas": alertas}
    if disparan:
        v = disparan[0]   # la ventana más corta que se cumple; las otras se ven en caidas_pct
        fila.update(caida_pct=round(caidas[v], 2), ventana=v, senal=senal(tendencia, dist, cerca))
    return fila


# ---------------------------------------------------------------- funciones por horario

def funcion_compra(datos, meta, cerca=CERCA_SOPORTE):
    evaluados = [(d, evaluar(d, cerca)) for d in datos]
    sin_precio = [d["ticker"] for d, f in evaluados if f is None]
    filas = [f for _, f in evaluados if f]
    con_caida = sorted((f for f in filas if "senal" in f),
                       key=lambda f: (ORDEN_SENAL[f["senal"]], f["caida_pct"]))
    sin_caida = sorted(({"ticker": f["ticker"], "caidas_pct": f["caidas_pct"]}
                        for f in filas if "senal" not in f), key=lambda f: f["caidas_pct"]["2"])
    conteo = {s: sum(f["senal"] == s for f in con_caida) for s in ORDEN_SENAL}
    # "En bloque": cae una parte grande del universo líquido (>= 40%) y la mayoría de lo que cae es ROJO.
    en_bloque = (len(con_caida) >= max(3, 0.4 * meta["liquidos"]) and conteo["ROJO"] > len(con_caida) / 2)
    return {"funcion": "compra", "generado": (meta.get("ahora") or datetime.now(AR)).isoformat(timespec="seconds"),
            "parametros": {"ventanas": VENTANAS, "cerca_soporte_pct": cerca, "piso_millones": meta["piso"] / 1e6,
                           "paneles": meta["paneles"]},
            "universo": {"especies": meta["universo"], "liquidas": meta["liquidos"],
                         "bajo_piso": meta["bajo_piso"], "sin_precio_hoy": sin_precio,
                         "con_error": meta["fallidos"], "calendario_ref": meta["calendario_ref"]},
            "conteo": conteo, "con_caida": len(con_caida), "en_bloque": en_bloque, "papeles": con_caida, "sin_caida": sin_caida}


VENTA_DEFINIDA = False   # poner en True cuando funcion_venta tenga lógica: el servidor no la corre mientras sea False


def funcion_venta(datos, meta):
    """GANCHO — FUNCIÓN VENTA (15:50). `datos` = lista por papel con las ruedas cerradas
    (`cerradas`), el precio de ahora (`precio`), monto y alertas; `niveles(cerradas, precio)` da
    tendencia y soporte. Cuando se defina la lógica, devolver un dict como funcion_compra."""
    raise NotImplementedError("La función VENTA todavía no está definida.")


FUNCIONES = {"compra": funcion_compra, "venta": funcion_venta}


# ---------------------------------------------------------------- salida

def n(x, dec=1, signo=False):
    """Número con coma decimal y punto de miles (formato argentino)."""
    if x is None:
        return "—"
    s = f"{x:{'+' if signo else ''},.{dec}f}"
    return s.replace(",", "\0").replace(".", ",").replace("\0", ".")


def celda_caidas(f):
    return " | ".join(n(f["caidas_pct"][str(d)], 1) + ("*" if d in f["ventanas_que_disparan"] else "")
                      for d, _ in VENTANAS)


COLORES = {"VERDE": "\033[92m", "AMARILLO": "\033[93m", "ROJO": "\033[91m"}


def imprimir(r, color):
    def pint(s, senal):
        return f"{COLORES[senal]}{s}\033[0m" if color else s
    u, cnt = r["universo"], r["conteo"]
    print(f"\nFUNCIÓN COMPRA — {r['generado'].replace('T', ' ')}  "
          f"(precio de ahora vs cierre de hace 2/3/4 ruedas; umbrales "
          f"{' / '.join(n(t, 1) + '%' for _, t in VENTANAS)})")
    print(f"Universo: {u['especies']} especies en pesos, {u['liquidas']} con monto >= "
          f"{n(r['parametros']['piso_millones'], 0)} M. Con alguna caída: {r['con_caida']} de {u['liquidas']}.")
    cab = f"{'SEÑAL':<9} {'TICKER':<7} {'CAÍDA %':>8} {'VENT':>4}  {'2d | 3d | 4d (* dispara)':<27} " \
          f"{'TENDENCIA':<9} {'PRECIO':>10} {'SOPORTE':>10} {'DIST.SOP %':>10} {'MONTO M':>9}"
    print("\n" + cab + "\n" + "-" * len(cab))
    for f in r["papeles"]:
        linea = (f"{f['senal']:<9} {f['ticker']:<7} {n(f['caida_pct'], 1, True):>8} {str(f['ventana']) + 'd':>4}  "
                 f"{celda_caidas(f):<27} {f['tendencia']:<9} {n(f['precio'], 2):>10} "
                 f"{n(f['soporte'], 2) if f['soporte'] else 'sin soporte':>10} "
                 f"{n(f['dist_soporte_pct'], 1):>10} {n(f['monto_millones'], 0):>9}")
        print(pint(linea, f["senal"]) + ("   ⚠ " + "; ".join(f["alertas"]) if f["alertas"] else ""))
    if not r["papeles"]:
        print("(ningún papel cumple alguna caída)")
    print(f"\nVERDE (comprable): {cnt['VERDE']}   AMARILLO (vigilar): {cnt['AMARILLO']}   "
          f"ROJO (solo estudio): {cnt['ROJO']}   —   total con caída: {r['con_caida']}")
    if r["en_bloque"]:
        print("Caída en bloque: una parte grande del mercado líquido cae y casi todo en ROJO.")
    if u["sin_precio_hoy"]:
        print(f"Sin precio de hoy (no medidos): {', '.join(u['sin_precio_hoy'])}")
    if u["con_error"]:
        print(f"SIN RESPUESTA de BYMA (no medidos): {', '.join(u['con_error'])}")


def html_compra(r):
    cls = {"VERDE": "v", "AMARILLO": "a", "ROJO": "r"}
    cnt = r["conteo"]
    filas = "".join(
        f"<tr class='{cls[f['senal']]}'><td>{f['senal']}</td><td><b>{html.escape(f['ticker'])}</b></td>"
        f"<td>{n(f['caida_pct'], 1, True)}</td><td>{f['ventana']}d</td><td>{celda_caidas(f)}</td>"
        f"<td>{f['tendencia']}</td><td>{n(f['precio'], 2)}</td>"
        f"<td>{n(f['soporte'], 2) if f['soporte'] else 'sin soporte'}</td><td>{n(f['dist_soporte_pct'], 1)}</td>"
        f"<td>{n(f['monto_millones'], 0)}</td><td>{html.escape('; '.join(f['alertas']))}</td></tr>"
        for f in r["papeles"])
    return f"""<!doctype html><html lang="es"><meta charset="utf-8"><title>Caídas acumuladas — compra</title>
<style>body{{font:14px system-ui;margin:20px}}table{{border-collapse:collapse}}td,th{{padding:4px 10px;border-bottom:1px solid #ddd;text-align:right}}
td:nth-child(-n+2),td:nth-child(6),td:last-child,th:nth-child(-n+2){{text-align:left}}
.v{{background:#c8f0cf}}.a{{background:#fff3b0}}.r{{background:#f8c9c9}}</style>
<h2>Función COMPRA — {r['generado'].replace('T', ' ')}</h2>
<p><b>VERDE (comprable): {cnt['VERDE']} · AMARILLO (vigilar): {cnt['AMARILLO']} · ROJO (solo estudio): {cnt['ROJO']}</b>
 — con caída {r['con_caida']} de {r['universo']['liquidas']} papeles líquidos.<br>
Precio de ahora vs cierre de hace 2/3/4 ruedas (umbrales 3,5 / 5 / 7 %); * = ventana que dispara.</p>
<table><tr><th>Señal<th>Ticker<th>Caída %<th>Vent.<th>2d | 3d | 4d<th>Tendencia<th>Precio<th>Soporte<th>Dist. sop. %<th>Monto M<th>Alertas</tr>{filas}</table></html>"""


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def ejecutar_compra(paneles=("lider",), piso=None, cerca=CERCA_SOPORTE):
    """Carga los datos de BYMA y corre la FUNCIÓN COMPRA. Es lo que usa el botón de la app."""
    datos, meta = cargar_datos(list(paneles), config.PISO_MONTO if piso is None else piso)
    return funcion_compra(datos, meta, cerca)


def guardar(r, carpeta=os.path.dirname(os.path.abspath(__file__))):
    with open(os.path.join(carpeta, "caidas_compra.json"), "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=2)
    with open(os.path.join(carpeta, "caidas_compra.html"), "w", encoding="utf-8") as f:
        f.write(html_compra(r))


def main():
    ap = argparse.ArgumentParser(description="Caídas acumuladas BYMA (compra 12:00 / venta 15:50)")
    ap.add_argument("funcion", nargs="?", choices=list(FUNCIONES), help="default: según la hora")
    ap.add_argument("--paneles", default="lider", help="lider, general o lider,general")
    ap.add_argument("--piso", type=float, help="piso de liquidez en MILLONES de pesos")
    ap.add_argument("--cerca", type=float, default=CERCA_SOPORTE)
    ap.add_argument("--sin-color", action="store_true")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
    os.system("")   # habilita colores ANSI en consolas de Windows
    funcion = a.funcion or ("compra" if datetime.now(AR).hour < 14 else "venta")
    paneles = [p.strip() for p in a.paneles.split(",")]
    if any(p not in PANELES for p in paneles):
        ap.error(f"paneles válidos: {', '.join(PANELES)}")
    piso = a.piso * 1e6 if a.piso is not None else config.PISO_MONTO

    t0 = time.time()
    datos, meta = cargar_datos(paneles, piso)
    log(f"Datos listos en {time.time() - t0:.0f} s.")
    try:
        r = FUNCIONES[funcion](datos, meta, a.cerca) if funcion == "compra" else FUNCIONES[funcion](datos, meta)
    except NotImplementedError as e:
        print(f"\nFUNCIÓN {funcion.upper()}: {e} (gancho listo en caidas.funcion_venta)")
        return
    imprimir(r, color=sys.stdout.isatty() and not a.sin_color)
    carpeta = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(carpeta, "caidas_compra.json"), "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=2)
    with open(os.path.join(carpeta, "caidas_compra.html"), "w", encoding="utf-8") as f:
        f.write(html_compra(r))
    log(f"\nGuardado: caidas_compra.json y caidas_compra.html en {carpeta}")


if __name__ == "__main__":
    main()
