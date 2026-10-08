"""
backtest.py — Backtest de la ESTRATEGIA BASE sobre acciones y CEDEARs de BYMA en pesos. Reglas fijas, sin optimizar.

ENTRADA (al cierre del día t, con datos hasta t; nada del futuro):
  1. Liquidez: monto promedio de las últimas 5 ruedas >= 1.000 M (con el monto de ESA época, en pesos nominales).
  2. Caída: el día anterior (t-1) el precio acumulaba una caída de >=3,5% en 2 días, >=5% en 3 o >=7% en 4
     (las mismas ventanas de la función COMPRA).
  3. Toca soporte: el mínimo de t-1 o t estuvo a +-2% de una zona de soporte de los últimos 8 meses (168 ruedas;
     zonas de pivotes con 2+ toques, mismas reglas que conector.py), y el cierre de t quedó por encima de esa zona.
  4. Día verde: cierre de t > cierre de t-1.
  5. Debe existir una resistencia de 8 meses por encima del cierre (si no, no hay objetivo y se descarta la señal).
SALIDA (lo que ocurra primero, evaluado desde t+1):
  - Resistencia: el máximo toca la resistencia -> sale en la resistencia (o en la apertura si abre por encima).
  - Stop: el mínimo toca el soporte menos 1% -> sale ahí (o en la apertura si abre por debajo).
  - Tiempo: a las 20 ruedas, al cierre.
  Si en la misma vela se tocan stop y resistencia, se asume el stop (lo conservador).
GESTIÓN: máximo 2 posiciones; cada una usa la mitad del capital DISPONIBLE (efectivo libre) al entrar.
  Variante informada aparte: la mitad del capital total (patrimonio) al entrar, tope el efectivo libre.
  Si el mismo día hay más señales que lugares, entra primero la de mayor monto operado.
COSTOS: comisión del broker + derechos de mercado, más IVA, en cada compra y cada venta. Impuesto a las ganancias: 0 por
  defecto (parámetro). Ver PARAMS: son supuestos, no los costos reales de un broker en particular.
Los precios se ajustan por splits/cambios de ratio de CEDEARs (saltos de razón entera: 2:1, 3:1, ...), registrados en 'ajustes'.
"""
import bisect, math
from datetime import date, datetime, timedelta, timezone

import conector

AR = timezone(timedelta(hours=-3))

PARAMS = {
    "capital": 10_000_000,            # capital inicial en pesos (no lo definió el pedido; los % no dependen de él)
    "ventana_ruedas": 168,            # 8 meses de soportes y resistencias
    "k_pivote": 3, "min_toques": 2, "tol_zona": 0.02,
    "ventanas_caida": [(2, 3.5), (3, 5.0), (4, 7.0)],     # (días, caída mínima %), medidas en t-1
    "stop_buffer": 0.01,              # stop = soporte - 1%
    "dias_max": 20,                   # salida por tiempo
    "max_posiciones": 2, "fraccion": 0.5,
    "piso_monto": 1_000_000_000, "ruedas_liquidez": 5,
    "comision_broker": 0.005,         # 0,50% por operación (supuesto típico de un broker minorista)
    "derechos_mercado": 0.0008,       # 0,08% derechos de mercado y garantía (supuesto)
    "iva": 0.21,                      # IVA sobre comisión y derechos
    "imp_ganancias": 0.0,             # sin impuesto a las ganancias (acciones y CEDEARs de personas humanas: verificar)
    # Filtro de tendencia alcista (apagado en la estrategia base): el cierre de t debe quedar POR ENCIMA de su media móvil
    # de 200 ruedas; si el papel aún no tiene 200 ruedas de histórico, de 150.
    "filtro_tendencia": False, "ma_larga": 200, "ma_corta": 150,
}


def costo_lado(p=PARAMS):
    return (p["comision_broker"] + p["derechos_mercado"]) * (1 + p["iva"])


# ---------------------------------------------------------------- datos

