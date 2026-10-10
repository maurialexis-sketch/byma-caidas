"""Pruebas de la estrategia de ruptura (series sintéticas):  python tests_ruptura.py"""
import unittest

import backtest as bt
import ruptura as rp
from tests_backtest import N, barras, papel_a_mano, serie_con_rango

P = rp.PARAMS_RUPTURA
SUBE = [110.0, 118.0, 125.0, 128.0, 132.0]          # el cierre 132 (índice N+4) rompe la resistencia (~130,4)


def papel(cola, previo=None):
    cierres = (previo if previo is not None else serie_con_rango()) + cola
    return bt.Papel("R", "accion", barras(cierres))


class Entrada(unittest.TestCase):
    def test_detecta_la_ruptura_el_dia_que_cierra_arriba_del_techo(self):
        s, _ = rp.senales_ruptura(papel(SUBE + [133.0] * 3))
        e = [x for x in s if x["i"] == N + 4]
        self.assertTrue(e, "debería haber señal el día que cierra en 132")
        self.assertAlmostEqual(e[0]["precio"], 132.0)
        self.assertTrue(129.0 < e[0]["resistencia"] < 131.5)                 # la resistencia rota (~130,4)
        self.assertEqual(e[0]["stop"], e[0]["resistencia"])

    def test_el_dia_antes_de_romper_no_hay_senal(self):
        s, _ = rp.senales_ruptura(papel(SUBE + [133.0] * 3))
        self.assertFalse([x for x in s if x["i"] == N + 3])                  # cierra en 128: todavía debajo del techo

    def test_si_ya_estaba_arriba_no_es_una_ruptura_nueva(self):
        s, _ = rp.senales_ruptura(papel(SUBE + [134.0, 136.0, 138.0]))
        self.assertFalse([x for x in s if x["i"] in (N + 5, N + 6, N + 7)])   # ya cerraba por encima del techo

    def test_exige_cierre_al_alza_y_liquidez(self):
        self.assertEqual(rp.senales_ruptura(bt.Papel("L", "accion", barras(serie_con_rango() + SUBE, v=1e5)))[0], [])

    def test_exige_tendencia_alcista(self):
        # 32 ruedas a 300 dentro de las últimas 200: la media de 200 queda ~140, por encima del cierre de 132
        previo = [300.0] * 32 + serie_con_rango()[32:]
        s, d = rp.senales_ruptura(papel(SUBE + [133.0] * 3, previo))
        self.assertFalse([x for x in s if x["i"] == N + 4])
        self.assertGreaterEqual(d["bajo_media"], 1)                            # rompió el techo pero no entra
        # el mismo escenario sin ese tramo (media ~116) sí entra
        self.assertTrue([x for x in rp.senales_ruptura(papel(SUBE + [133.0] * 3))[0] if x["i"] == N + 4])

    def test_tendencia_usa_150_si_no_hay_200(self):
        # solo se ejercita la lógica compartida: con 200 ruedas exactas manda la media de 200
        self.assertEqual((P["ma_larga"], P["ma_corta"], P["filtro_tendencia"]), (200, 150, True))


