"""
sectores.py — Clasificación del universo por grupo y sector, y filtro por sector.

  Grupo   : 'Merval' (acciones argentinas) o 'CEDEAR'. Sale del tipo de especie del panel de BYMA.
  Sector  : Merval -> energeticas, bancos, otros.
            CEDEAR -> energeticas, tecnologicas, ETF, bancos, alimentarias, otros.
  Subsector (solo tecnologicas): IA, computadoras, satelites, otras.
  'sin_clasificar' = papel que todavía no está en datos/sectores.json (no se sabe a qué sector pertenece; hay que revisarlo a mano).

La clasificación vive en datos/sectores.json (editable): papeles -> {grupo, sector, subsector}. Las especies que son otra línea de la misma
empresa (AAPLB es AAPL, GGALB es GGAL) están en 'subyacente', para no contar dos veces a la misma empresa ni analizarla dos veces.

Este módulo solo CLASIFICA y FILTRA. No contiene estrategias.
"""
import json, os, unicodedata

RUTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "datos", "sectores.json")

GRUPOS = {"Merval": ("energeticas", "bancos", "otros"),
          "CEDEAR": ("energeticas", "tecnologicas", "ETF", "bancos", "alimentarias", "otros")}
SUBSECTORES = {"tecnologicas": ("IA", "computadoras", "satelites", "otras")}


def _norm(x):
    """Minúsculas y sin acentos: 'Energéticas' == 'energeticas'."""
    if x is None:
        return None
    return unicodedata.normalize("NFKD", str(x)).encode("ascii", "ignore").decode().strip().lower()


def cargar(ruta=RUTA):
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def subyacente(ticker, datos):
    """Ticker de la empresa de la que esta especie es otra línea (si no es una variante, el mismo ticker)."""
    return datos.get("subyacente", {}).get(ticker, ticker)


def etiquetar(ticker, tipo, datos):
    """{'grupo','sector','subsector','subyacente','clasificado'} de un papel. tipo: 'accion' o 'cedear' (el del panel de BYMA)."""
    base = subyacente(ticker, datos)
    grupo = "Merval" if tipo == "accion" else "CEDEAR"
    e = datos["papeles"].get(base) or datos["papeles"].get(ticker)
    if e:
        return {"grupo": e["grupo"], "sector": e["sector"], "subsector": e.get("subsector"), "subyacente": base, "clasificado": True}
    return {"grupo": grupo, "sector": "sin_clasificar", "subsector": None, "subyacente": base, "clasificado": False}


def filtrar(papeles, grupo=None, sector=None, subsector=None, datos=None):
    """Papeles (objetos con .ticker y .tipo) que cumplen el filtro. Los argumentos aceptan mayúsculas, minúsculas y acentos."""
    datos = datos or cargar()
    g, s, ss = _norm(grupo), _norm(sector), _norm(subsector)
    out = []
    for p in papeles:
        e = etiquetar(p.ticker, p.tipo, datos)
        if g and _norm(e["grupo"]) != g:
            continue
        if s and _norm(e["sector"]) != s:
            continue
        if ss and _norm(e["subsector"]) != ss:
            continue
        out.append(p)
    return out


def sectores_validos(datos=None):
    """Combinaciones (grupo, sector, subsector) de la taxonomía, en orden, para armar tablas completas aunque haya sectores vacíos."""
    filas = []
    for grupo, sectores in GRUPOS.items():
        for sector in sectores:
            subs = SUBSECTORES.get(sector) if grupo == "CEDEAR" else None
            if subs:
                filas += [(grupo, sector, sub) for sub in subs]
            else:
                filas.append((grupo, sector, None))
    return filas


def contar(papeles, piso, datos=None, desde=None):
    """Cuántos papeles hay en cada sector. Cada papel (con .ticker, .tipo, .monto5) cuenta como:
       - especie: cada línea cotizada (AAPL y AAPLB son 2);
       - subyacente: cada empresa distinta (AAPL y AAPLB son 1).
       'hoy' = monto promedio de las últimas 5 ruedas >= piso (la definición de la app). 'alguna vez' = lo fue en algún momento del período
       (es lo que puede entrar a un backtest, que mira cada fecha con su liquidez de ese momento).
       'promedio_diario' = cuántas empresas líquidas hay, en promedio, en un día del período (desde `desde`): es lo que de verdad se puede
       analizar en una fecha cualquiera; 'alguna vez' lo sobrestima porque hay papeles que fueron líquidos solo unas semanas."""
    datos = datos or cargar()
    filas = {}
    for p in papeles:
        e = etiquetar(p.ticker, p.tipo, datos)
        clave = (e["grupo"], e["sector"], e["subsector"])
        f = filas.setdefault(clave, {"especies": set(), "hoy": set(), "alguna": set(), "sub_especies": set(), "sub_hoy": set(), "sub_alguna": set(), "dias": {}})
        for fecha, m in zip(p.f, p.monto5):
            if m >= piso and (desde is None or fecha >= desde):
                f["dias"].setdefault(fecha, set()).add(e["subyacente"])
        f["especies"].add(p.ticker); f["sub_especies"].add(e["subyacente"])
        if p.monto5 and p.monto5[-1] >= piso:
            f["hoy"].add(p.ticker); f["sub_hoy"].add(e["subyacente"])
        if p.monto5 and max(p.monto5) >= piso:
            f["alguna"].add(p.ticker); f["sub_alguna"].add(e["subyacente"])
    out = []
    dias_total = sorted({fecha for p in papeles for fecha in p.f if desde is None or fecha >= desde})
    orden = {k: i for i, k in enumerate(sectores_validos(datos))}
    for clave in sorted(set(filas) | set(orden), key=lambda k: (orden.get(k, 999), k[0], k[1], str(k[2]))):
        f = filas.get(clave, {})
        g = lambda k: sorted(f.get(k, ()))
        out.append({"grupo": clave[0], "sector": clave[1], "subsector": clave[2],
                    "especies": len(g("especies")), "empresas": len(g("sub_especies")),
                    "liquidas_hoy": len(g("hoy")), "empresas_liquidas_hoy": len(g("sub_hoy")),
                    "liquidas_alguna_vez": len(g("alguna")), "empresas_liquidas_alguna_vez": len(g("sub_alguna")),
                    "promedio_diario": round(sum(len(v) for v in f.get("dias", {}).values()) / max(1, len(dias_total)), 2),
                    "tickers_liquidos_alguna_vez": g("alguna")})
    return out
