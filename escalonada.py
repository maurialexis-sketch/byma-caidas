"""
escalonada.py — Estrategia de RUPTURA con SALIDA ESCALONADA (toma de ganancia por tramos). Estrategia NUEVA y separada: no cambia ninguna de las anteriores.

ENTRADA: exactamente la misma de la ruptura (ruptura.senales_ruptura): papel líquido (monto promedio de 5 ruedas >= 1.000 M), en tendencia alcista
  (cierre sobre su media de 200 ruedas; 150 si no hay 200) y cierre por encima de una resistencia de 8 meses que el cierre anterior no había superado.
SALIDA, medida sobre el PRECIO DE COMPRA y evaluada con CIERRES (igual que el trailing de la ruptura: no se supone ninguna orden intradiaria):
  - cierre >= +10%: se vende el 40% de la posición original;  cierre >= +15%: otro 40%;  cierre >= +20%: el 20% restante.
    Si un solo cierre cruza varios escalones (un gap), se venden todos esos tramos a ese cierre.
  - Stop inicial (hasta que algún cierre toque +10%): si el cierre cae 8% o más bajo el precio de compra, se vende TODO lo que quede.
  - Stop trailing (desde que un cierre tocó +10%): 8% bajo el máximo cierre alcanzado desde la compra; nunca baja. Si el cierre lo toca, se vende TODO lo que
    quede. El trailing reemplaza al stop inicial recién en ese momento. El nivel que rige un día es el de la rueda anterior (se actualiza después de mirar el cierre).
  No hay límite de ruedas ni stop de ruptura. Lo que sigue sin vender al final de los datos queda ABIERTO y se informa aparte.
GESTIÓN Y COSTOS: la cartera de 3 posiciones de 1/3 del patrimonio (tope en el efectivo libre) y los mismos costos que el resto (≈0,70% por lado). CADA VENTA
  PARCIAL PAGA SU COSTO: el costo es proporcional al monto de cada orden (no se modela un mínimo por orden del broker).
Las acciones son enteras: los tramos del 40% se redondean hacia abajo y el último tramo vende lo que queda.
"""
import math

import backtest as bt
import ruptura as rp

OBJETIVOS = [[10.0, 0.4], [15.0, 0.4], [20.0, 0.2]]     # [ganancia % sobre la compra, fracción de la posición ORIGINAL que se vende]

PARAMS_ESCALONADA = dict(rp.PARAMS_TRAILING_SOLO, salida="escalonada", objetivos=OBJETIVOS, stop_inicial_pct=8.0, trailing_pct=8.0,
                         umbral_trailing_pct=10.0, max_posiciones=3, fraccion=1.0 / 3, sizing="patrimonio", stop_ruptura=False)


def salida_escalonada(papel, i, p=PARAMS_ESCALONADA):
    """Simula la salida desde i+1. Devuelve (tramos, abierta). Cada tramo: {'j','fecha','px','frac','acum','motivo'}; 'frac' es la fracción de la posición
    ORIGINAL que se vende en ese tramo y 'acum' lo vendido hasta ahí. Si los datos terminan con posición sin vender, abierta=True."""
    compra = papel.c[i]
    objetivos = [(compra * (1 + pct / 100), frac, pct) for pct, frac in p["objetivos"]]
    umbral = compra * (1 + p["umbral_trailing_pct"] / 100)
    k = 1 - p["trailing_pct"] / 100
    stop = compra * (1 - p["stop_inicial_pct"] / 100)
    maximo, trailing, hechos, acum, tramos = compra, False, 0, 0.0, []
    eps = compra * 1e-9                                  # 100 × 1,10 da 110,00000000000001: el borde exacto (cierre justo en +10%) cuenta
    for j in range(i + 1, len(papel.c)):
        c = papel.c[j]
        if c <= stop + eps:                              # el stop vigente es el de la rueda anterior
            tramos.append({"j": j, "fecha": papel.f[j], "px": c, "frac": 1.0 - acum, "acum": 1.0, "motivo": "trailing" if trailing else "stop"})
            return tramos, False
        maximo = max(maximo, c)
        while hechos < len(objetivos) and c >= objetivos[hechos][0] - eps:
            _, frac, pct = objetivos[hechos]
            acum = 1.0 if hechos == len(objetivos) - 1 else acum + frac
            tramos.append({"j": j, "fecha": papel.f[j], "px": c, "frac": frac, "acum": acum, "motivo": f"+{pct:g}%"})
            hechos += 1
        if hechos == len(objetivos):
            return tramos, False
        if c >= umbral - eps:
            trailing = True
        if trailing:
            stop = max(stop, maximo * k)
    return tramos, True