class Salida(unittest.TestCase):
    def papel(self, cierres, minimos=None):
        n = len(cierres)
        return papel_a_mano([100.0] * n, [max(c, 100.0) + 1 for c in cierres], minimos or [min(c, 100.0) - 1 for c in cierres], cierres)

    def test_stop_por_cierre_bajo_la_resistencia_rota(self):
        p = self.papel([101.0, 102.0, 101.0, 99.0, 98.0] + [100.0] * 20)
        self.assertEqual(rp.salida_ruptura(p, 0, 100.0), (3, 99.0, "stop"))      # sale al CIERRE de 99, no en el nivel

    def test_una_mecha_bajo_el_nivel_no_dispara_el_stop(self):
        p = self.papel([101.0] * 25, minimos=[90.0] * 25)                        # mínimos muy por debajo, pero cierra arriba
        self.assertEqual(rp.salida_ruptura(p, 0, 100.0)[2], "tiempo")

    def test_igual_al_nivel_no_es_cerrar_por_debajo(self):
        p = self.papel([101.0, 100.0] + [101.0] * 23)
        self.assertEqual(rp.salida_ruptura(p, 0, 100.0)[2], "tiempo")

    def test_tiempo_a_las_20_ruedas(self):
        p = self.papel([101.0] * 5 + [105.0] * 20)
        self.assertEqual(rp.salida_ruptura(p, 0, 100.0), (20, 105.0, "tiempo"))

    def test_abierta_si_faltan_datos(self):
        self.assertEqual(rp.salida_ruptura(self.papel([101.0] * 6), 0, 100.0)[2], "abierta")

    def test_si_el_dia_20_tambien_cierra_bajo_el_nivel_el_motivo_es_stop(self):
        p = self.papel([101.0] * 20 + [99.0] + [101.0] * 3)                      # índice 20 = última rueda y cierra en 99
        self.assertEqual(rp.salida_ruptura(p, 0, 100.0), (20, 99.0, "stop"))     # mismo precio que por tiempo; gana el stop
        p2 = self.papel([101.0] * 19 + [99.0] + [101.0] * 4)
        self.assertEqual(rp.salida_ruptura(p2, 0, 100.0), (19, 99.0, "stop"))


class Cartera(unittest.TestCase):
    def test_corre_en_el_mismo_simulador_con_la_misma_gestion_y_costos(self):
        pa = papel(SUBE + [133.0] * 30)
        res = bt.correr([pa], None, P, generar=rp.senales_ruptura)
        self.assertIsNotNone(res)
        cerr = res["base"]["cerradas"]
        e = [t for t in cerr if t["i"] == N + 4]
        self.assertTrue(e)
        self.assertEqual(e[0]["motivo"], "tiempo")
        self.assertEqual(e[0]["j"] - e[0]["i"], 20)
        lado = bt.costo_lado(P)
        a = e[0]["acciones"]
        self.assertEqual(a, int(0.5 * P["capital"] / (132.0 * (1 + lado))))      # mitad del efectivo libre
        self.assertAlmostEqual(e[0]["pnl"], a * 133.0 * (1 - lado) - a * 132.0 * (1 + lado), places=4)

    def test_la_estrategia_de_caidas_no_cambia(self):
        # las señales de caídas siguen saliendo del mismo generador por defecto
        cola = [106.5, 103.0, 100.5, 99.8, 101.5] + [104, 108, 112, 118, 125, 131]
        pa = bt.Papel("T", "accion", barras(serie_con_rango() + cola))
        a = bt.correr([pa])
        b = bt.correr([pa], generar=bt.señales)
        self.assertEqual(a["base"]["metricas"], b["base"]["metricas"])

    def test_estadistica_de_senales_una_por_una(self):
        pa = papel(SUBE + [133.0] * 30)
        est = bt.estadistica_senales([pa], rp.senales_ruptura, P)
        n = len(rp.senales_ruptura(pa)[0])
        self.assertEqual(est["n"], n)
        self.assertGreaterEqual(n, 1)
        lado = bt.costo_lado(P)
        primera = rp.senales_ruptura(pa)[0][0]
        esperado = ((primera["px_salida"] * (1 - lado)) / (primera["precio"] * (1 + lado)) - 1) * 100
        if n == 1:
            self.assertAlmostEqual(est["media_pct"], esperado, places=6)
        self.assertEqual(bt.estadistica_senales([], rp.senales_ruptura, P), {"n": 0})

    def test_no_mira_el_futuro(self):
        completo, _ = rp.senales_ruptura(papel(SUBE + [133.0] * 4))
        clave = lambda s, tope: [(x["fecha"], round(x["precio"], 6), round(x["resistencia"], 6)) for x in s if x["i"] <= tope]
        parcial, _ = rp.senales_ruptura(papel(SUBE))
        alterado, _ = rp.senales_ruptura(papel(SUBE + [200.0, 61.0, 190.0, 58.0]))
        self.assertEqual(clave(completo, N + 4), clave(parcial, N + 4))
        self.assertEqual(clave(completo, N + 4), clave(alterado, N + 4))
        self.assertTrue(clave(completo, N + 4))


