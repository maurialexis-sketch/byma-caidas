"""
bollinger.py — Estrategia de BANDAS DE BOLLINGER (giro de la línea central en forma de U). Estrategia NUEVA y separada. La misma detección sirve para el BACKTEST (todas las
veces que aparece el patrón, sin período fijo) y para el informe de CANDIDATOS (¿aparece HOY?).

Bandas: línea central = media simple de 'bb_periodo' cierres (ajustados por splits); bandas = central ± 'bb_desvios' desvíos estándar (poblacional) de esos mismos cierres.
Pendiente de la central en la rueda d = central[d] − central[d−1].

ENTRADA (al cierre de la rueda t; todas las condiciones juntas; nada del futuro):
  1. GIRO EN U: la pendiente de la central era NEGATIVA y pasa a POSITIVA durante al menos 'bb_dias' ruedas seguidas, y en esas 'bb_dias' ruedas la central sube al menos
     'bb_magnitud_pct'% (central[t] / central[t − bb_dias] − 1). Para que sea una U (y no un día suelto de pendiente negativa) la bajada tiene que haber durado al menos
     'bb_dias' ruedas seguidas con pendiente negativa (INTERPRETACIÓN: el pedido no fija el largo de la bajada; se toma el mismo número de ruedas que la subida).
  2. BAJADA POR DEBAJO: durante la bajada (la racha de pendientes negativas que termina justo antes del giro, dentro de la ventana) los cierres estaban por DEBAJO de la central,
     hasta el cruce de la condición 3.
  3. CRUCE EN EL PISO: dentro de la ventana, al menos una rueda cruza la central de abajo hacia arriba (cierre previo debajo, cierre de esa rueda encima). Puede ocurrir con la
     central todavía bajando o ya girando: la central es una media y gira DESPUÉS que el precio. Se toma el último cruce de la ventana.
  4. ENCIMA TRAS EL GIRO: desde ese cruce hasta t, todos los cierres quedan por ENCIMA de la central.
  Todo el patrón (la bajada y el giro) tiene que caber en 'bb_ventana' ruedas que terminan en t. La señal sale UNA vez por giro: la primera rueda en que se cumple todo.
  Además, en el backtest, liquidez: monto promedio de 5 ruedas >= el piso (1.000 M). NO se exige tendencia alcista (no estaba en la regla): en CANDIDATOS rige, como para las otras señales, el
  filtro de tendencia, y lo que lo incumple se muestra aparte como informativo.
SALIDA (por tramos; se evalúa con CIERRES, igual que la ruptura escalonada; 'bb_pesos' = reparto, por defecto 1/3 cada uno):
  - TRAMO 1: primer toque de la banda superior (cierre >= banda superior de esa rueda). Un 'toque' es un episodio: varios cierres seguidos sobre la banda cuentan como uno; para
    el siguiente toque el precio tiene que volver a cerrar por debajo de la banda y después tocarla otra vez.
  - TRAMO 2: segundo toque (nuevo episodio).
  - TRAMO 3 (final): la central gira a pendiente negativa (pendiente < 0): se vende TODO lo que quede (si todavía no hubo dos toques, queda más de 1/3 y se vende igual).
  - STOP (editable, 'bb_stop'): un cierre por debajo de la banda inferior de esa rueda vende TODO lo que quede. Se mira primero.
Gestión y costos: los de la ruptura escalonada (3 posiciones de 1/3 del patrimonio; cada venta paga su costo; acciones enteras).
"""
import math

import backtest as bt
import escalonada

DEFECTO = {"bb_periodo": 20, "bb_desvios": 2.0, "bb_dias": 3, "bb_ventana": 10, "bb_magnitud_pct": 1.0, "bb_pesos": [1, 1, 1], "bb_stop": True, "bb_velas_caida": 5, "bb_velas_giro": 2, "bb_periodo_listas": 20, "bb_ventana_listas": 10}

PARAMS_BOLLINGER = dict(bt.PARAMS, estrategia="bollinger", salida="bollinger", filtro_tendencia=False, max_posiciones=3, fraccion=1.0 / 3, sizing="patrimonio", **DEFECTO)
PARAMS_BOLLINGER["ventana_ruedas"] = DEFECTO["bb_periodo"] + DEFECTO["bb_ventana"] + DEFECTO["bb_dias"]      # ruedas de arranque del motor (no hay niveles de 8 meses)


