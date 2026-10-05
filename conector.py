"""
conector.py — Baja el histórico diario de BYMA y calcula tendencia, soporte,
resistencia, stop sugerido y relación riesgo/beneficio.

Uso masivo (autónomo):   python conector.py                 -> universo líquido completo
                         python conector.py --piso 2000     -> piso en millones de pesos
Uso manual:              python conector.py GGAL YPFD GOOGL MELI

Modo masivo:
  1. Baja de los paneles de BYMA Data (líderes, panel general, CEDEARs) todas las
     especies en pesos a 24hs; descarta las versiones en dólares (MEP) y cable.
  2. Calcula el monto operado = promedio de las últimas RUEDAS_LIQUIDEZ ruedas
     (volumen x cierre, del histórico). Se usa el histórico y no el volumeAmount
     del panel porque el panel vuelve a 0 fuera de rueda y es parcial intradiario.
  3. Filtra monto >= PISO_MONTO y analiza niveles solo de esos.
  4. Filtro final: tendencia alcista + recorrido a resistencia >= 10% + R/B >= 2.
     watchlist_conector.json = solo los que pasan, ordenados por R/B (lo que importa Timón).
     watchlist_completo.json = todos los analizados, para auditar.
Calcula datos; NO decide ni opera.
"""
import requests, time, json, sys, os, argparse
from concurrent.futures import ThreadPoolExecutor
import config

# ---- Parámetros de análisis (calibrar contra gráficos conocidos) ----
K_PIVOTE = 3       # ventana ±k para detectar pisos/techos locales (calibrado vs YPFD/GOOGL)
MIN_TOQUES = 2     # una zona es soporte/resistencia si el precio frenó y rebotó ahí >= 2 veces
TOL_ZONA = 0.02    # 2%: niveles más cercanos que esto se agrupan en una zona (calibrado)
DIAS = 400         # histórico pedido (las medias móviles de 200 ruedas necesitan ~290 días)
VENTANA_RUEDAS = 168   # ~8 meses: pisos/techos solo de esta ventana, los más viejos no cuentan
MAX_DIST = 0.12        # niveles a más de 12% del precio = lejanos, se descartan
# ---- Filtro final ----
MIN_RECORRIDO = 0.10   # resistencia al menos 10% arriba del precio
MIN_RB = 2.0           # relación riesgo/beneficio mínima
MAX_DIF_PANEL = 0.03   # alerta si el cierre del histórico difiere >3% del precio del panel
MAX_SALTO = 0.20       # alerta si la última rueda salta >20% vs la anterior (split / cambio de ratio)

VELA_PANEL = {}        # {ticker: vela de hoy según el panel}, se llena en universo() si hubo rueda hoy
CORTE_TS = None        # con --cierre: se descartan velas desde este timestamp (hoy 00:00 AR) y el panel

_http = requests.Session()
RELOJ = time.time   # hook: la app en la nube lo reemplaza por la hora de mercado verificada

REINTENTOS = 6

def _get(url, **kw):
    # BYMA Data responde 503 si se le pega muy rápido: reintentar con espera creciente
    for intento in range(REINTENTOS):
        try:
            r = _http.get(url, timeout=20, **kw); r.raise_for_status(); return r
        except requests.RequestException:
            if intento == REINTENTOS - 1: raise
            time.sleep(2 ** intento)

def _post(url, body):
    for intento in range(3):
        try:
            r = _http.post(url, json=body, timeout=30,
                           headers={"Content-Type": "application/json", **config.HEADERS})
            r.raise_for_status(); return r
        except requests.RequestException:
            if intento == 2: raise
            time.sleep(1 + intento * 2)

def get_daily_ohlc(symbol, dias=DIAS):
    if not config.UDF_BASE:
        raise RuntimeError("Falta config.UDF_BASE. Corré descubrir_endpoint.py primero.")
    to_ts = int(RELOJ()); from_ts = to_ts - dias * 24 * 3600
    sym = config.SYMBOL_FMT.format(ticker=symbol)
    d = _get(config.UDF_BASE,
             params={"symbol": sym, "resolution": "D", "from": from_ts, "to": to_ts},
             headers=config.HEADERS or None).json()
    if d.get("s") == "no_data":
        return []
    if d.get("s") != "ok":
        raise RuntimeError(f"Datafeed respondió {d.get('s')}: {d}")
    n = len(d["t"]); v = d.get("v") or [0] * n
    bars = [{"t": d["t"][i], "o": d["o"][i], "h": d["h"][i],
             "l": d["l"][i], "c": d["c"][i], "v": v[i] or 0} for i in range(n)]
    bars = [b for b in bars if min(b["o"], b["h"], b["l"], b["c"]) > 0   # velas en 0 = sin operar
            and (CORTE_TS is None or b["t"] < CORTE_TS)]
    # BYMA publica la vela diaria en el histórico recién un rato después del cierre: mientras tanto
    # se arma la vela de hoy con el panel (apertura, máx, mín, cierre, volumen) para no mezclar días.
    hoy = hoy_ts()
    if CORTE_TS is None and symbol in VELA_PANEL and bars and bars[-1]["t"] < hoy:
        bars.append({"t": hoy, **VELA_PANEL[symbol], "panel": True})
    return bars

