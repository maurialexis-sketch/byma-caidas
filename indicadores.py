"""
indicadores.py — Medias móviles simples y Bandas de Bollinger sobre el CIERRE AJUSTADO (los cierres de Papel ya vienen ajustados por splits y cambios de ratio; BYMA no publica dividendos), y las variables
derivadas por activo. Los períodos (9, 50, 200), el de Bollinger (20) y sus desvíos (2) están en config_indicadores.json: no están escritos en el código.

REGLA DE DATOS: si hay menos ruedas que el período, el valor queda VACÍO (None / null). No se rellena ni se aproxima (no hay «media con las ruedas que haya»).

Variables derivadas (de la última rueda de cada activo):
  - mm{n}                : media móvil simple de n cierres.
  - dist_mm{n}_pct       : distancia % del precio a esa media = precio / media − 1.
  - pend_mm{n}_pct       : pendiente de la media = variación % de la media en 'pendiente_ruedas' (5) ruedas = media[hoy] / media[hoy − 5] − 1.
  - tendencia_de_fondo   : precio > MM200 → 'alcista'; precio < MM200 → 'bajista'; igual → 'neutra'; sin MM200 → None.
  - cruces               : para cada par de 'cruces_pares' (MM9/MM50 y MM50/MM200), el cruce más reciente dentro de las últimas 'cruces_ventana' (10) ruedas:
                           'alcista' = la media corta pasa de estar debajo (o igual) a estar por encima de la larga; 'bajista' = al revés. Con fecha y cuántas ruedas atrás.
  - bollinger            : central (media de 20), superior e inferior (± 2 desvíos estándar poblacionales de esos mismos 20 cierres).
Nada de esto modifica los filtros de la lista corta de candidatos: es solo información.
"""
import json, math, os

RUTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config_indicadores.json")
_CACHE = {}


def cargar(ruta=None):
    """La configuración (validada). Sin ruta, la del repositorio (se lee una vez)."""
    ruta = ruta or RUTA
    if ruta not in _CACHE:
        with open(ruta, encoding="utf-8") as f:
            c = json.load(f)
        per = c.get("mm_periodos")
        if not per or any(not isinstance(n, int) or n < 2 for n in per):
            raise ValueError(f"{os.path.basename(ruta)}: 'mm_periodos' tiene que ser una lista de enteros >= 2")
        b = c.get("bollinger") or {}
        if not isinstance(b.get("periodo"), int) or b["periodo"] < 2 or not (isinstance(b.get("desvios"), (int, float)) and b["desvios"] > 0):
            raise ValueError(f"{os.path.basename(ruta)}: 'bollinger' necesita 'periodo' (entero >= 2) y 'desvios' (> 0)")
        for par in c.get("cruces_pares", []):
            if len(par) != 2 or any(n not in per for n in par):
                raise ValueError(f"{os.path.basename(ruta)}: cada par de 'cruces_pares' tiene que usar períodos de 'mm_periodos'")
        if c.get("tendencia_de_fondo_mm") not in per:
            raise ValueError(f"{os.path.basename(ruta)}: 'tendencia_de_fondo_mm' tiene que ser uno de 'mm_periodos'")
        _CACHE[ruta] = c
    return _CACHE[ruta]


def sma(cierres, n):
    """Media móvil simple de n cierres en cada rueda; None donde todavía no hay n ruedas (no se rellena)."""
    N = len(cierres)
    out = [None] * N
    if n > N:
        return out
    acc = sum(cierres[:n])
    out[n - 1] = acc / n
    for i in range(n, N):
        acc += cierres[i] - cierres[i - n]
        out[i] = acc / n
    return out


def bandas(cierres, periodo, desvios):
    """(central, superior, inferior) por rueda: media de 'periodo' cierres ± 'desvios' desvíos estándar poblacionales (la fórmula clásica de Bollinger). None donde no hay 'periodo' ruedas."""
    N = len(cierres)
    c, s, i = [None] * N, [None] * N, [None] * N
    for t in range(periodo - 1, N):
        w = cierres[t - periodo + 1:t + 1]
        m = sum(w) / periodo
        sd = math.sqrt(sum((x - m) ** 2 for x in w) / periodo)
        c[t], s[t], i[t] = m, m + desvios * sd, m - desvios * sd
    return c, s, i


def _cruces(mm, a, b, t, ventana, fechas):
    """Cruce más reciente de la media a (corta) con la b (larga) entre las últimas 'ventana' ruedas que terminan en t."""
    sa, sb = mm[a], mm[b]
    hay = sa[t] is not None and sb[t] is not None
    res = {"hay_datos": hay, "tipo": None, "fecha": None, "ruedas_atras": None}
    for j in range(t, max(t - ventana, 0), -1):                                   # j = rueda del cruce (j-1 es la anterior): j recorre las últimas 'ventana' ruedas
        if None in (sa[j], sb[j], sa[j - 1], sb[j - 1]):
            continue
        previo, hoy = sa[j - 1] - sb[j - 1], sa[j] - sb[j]
        if previo <= 0 < hoy:
            return {**res, "tipo": "alcista", "fecha": str(fechas[j]), "ruedas_atras": t - j}
        if previo >= 0 > hoy:
            return {**res, "tipo": "bajista", "fecha": str(fechas[j]), "ruedas_atras": t - j}
    return res