class Papel:
    """Velas diarias de un papel: precios ajustados por splits (o,h,l,c) y cierre/volumen sin ajustar (para el monto)."""
    def __init__(self, ticker, tipo, barras, hoy=None):
        b = sorted((x for x in barras if min(x["o"], x["h"], x["l"], x["c"]) > 0), key=lambda x: x["t"])
        if hoy:   # nunca se usa una vela de hoy (puede estar a medias)
            b = [x for x in b if datetime.fromtimestamp(x["t"], AR).date() < hoy]
        self.ticker, self.tipo = ticker, tipo
        self.f = [datetime.fromtimestamp(x["t"], AR).date() for x in b]
        raw = [x["c"] for x in b]
        self.ajustes = []
        fac = [1.0] * len(b)
        for i in range(len(b) - 1, 0, -1):
            fac[i - 1] = fac[i]
            r = raw[i - 1] / raw[i]          # >1: el precio cayó (split directo); <1: subió (contrasplit)
            if es_razon_entera(r):
                fac[i - 1] = fac[i] * raw[i] / raw[i - 1]
                self.ajustes.append({"ticker": ticker, "fecha": str(self.f[i]), "razon": round(r if r > 1 else 1 / r, 3),
                                     "tipo": "split" if r > 1 else "contrasplit"})
        self.o = [x["o"] * k for x, k in zip(b, fac)]
        self.h = [x["h"] * k for x, k in zip(b, fac)]
        self.l = [x["l"] * k for x, k in zip(b, fac)]
        self.c = [x["c"] * k for x, k in zip(b, fac)]
        self.monto = [x["c"] * x["v"] for x in b]       # monto nominal de la época
        self.idx = {d: i for i, d in enumerate(self.f)}
        self.monto5 = []                                # promedio móvil del monto (ruedas_liquidez)
        n = PARAMS["ruedas_liquidez"]; acc = 0.0
        for i, m in enumerate(self.monto):
            acc += m - (self.monto[i - n] if i >= n else 0.0)
            self.monto5.append(acc / n if i >= n - 1 else 0.0)
        self.cs = [0.0]                                 # sumas acumuladas del cierre ajustado (para medias móviles)
        for x in self.c:
            self.cs.append(self.cs[-1] + x)

    def sma(self, i, n):
        """Media móvil simple de n cierres que termina en i (incluye el cierre de i); None si faltan datos."""
        return (self.cs[i + 1] - self.cs[i + 1 - n]) / n if i + 1 >= n else None


def es_razon_entera(r, tol=0.03):
    """r = precio_anterior / precio_nuevo. Salto de split o contrasplit si r (o 1/r) es ~ un entero >= 2."""
    for x in (r, 1 / r):
        k = round(x)
        if k >= 2 and abs(x - k) / k < tol:
            return True
    return False


# ---------------------------------------------------------------- señales

def niveles(papel, i, p=PARAMS):
    """Zonas de soporte y resistencia con datos hasta i (los pivotes necesitan k ruedas después: solo se ven los confirmados)."""
    ini = max(0, i - p["ventana_ruedas"] + 1)
    barras = [{"l": papel.l[j], "h": papel.h[j]} for j in range(ini, i + 1)]
    lows, highs = conector.pivots(barras, p["k_pivote"])
    pisos = [z for z, n in conector.zonas(lows, p["tol_zona"]) if n >= p["min_toques"]]
    techos = [z for z, n in conector.zonas(highs, p["tol_zona"]) if n >= p["min_toques"]]
    return pisos, techos


def caida_previa(papel, i, p=PARAMS):
    """Primera ventana (días, umbral) en la que el cierre de i-1 acumula la caída; None si ninguna."""
    for n, umbral in p["ventanas_caida"]:
        if i - 1 - n >= 0 and papel.c[i - 1] / papel.c[i - 1 - n] - 1 <= -umbral / 100:
            return n, (papel.c[i - 1] / papel.c[i - 1 - n] - 1) * 100
    return None


def salida(papel, i, resistencia, stop, p=PARAMS):
    """Simula la salida desde i+1. Devuelve (índice, precio, motivo); motivo 'abierta' si los datos terminan antes."""
    n = len(papel.c)
    for j in range(i + 1, min(n, i + p["dias_max"] + 1)):
        o, h, l, c = papel.o[j], papel.h[j], papel.l[j], papel.c[j]
        if o <= stop:
            return j, o, "stop"
        if l <= stop:
            return j, stop, "stop"          # si en la misma vela se toca la resistencia, gana el stop
        if o >= resistencia:
            return j, o, "resistencia"
        if h >= resistencia:
            return j, resistencia, "resistencia"
        if j - i == p["dias_max"]:
            return j, c, "tiempo"
    return n - 1, papel.c[n - 1], "abierta"


def sobre_la_media(papel, i, p=PARAMS):
    """Filtro de tendencia alcista: cierre de i por encima de su media de 200 ruedas (de 150 si no hay 200 de histórico)."""
    n = p["ma_larga"] if i + 1 >= p["ma_larga"] else p["ma_corta"]
    m = papel.sma(i, n)
    return m is not None and papel.c[i] > m


