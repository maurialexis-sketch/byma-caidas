"""
ruptura.py — Estrategia de RUPTURA al alza (separada de la de caídas; corre en el mismo motor de backtest.py).

ENTRADA (al cierre del día t, con datos hasta t; nada del futuro):
  1. Liquidez: monto promedio de las últimas 5 ruedas >= 1.000 M (con el monto de ESA época, en pesos nominales).
  2. Ruptura: el cierre de t queda por encima de una resistencia de los últimos 8 meses (168 ruedas; zonas de pivotes
     con 2+ toques, las mismas que usa la estrategia de caídas) que el cierre de t-1 todavía no había superado.
     Si en un día se superan varias zonas, la resistencia rota es la más alta de ellas.
  3. Tendencia alcista: el cierre de t por encima de su media móvil de 200 ruedas (de 150 si el papel no tiene 200 de histórico).
SALIDA (lo que ocurra primero, evaluado desde t+1):
  - Stop: el papel VUELVE A CERRAR por debajo de la resistencia rota -> sale a ese cierre (no hay stop intradiario).
  - Tiempo: a las 20 ruedas, al cierre.
  No hay objetivo de ganancia: el tiempo es la única salida con ganancia.
GESTIÓN Y COSTOS: idénticos a la estrategia de caídas (máximo 2 posiciones, cada una con la mitad del efectivo libre;
  mismas comisiones, derechos de mercado e IVA; mismo criterio de desempate por monto operado).
Las señales usan los mismos campos que las de caídas para correr en el mismo simulador de cartera.
"""
import backtest as bt

# Mismos parámetros de gestión, costos y liquidez que la estrategia de caídas (se copian de bt.PARAMS); acá no hay stop por
# porcentaje ni filtro de caída. 'filtro_tendencia' queda en True porque en esta estrategia la tendencia es parte de la regla.
PARAMS_RUPTURA = dict(bt.PARAMS, filtro_tendencia=True, estrategia="ruptura")


def salida_ruptura(papel, i, nivel, p=PARAMS_RUPTURA):
    """Simula la salida desde i+1: stop si el CIERRE queda por debajo de la resistencia rota, o tiempo a las dias_max ruedas."""
    n = len(papel.c)
    for j in range(i + 1, min(n, i + p["dias_max"] + 1)):
        if papel.c[j] < nivel:
            return j, papel.c[j], "stop"
        if j - i == p["dias_max"]:
            return j, papel.c[j], "tiempo"
    return n - 1, papel.c[n - 1], "abierta"


def senales_ruptura(papel, i_min=None, p=PARAMS_RUPTURA):
    """Todas las señales de ruptura de un papel (con su salida ya simulada) y un conteo de descartes.
    'bajo_media' cuenta las rupturas que NO entraron por cotizar bajo su media móvil (dato informativo)."""
    desc = {"sin_resistencia": 0, "bajo_media": 0}
    out = []
    i_min = max(p["ventana_ruedas"] - 1, 1) if i_min is None else i_min
    for i in range(i_min, len(papel.c)):
        if papel.monto5[i] < p["piso_monto"] or papel.c[i] <= papel.c[i - 1]:
            continue                                   # sin liquidez, o no subió (una ruptura nueva implica cierre al alza)
        _, techos = bt.niveles(papel, i, p)
        rotas = [z for z in techos if papel.c[i - 1] <= z < papel.c[i]]
        if not rotas:
            continue
        z = max(rotas)
        if not bt.sobre_la_media(papel, i, p):
            desc["bajo_media"] += 1                    # rompió el techo, pero no está en tendencia alcista: no entra
            continue
        j, px, motivo = salida_ruptura(papel, i, z, p)
        out.append({"papel": papel, "i": i, "fecha": papel.f[i], "precio": papel.c[i], "soporte": None, "resistencia": z,
                    "stop": z, "monto5": papel.monto5[i], "caida_dias": None, "caida_pct": None,
                    "j": j, "f_salida": papel.f[j], "px_salida": px, "motivo": motivo})
    return out, desc
