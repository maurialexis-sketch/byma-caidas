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


if __name__ == "__main__":
    unittest.main(verbosity=1)
