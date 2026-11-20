"""
sanmarino_bt.py — BACKTEST del LISTADO 2 de SAN MARINO («despegó»: el MACD ya cruzó hacia arriba la señal, hace pocas ruedas, con poca separación y con el Vortex confirmando).

ENTRADA (al cierre de la rueda t, con datos hasta t; nada del futuro): el papel cumple TODAS las condiciones del listado 2 (macd.etapas_listado2: la misma función que arma el listado, así la
  regla es una sola) y es OPERABLE (monto promedio de 5 ruedas >= el piso de liquidez: en el listado se muestra todo, pero para operar hace falta liquidez, igual que en todos los backtests).
  Una señal por CRUCE: si el papel cumple varias ruedas seguidas desde el mismo cruce, entra la primera en que además tiene liquidez.
SALIDA (regla fija, elegida antes de ver ningún resultado y sin parámetros): al CIERRE de la primera rueda posterior en que el MACD vuelve a quedar en la señal o por debajo de ella
  (histograma <= 0: el cruce hacia abajo, el reverso exacto de la entrada). Sin stop ni límite de tiempo. Si los datos terminan antes, la posición queda «abierta» y se valúa al último cierre.
GESTIÓN: 3 posiciones, cada una 1/3 del patrimonio al entrar (igual que los backtests de Bollinger). Con más señales que lugares entra la de mayor monto operado.
COSTOS: los de siempre (≈0,70% por lado). Entrada y salida al cierre de la rueda de la señal, sin deslizamiento: es el supuesto de todos los backtests de esta herramienta, optimista porque
  el cruce recién se conoce al cierre. No hay impuesto a las ganancias.
Los parámetros del MACD, de la separación, de las ruedas desde el cruce y del Vortex son los GUARDADOS de San Marino (parametros_macd.json: los de la pestaña, no se cambian acá).
"""
import backtest as bt
import macd
import parametros_macd as pm

ESTRATEGIA = "sanmarino_listado2"
MOTIVO_SALIDA = "macd_cruce_abajo"


def parametros(valores=None):
    """Los parámetros del motor para este backtest: la cartera (3 posiciones de 1/3 del patrimonio) y, en p['sm'], los del MACD/Vortex de San Marino ('valores' o, si no, los guardados).
    'ventana_ruedas' (las ruedas de arranque del motor) es el mínimo que necesita el MACD; 'piso_monto' sale del piso de liquidez de San Marino."""
    mp = macd.de_params(pm.validar(valores) if valores is not None else pm.cargar())
    p = dict(bt.PARAMS, estrategia=ESTRATEGIA, filtro_tendencia=False, max_posiciones=3, fraccion=1.0 / 3, sizing="patrimonio")
    p["sm"] = mp
    p["ventana_ruedas"] = macd.ruedas_minimas(mp)
    p["piso_monto"] = mp["piso_millones"] * 1e6
    return p


def _salida(h, cierres, t):
    """(índice, precio, motivo) de la salida de una entrada en t: el primer cierre posterior con el histograma <= 0; 'abierta' (al último cierre) si no llega."""
    n = len(cierres)
    for j in range(t + 1, n):
        if not h[j] > macd.EPS * cierres[j]:                              # el mismo criterio de «arriba» del listado, al revés
            return j, cierres[j], MOTIVO_SALIDA
    return n - 1, cierres[n - 1], "abierta"


def senales_sanmarino2(papel, i_min=None, p=None):
    """Todas las señales de entrada del listado 2 de un papel (con su salida ya simulada) y un conteo de descartes. Mismo formato que las demás estrategias (corre en bt.simular)."""
    p = p or parametros()
    mp = p["sm"]
    desc = {"sin_resistencia": 0, "bajo_media": 0, "sin_liquidez": 0, "episodios": 0}
    out = []
    n = len(papel.c)
    minimo = macd.ruedas_minimas(mp)
    if papel.tipo != "cedear" or n < minimo:
        return out, desc
    s = macd.serie(papel.c, mp["rapido"], mp["lento"], mp["senal"])
    vs = macd.vortex_serie(papel.h, papel.l, papel.c, mp["vortex_periodo"])
    i_min = max(minimo - 1, p.get("ventana_ruedas", 1) - 1) if i_min is None else max(i_min, minimo - 1)
    usados, vistos = set(), set()
    for t in range(i_min, n):
        e = macd.estado_en(s, papel.c, t, mp)
        v = macd.vortex_en(vs, t)
        if e is None or not all(macd.etapas_listado2(e, v, mp)):
            continue
        cruce = t - e["ruedas_desde_cruce"]                               # la rueda del cruce identifica el episodio
        if cruce in usados:
            continue
        if cruce not in vistos:
            vistos.add(cruce)
            desc["episodios"] += 1
        if papel.monto5[t] < p["piso_monto"]:
            desc["sin_liquidez"] += 1                                     # si el papel gana liquidez más adelante en el mismo episodio, entra ese día
            continue
        usados.add(cruce)
        j, px, motivo = _salida(s["hist"], papel.c, t)
        out.append({"papel": papel, "i": t, "fecha": papel.f[t], "precio": papel.c[t], "soporte": None, "resistencia": None, "stop": None,
                    "monto5": papel.monto5[t], "caida_dias": None, "caida_pct": None, "j": j, "f_salida": papel.f[j], "px_salida": px, "motivo": motivo,
                    "hist_pct": e["hist_pct"], "ruedas_desde_cruce": e["ruedas_desde_cruce"], "vi_mas": v["mas"] if v else None, "vi_menos": v["menos"] if v else None})
    return out, desc


def regla(p):
    """El texto de la regla, con los valores usados en esta corrida (para el informe)."""
    mp = p["sm"]
    return (f"Entrada: al cierre de la rueda en que un CEDEAR entra al LISTADO 2 de San Marino (el MACD {mp['rapido']}/{mp['lento']}/{mp['senal']} ya cruzó hacia arriba la señal hace "
            f"{mp['ruedas_cruce']} ruedas o menos, las líneas se siguen abriendo, la separación es de {str(mp['dist2_pct']).replace('.', ',')}% del precio o menos"
            + (f" y el Vortex de {mp['vortex_periodo']} ruedas confirma: VI+ > VI−" if mp["vortex_exigir"] else "; el Vortex no se exige en esta corrida")
            + f"), siempre que sea operable (monto promedio de 5 ruedas ≥ {format(mp['piso_millones'], ',').replace(',', '.')} M). Una señal por cruce. Salida: al cierre de la primera rueda en que el MACD vuelve a quedar en la señal "
              "o por debajo (el cruce hacia abajo); sin stop ni límite de tiempo. Cartera de 3 posiciones de 1/3 del patrimonio. Costos ≈0,70% por lado. Compra y venta al cierre, sin "
              "deslizamiento. Esta regla de salida se fijó antes de ver resultados y no se probó ninguna otra.")