def de_params(p):
    """Los parámetros de Bollinger de un diccionario de parámetros (con los de fábrica si faltan)."""
    bp = {k: p.get(k, v) for k, v in DEFECTO.items()}
    bp["bb_pesos"] = list(bp["bb_pesos"])
    return bp


def con_bollinger(p, bp):
    """Copia de los parámetros del motor con los de Bollinger aplicados y las ruedas de arranque recalculadas."""
    q = dict(p, **bp)
    q["bb_pesos"] = list(bp["bb_pesos"])
    q["ventana_ruedas"] = bp["bb_periodo"] + bp["bb_ventana"] + bp["bb_dias"]
    return q


# ---------------------------------------------------------------- bandas

def bandas(cierres, periodo, desvios):
    """{'c': central, 's': superior, 'i': inferior, 'd': pendiente de la central} (listas; None donde no hay datos todavía)."""
    n, N = periodo, len(cierres)
    c, s, i, d = [None] * N, [None] * N, [None] * N, [None] * N
    for t in range(n - 1, N):
        w = cierres[t - n + 1:t + 1]
        m = sum(w) / n
        sd = math.sqrt(sum((x - m) ** 2 for x in w) / n)
        c[t], s[t], i[t] = m, m + desvios * sd, m - desvios * sd
        if t > n - 1:
            d[t] = m - c[t - 1]
    return {"c": c, "s": s, "i": i, "d": d}


def _racha_positiva(bb, t, tope):
    r, j = 0, t
    while r <= tope and j >= 0 and bb["d"][j] is not None and bb["d"][j] > 0:
        r += 1
        j -= 1
    return r


ETAPAS = ("giro", "magnitud", "bajada", "cruce", "encima")


def evaluar_patron(cierres, bb, t, bp):
    """(patron, etapa): patron = detalle si en la rueda t se cumplen TODAS las condiciones (None si no); etapa = cuántas condiciones seguidas, en el orden de ETAPAS, se
    cumplen (-1 si ni el giro se confirma; 4 = todas). No mira nada posterior a t."""
    L, W = bp["bb_dias"], bp["bb_ventana"]
    r = _racha_positiva(bb, t, W)
    if r < L or r + L > W:                                         # la racha de pendiente positiva tiene que ser de L ruedas o más y dejar lugar a la bajada (L ruedas) dentro de la ventana
        return None, -1
    s = t - r + 1
    ws = max(t - W + 1, 0)
    largo, d = 0, s - 1                                            # la bajada: pendientes negativas seguidas hasta el giro, dentro de la ventana
    while d >= ws and bb["d"][d] is not None and bb["d"][d] < 0:
        largo += 1
        d -= 1
    if largo < L:                                                  # forma de U: la central tiene que haber BAJADO al menos tantas ruedas como subió (un solo día negativo no es una U)
        return None, -1
    if bb["c"][t - L] is None:
        return None, -1
    c, cen = cierres, bb["c"]
    subida = cen[t] / cen[t - L] - 1
    if subida < bp["bb_magnitud_pct"] / 100 - 1e-12:
        return None, 0
    # el cruce en el piso: la última rueda de la ventana en que el cierre pasa de abajo de la central a arriba (puede ocurrir con la central todavía bajando: la central
    # es una media y gira después que el precio)
    cruces = [j for j in range(ws + 1, t + 1) if cen[j - 1] is not None and cen[j] is not None and c[j - 1] < cen[j - 1] and c[j] > cen[j]]
    j = cruces[-1] if cruces else t + 1
    # bajada: los cierres de la bajada (pendientes negativas seguidas hasta el giro, dentro de la ventana) que van ANTES del cruce estaban por debajo de la central
    bajada = 0
    for d in range(s - 1, s - 1 - largo, -1):
        if d < j:
            if c[d] >= cen[d]:
                return None, 1
            bajada += 1
    if not cruces:
        return None, 2
    if any(c[x] <= cen[x] for x in range(j, t + 1)):               # desde el cruce hasta hoy, todos los cierres encima de la central
        return None, 3
    return {"t": t, "giro_desde": s, "racha": r, "subida_central_pct": subida * 100, "cruce": j, "ruedas_bajada": bajada}, 4


