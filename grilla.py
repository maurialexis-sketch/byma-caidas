"""
grilla.py — Grilla de la estrategia de RUPTURA con SOLO trailing stop: cantidad de posiciones cruzada con el porcentaje del trailing.

Misma entrada, mismos datos y costos en las 6 celdas; solo cambian la cantidad de posiciones y el trailing. Para que la cantidad de
posiciones sea lo único que varía, cada posición es 1/N del patrimonio total al entrar (con tope en el efectivo libre).

ESTABILIDAD: cada celda se simula empezando en 17 fechas distintas (una por semana, semanas 0 a 16 desde el inicio del backtest) y se miden:
  - amplitud: mejor retorno menos peor retorno entre los arranques (en puntos porcentuales);
  - el peor arranque, la mediana y el mejor;
  - en cuántos arranques la ganancia es positiva y en cuántos le gana al Merval del MISMO tramo;
  - la amplitud del exceso sobre el Merval (retorno de la estrategia menos el del Merval, arranque por arranque).
Una amplitud baja sola puede premiar a una estrategia que casi no opera; por eso se muestran las demás.
"""
import backtest as bt
import ruptura as rp

POSICIONES = (2, 3, 5)
TRAILINGS = (15.0, 20.0)
SEMANAS = tuple(range(0, 17))


def parametros(n, trailing):
    """Parámetros de una celda: solo trailing, n posiciones de 1/n del patrimonio cada una."""
    return dict(rp.PARAMS_TRAILING_SOLO, trailing_pct=float(trailing), max_posiciones=n, fraccion=1.0 / n, sizing="patrimonio")


def clave(n, trailing):
    return f"{n}p_{trailing:g}"


def configuraciones(posiciones=POSICIONES, trailings=TRAILINGS):
    return [(n, t, parametros(n, t)) for n in posiciones for t in trailings]


def estabilidad(filas):
    """Estadísticas de estabilidad a partir de bt.sensibilidad_inicio (una fila por día de arranque)."""
    r = sorted(f["retorno_pct"] for f in filas)
    exceso = [f["retorno_pct"] - f["merval_pct"] for f in filas if f["merval_pct"] is not None]
    n = len(r)
    mediana = r[n // 2] if n % 2 else (r[n // 2 - 1] + r[n // 2]) / 2
    return {"arranques": n, "amplitud_pp": r[-1] - r[0], "peor_pct": r[0], "mediana_pct": mediana, "mejor_pct": r[-1],
            "positivos": sum(x > 0 for x in r), "le_ganan_al_merval": sum(1 for f in filas if f["merval_pct"] is not None and f["retorno_pct"] > f["merval_pct"]),
            "amplitud_exceso_pp": (max(exceso) - min(exceso)) if exceso else None,
            "peor_exceso_pp": min(exceso) if exceso else None}


def mas_estable(celdas):
    """La celda de menor amplitud; ante empate, la de mejor peor arranque. (Criterio pedido: estabilidad, no ganancia.)"""
    return min(celdas, key=lambda c: (round(c["estabilidad"]["amplitud_pp"], 6), -c["estabilidad"]["peor_pct"]))["clave"]


def correr_grilla(papeles, merval, posiciones=POSICIONES, trailings=TRAILINGS, semanas=SEMANAS):
    """Corre las celdas. Devuelve [{'clave','posiciones','trailing','params','res','arranques','estabilidad'}]."""
    celdas = []
    for n, t, p in configuraciones(posiciones, trailings):
        res = bt.correr(papeles, merval, p, generar=rp.senales_ruptura)
        if not res:
            continue
        filas = bt.sensibilidad_inicio(papeles, p, rp.senales_ruptura, merval, semanas=semanas)
        celdas.append({"clave": clave(n, t), "posiciones": n, "trailing": t, "params": p, "res": res,
                       "arranques": filas, "estabilidad": estabilidad(filas)})
    return celdas
