"""Pruebas de la ruptura con salida escalonada:  python tests_escalonada.py"""
import math
import unittest
from datetime import date, timedelta

import backtest as bt
import escalonada as es
import ruptura as rp
from tests_backtest import barras, serie_con_rango, N

LADO = bt.costo_lado()


def papel(camino, ticker="T"):
    """Papel que compra a 100 en la rueda 4 y luego sigue 'camino' (cierres)."""
    return bt.Papel(ticker, "cedear", barras([100.0] * 5 + list(camino)))


def salida(camino, p=es.PARAMS_ESCALONADA):
    return es.salida_escalonada(papel(camino), 4, p)


def motivos(tramos):
    return [t["motivo"] for t in tramos]


class Salida(unittest.TestCase):
    def test_sube_derecho_vende_40_40_20_en_los_escalones(self):
        tramos, abierta = salida([105, 111, 116, 121])
        self.assertFalse(abierta)
        self.assertEqual(motivos(tramos), ["+10%", "+15%", "+20%"])
        self.assertEqual([t["px"] for t in tramos], [111, 116, 121])
        self.assertEqual([t["frac"] for t in tramos], [0.4, 0.4, 0.2])
        self.assertAlmostEqual(sum(t["frac"] for t in tramos), 1.0)

    def test_un_escalon_es_con_cierre_igual_o_mayor(self):
        self.assertEqual(motivos(salida([110.0, 90.0])[0]), ["+10%", "trailing"])           # justo +10%: vende el primer tramo
        self.assertEqual(salida([109.99, 120.0])[0][0]["motivo"], "+10%")                   # y 109,99 no alcanza: el primer tramo sale cuando llega 120

    def test_stop_inicial_menos_8_desde_la_compra_vende_todo(self):
        tramos, abierta = salida([95, 92.0, 150])
        self.assertEqual((motivos(tramos), tramos[0]["px"], tramos[0]["frac"]), (["stop"], 92.0, 1.0))        # cierre <= 92: sale ahí
        self.assertFalse(abierta)
        self.assertEqual(salida([95, 92.01, 110])[0][0]["motivo"], "+10%")                  # 92,01 no dispara

    def test_antes_del_10_el_stop_es_fijo_y_no_sigue_al_maximo(self):
        tramos, abierta = salida([105, 109, 101, 95])                                       # subió a 109 y cayó a 95: desde el máximo es −13%, desde la compra solo −5%
        self.assertEqual(tramos, []); self.assertTrue(abierta)

    def test_despues_de_tocar_el_10_rige_el_trailing_del_8_desde_el_maximo(self):
        tramos, _ = salida([111, 114, 114.9, 105.7])                                        # máximo 114,9 → stop 105,708; 105,7 lo toca
        self.assertEqual(motivos(tramos), ["+10%", "trailing"])
        self.assertEqual((tramos[1]["px"], round(tramos[1]["frac"], 6)), (105.7, 0.6))      # vende el 60% que quedaba
        tramos, _ = salida([111, 114, 114.9, 105.8, 100])                                   # 105,8 no lo toca; 100 sí
        self.assertEqual(tramos[-1]["px"], 100)

    def test_el_trailing_reemplaza_al_stop_inicial_recien_al_cruzar_el_10(self):
        # tras tocar +10% el stop pasa a 0,92 × 111 = 102,12 (arriba del inicial de 92): un 101 ya vende, aunque no sea −8% de la compra
        tramos, _ = salida([111, 101])
        self.assertEqual(motivos(tramos), ["+10%", "trailing"]); self.assertEqual(tramos[-1]["px"], 101)

    def test_el_nivel_del_trailing_se_fija_con_el_maximo_del_dia_que_cruza_el_10(self):
        self.assertEqual(motivos(salida([111, 102.1])[0]), ["+10%", "trailing"])             # stop = 0,92 × 111 = 102,12: 102,1 lo toca
        self.assertEqual(motivos(salida([111, 102.2])[0]), ["+10%"])                        # 102,2 no

    def test_un_gap_vende_todos_los_escalones_cruzados_a_ese_cierre(self):
        tramos, abierta = salida([105, 125])
        self.assertEqual((motivos(tramos), [t["px"] for t in tramos], abierta), (["+10%", "+15%", "+20%"], [125, 125, 125], False))
        tramos, _ = salida([105, 116, 90])                                                  # cruza +10 y +15 el mismo día, y después el trailing vende el 20% que queda
        self.assertEqual(motivos(tramos), ["+10%", "+15%", "trailing"])
        self.assertAlmostEqual(tramos[-1]["frac"], 0.2)

    def test_sin_vender_todo_al_final_queda_abierta(self):
        tramos, abierta = salida([105, 108])
        self.assertEqual(tramos, []); self.assertTrue(abierta)
        tramos, abierta = salida([111, 116, 118])
        self.assertEqual(motivos(tramos), ["+10%", "+15%"]); self.assertTrue(abierta)

    def test_el_trailing_no_baja(self):
        tramos, _ = salida([111, 118, 110, 108])                                            # máximo 118 → stop 108,56: 110 no lo toca (aunque cayó desde 118), 108 sí
        self.assertEqual((motivos(tramos), tramos[-1]["px"]), (["+10%", "+15%", "trailing"], 108))