def dispara(cierres, bb, t, bp):
    """¿Hay señal en t? Se cumple el patrón en t y NO se cumplía en una rueda anterior del mismo giro (una señal por giro). Devuelve el patrón o None."""
    pat, _ = evaluar_patron(cierres, bb, t, bp)
    if pat is None:
        return None
    for u in range(pat["giro_desde"] + bp["bb_dias"] - 1, t):
        if evaluar_patron(cierres, bb, u, bp)[0] is not None:
            return None
    return pat


# ---------------------------------------------------------------- salida

def salida_bollinger(cierres, bb, i, bp):
    """Simula la salida desde i+1 con cierres. Devuelve (tramos, abierta); cada tramo: {'j','px','frac','acum','motivo'} (frac = fracción de la posición ORIGINAL)."""
    w1, w2, w3 = bp["bb_pesos"]
    S = float(w1 + w2 + w3)
    objetivo = [(w1 / S, "banda superior (1.er toque)"), ((w1 + w2) / S, "banda superior (2.º toque)")]
    pesos_t = [w1 / S, w2 / S]
    toques, acum, tramos = 0, 0.0, []
    arriba_antes = bb["s"][i] is not None and cierres[i] >= bb["s"][i]
    for j in range(i + 1, len(cierres)):
        c = cierres[j]
        if bb["i"][j] is None:
            continue
        if bp["bb_stop"] and c < bb["i"][j]:
            tramos.append({"j": j, "px": c, "frac": 1.0 - acum, "acum": 1.0, "motivo": "stop (cierre bajo la banda inferior)"})
            return tramos, False
        if bb["d"][j] is not None and bb["d"][j] < 0:
            tramos.append({"j": j, "px": c, "frac": 1.0 - acum, "acum": 1.0, "motivo": "línea central a la baja"})
            return tramos, False
        arriba = c >= bb["s"][j]
        if arriba and not arriba_antes:
            toques += 1
            if toques <= 2 and pesos_t[toques - 1] > 0:
                acum = 1.0 if objetivo[toques - 1][0] >= 1 - 1e-9 else objetivo[toques - 1][0]
                tramos.append({"j": j, "px": c, "frac": pesos_t[toques - 1], "acum": acum, "motivo": objetivo[toques - 1][1]})
                if acum >= 1.0:
                    return tramos, False
        arriba_antes = arriba
    return tramos, True


# ---------------------------------------------------------------- señales (backtest)

def senales_bollinger(papel, i_min=None, p=PARAMS_BOLLINGER):
    """Todas las señales de entrada de un papel (con su salida por tramos ya simulada) y un conteo de descartes. Mismo formato que las de la ruptura escalonada,
    así corre en el mismo simulador de cartera por tramos (escalonada.simular_escalonada)."""
    bp = de_params(p)
    desc = {"sin_resistencia": 0, "bajo_media": 0, "sin_liquidez": 0}
    out = []
    n = len(papel.c)
    if n <= bp["bb_periodo"] + bp["bb_dias"]:
        return out, desc
    bb = bandas(papel.c, bp["bb_periodo"], bp["bb_desvios"])
    arranque = bp["bb_periodo"] + bp["bb_dias"]
    i_min = max(arranque, p.get("ventana_ruedas", 1) - 1) if i_min is None else max(i_min, arranque)   # el motor fija desde qué rueda se opera (ventana_ruedas)
    for t in range(i_min, n):
        if not (bb["d"][t] is not None and bb["d"][t] > 0):
            continue
        pat = dispara(papel.c, bb, t, bp)
        if not pat:
            continue
        if papel.monto5[t] < p["piso_monto"]:
            desc["sin_liquidez"] += 1
            continue
        out.append(_senal(papel, bb, bp, t))
    return out, desc