def senales_escalonada(papel, i_min=None, p=PARAMS_ESCALONADA):
    """Las señales de la ruptura (las MISMAS entradas, tomadas de ruptura.senales_ruptura) con la salida escalonada ya simulada."""
    p_entrada = dict(p, salida="trailing", trailing_pct=15.0, stop_ruptura=False)      # solo para reutilizar la entrada; su salida se descarta
    base, desc = rp.senales_ruptura(papel, i_min, p_entrada)
    out = []
    for x in base:
        tramos, abierta = salida_escalonada(papel, x["i"], p)
        n = len(papel.c)
        vendido = sum(t["frac"] for t in tramos)
        ultimo = papel.c[n - 1]
        px_prom = (sum(t["frac"] * t["px"] for t in tramos) + (0.0 if not abierta else (1.0 - vendido) * ultimo)) / 1.0
        if abierta:
            j, motivo = n - 1, "abierta"
        else:
            j, motivo = tramos[-1]["j"], tramos[-1]["motivo"]
        out.append({**x, "j": j, "f_salida": papel.f[j], "px_salida": px_prom, "motivo": motivo, "tramos_plan": tramos, "abierta_plan": abierta,
                    "stop": papel.c[x["i"]] * (1 - p["stop_inicial_pct"] / 100)})
    return out, desc


def _acciones_a_vender(tramo, N, vendidas):
    """Acciones del tramo: objetivos parciales = piso(acum × N) − ya vendidas; el tramo que cierra la posición vende todo lo que queda."""
    if tramo["acum"] >= 1.0 - 1e-9:
        return N - vendidas
    return max(0, math.floor(tramo["acum"] * N + 1e-9) - vendidas)


def simular_escalonada(todas, calendario, sizing="patrimonio", p=PARAMS_ESCALONADA):
    """Igual que bt.simular, pero cada posición se vende por tramos (cada uno devuelve efectivo y paga su costo). Devuelve el mismo
    (cerradas, abiertas, serie, descartes). Cada operación lleva: acciones (las compradas), costo_total (compra con costos), px_salida (precio medio de
    venta; en una abierta, el precio EQUIVALENTE que da su resultado total al valuar lo no vendido al último cierre), pnl, tramos y los costos pagados."""
    lado = bt.costo_lado(p)
    por_fecha = {}
    for s in todas:
        por_fecha.setdefault(s["fecha"], []).append(s)
    cash, abiertas, cerradas = float(p["capital"]), [], []
    serie, desc = [], {"sin_lugar": 0, "ya_en_cartera": 0, "sin_efectivo": 0}

    def vender(pos, tr, d):
        nonlocal cash
        n = _acciones_a_vender(tr, pos["acciones"], pos["vendidas"])
        if n <= 0:
            return
        bruto = n * tr["px"]
        cash += bruto * (1 - lado)
        pos["vendidas"] += n
        pos["ingreso_bruto"] += bruto
        pos["costo_ventas"] += bruto * lado
        pos["tramos"].append({"fecha": str(tr["fecha"]), "px": tr["px"], "acciones": n, "motivo": tr["motivo"], "pct_posicion": n / pos["acciones"] * 100})

    for d in calendario:
        for pos in list(abiertas):
            while pos["pendientes"] and pos["pendientes"][0]["fecha"] <= d:
                vender(pos, pos["pendientes"].pop(0), d)
            if pos["vendidas"] >= pos["acciones"] or (not pos["pendientes"] and not pos["abierta_plan"]):
                if pos["vendidas"] < pos["acciones"]:                        # no debería pasar: el último tramo vende todo
                    raise AssertionError("posición sin vender del todo")
                neto = pos["ingreso_bruto"] * (1 - lado)
                ganancia = neto - pos["costo_total"]
                if ganancia > 0 and p["imp_ganancias"]:
                    cash -= ganancia * p["imp_ganancias"]
                    ganancia *= 1 - p["imp_ganancias"]
                ult = pos["tramos_plan"][-1]
                cerradas.append({**pos, "px_salida": pos["ingreso_bruto"] / pos["acciones"], "pnl": ganancia, "pnl_pct": ganancia / pos["costo_total"] * 100,
                                 "j": ult["j"], "f_salida": ult["fecha"], "motivo": ult["motivo"]})
                abiertas.remove(pos)
        for s in sorted(por_fecha.get(d, []), key=lambda x: -x["monto5"]):
            if any(x["papel"] is s["papel"] for x in abiertas):
                desc["ya_en_cartera"] += 1
                continue
            if len(abiertas) >= p["max_posiciones"]:
                desc["sin_lugar"] += 1
                continue
            patrimonio = cash + sum((x["acciones"] - x["vendidas"]) * bt.precio_en(x["papel"], d) for x in abiertas)
            presupuesto = p["fraccion"] * cash if sizing == "efectivo" else min(p["fraccion"] * patrimonio, cash)
            acciones = math.floor(presupuesto / (s["precio"] * (1 + lado)))
            if acciones < 1:
                desc["sin_efectivo"] += 1
                continue
            costo = acciones * s["precio"] * (1 + lado)
            cash -= costo
            abiertas.append({**s, "acciones": acciones, "costo_total": costo, "costo_compra": acciones * s["precio"] * lado, "vendidas": 0,
                             "ingreso_bruto": 0.0, "costo_ventas": 0.0, "tramos": [], "pendientes": list(s["tramos_plan"]), "abierta_plan": s["abierta_plan"]})
        serie.append((d, cash + sum((x["acciones"] - x["vendidas"]) * bt.precio_en(x["papel"], d) for x in abiertas)))
    # lo que sigue abierto: px_salida = precio equivalente para que (acciones × px × (1 − lado) − costo_total) sea su resultado total hoy (lo vendido + lo que queda al último cierre)
    for pos in abiertas:
        resto = pos["acciones"] - pos["vendidas"]
        ultimo = bt.precio_en(pos["papel"], calendario[-1])
        pos["px_salida"] = (pos["ingreso_bruto"] + resto * ultimo) / pos["acciones"]
        pos["f_salida"], pos["j"], pos["motivo"] = calendario[-1], len(pos["papel"].c) - 1, "abierta"
    return cerradas, abiertas, serie, desc