def fila_senal(p, i, papel_, monto=5e9, **extra):
    """Señal de entrada manual con su salida escalonada simulada."""
    tramos, abierta = es.salida_escalonada(papel_, i, p)
    n = len(papel_.c)
    vendido = sum(t["frac"] for t in tramos)
    j = n - 1 if abierta else tramos[-1]["j"]
    px = (sum(t["frac"] * t["px"] for t in tramos) + (1 - vendido) * papel_.c[n - 1] * abierta)
    return {"papel": papel_, "i": i, "fecha": papel_.f[i], "precio": papel_.c[i], "soporte": None, "resistencia": 100.0, "stop": 92.0, "monto5": monto,
            "caida_dias": None, "caida_pct": None, "j": j, "f_salida": papel_.f[j], "px_salida": px, "motivo": "abierta" if abierta else tramos[-1]["motivo"],
            "tramos_plan": tramos, "abierta_plan": abierta, **extra}


def cal(papel_):
    return sorted(set(papel_.f))


class Cartera(unittest.TestCase):
    P1 = dict(es.PARAMS_ESCALONADA, capital=10_000_000, max_posiciones=1, fraccion=1.0, sizing="patrimonio")

    def test_cada_venta_parcial_devuelve_efectivo_y_paga_su_costo(self):
        pa = papel([105, 111, 116, 121])
        sig = fila_senal(self.P1, 4, pa)
        cerradas, abiertas, serie, _ = es.simular_escalonada([sig], cal(pa), "patrimonio", self.P1)
        self.assertEqual((len(cerradas), len(abiertas)), (1, 0))
        t = cerradas[0]
        N_ = t["acciones"]
        self.assertEqual(N_, math.floor(10_000_000 / (100 * (1 + LADO))))
        v = [t_["acciones"] for t_ in t["tramos"]]
        self.assertEqual(v, [math.floor(0.4 * N_), math.floor(0.8 * N_) - math.floor(0.4 * N_), N_ - math.floor(0.8 * N_)])
        self.assertEqual(sum(v), N_)
        bruto = v[0] * 111 + v[1] * 116 + v[2] * 121
        esperado = bruto * (1 - LADO) - N_ * 100 * (1 + LADO)
        self.assertAlmostEqual(t["pnl"], esperado, places=4)
        self.assertAlmostEqual(t["costo_ventas"], bruto * LADO, places=4)                       # cada tramo paga 0,70% de SU monto
        self.assertAlmostEqual(t["costo_compra"], N_ * 100 * LADO, places=4)
        self.assertAlmostEqual(serie[-1][1], 10_000_000 + t["pnl"], places=3)                    # el patrimonio final = capital + resultado
        self.assertEqual(t["motivo"], "+20%")
        self.assertAlmostEqual(t["px_salida"], bruto / N_, places=6)

    def test_equivale_a_la_cartera_comun_cuando_hay_una_sola_salida(self):
        """Con una sola venta total (stop inicial) el resultado es el mismo que el del simulador de siempre."""
        pa = papel([95, 91, 100, 100])
        sig = fila_senal(self.P1, 4, pa)
        c1, a1, s1, _ = es.simular_escalonada([sig], cal(pa), "patrimonio", self.P1)
        sig2 = {k: v for k, v in sig.items() if k not in ("tramos_plan", "abierta_plan")}
        c2, a2, s2, _ = bt.simular([sig2], cal(pa), "patrimonio", self.P1)
        self.assertEqual([round(e, 4) for _, e in s1], [round(e, 4) for _, e in s2])
        self.assertAlmostEqual(c1[0]["pnl"], c2[0]["pnl"], places=4)

    def test_una_posicion_abierta_se_valua_con_lo_vendido_mas_lo_que_queda(self):
        pa = papel([111, 118])                                                                  # vende 40% a 111 y otro 40% a 118: queda abierto el 20% final
        sig = fila_senal(self.P1, 4, pa)
        cerradas, abiertas, serie, _ = es.simular_escalonada([sig], cal(pa), "patrimonio", self.P1)
        self.assertEqual((len(cerradas), len(abiertas)), (0, 1))
        t = abiertas[0]
        resto = t["acciones"] - t["vendidas"]
        self.assertAlmostEqual(resto, t["acciones"] - sum(x["acciones"] for x in t["tramos"]))
        self.assertGreater(resto, 0)
        total = t["ingreso_bruto"] * (1 - LADO) + resto * 118 * (1 - LADO) - t["costo_total"]
        self.assertAlmostEqual(t["acciones"] * t["px_salida"] * (1 - LADO) - t["costo_total"], total, places=3)     # lo que usa el resumen para las abiertas
        self.assertEqual(t["motivo"], "abierta")

    def test_vender_un_tramo_no_libera_el_lugar_de_la_cartera(self):
        p = dict(self.P1, max_posiciones=1)
        a, b = papel([105, 111, 116, 121], "A"), papel([100] * 10, "B")
        sa, sb = fila_senal(p, 4, a), fila_senal(p, 6, b)                                       # B quiere entrar el día en que A ya vendió el primer tramo
        cerradas, abiertas, _, desc = es.simular_escalonada([sa, sb], cal(a), "patrimonio", p)
        self.assertEqual((desc["sin_lugar"], len(cerradas), len(abiertas)), (1, 1, 0))

    def test_las_acciones_son_enteras_y_el_ultimo_tramo_vende_lo_que_queda(self):
        pa = papel([105, 111, 116, 121])
        p = dict(self.P1, capital=1000)                                                          # 9 acciones a ~100: 40% = 3,6 → 3; 80% = 7,2 → 7; resto 2
        sig = fila_senal(p, 4, pa)
        cerradas, _, _, _ = es.simular_escalonada([sig], cal(pa), "patrimonio", p)
        self.assertEqual([x["acciones"] for x in cerradas[0]["tramos"]], [3, 4, 2])