class Trailing(unittest.TestCase):
    """Cambio único: la salida por tiempo de 20 ruedas pasa a ser un trailing stop del 15%, sin límite de días."""
    A = rp.PARAMS_TRAILING            # trailing + stop de ruptura
    B = rp.PARAMS_TRAILING_SOLO       # solo trailing

    def papel(self, cierres):
        return papel_a_mano([100.0] * len(cierres), [c + 1 for c in cierres], [c - 1 for c in cierres], [float(c) for c in cierres])

    def test_parametros(self):
        self.assertEqual((self.A["salida"], self.A["trailing_pct"], self.A["stop_ruptura"]), ("trailing", 15.0, True))
        self.assertEqual((self.B["salida"], self.B["trailing_pct"], self.B["stop_ruptura"]), ("trailing", 15.0, False))
        self.assertEqual(rp.PARAMS_RUPTURA["salida"], "tiempo")                   # la base no cambia

    def test_el_stop_inicial_esta_15_por_ciento_bajo_la_entrada(self):
        # entrada a 100 -> stop 85. El cierre de 85,5 no lo toca; 84,9 sí y se vende a ese cierre
        p = self.papel([100, 90, 85.5, 84.9, 120])
        self.assertEqual(rp.salida_trailing(p, 0, 50.0, self.B), (3, 84.9, "trailing"))

    def test_tocar_el_stop_es_menor_o_igual(self):
        self.assertEqual(rp.salida_trailing(self.papel([100, 90, 85.0, 120]), 0, 50.0, self.B), (2, 85.0, "trailing"))

    def test_el_stop_sube_con_el_maximo_cierre(self):
        # máximo cierre 120 -> stop 102. Cierra 101 -> se vende
        self.assertEqual(rp.salida_trailing(self.papel([100, 110, 120, 103, 101, 130]), 0, 50.0, self.B), (4, 101.0, "trailing"))

    def test_el_stop_nunca_baja(self):
        # tras el máximo de 120 (stop 102) el precio retrocede a 110 y rebota a 112: el stop sigue en 102 (no se recalcula a 0,85*112)
        # 102,5 no lo toca; 101,9 sí
        p = self.papel([100, 120, 110, 112, 108, 102.5, 101.9, 150])
        self.assertEqual(rp.salida_trailing(p, 0, 50.0, self.B), (6, 101.9, "trailing"))

    def test_incluye_el_cierre_de_entrada_como_maximo(self):
        # entrada a 100 con cierre posterior de 99: el máximo sigue siendo 100 -> stop 85, no 84,15
        self.assertEqual(rp.salida_trailing(self.papel([100, 99, 98, 84.9]), 0, 50.0, self.B)[0], 3)

    def test_sin_limite_de_ruedas(self):
        p = self.papel([100 + k * 0.5 for k in range(80)])                          # sube lento durante 80 ruedas: nunca toca el stop
        j, px, motivo = rp.salida_trailing(p, 0, 50.0, self.B)
        self.assertEqual(motivo, "abierta")
        self.assertEqual(j, 79)                                                      # no hay salida por tiempo a las 20 ruedas

    def test_con_stop_de_ruptura_sale_al_cerrar_bajo_la_resistencia(self):
        # entrada 105, resistencia rota 100: cierra 99,5 -> sale (el trailing, en 89,25, ni se toca)
        p = self.papel([105, 104, 99.5, 101, 90])
        self.assertEqual(rp.salida_trailing(p, 0, 100.0, self.A), (2, 99.5, "stop"))

    def test_solo_trailing_ignora_el_stop_de_ruptura(self):
        p = self.papel([105, 104, 99.5, 101, 90])
        self.assertEqual(rp.salida_trailing(p, 0, 100.0, self.B), (4, 90.0, "abierta"))   # 90 > 89,25: sigue abierta
        p2 = self.papel([105, 104, 99.5, 101, 89.0])
        self.assertEqual(rp.salida_trailing(p2, 0, 100.0, self.B), (4, 89.0, "trailing"))

    def test_el_stop_de_ruptura_exige_cerrar_por_debajo_igual_no_vale(self):
        self.assertEqual(rp.salida_trailing(self.papel([105, 100.0, 120]), 0, 100.0, self.A)[2], "abierta")

    def test_las_entradas_son_exactamente_las_mismas_solo_cambia_la_salida(self):
        pa = papel(SUBE + [133.0] * 30)
        clave = lambda s: [(x["fecha"], x["precio"], x["resistencia"], x["monto5"]) for x in s]
        base, _ = rp.senales_ruptura(pa, p=rp.PARAMS_RUPTURA)
        for p in (self.A, self.B):
            otra, _ = rp.senales_ruptura(pa, p=p)
            self.assertEqual(clave(base), clave(otra))
        self.assertEqual([x["motivo"] for x in rp.senales_ruptura(pa, p=rp.PARAMS_RUPTURA)[0] if x["i"] == N + 4], ["tiempo"])
        self.assertEqual([x["motivo"] for x in rp.senales_ruptura(pa, p=self.B)[0] if x["i"] == N + 4], ["abierta"])   # sigue abierta

    def test_sensibilidad_de_inicio_coincide_con_la_corrida_completa_en_semana_0(self):
        pa = papel(SUBE + [133.0] * 30)
        for p in (rp.PARAMS_RUPTURA, self.B):
            res = bt.correr([pa], None, p, generar=rp.senales_ruptura)
            filas = bt.sensibilidad_inicio([pa], p, rp.senales_ruptura, None, semanas=(0, 1))
            self.assertAlmostEqual(filas[0]["retorno_pct"], res["base"]["metricas"]["ganancia_total_pct"], places=9)
            self.assertEqual(filas[0]["trades"], len(res["base"]["cerradas"]))
            self.assertLess(filas[0]["inicio"], filas[1]["inicio"])                 # semana 1 empieza después

    def test_la_salida_no_usa_datos_posteriores(self):
        completo = self.papel([100, 110, 120, 103, 101, 130, 140])
        recortado = self.papel([100, 110, 120, 103, 101])
        self.assertEqual(rp.salida_trailing(completo, 0, 50.0, self.B), rp.salida_trailing(recortado, 0, 50.0, self.B))

    def test_corre_en_el_simulador_de_cartera_con_posiciones_abiertas(self):
        pa = papel(SUBE + [133.0] * 30)
        res = bt.correr([pa], None, self.B, generar=rp.senales_ruptura)
        self.assertEqual(len(res["base"]["cerradas"]), 0)
        self.assertEqual(len(res["base"]["abiertas"]), 1)                            # sin límite de días: queda abierta al final
        self.assertEqual(res["base"]["abiertas"][0]["motivo"], "abierta")