def _senal(papel, bb, bp, t):
    """Señal de entrada al cierre de t con la salida por tramos de Bollinger ya simulada (formato del simulador por tramos)."""
    n = len(papel.c)
    tramos, abierta = salida_bollinger(papel.c, bb, t, bp)
    tramos = [{**x, "fecha": papel.f[x["j"]]} for x in tramos]
    vendido = sum(x["frac"] for x in tramos)
    px_prom = sum(x["frac"] * x["px"] for x in tramos) + ((1.0 - vendido) * papel.c[n - 1] if abierta else 0.0)
    j, motivo = (n - 1, "abierta") if abierta else (tramos[-1]["j"], tramos[-1]["motivo"])
    return {"papel": papel, "i": t, "fecha": papel.f[t], "precio": papel.c[t], "soporte": bb["i"][t], "resistencia": bb["s"][t], "stop": bb["i"][t],
            "monto5": papel.monto5[t], "caida_dias": None, "caida_pct": None, "j": j, "f_salida": papel.f[j], "px_salida": px_prom, "motivo": motivo,
            "tramos_plan": tramos, "abierta_plan": abierta}


def diagnostico_patron(papeles, p=PARAMS_BOLLINGER):
    """Solo informativo: cuántos giros de la central (pendiente negativa que pasa a positiva y se sostiene 'bb_dias' ruedas) hay en todo el historial y cuántos superan cada
    condición, para ver qué descarta cada una. Se cuenta por giro, en su mejor rueda dentro de la ventana. Devuelve {'giros', 'en_u', 'con_magnitud', 'con_bajada', 'con_cruce', 'senales'}:
    'giros' = rachas de pendiente positiva de 'bb_dias' ruedas o más que vienen de una pendiente negativa; cada cifra siguiente es la cantidad que supera esa condición Y todas
    las anteriores (en_u: la bajada duró al menos 'bb_dias' ruedas; la última es la señal completa, sin el filtro de liquidez)."""
    bp = de_params(p)
    L, W = bp["bb_dias"], bp["bb_ventana"]
    cont = {"giros": 0, "en_u": 0, "con_magnitud": 0, "con_bajada": 0, "con_cruce": 0, "senales": 0}
    for papel in papeles:
        n = len(papel.c)
        if n <= bp["bb_periodo"] + L + 2:
            continue
        bb = bandas(papel.c, bp["bb_periodo"], bp["bb_desvios"])
        d = bb["d"]
        t = bp["bb_periodo"] + 1
        while t < n:
            if d[t] is not None and d[t] > 0 and d[t - 1] is not None and d[t - 1] < 0:        # empieza una racha de pendiente positiva
                s, u, mejor = t, t, None
                while u < n and d[u] is not None and d[u] > 0 and u - s + 2 <= W:
                    if u - s + 1 >= L:
                        pat, etapa = evaluar_patron(papel.c, bb, u, bp)
                        mejor = max(-1 if mejor is None else mejor, 4 if pat else etapa)
                    u += 1
                if mejor is not None:                                                        # el giro se sostuvo las ruedas exigidas
                    cont["giros"] += 1
                    cont["en_u"] += mejor >= 0
                    cont["con_magnitud"] += mejor >= 1
                    cont["con_bajada"] += mejor >= 2
                    cont["con_cruce"] += mejor >= 3
                    cont["senales"] += mejor >= 4
                t = max(u, t + 1)
            else:
                t += 1
    return cont


# ---------------------------------------------------------------- listados de CANDIDATOS (en caída / giro confirmado), sin filtro de liquidez

def _central(cierres, n):
    """Línea central (media de n cierres) y su pendiente, por rueda (None donde no hay datos)."""
    N = len(cierres)
    c, d = [None] * N, [None] * N
    for t in range(n - 1, N):
        c[t] = sum(cierres[t - n + 1:t + 1]) / n
        if t > n - 1:
            d[t] = c[t] - c[t - 1]
    return c, d


def _preparar_listas(cierres, n):
    """Central, pendiente y 'cierres seguidos por debajo de la central' en cada rueda (se calculan una vez por papel)."""
    cen, d = _central(cierres, n)
    bajo = [0] * len(cierres)
    for i in range(n - 1, len(cierres)):
        bajo[i] = ((bajo[i - 1] + 1) if i > n - 1 else 1) if cierres[i] < cen[i] else 0
    return cen, d, bajo