class Entrada(unittest.TestCase):
    def papel_con_ruptura(self):
        from tests_informe import dos_regimenes
        return dos_regimenes()

    def test_las_entradas_son_exactamente_las_de_la_ruptura(self):
        p = self.papel_con_ruptura()
        base, d1 = rp.senales_ruptura(p, p=rp.PARAMS_TRAILING_SOLO)
        nuevo, d2 = es.senales_escalonada(p)
        self.assertGreaterEqual(len(base), 1)
        self.assertEqual([(x["i"], x["precio"], x["resistencia"], x["monto5"]) for x in base], [(x["i"], x["precio"], x["resistencia"], x["monto5"]) for x in nuevo])
        self.assertEqual(d1, d2)

    def test_la_salida_de_las_demas_estrategias_no_cambio(self):
        p = self.papel_con_ruptura()
        a = rp.senales_ruptura(p, p=rp.PARAMS_TRAILING_SOLO)[0]
        es.senales_escalonada(p)
        b = rp.senales_ruptura(p, p=rp.PARAMS_TRAILING_SOLO)[0]
        self.assertEqual([(x["j"], x["px_salida"], x["motivo"]) for x in a], [(x["j"], x["px_salida"], x["motivo"]) for x in b])
        self.assertEqual(rp.PARAMS_TRAILING_SOLO["trailing_pct"], 15.0)                         # los parámetros de la estrategia anterior siguen intactos


class Costos(unittest.TestCase):
    def test_resumen_de_costos_de_una_escalonada_y_de_una_simple(self):
        pa = papel([105, 111, 116, 121])
        P1 = Cartera.P1
        sig = fila_senal(P1, 4, pa)
        c, a, s, _ = es.simular_escalonada([sig], cal(pa), "patrimonio", P1)
        c0, a0, s0, _ = es.simular_escalonada([sig], cal(pa), "patrimonio", dict(P1, comision_broker=0.0, derechos_mercado=0.0))
        res = {"base": {"cerradas": c, "abiertas": a, "metricas": bt.metricas(c, s, P1)}, "sin_costos": bt.metricas(c0, s0, dict(P1, comision_broker=0.0, derechos_mercado=0.0))}
        r = es.resumen_costos(res, P1)
        t = c[0]
        self.assertEqual((r["ordenes_compra"], r["ordenes_venta"]), (1, 3))
        self.assertAlmostEqual(r["total"], t["costo_compra"] + t["costo_ventas"], places=4)
        self.assertAlmostEqual(r["peso_en_retorno_pp"], r["retorno_sin_costos_pct"] - r["retorno_neto_pct"], places=9)
        self.assertGreater(r["peso_en_retorno_pp"], 0)
        self.assertAlmostEqual(r["costo_medio_por_operacion_pct"], (t["costo_compra"] + t["costo_ventas"]) / t["costo_total"] * 100, places=6)
        # el costo por peso vendido es el mismo con 1 o con 3 tramos: partir la venta NO sube el porcentaje (solo suma órdenes)
        self.assertAlmostEqual(t["costo_ventas"] / sum(x["acciones"] * x["px"] for x in t["tramos"]), LADO, places=9)

    def test_una_operacion_comun_abierta_solo_pago_la_compra(self):
        t = {"acciones": 100, "precio": 100.0, "px_salida": 110.0, "motivo": "abierta"}
        self.assertEqual(es.costos_pagados(t, LADO), (100 * 100.0 * LADO, 0.0))
        self.assertEqual(es.ordenes(t), (1, 0))
        t["motivo"] = "trailing"
        self.assertEqual(es.costos_pagados(t, LADO), (100 * 100.0 * LADO, 100 * 110.0 * LADO))
        self.assertEqual(es.ordenes(t), (1, 1))


if __name__ == "__main__":
    unittest.main()