def señales(papel, i_min=None, p=PARAMS):
    """Todas las señales de entrada de un papel (con su salida ya simulada) y un conteo de descartes."""
    desc = {"sin_resistencia": 0, "bajo_media": 0}
    out = []
    i_min = max(p["ventana_ruedas"] - 1, 1) if i_min is None else i_min
    for i in range(i_min, len(papel.c)):
        if papel.monto5[i] < p["piso_monto"] or papel.c[i] <= papel.c[i - 1]:
            continue
        caida = caida_previa(papel, i, p)
        if not caida:
            continue
        pisos, techos = niveles(papel, i, p)
        minimo = min(papel.l[i - 1], papel.l[i])
        tocados = [z for z in pisos if z <= papel.c[i] and z * (1 - p["tol_zona"]) <= minimo <= z * (1 + p["tol_zona"])]
        if not tocados:
            continue
        z = max(tocados)
        arriba = [r for r in techos if r > papel.c[i]]
        if not arriba:
            desc["sin_resistencia"] += 1
            continue
        r = min(arriba)
        if p["filtro_tendencia"] and not sobre_la_media(papel, i, p):
            desc["bajo_media"] += 1       # cumplía todo lo demás, pero cotiza por debajo de su media: no entra
            continue
        stop = z * (1 - p["stop_buffer"])
        j, px, motivo = salida(papel, i, r, stop, p)
        out.append({"papel": papel, "i": i, "fecha": papel.f[i], "precio": papel.c[i], "soporte": z, "resistencia": r,
                    "stop": stop, "monto5": papel.monto5[i], "caida_dias": caida[0], "caida_pct": caida[1],
                    "j": j, "f_salida": papel.f[j], "px_salida": px, "motivo": motivo})
    return out, desc