def _estado_en(t, cierres, cen, d, bajo, n, K, G, W):
    """Estado de la rueda t (usa solo datos hasta t): {'lista': 1 | 2 | None, ...}. Ver estado_listas."""
    base = {"precio": cierres[t], "central": cen[t], "dist_central_pct": (cierres[t] / cen[t] - 1) * 100,
            "pendiente_pct": d[t] / cen[t] * 100 if d[t] is not None else None, "lista": None}
    if d[t] is not None and d[t] < 0 and bajo[t] >= K:
        return {**base, "lista": 1, "velas_bajo": bajo[t]}
    sobre = 0                                                                      # cierres SEGUIDOS por encima de la central, terminando hoy (no hay tope: alcanza con G o más)
    while t - sobre >= n and cierres[t - sobre] > cen[t - sobre]:
        sobre += 1
    if sobre >= G and d[t] is not None and d[t] > 0:                               # giro confirmado: al menos G cierres encima y la central EN ALZA hoy
        # el cambio de pendiente de negativa a positiva: antes el papel estuvo en el listado 1 (K o más cierres seguidos bajo la central con la central BAJANDO), terminado hace W ruedas o menos
        # y antes de esas ruedas por encima; entre una cosa y otra puede haber velas atravesadas por la línea
        caidas = [u for u in range(max(n, t - W), t - G + 1) if d[u] is not None and d[u] < 0 and bajo[u] >= K]
        if caidas:
            return {**base, "lista": 2, "velas_sobre": sobre, "velas_bajo_antes": max(bajo[u] for u in caidas), "ruedas_desde_listado1": t - caidas[-1], "ultimo_listado1": caidas[-1]}
    return base


def estado_listas(papel, p):
    """Dónde está un papel en la última rueda, según los dos listados (para los CEDEARs; sin mirar la liquidez):
    LISTADO 1 (en caída): al menos 'bb_velas_caida' cierres SEGUIDOS (terminando hoy) por debajo de la línea central, y la central con pendiente negativa hoy.
    (La central de los listados es la media de 'bb_periodo_listas' cierres, 5 por defecto: propia de los listados y editable, independiente de la 'bb_periodo' de la estrategia de Bollinger.)
    LISTADO 2 (cambio de pendiente de negativa a positiva, señal de entrada): (1) la central EN ALZA hoy (pendiente positiva); (2) AL MENOS 'bb_velas_giro' (2) cierres seguidos por ENCIMA de la
      central terminando hoy (no importa cuántos más); (3) el cambio de pendiente: antes el papel estuvo en el listado 1 (al menos 'bb_velas_caida' = 5 cierres seguidos por DEBAJO de la central con
      la central con pendiente NEGATIVA) y esa caída terminó hace 'bb_ventana_listas' ruedas (10) o menos. Entre la caída y los cierres por encima puede haber velas atravesadas por la línea.
      (Una versión anterior no exigía la pendiente positiva y dejaba entrar papeles con la central todavía bajando.)
    Devuelve None si no hay datos suficientes; si no, {'lista': 1 | 2 | None, ...detalle}."""
    bp = de_params(p)
    n, K, G = bp["bb_periodo_listas"], bp["bb_velas_caida"], bp["bb_velas_giro"]
    N = len(papel.c)
    if N < n + K + G + 2:
        return None
    cen, d, bajo = _preparar_listas(papel.c, n)
    return _estado_en(N - 1, papel.c, cen, d, bajo, n, K, G, bp["bb_ventana_listas"])


PARAMS_LISTAS = dict(PARAMS_BOLLINGER, estrategia="bollinger_listas")