class CincoPosiciones(unittest.TestCase):
    """Cambio único: la cartera pasa de 2 a 5 posiciones simultáneas, cada una con el 20% del capital."""
    P2, P5 = rp.PARAMS_TRAILING_SOLO, rp.PARAMS_TRAILING_5POS

    def test_solo_cambian_la_cantidad_de_posiciones_y_su_tamano(self):
        distintos = {k for k in set(self.P2) | set(self.P5) if self.P2.get(k) != self.P5.get(k)}
        self.assertEqual(distintos, {"max_posiciones", "fraccion", "sizing"})
        self.assertEqual((self.P5["max_posiciones"], self.P5["fraccion"], self.P5["sizing"]), (5, 0.20, "patrimonio"))
        self.assertEqual((self.P2["max_posiciones"], self.P2["fraccion"], self.P2["sizing"]), (2, 0.5, "efectivo"))
        for k in ("salida", "trailing_pct", "stop_ruptura", "comision_broker", "derechos_mercado", "iva", "piso_monto", "capital"):
            self.assertEqual(self.P2[k], self.P5[k])                                   # entrada, trailing y costos idénticos

    def test_las_entradas_y_las_salidas_son_las_mismas(self):
        pa = papel(SUBE + [133.0] * 30)
        clave = lambda s: [(x["fecha"], x["precio"], x["resistencia"], x["j"], x["px_salida"], x["motivo"]) for x in s]
        self.assertEqual(clave(rp.senales_ruptura(pa, p=self.P2)[0]), clave(rp.senales_ruptura(pa, p=self.P5)[0]))

    def entrar_seis(self):
        papeles = [papel(SUBE + [133.0] * 30) for _ in range(6)]                       # 6 rupturas el mismo día
        return bt.correr(papeles, None, self.P5, generar=rp.senales_ruptura)

    def test_entran_cinco_y_la_sexta_queda_sin_lugar(self):
        res = self.entrar_seis()
        self.assertEqual(len(res["base"]["abiertas"]) + len(res["base"]["cerradas"]), 5)
        self.assertEqual(res["base"]["desc"]["sin_lugar"], 1)

    def test_cada_posicion_es_el_20_por_ciento_del_patrimonio(self):
        res = self.entrar_seis()
        lado = bt.costo_lado(self.P5)
        pos = sorted(res["base"]["abiertas"] + res["base"]["cerradas"], key=lambda t: -t["acciones"])
        for t in pos:
            invertido = t["acciones"] * 132.0 * (1 + lado)
            self.assertAlmostEqual(invertido / self.P5["capital"], 0.20, delta=0.01)    # ~20% (la 5ª queda un poco menor por los costos)
        self.assertLessEqual(sum(t["costo_total"] for t in pos), self.P5["capital"])    # nunca se invierte más que el capital

    def test_el_tamano_no_depende_de_quedar_efectivo_(self):
        # con 'efectivo' (el criterio anterior) la 5ª posición sería 20% del efectivo restante: bastante menor
        p = dict(self.P5, sizing="efectivo")
        papeles = [papel(SUBE + [133.0] * 30) for _ in range(5)]
        res = bt.correr(papeles, None, p, generar=rp.senales_ruptura)
        acc = sorted((t["acciones"] for t in res["base"]["abiertas"]), reverse=True)
        self.assertGreater(acc[0] / acc[-1], 1.5)                                       # 20%, 16%, 12,8%, ... del efectivo
        base5 = bt.correr(papeles, None, self.P5, generar=rp.senales_ruptura)
        acc5 = sorted((t["acciones"] for t in base5["base"]["abiertas"]), reverse=True)
        self.assertLess(acc5[0] / acc5[-1], 1.05)                                       # con patrimonio quedan casi iguales

    def test_la_corrida_principal_usa_el_tamano_del_parametro_y_la_variante_el_otro(self):
        res = self.entrar_seis()
        a = sorted(t["acciones"] for t in res["base"]["abiertas"])
        b = sorted(t["acciones"] for t in res["variante"]["abiertas"])
        self.assertNotEqual(a, b)                                                       # patrimonio vs efectivo
        r2 = bt.correr([papel(SUBE + [133.0] * 30)], None, rp.PARAMS_RUPTURA, generar=rp.senales_ruptura)
        self.assertEqual(r2["base"]["abiertas"][0]["acciones"] if r2["base"]["abiertas"] else r2["base"]["cerradas"][0]["acciones"],
                         int(0.5 * rp.PARAMS_RUPTURA["capital"] / (132.0 * (1 + bt.costo_lado(rp.PARAMS_RUPTURA)))))   # sigue siendo 50% del efectivo

    def test_por_defecto_nada_cambia(self):
        self.assertEqual((bt.PARAMS["max_posiciones"], bt.PARAMS["fraccion"], bt.PARAMS["sizing"]), (2, 0.5, "efectivo"))
        self.assertEqual((rp.PARAMS_RUPTURA["max_posiciones"], rp.PARAMS_TRAILING_SOLO["max_posiciones"]), (2, 2))


if __name__ == "__main__":
    unittest.main(verbosity=1)