def hoy_ts():
    """Timestamp de hoy 00:00 hora Argentina (así fecha BYMA las velas diarias)."""
    return int((time.time() - 3 * 3600) // 86400 * 86400 + 3 * 3600)

# ---- Universo y liquidez ----

def universo():
    """{ticker: tipo} de todas las especies en pesos (ARS) a 24hs de los paneles."""
    especies = {}
    for panel, tipo in config.PANELES.items():
        pagina, paginas = 1, 1
        while pagina <= paginas:
            d = _post(config.PANEL_BASE + panel,
                      {"excludeZeroPxAndQty": False, "T1": True, "T0": False,
                       "page_number": pagina}).json()
            filas = d if isinstance(d, list) else d.get("data", [])
            if isinstance(d, dict):
                paginas = d.get("content", {}).get("page_count", 1) or 1
            for f in filas:
                if f.get("denominationCcy") == "ARS":   # afuera USD (MEP) y EXT (cable)
                    especies.setdefault(f["symbol"], tipo)
                    c = f.get("closingPrice") or f.get("trade") or 0   # 0 fuera de rueda
                    if c > 0 and f.get("openingPrice") and f.get("tradingHighPrice"):
                        VELA_PANEL[f["symbol"]] = {"o": f["openingPrice"], "h": f["tradingHighPrice"],
                                                   "l": f["tradingLowPrice"], "c": c, "v": f.get("volume") or 0}
            pagina += 1
    return especies

def monto_promedio(symbol):
    """Monto operado promedio en pesos de las últimas RUEDAS_LIQUIDEZ ruedas."""
    bars = [b for b in get_daily_ohlc(symbol, dias=config.RUEDAS_LIQUIDEZ * 2 + 6) if b["v"]]
    ult = bars[-config.RUEDAS_LIQUIDEZ:]
    if not ult or time.time() - ult[-1]["t"] > 10 * 24 * 3600:   # sin operar hace >10 días
        return 0
    return sum(b["c"] * b["v"] for b in ult) / len(ult)

# ---- Análisis técnico ----

def sma(vals, n):
    return sum(vals[-n:]) / n if len(vals) >= n else None

def pivots(bars, k=K_PIVOTE):
    lows, highs = [], []
    for i in range(k, len(bars) - k):
        win = bars[i - k:i + k + 1]
        if bars[i]["l"] == min(b["l"] for b in win): lows.append(bars[i]["l"])
        if bars[i]["h"] == max(b["h"] for b in win): highs.append(bars[i]["h"])
    return lows, highs

def zonas(niveles, tol=TOL_ZONA):
    """Agrupa pivotes cercanos (±tol) en zonas: [(nivel promedio, cantidad de pivotes)]."""
    if not niveles: return []
    niveles = sorted(niveles); res, act = [], [niveles[0]]
    for x in niveles[1:]:
        if abs(x - act[-1]) / act[-1] <= tol: act.append(x)
        else: res.append((sum(act) / len(act), len(act))); act = [x]
    res.append((sum(act) / len(act), len(act))); return res

def ruedas_desde_toque(bars, nivel, tol=TOL_ZONA):
    """Ruedas desde la última vela cuyo rango tocó la zona nivel ±tol (0 = la última rueda)."""
    for i in range(len(bars) - 1, -1, -1):
        if bars[i]["l"] <= nivel * (1 + tol) and bars[i]["h"] >= nivel * (1 - tol):
            return len(bars) - 1 - i
    return None

def analizar(symbol):
    bars = get_daily_ohlc(symbol)
    if len(bars) < 60:
        raise RuntimeError(f"{symbol}: pocos datos ({len(bars)} barras)")
    closes = [b["c"] for b in bars]; last = closes[-1]
    alertas = validar(bars)
    fecha = time.strftime("%d/%m/%Y", time.gmtime(bars[-1]["t"]))
    if bars[-1].get("panel"):
        fuente = f"cierre panel BYMA {fecha} (histórico aún sin la vela de hoy)"
    else:
        fuente = f"cierre BYMA {fecha}"
        vp = None if CORTE_TS else VELA_PANEL.get(symbol)
        if vp and bars[-1]["t"] == hoy_ts() and abs(vp["c"] / last - 1) > MAX_DIF_PANEL:
            alertas.append(f"panel {vp['c']} vs cierre histórico {last} ({100 * (vp['c'] / last - 1):+.1f}%)")
    s50, s200 = sma(closes, 50), sma(closes, 200)
    tendencia = ("alcista" if s50 and last > s50 and (not s200 or s50 > s200)
                 else "bajista" if s50 and last < s50 else "lateral")
    ventana = bars[-VENTANA_RUEDAS:]
    lows, highs = pivots(ventana)
    # Solo zonas donde el precio frenó y rebotó >= MIN_TOQUES veces (no mínimos/máximos sueltos)
    pisos = [(z, n) for z, n in zonas(lows) if n >= MIN_TOQUES and z < last]
    techos = [(z, n) for z, n in zonas(highs) if n >= MIN_TOQUES and z > last]
    sop = max(pisos) if pisos else None            # el más cercano por debajo
    res = min(techos) if techos else None          # el más cercano por arriba
    notas = []
    if sop and (last - sop[0]) / last > MAX_DIST:
        notas.append(f"soporte {sop[0]:.2f} a {100 * (last - sop[0]) / last:.0f}%: lejano, descartado"); sop = None
    if res and (res[0] - last) / last > MAX_DIST:
        notas.append(f"resistencia {res[0]:.2f} a {100 * (res[0] - last) / last:.0f}%: lejana, descartada"); res = None
    if not pisos: notas.append("sin zona de soporte con 2+ toques por debajo en 8 meses")
    if not techos: notas.append("sin zona de resistencia con 2+ toques por encima en 8 meses")
    soporte, resistencia = (sop[0] if sop else None), (res[0] if res else None)
    out = {"ticker": symbol, "ultimo": round(last, 2), "ultimo_fecha": fecha, "ultimo_fuente": fuente,
           "tendencia": tendencia,
           "soporte": round(soporte, 2) if soporte else None,
           "soporte_toques": sop[1] if sop else None,
           "soporte_ruedas_desde_toque": ruedas_desde_toque(ventana, soporte) if soporte else None,
           "resistencia": round(resistencia, 2) if resistencia else None,
           "resistencia_toques": res[1] if res else None,
           "resistencia_ruedas_desde_toque": ruedas_desde_toque(ventana, resistencia) if resistencia else None,
           "stop_sugerido": round(soporte * 0.99, 2) if soporte else None,
           "recorrido_pct": round(100 * (resistencia - last) / last, 1) if resistencia else None,
           "relacion_rb": None}
    if soporte and resistencia:
        riesgo = last - out["stop_sugerido"]; recorrido = resistencia - last
        out["relacion_rb"] = round(recorrido / riesgo, 2) if riesgo > 0 else None
    if notas:
        out["nota"] = "; ".join(notas)
    out["alertas"] = alertas
    return out

def validar(bars):
    """Chequeos de coherencia del último dato; devuelve lista de alertas (vacía = OK)."""
    a, b, prev = [], bars[-1], bars[-2]
    if not b["l"] <= b["c"] <= b["h"] or not b["l"] <= b["o"] <= b["h"]:
        a.append(f"vela incoherente: o={b['o']} h={b['h']} l={b['l']} c={b['c']}")
    salto = b["c"] / prev["c"] - 1
    if abs(salto) > MAX_SALTO:
        a.append(f"salto de {100 * salto:+.0f}% vs rueda anterior (¿split o cambio de ratio?)")
    dias = (time.time() - b["t"]) / 86400
    if dias > 5:
        a.append(f"último dato de hace {dias:.0f} días")
    return a

def pasa_filtro(a):
    """Las tres condiciones a la vez: alcista, recorrido >= 10%, R/B >= 2."""
    return (a.get("tendencia") == "alcista"
            and (a.get("recorrido_pct") or 0) >= MIN_RECORRIDO * 100
            and (a.get("relacion_rb") or 0) >= MIN_RB)

def _seguro(fn, t):
    try:
        return fn(t)
    except Exception as e:
        return e

def masivo(piso):
    t0 = time.time()
    especies = universo()
    log(f"Universo en pesos: {len(especies)} especies "
        f"({sum(v == 'accion' for v in especies.values())} acciones, "
        f"{sum(v == 'cedear' for v in especies.values())} CEDEARs). Midiendo liquidez...")
    tickers = sorted(especies)
    with ThreadPoolExecutor(config.WORKERS) as ex:
        montos = dict(zip(tickers, ex.map(lambda t: _seguro(monto_promedio, t), tickers)))
    for t in [t for t, m in montos.items() if isinstance(m, Exception)]:   # 2º pase, de a uno
        montos[t] = _seguro(monto_promedio, t)
    fallidos = [t for t, m in montos.items() if isinstance(m, Exception)]
    liquidos = sorted((t for t, m in montos.items() if not isinstance(m, Exception) and m >= piso),
                      key=lambda t: -montos[t])
    log(f"Pasan el piso de {piso / 1e6:,.0f} M: {len(liquidos)}"
        + (f"  (sin respuesta: {len(fallidos)}: {', '.join(fallidos)})" if fallidos else "") + ". Analizando niveles...")
    with ThreadPoolExecutor(config.WORKERS) as ex:
        analisis = list(ex.map(lambda t: _seguro(analizar, t), liquidos))
    analisis = [_seguro(analizar, t) if isinstance(a, Exception) else a   # 2º pase, de a uno
                for t, a in zip(liquidos, analisis)]
    res = []
    fechas = [a["ultimo_fecha"] for a in analisis if isinstance(a, dict)]
    ultima = max(fechas, key=lambda f: time.strptime(f, "%d/%m/%Y"), default=None)
    for t, a in zip(liquidos, analisis):
        if isinstance(a, dict) and a["ultimo_fecha"] != ultima:
            a["alertas"].append(f"sin cotización en la última rueda ({ultima}); dato viejo")
        fila = {"ticker": t, "error": str(a)} if isinstance(a, Exception) else a
        fila["tipo"] = especies[t]
        fila["monto_operado"] = round(montos[t])
        res.append(fila)
    log(f"Listo en {time.time() - t0:.0f} s.")
    return res

def log(msg):
    print(msg, file=sys.stderr, flush=True)

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Conector BYMA -> Timón")
    ap.add_argument("tickers", nargs="*", help="modo manual: tickers a analizar")
    ap.add_argument("--piso", type=float, help="piso de liquidez en MILLONES de pesos")
    ap.add_argument("--cierre", action="store_true",
                    help="analizar al cierre de la rueda anterior (ignora el intradiario de hoy)")
    args = ap.parse_args()
    if args.cierre:   # velas diarias de BYMA fechadas 00:00 hora Argentina (UTC-3)
        CORTE_TS = hoy_ts()

    if args.tickers:
        res = []
        for t in args.tickers:
            try:
                res.append(analizar(t))
            except Exception as e:
                res.append({"ticker": t, "error": str(e)})
    else:
        piso = args.piso * 1e6 if args.piso is not None else config.PISO_MONTO
        res = masivo(piso)

    carpeta = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(carpeta, "watchlist_completo.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)   # todo lo analizado, para auditar
    ok = [a for a in res if "error" not in a]
    pasan = sorted((a for a in ok if pasa_filtro(a)), key=lambda a: -a["relacion_rb"])
    salida = json.dumps(pasan, ensure_ascii=False, indent=2)
    print(salida)
    # Archivo que importa Timón (UTF-8, junto a este script): solo los que pasan el filtro
    ruta = os.path.join(carpeta, "watchlist_conector.json")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(salida)
    log(f"\nAnalizados: {len(ok)} (+{len(res) - len(ok)} con error). "
        f"Alcistas: {sum(a['tendencia'] == 'alcista' for a in ok)}. "
        f"Recorrido >= {MIN_RECORRIDO:.0%}: {sum((a['recorrido_pct'] or 0) >= MIN_RECORRIDO * 100 for a in ok)}. "
        f"R/B >= {MIN_RB:g}: {sum((a['relacion_rb'] or 0) >= MIN_RB for a in ok)}. "
        f"Pasan las tres: {len(pasan)}.")
    if not pasan:
        log("Hoy ningún activo cumple")
    log(f"Guardado en {ruta}")