def diagnostico_filtro(papeles, p=PARAMS):
    """Solo informativo: cómo les iría, una por una y sin el límite de posiciones, a las señales de la estrategia base que
    el filtro de tendencia deja pasar y a las que elimina (rendimiento neto de costos de cada operación)."""
    base, lado = dict(p, filtro_tendencia=False), costo_lado(p)
    grupos = {"pasan": [], "eliminadas": []}
    for papel in papeles:
        if len(papel.c) <= p["ventana_ruedas"]:
            continue
        for x in señales(papel, p=base)[0]:
            neto = (x["px_salida"] * (1 - lado)) / (x["precio"] * (1 + lado)) - 1
            grupos["pasan" if sobre_la_media(papel, x["i"], p) else "eliminadas"].append(neto * 100)

    def resumen(v):
        if not v:
            return {"n": 0, "ganadoras_pct": None, "media_pct": None, "mediana_pct": None}
        v2 = sorted(v)
        mediana = v2[len(v2) // 2] if len(v2) % 2 else (v2[len(v2) // 2 - 1] + v2[len(v2) // 2]) / 2
        return {"n": len(v), "ganadoras_pct": sum(x > 0 for x in v) / len(v) * 100, "media_pct": sum(v) / len(v), "mediana_pct": mediana}
    return {k: resumen(v) for k, v in grupos.items()}


def estadistica_senales(papeles, generar, p=PARAMS):
    """Solo informativo: rendimiento neto de costos de CADA señal de una estrategia, una por una y sin el límite de posiciones.
    Sirve para saber si la ventaja existe en las señales o depende de cuáles entraron a la cartera."""
    lado = costo_lado(p)
    r = []
    for papel in papeles:
        if len(papel.c) <= p["ventana_ruedas"]:
            continue
        for x in generar(papel, p=p)[0]:
            r.append(((x["px_salida"] * (1 - lado)) / (x["precio"] * (1 + lado)) - 1) * 100)
    if not r:
        return {"n": 0}
    g, pe = [v for v in r if v > 0], [v for v in r if v < 0]
    v2 = sorted(r)
    mediana = v2[len(v2) // 2] if len(v2) % 2 else (v2[len(v2) // 2 - 1] + v2[len(v2) // 2]) / 2
    return {"n": len(r), "ganadoras_pct": len(g) / len(r) * 100, "media_pct": sum(r) / len(r), "mediana_pct": mediana,
            "profit_factor": sum(g) / -sum(pe) if pe else None,
            "payoff": (sum(g) / len(g)) / (-sum(pe) / len(pe)) if g and pe else None}


# ---------------------------------------------------------------- cartera

def precio_en(papel, d):
    """Último cierre conocido del papel hasta la fecha d (si ese día no operó, vale el anterior)."""
    k = bisect.bisect_right(papel.f, d)
    return papel.c[k - 1] if k else papel.c[0]


def simular(todas, calendario, sizing="efectivo", p=PARAMS):
    """Recorre el calendario día a día. Devuelve (operaciones cerradas, abiertas, serie de patrimonio, descartes)."""
    lado = costo_lado(p)
    por_fecha = {}
    for s in todas:
        por_fecha.setdefault(s["fecha"], []).append(s)
    cash, abiertas, cerradas = float(p["capital"]), [], []
    serie, desc = [], {"sin_lugar": 0, "ya_en_cartera": 0, "sin_efectivo": 0}
    for d in calendario:
        for pos in [x for x in abiertas if x["f_salida"] == d and x["motivo"] != "abierta"]:
            bruto = pos["acciones"] * pos["px_salida"]
            neto = bruto * (1 - lado)
            ganancia = neto - pos["costo_total"]
            if ganancia > 0:
                neto -= ganancia * p["imp_ganancias"]
                ganancia *= 1 - p["imp_ganancias"]
            cash += neto
            cerradas.append({**pos, "pnl": ganancia, "pnl_pct": ganancia / pos["costo_total"] * 100})
            abiertas.remove(pos)
        for s in sorted(por_fecha.get(d, []), key=lambda x: -x["monto5"]):
            if any(x["papel"] is s["papel"] for x in abiertas):
                desc["ya_en_cartera"] += 1
                continue
            if len(abiertas) >= p["max_posiciones"]:
                desc["sin_lugar"] += 1
                continue
            patrimonio = cash + sum(x["acciones"] * precio_en(x["papel"], d) for x in abiertas)
            presupuesto = p["fraccion"] * cash if sizing == "efectivo" else min(p["fraccion"] * patrimonio, cash)
            acciones = math.floor(presupuesto / (s["precio"] * (1 + lado)))
            if acciones < 1:
                desc["sin_efectivo"] += 1
                continue
            costo = acciones * s["precio"] * (1 + lado)
            cash -= costo
            abiertas.append({**s, "acciones": acciones, "costo_total": costo})
        valor = sum(x["acciones"] * precio_en(x["papel"], d) for x in abiertas)
        serie.append((d, cash + valor))
    return cerradas, abiertas, serie, desc


# ---------------------------------------------------------------- métricas

def max_drawdown(serie):
    pico, mdd, mdd_abs, f_pico, f_fin = serie[0][1], 0.0, 0.0, serie[0][0], serie[0][0]
    f_pico_act = serie[0][0]
    for d, e in serie:
        if e > pico:
            pico, f_pico_act = e, d
        dd = (pico - e) / pico
        if dd > mdd:
            mdd, mdd_abs, f_pico, f_fin = dd, pico - e, f_pico_act, d
    return {"pct": mdd * 100, "monto": mdd_abs, "desde": str(f_pico), "hasta": str(f_fin)}


def metricas(cerradas, serie, p=PARAMS):
    capital = p["capital"]
    final = serie[-1][1]
    ganadoras = [t["pnl"] for t in cerradas if t["pnl"] > 0]
    perdedoras = [t["pnl"] for t in cerradas if t["pnl"] < 0]
    bruto_g, bruto_p = sum(ganadoras), -sum(perdedoras)
    anios = max((serie[-1][0] - serie[0][0]).days / 365.25, 1e-9)
    total = final / capital - 1
    n = len(cerradas)
    return {
        "ganancia_total": final - capital, "ganancia_total_pct": total * 100, "patrimonio_final": final,
        "profit_factor": bruto_g / bruto_p if bruto_p else None,
        "payoff_ratio": (bruto_g / len(ganadoras)) / (bruto_p / len(perdedoras)) if ganadoras and perdedoras else None,
        "max_drawdown": max_drawdown(serie),
        "ganadores_pct": len(ganadoras) / n * 100 if n else None, "trades": n,
        "duracion_media_dias": sum((t["f_salida"] - t["fecha"]).days for t in cerradas) / n if n else None,
        "duracion_media_ruedas": sum(t["j"] - t["i"] for t in cerradas) / n if n else None,
        "ganancia_media_trade": sum(t["pnl"] for t in cerradas) / n if n else None,
        "ganancia_media_trade_pct": sum(t["pnl_pct"] for t in cerradas) / n if n else None,
        "retorno_anual_promedio_pct": total / anios * 100,          # retorno total / años (simple, sin capitalizar)
        "cagr_pct": ((1 + total) ** (1 / anios) - 1) * 100 if total > -1 else -100.0,
        "anios": anios,
    }


def metricas_serie(serie):
    """Retorno total, CAGR y máximo drawdown de una serie (para el Merval)."""
    anios = max((serie[-1][0] - serie[0][0]).days / 365.25, 1e-9)
    total = serie[-1][1] / serie[0][1] - 1
    return {"retorno_total_pct": total * 100, "cagr_pct": ((1 + total) ** (1 / anios) - 1) * 100, "max_drawdown": max_drawdown(serie)}


def por_anio(cerradas, serie, merval=None, p=PARAMS):
    """Rendimiento por año calendario (el primero y el último suelen ser parciales)."""
    filas, previo = [], p["capital"]
    anios = sorted({d.year for d, _ in serie})
    for a in anios:
        tramo = [(d, e) for d, e in serie if d.year == a]
        fin = tramo[-1][1]
        ops = [t for t in cerradas if t["f_salida"].year == a]
        g = [t for t in ops if t["pnl"] > 0]
        fila = {"anio": a, "desde": str(tramo[0][0]), "hasta": str(tramo[-1][0]),
                "parcial": not (tramo[0][0] <= date(a, 1, 10) and tramo[-1][0] >= date(a, 12, 20)),
                "retorno_pct": (fin / previo - 1) * 100, "ganancia": fin - previo, "trades": len(ops),
                "ganadores_pct": len(g) / len(ops) * 100 if ops else None, "merval_pct": None}
        if merval:
            m = [(d, v) for d, v in merval if d.year == a]
            ant = [(d, v) for d, v in merval if d.year < a]
            base = ant[-1][1] if ant else m[0][1]
            if m:
                fila["merval_pct"] = (m[-1][1] / base - 1) * 100
        filas.append(fila)
        previo = fin
    return filas


def alinear(merval_crudo, calendario, capital):
    """Serie del Merval en 'pesos de la cartera': normalizada al capital en la primera fecha del calendario."""
    if not merval_crudo:
        return None
    fechas = [d for d, _ in merval_crudo]
    out, base = [], None
    for d in calendario:
        k = bisect.bisect_right(fechas, d)       # último dato con fecha <= d
        if k == 0:
            continue
        v = merval_crudo[k - 1][1]
        base = base or v
        out.append((d, capital * v / base))
    return out or None


# ---------------------------------------------------------------- corrida completa

def correr(papeles, merval_crudo=None, p=PARAMS, generar=None):
    """papeles: lista de Papel. Devuelve el diccionario de resultados (serializable a JSON).
    `generar(papel, p=p)` produce las señales de entrada de la estrategia (por defecto, la de caídas)."""
    generar = generar or señales
    todas, desc_total, con_senal = [], {"sin_resistencia": 0, "bajo_media": 0}, 0
    for papel in papeles:
        if len(papel.c) <= p["ventana_ruedas"]:
            continue
        s, d = generar(papel, p=p)
        todas += s
        con_senal += bool(s)
        for k in desc_total:
            desc_total[k] += d[k]
    if not todas:
        return None
    # calendario: todas las fechas desde la primera con ventana completa (en el papel con más historia)
    inicio = min(papel.f[p["ventana_ruedas"] - 1] for papel in papeles if len(papel.c) >= p["ventana_ruedas"])
    calendario = sorted({d for papel in papeles for d in papel.f if d >= inicio})
    res = {}
    for nombre, sizing in (("base", "efectivo"), ("variante", "patrimonio")):
        cerradas, abiertas, serie, desc = simular(todas, calendario, sizing, p)
        res[nombre] = {"cerradas": cerradas, "abiertas": abiertas, "serie": serie, "desc": desc,
                       "metricas": metricas(cerradas, serie, p)}
    # Sensibilidad informativa (no es una optimización): la misma estrategia sin comisiones ni derechos de mercado
    sin_costos = dict(p, comision_broker=0.0, derechos_mercado=0.0)
    c0, _, s0, _ = simular(todas, calendario, "efectivo", sin_costos)
    res["sin_costos"] = metricas(c0, s0, sin_costos)
    merval = alinear(merval_crudo, calendario, p["capital"])
    res["merval"] = merval
    res["merval_metricas"] = metricas_serie(merval) if merval else None
    res["anios"] = por_anio(res["base"]["cerradas"], res["base"]["serie"], merval, p)
    res["calendario"] = (calendario[0], calendario[-1])
    res["senales_total"] = len(todas)
    res["papeles_con_senal"] = con_senal
    res["descartes_senal"] = desc_total
    return res