def senales_listas(papel, i_min=None, p=PARAMS_LISTAS):
    """ESTRATEGIA DE LOS DOS LISTADOS. Entrada al cierre de la primera rueda en que el papel está en el LISTADO 2 (giro confirmado tras haber estado en el LISTADO 1) para cada episodio
    de caída (se identifica por la última rueda en que estuvo en el listado 1: un episodio da UNA señal), y operable: monto promedio de 5 ruedas >= el piso de liquidez (en los listados el
    filtro se saca para VER las señales; para operar hace falta liquidez, igual que en todos los backtests). Salida: la escalonada de Bollinger (tramos en los toques de la banda
    superior, central a la baja, stop bajo la banda inferior). Mismo formato de señales que las demás (corre en el simulador por tramos)."""
    bp = de_params(p)
    n, K, G, W = bp["bb_periodo_listas"], bp["bb_velas_caida"], bp["bb_velas_giro"], bp["bb_ventana_listas"]       # la entrada usa la central de los listados; la salida, las bandas de Bollinger (bb_periodo, bb_desvios)
    desc = {"sin_resistencia": 0, "bajo_media": 0, "sin_liquidez": 0, "episodios": 0}
    out = []
    N = len(papel.c)
    arranque = max(n + K + G + 2, bp["bb_periodo"] + bp["bb_dias"])
    if N < arranque:
        return out, desc
    bb = bandas(papel.c, bp["bb_periodo"], bp["bb_desvios"])
    cen, d, bajo = _preparar_listas(papel.c, n)
    i_min = max(arranque, p.get("ventana_ruedas", 1) - 1) if i_min is None else max(i_min, arranque)
    usados, vistos = set(), set()
    for t in range(i_min, N):
        e = _estado_en(t, papel.c, cen, d, bajo, n, K, G, W)
        if e["lista"] != 2 or e["ultimo_listado1"] in usados:
            continue
        if e["ultimo_listado1"] not in vistos:
            vistos.add(e["ultimo_listado1"])
            desc["episodios"] += 1
        if papel.monto5[t] < p["piso_monto"]:
            desc["sin_liquidez"] += 1                                             # si el papel gana liquidez más adelante en el mismo episodio, entra ese día
            continue
        usados.add(e["ultimo_listado1"])
        out.append(_senal(papel, bb, bp, t))
    return out, desc


def listas(papeles, p, datos_sectores=None, etiquetar=None):
    """Los dos listados para los CEDEARs en pesos. SIN filtro de liquidez (en caída el volumen baja): cada papel lleva su monto promedio de 5 ruedas, el monto y el volumen de la
    última rueda, y si es 'operable' (monto promedio >= el piso de liquidez) o 'solo señal'. Una empresa una vez (la línea más líquida). Ordenado: operables primero, y por monto."""
    piso = p.get("piso_monto", bt.PARAMS["piso_monto"])
    por_lista = {1: {}, 2: {}}
    evaluados = 0
    ultima = max((x.f[-1] for x in papeles if x.f), default=None)
    for pa in papeles:
        if pa.tipo != "cedear" or not pa.f or (ultima - pa.f[-1]).days > 5:          # solo CEDEARs con cotización reciente
            continue
        e = estado_listas(pa, p)
        if e is None:
            continue
        evaluados += 1
        if not e["lista"]:
            continue
        emp = etiquetar(pa.ticker) if etiquetar else pa.ticker
        fila = {"ticker": pa.ticker, "empresa": emp, **{k: v for k, v in e.items() if k != "lista"}, "fecha": str(pa.f[-1]),
                "monto5_millones": pa.monto5[-1] / 1e6, "monto_dia_millones": pa.monto[-1] / 1e6, "volumen_dia": pa.vol[-1], "operable": pa.monto5[-1] >= piso}
        previa = por_lista[e["lista"]].get(emp)
        if previa is None or fila["monto5_millones"] > previa["monto5_millones"]:
            fila["otras_lineas"] = sorted(([previa["ticker"]] + previa.get("otras_lineas", [])) if previa else [])
            por_lista[e["lista"]][emp] = fila
        else:
            previa["otras_lineas"] = sorted(previa.get("otras_lineas", []) + [fila["ticker"]])
    orden = lambda L: sorted(L.values(), key=lambda f: (not f["operable"], -f["monto5_millones"]))
    l1, l2 = orden(por_lista[1]), orden(por_lista[2])
    bp = de_params(p)
    return {"evaluados": evaluados, "piso_millones": piso / 1e6, "lista1": l1, "lista2": l2,
            "criterios": {"periodo": bp["bb_periodo_listas"], "velas_caida": bp["bb_velas_caida"], "velas_giro": bp["bb_velas_giro"], "ventana": bp["bb_ventana_listas"]},
            "resumen": {"lista1": len(l1), "lista1_operables": sum(f["operable"] for f in l1), "lista2": len(l2), "lista2_operables": sum(f["operable"] for f in l2)}}