def _r(x, d=4):
    return None if x is None else round(x, d)


def calcular(cierres, fechas, t=None, cfg=None):
    """Todos los indicadores de la rueda t (la última por defecto), con sus derivadas. 'cierres' = cierres ajustados; 'fechas' = fecha de cada uno."""
    cfg = cfg or cargar()
    t = len(cierres) - 1 if t is None else t
    mm = {n: sma(cierres[:t + 1], n) for n in cfg["mm_periodos"]}
    k = cfg["pendiente_ruedas"]
    precio = cierres[t]
    out = {"fecha": str(fechas[t]), "cierre": _r(precio), "ruedas": t + 1}
    for n in cfg["mm_periodos"]:
        m = mm[n][t]
        previa = mm[n][t - k] if t - k >= 0 else None
        out[f"mm{n}"] = _r(m)
        out[f"dist_mm{n}_pct"] = _r((precio / m - 1) * 100, 2) if m is not None else None
        out[f"pend_mm{n}_pct"] = _r((m / previa - 1) * 100, 3) if m is not None and previa is not None else None
    base = mm[cfg["tendencia_de_fondo_mm"]][t]
    out["tendencia_de_fondo"] = None if base is None else ("alcista" if precio > base else "bajista" if precio < base else "neutra")
    out["cruces"] = {f"mm{a}_mm{b}": _cruces(mm, a, b, t, cfg["cruces_ventana"], fechas) for a, b in cfg["cruces_pares"]}
    c, s, i = bandas(cierres[:t + 1], cfg["bollinger"]["periodo"], cfg["bollinger"]["desvios"])
    out["bollinger"] = {"central": _r(c[t]), "superior": _r(s[t]), "inferior": _r(i[t])}
    return out


def ultimos_dias(cierres, fechas, k=5, cfg=None):
    """Los indicadores de las últimas k ruedas (para comparar contra un gráfico): [{'fecha','cierre','mm9',...,'bb_central','bb_superior','bb_inferior'}]."""
    cfg = cfg or cargar()
    N = len(cierres)
    mm = {n: sma(cierres, n) for n in cfg["mm_periodos"]}
    c, s, i = bandas(cierres, cfg["bollinger"]["periodo"], cfg["bollinger"]["desvios"])
    filas = []
    for t in range(N - k, N):
        fila = {"fecha": str(fechas[t]), "cierre": _r(cierres[t])}
        for n in cfg["mm_periodos"]:
            fila[f"mm{n}"] = _r(mm[n][t])
        fila.update({"bb_central": _r(c[t]), "bb_superior": _r(s[t]), "bb_inferior": _r(i[t])})
        filas.append(fila)
    return filas


def de_papel(papel, cfg=None):
    """Indicadores de la última rueda de un Papel (cierre ajustado)."""
    return calcular(papel.c, papel.f, None, cfg)


def columnas(cfg=None):
    """Nombres de las columnas de la tabla plana (una fila por activo) que viaja en el informe y se baja como CSV. Salen de la configuración."""
    cfg = cfg or cargar()
    cols = ["ticker", "tipo", "fecha", "cierre_ajustado", "ruedas", "monto_5_ruedas_millones", "operable", "en_lista"]
    cols += [f"mm{n}" for n in cfg["mm_periodos"]]
    cols += [f"dist_mm{n}_pct" for n in cfg["mm_periodos"]]
    cols += [f"pend_mm{n}_{cfg['pendiente_ruedas']}r_pct" for n in cfg["mm_periodos"]]
    cols += ["tendencia_de_fondo"]
    for a, b in cfg["cruces_pares"]:
        cols += [f"cruce_mm{a}_mm{b}", f"cruce_mm{a}_mm{b}_ruedas_atras"]
    cols += [f"bb{cfg['bollinger']['periodo']}_central", f"bb{cfg['bollinger']['periodo']}_superior", f"bb{cfg['bollinger']['periodo']}_inferior"]
    return cols


def fila_plana(ticker, tipo, ind, monto5_millones, operable, en_lista, cfg=None):
    """Una fila de la tabla plana (en el orden de columnas())."""
    cfg = cfg or cargar()
    fila = [ticker, tipo, ind["fecha"], ind["cierre"], ind["ruedas"], None if monto5_millones is None else round(monto5_millones, 1), 1 if operable else 0, en_lista or ""]
    fila += [ind[f"mm{n}"] for n in cfg["mm_periodos"]]
    fila += [ind[f"dist_mm{n}_pct"] for n in cfg["mm_periodos"]]
    fila += [ind[f"pend_mm{n}_pct"] for n in cfg["mm_periodos"]]
    fila += [ind["tendencia_de_fondo"]]
    for a, b in cfg["cruces_pares"]:
        x = ind["cruces"][f"mm{a}_mm{b}"]
        fila += [x["tipo"], x["ruedas_atras"]]
    fila += [ind["bollinger"]["central"], ind["bollinger"]["superior"], ind["bollinger"]["inferior"]]
    return fila