# ---------------------------------------------------------------- costos pagados (para medir cuánto pesó la comisión)

def costos_pagados(t, lado):
    """(costo de compra, costo de ventas) que la operación pagó de verdad. Una operación de una sola venta (las demás estrategias) paga el costo de esa venta;
    las posiciones abiertas de esas estrategias solo pagaron la compra. Una escalonada paga cada tramo vendido."""
    compra = t["acciones"] * t["precio"] * lado
    if "costo_ventas" in t:
        return compra, t["costo_ventas"]
    return compra, 0.0 if t["motivo"] == "abierta" else t["acciones"] * t["px_salida"] * lado


def ordenes(t):
    """(órdenes de compra, órdenes de venta) de la operación."""
    if "tramos" in t:
        return 1, len(t["tramos"])
    return 1, 0 if t["motivo"] == "abierta" else 1


def resumen_costos(res, p):
    """Cuánto pesó la comisión en esta corrida: costos pagados (compras + ventas), cantidad de órdenes, costo por operación completa y el efecto sobre
    el retorno (comparando con la misma corrida sin comisiones ni derechos de mercado)."""
    lado = bt.costo_lado(p)
    ops = res["base"]["cerradas"] + res["base"]["abiertas"]
    compras = ventas = 0.0
    o_c = o_v = 0
    for t in ops:
        c, v = costos_pagados(t, lado)
        compras += c
        ventas += v
        oc, ov = ordenes(t)
        o_c += oc
        o_v += ov
    total = compras + ventas
    cerr = res["base"]["cerradas"]
    por_op = [sum(costos_pagados(t, lado)) / t["costo_total"] * 100 for t in cerr]
    m, m0 = res["base"]["metricas"], res["sin_costos"]
    return {"compras": compras, "ventas": ventas, "total": total, "pct_capital": total / p["capital"] * 100, "ordenes_compra": o_c, "ordenes_venta": o_v,
            "ordenes_por_operacion": (o_c + o_v) / len(ops) if ops else None, "costo_medio_por_operacion_pct": sum(por_op) / len(por_op) if por_op else None,
            "ganancia_neta": m["ganancia_total"], "ganancia_sin_costos": m0["ganancia_total"],
            "retorno_neto_pct": m["ganancia_total_pct"], "retorno_sin_costos_pct": m0["ganancia_total_pct"],
            "peso_en_retorno_pp": m0["ganancia_total_pct"] - m["ganancia_total_pct"],
            "pct_de_la_ganancia_bruta": total / (m["ganancia_total"] + total) * 100 if m["ganancia_total"] + total > 0 else None}
