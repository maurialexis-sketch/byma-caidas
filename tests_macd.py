"""Pruebas de la pestaña SAN MARINO (MACD a punto de cruzar): cálculo, condiciones, listado, parámetros, corrida y página:  python tests_macd.py"""
import ast, json, math, os, re, sys, tempfile, unittest
from datetime import datetime, timedelta
from unittest import mock

import backtest as bt
import generar_sanmarino as gs
import macd
import parametros_macd as pm
from tests_backtest import barras

AR = bt.AR
AQUI = os.path.dirname(os.path.abspath(__file__))
P = {"rapido": 12, "lento": 26, "senal": 9, "dias": 2, "dist_pct": 0.5, "bajo_cero": False, "piso_millones": 1000,
     "dist2_pct": 0.15, "ruedas_cruce": 3, "vortex_exigir": True, "vortex_periodo": 14}
ONDA = [100 + 10 * math.sin(k / 6.0) for k in range(300)]          # una onda: el MACD sube y baja alrededor de su señal
SUAVE = [100 + 2 * math.sin(k / 6.0) for k in range(300)]                                      # la misma onda con poca amplitud: el MACD cruza hacia arriba en t=72 con +0,04% y sigue separándose
A_PUNTO = ONDA[:71]                                                # termina con el MACD debajo de la señal, subiendo y a 0,44% de cruzarla


class Calculo(unittest.TestCase):
    def test_ema_a_mano(self):
        e = macd.ema([1, 2, 3, 4, 5], 3)
        self.assertEqual(e[:2], [None, None])                                          # hasta tener n valores no se rellena
        self.assertAlmostEqual(e[2], 2.0); self.assertAlmostEqual(e[3], 3.0); self.assertAlmostEqual(e[4], 4.0)

    def test_ema_con_menos_valores_que_el_periodo_queda_vacia(self):
        self.assertEqual(macd.ema([1.0] * 5, 9), [None] * 5)
        self.assertEqual(macd.ema([], 3), [])

    def test_macd_senal_e_histograma_a_mano(self):
        # cierres 10 11 13 12 14 15 13 con EMA 2, EMA 3 y señal 2 (calculado a mano, semilla = media simple)
        s = macd.serie([10, 11, 13, 12, 14, 15, 13], 2, 3, 2)
        esperado_macd = [None, None, 0.8333, 0.3889, 0.5185, 0.5340, 0.0252]
        esperado_sen = [None, None, None, 0.6111, 0.5494, 0.5391, 0.1965]
        esperado_hist = [None, None, None, -0.2222, -0.0309, -0.0051, -0.1713]
        for real, esp in ((s["macd"], esperado_macd), (s["senal"], esperado_sen), (s["hist"], esperado_hist)):
            self.assertEqual([x is None for x in real], [x is None for x in esp])
            for a, b in zip(real, esp):
                if b is not None:
                    self.assertAlmostEqual(a, b, places=3)

    def test_una_serie_constante_tiene_macd_cero(self):
        s = macd.serie([50.0] * 80, 12, 26, 9)
        self.assertAlmostEqual(s["macd"][-1], 0.0, places=9); self.assertAlmostEqual(s["hist"][-1], 0.0, places=9)

    def test_en_una_suba_pareja_el_macd_es_positivo(self):
        s = macd.serie([100 + k for k in range(120)], 12, 26, 9)
        self.assertGreater(s["macd"][-1], 0)

    def test_la_primera_rueda_con_macd_y_con_senal_son_las_esperadas(self):
        s = macd.serie(ONDA, 12, 26, 9)
        self.assertEqual(next(i for i, x in enumerate(s["macd"]) if x is not None), 25)      # lento − 1
        self.assertEqual(next(i for i, x in enumerate(s["senal"]) if x is not None), 33)     # lento + señal − 2


class Condiciones(unittest.TestCase):
    def test_el_caso_a_punto_de_cruzar_cumple_todo(self):
        e = macd.estado(A_PUNTO, P)
        self.assertTrue(e["debajo"] and e["subiendo"] and e["cerca"] and e["cumple"])
        self.assertLess(e["macd"], e["senal"]); self.assertLess(e["hist"], 0); self.assertAlmostEqual(abs(e["hist_pct"]), 0.4364, places=3)
        self.assertGreaterEqual(e["dias_subiendo"], 2)
        self.assertGreater(e["ruedas_al_cruce"], 0)

    def test_si_ya_cruzo_hacia_arriba_no_entra(self):
        s = macd.serie(ONDA, 12, 26, 9)
        t = next(i for i in range(60, 120) if s["hist"][i] >= 0 and s["hist"][i - 1] < 0)         # la rueda en que cruzó
        e = macd.estado(ONDA[:t + 1], P)
        self.assertFalse(e["debajo"]); self.assertFalse(e["cumple"]); self.assertIsNone(e["ruedas_al_cruce"])

    def test_si_se_aleja_en_vez_de_acercarse_no_entra(self):
        s = macd.serie(ONDA, 12, 26, 9)
        t = next(i for i in range(100, 200) if s["hist"][i] < 0 and s["hist"][i] < s["hist"][i - 1] and s["hist"][i - 1] < s["hist"][i - 2])   # la negra cae por debajo de la roja
        e = macd.estado(ONDA[:t + 1], dict(P, dist_pct=100))
        self.assertFalse(e["subiendo"]); self.assertFalse(e["cumple"])

    def test_si_esta_lejos_no_entra_pero_con_mas_tolerancia_si(self):
        e1 = macd.estado(A_PUNTO, dict(P, dist_pct=0.3)); e2 = macd.estado(A_PUNTO, dict(P, dist_pct=0.5))
        self.assertFalse(e1["cerca"]); self.assertFalse(e1["cumple"]); self.assertTrue(e2["cumple"])

    def test_mas_dias_subiendo_es_mas_exigente(self):
        e = macd.estado(A_PUNTO, P)
        self.assertTrue(macd.estado(A_PUNTO, dict(P, dias=e["dias_subiendo"]))["cumple"])
        self.assertFalse(macd.estado(A_PUNTO, dict(P, dias=e["dias_subiendo"] + 1))["cumple"])

    def test_exigir_bajo_cero(self):
        e = macd.estado(A_PUNTO, P)
        self.assertTrue(e["bajo_cero"] and macd.estado(A_PUNTO, dict(P, bajo_cero=True))["cumple"])
        suba = [100 + 1.5 * k + 10 * math.sin(k / 6.0) for k in range(300)]                          # con tendencia el MACD se queda sobre cero
        s = macd.serie(suba, 12, 26, 9)
        t = next(i for i in range(60, 300) if s["macd"][i] > 0 and s["hist"][i] < 0 and s["hist"][i] > s["hist"][i - 1] > s["hist"][i - 2]
                 and abs(s["hist"][i]) / suba[i] * 100 <= 0.5)                                       # a punto de cruzar pero con el MACD sobre cero
        arriba = macd.estado(suba[:t + 1], P)
        self.assertTrue(arriba["cumple"] and not arriba["bajo_cero"])
        self.assertFalse(macd.estado(suba[:t + 1], dict(P, bajo_cero=True))["cumple"])

    def test_una_linea_recta_no_cuenta_como_estar_debajo_de_la_senal(self):
        e = macd.estado([100.0 + k for k in range(80)], dict(P, dist_pct=100))                       # el histograma da ~1e-15 por redondeo: es cero, no «debajo»
        self.assertFalse(e["debajo"]); self.assertFalse(e["cumple"])
        self.assertFalse(macd.estado([50.0] * 80, P)["debajo"])

    def test_sin_ruedas_suficientes_no_se_aproxima(self):
        n = macd.ruedas_minimas(P)
        self.assertEqual(n, 26 + 9 - 1 + 2)
        self.assertIsNone(macd.estado(ONDA[:n - 1], P))
        self.assertIsNotNone(macd.estado(ONDA[:n], P))

    def test_en_toda_la_serie_cumple_implica_las_tres_condiciones(self):
        hubo = 0
        for dist in (0.5, 5.0):
            p = dict(P, dist_pct=dist)
            for t in range(macd.ruedas_minimas(p), len(ONDA)):
                e = macd.estado(ONDA[:t + 1], p)
                if e["hist"] >= 0:
                    self.assertFalse(e["cumple"], t)                                              # ya cruzó o toca justo: nunca entra
                if e["cumple"]:
                    hubo += 1
                    self.assertTrue(e["hist"] < 0 and e["dias_subiendo"] >= p["dias"] and abs(e["hist_pct"]) <= dist, t)
        self.assertGreater(hubo, 10)

    def test_ruedas_estimadas_al_cruce(self):
        e = macd.estado(A_PUNTO, P)
        s = macd.serie(A_PUNTO, 12, 26, 9)
        self.assertAlmostEqual(e["ruedas_al_cruce"], -s["hist"][-1] / (s["hist"][-1] - s["hist"][-2]), places=9)


def papel(ticker, cierres, tipo="cedear", v=5e7, fin=datetime(2026, 10, 13).date()):
    ini = fin - timedelta(days=len(cierres) - 1)
    return bt.Papel(ticker, tipo, barras(cierres, inicio=ini, v=v), fin + timedelta(days=1))


def barras_v(cierres, inicio, alcista=True, v=5e7):
    """Velas con los cierres dados pero máximos y mínimos que suben (o bajan) 1 por rueda con rango de 0,2: con eso el Vortex es alcista (o bajista) sin tocar el MACD."""
    b = barras(cierres, inicio=inicio, v=v)
    for k, x in enumerate(b):
        base = 100 + (k if alcista else -k)
        x["h"], x["l"] = base + 0.1, base - 0.1
    return b


def papel_v(ticker, cierres, tipo="cedear", v=5e7, fin=datetime(2026, 10, 13).date(), alcista=True):
    return bt.Papel(ticker, tipo, barras_v(cierres, fin - timedelta(days=len(cierres) - 1), alcista, v), fin + timedelta(days=1))


class Listado(unittest.TestCase):
    def listar(self, papeles, **kw):
        return macd.listado(papeles, dict(P, **kw), {"papeles": {}}, lambda t: t.rstrip("B") if t.startswith("AAPL") else t)

    def test_solo_cedears_y_una_empresa_una_vez_con_la_linea_mas_liquida(self):
        r = self.listar([papel("AAPL", A_PUNTO, v=1e7), papel("AAPLB", A_PUNTO, v=9e7), papel("GGAL", A_PUNTO, tipo="accion"), papel("NADA", [50.0] * 71)])
        self.assertEqual([f["ticker"] for f in r["lista"]], ["AAPLB"])
        self.assertEqual(r["lista"][0]["otras_lineas"], ["AAPL"])
        self.assertEqual(r["evaluados"], 3)                                                       # las 3 líneas de CEDEARs; la acción no se evalúa

    def test_sin_filtro_de_liquidez_pero_con_marca_operable_y_operables_primero(self):
        mio = [100 + 10 * math.sin(k / 6.0) for k in range(71)]
        r = self.listar([papel("POCO", mio, v=1e3), papel("MUCHO", [x * 1.0 for x in mio], v=9e7)])
        self.assertEqual([(f["ticker"], f["operable"]) for f in r["lista"]], [("MUCHO", True), ("POCO", False)])
        self.assertEqual(r["resumen"], {"total": 2, "operables": 1})

    def test_ordena_por_cercania_dentro_de_cada_grupo(self):
        c1, c2 = ONDA[:70], ONDA[:71]                                                              # la misma onda un día antes está más lejos del cruce
        r = self.listar([papel("LEJOS", c1), papel("CERCA", c2)], dist_pct=5.0)
        self.assertEqual([f["ticker"] for f in r["lista"]], ["CERCA", "LEJOS"])

    def test_un_papel_con_pocas_ruedas_se_cuenta_aparte_y_no_se_aproxima(self):
        r = self.listar([papel("NUEVO", ONDA[:20]), papel("AAPL", A_PUNTO)])
        self.assertEqual(r["embudo"]["sin_historia"], 1); self.assertEqual(r["evaluados"], 1)

    def test_el_embudo_es_acumulado(self):
        r = self.listar([papel("A", A_PUNTO), papel("B", [100 + k for k in range(80)])])
        e = r["embudo"]
        self.assertEqual((e["evaluados"], e["debajo"], e["subiendo"], e["cerca"], e["bajo_cero"]), (2, 1, 1, 1, 1))

    def test_sin_candidatos_la_lista_queda_vacia_sin_bajar_filtros(self):
        r = self.listar([papel("B", [100 + k for k in range(80)])])
        self.assertEqual((r["lista"], r["resumen"]["total"]), ([], 0))


class Vortex(unittest.TestCase):
    def test_a_mano(self):
        # n=2, 4 velas: VM+ = 4,4,1 · VM− = 1,1,3 · TR = 3,2,2 (calculado a mano) → en la última: VI+ = 5/4, VI− = 4/4
        v = macd.vortex([10, 12, 13, 12], [8, 9, 11, 10], [9, 11, 12, 11], 2)
        self.assertAlmostEqual(v["mas"], 1.25); self.assertAlmostEqual(v["menos"], 1.0)
        self.assertTrue(v["alcista"]); self.assertEqual(v["ruedas"], 2)                       # un día antes también era alcista (1,6 contra 0,4); dos antes no hay datos

    def test_una_baja_es_bajista(self):
        v = macd.vortex([12, 10, 9, 8], [10, 8, 7, 6], [11, 9, 8, 7], 2)
        self.assertGreater(v["menos"], v["mas"]); self.assertFalse(v["alcista"]); self.assertEqual(v["ruedas"], 0)

    def test_sin_velas_suficientes_o_sin_movimiento_no_se_aproxima(self):
        self.assertIsNone(macd.vortex([10, 12], [8, 9], [9, 11], 2))                         # hacen falta n+1 velas
        self.assertIsNone(macd.vortex([5.0] * 20, [5.0] * 20, [5.0] * 20, 14))               # rango verdadero 0: no hay nada que medir
        self.assertIsNone(macd.vortex([10, 12, 13], [8, 9], [9, 11, 12], 2))                 # series de largos distintos

    def test_con_una_suba_sostenida_confirma_y_el_periodo_sale_de_la_configuracion(self):
        p = papel("S", [100 + 0.5 * k + math.sin(k) for k in range(60)])
        v = macd.vortex(p.h, p.l, p.c, 14)
        self.assertTrue(v["alcista"]); self.assertGreater(v["ruedas"], 3)
        self.assertEqual(macd.de_params(pm.defectos())["vortex_periodo"], macd.cargar()["vortex_periodo"])


class CruceReciente(unittest.TestCase):
    def test_marca_el_cruce_y_las_ruedas_desde_que_ocurrio(self):
        s = macd.serie(SUAVE, 12, 26, 9)
        t0 = next(i for i in range(60, 120) if s["hist"][i] > 0 and s["hist"][i - 1] <= 0)       # la rueda en que cruzó hacia arriba
        for k in range(0, 4):
            e = macd.estado(SUAVE[:t0 + k + 1], P)
            self.assertTrue(e["arriba"]); self.assertEqual(e["ruedas_desde_cruce"], k); self.assertTrue(e["se_separa"])
        e = macd.estado(SUAVE[:t0], P)                                                           # un día antes todavía estaba debajo
        self.assertFalse(e["arriba"]); self.assertIsNone(e["ruedas_desde_cruce"])

    def test_si_siempre_estuvo_arriba_no_hay_cruce_a_la_vista(self):
        e = macd.estado([100 * 1.01 ** k for k in range(80)], P)
        self.assertTrue(e["arriba"]); self.assertIsNone(e["ruedas_desde_cruce"])

    def test_si_se_vuelve_a_cerrar_no_se_separa(self):
        s = macd.serie(SUAVE, 12, 26, 9)
        t = next(i for i in range(75, 120) if s["hist"][i] > 0 and s["hist"][i] < s["hist"][i - 1])
        self.assertFalse(macd.estado(SUAVE[:t + 1], P)["se_separa"])

    def test_la_linea_recta_no_cuenta_como_estar_arriba(self):
        self.assertFalse(macd.estado([100.0 + k for k in range(80)], P)["arriba"])


class Listado2(unittest.TestCase):
    T0 = 72                                                                                      # el MACD de SUAVE cruza hacia arriba en la rueda 72 (índice)

    def listar(self, papeles, **kw):
        return macd.listado2(papeles, dict(P, **kw), {"papeles": {}}, lambda t: t.rstrip("B") if t.startswith("AAPL") else t)

    def setUp(self):
        s = macd.serie(SUAVE, 12, 26, 9)
        self.t0 = next(i for i in range(60, 120) if s["hist"][i] > 0 and s["hist"][i - 1] <= 0)
        self.assertEqual(self.t0, self.T0)

    def pasa(self, k=1):
        """Una serie que cruzó hace k ruedas."""
        return SUAVE[:self.t0 + k + 1]

    def test_entra_si_cruzo_hace_poco_con_poca_separacion_y_el_vortex_confirma(self):
        r = self.listar([papel_v("A", self.pasa(1))])
        f = r["lista"][0]
        self.assertEqual((f["ticker"], f["ruedas_desde_cruce"]), ("A", 1)); self.assertTrue(f["vortex_alcista"]); self.assertGreater(f["hist_pct"], 0); self.assertLessEqual(f["hist_pct"], 0.15)
        self.assertEqual(r["embudo"], {"evaluados": 1, "arriba": 1, "reciente": 1, "se_separa": 1, "pegado": 1, "vortex": 1, "sin_historia": 0})

    def test_si_la_separacion_pasa_el_limite_no_entra_pero_con_mas_tolerancia_si(self):
        c = self.pasa(3)                                                                         # a 3 ruedas del cruce ya está a ~0,2%
        self.assertEqual(self.listar([papel_v("A", c)])["lista"], [])
        self.assertEqual(self.listar([papel_v("A", c)], dist2_pct=0.5)["resumen"]["total"], 1)

    def test_cruce_viejo_no_entra_y_el_limite_de_ruedas_es_inclusivo(self):
        c = self.pasa(2)
        self.assertEqual(self.listar([papel_v("A", c)], ruedas_cruce=1, dist2_pct=5)["lista"], [])
        self.assertEqual(self.listar([papel_v("A", c)], ruedas_cruce=2, dist2_pct=5)["resumen"]["total"], 1)
        self.assertEqual(self.listar([papel_v("A", self.pasa(0))], ruedas_cruce=0)["resumen"]["total"], 1)     # 0 = cruzó hoy

    def test_si_las_lineas_se_cierran_de_nuevo_no_entra(self):
        s = macd.serie(SUAVE, 12, 26, 9)
        t = next(i for i in range(75, 120) if s["hist"][i] > 0 and s["hist"][i] < s["hist"][i - 1])
        r = self.listar([papel_v("A", SUAVE[:t + 1])], ruedas_cruce=20, dist2_pct=5)
        self.assertEqual(r["lista"], []); self.assertEqual((r["embudo"]["reciente"], r["embudo"]["se_separa"]), (1, 0))

    def test_el_que_ya_estaba_arriba_sin_cruce_a_la_vista_o_sigue_debajo_no_entra(self):
        r = self.listar([papel_v("SIEMPRE", [100 * 1.01 ** k for k in range(80)]), papel_v("DEBAJO", SUAVE[:self.t0])], ruedas_cruce=20, dist2_pct=5)
        self.assertEqual(r["lista"], []); self.assertEqual((r["embudo"]["evaluados"], r["embudo"]["arriba"], r["embudo"]["reciente"]), (2, 1, 0))

    def test_el_vortex_es_condicion_y_se_puede_apagar(self):
        bajista = papel_v("A", self.pasa(1), alcista=False)                                      # el MACD cruzó pero el Vortex dice que no hay fuerza alcista
        r = self.listar([bajista])
        self.assertEqual(r["lista"], []); self.assertEqual((r["embudo"]["pegado"], r["embudo"]["vortex"]), (1, 0))
        r = self.listar([bajista], vortex_exigir=False)                                          # sin exigirlo entra, pero la fila dice que no confirma
        self.assertEqual(len(r["lista"]), 1); self.assertFalse(r["lista"][0]["vortex_alcista"]); self.assertLess(r["lista"][0]["vi_mas"], r["lista"][0]["vi_menos"])
        with mock.patch.object(macd, "vortex", return_value=None):                               # sin dato del Vortex tampoco se da por confirmado
            self.assertEqual(self.listar([papel_v("A", self.pasa(1))])["lista"], [])

    def test_solo_cedears_una_empresa_una_vez_y_operables_primero(self):
        r = self.listar([papel_v("AAPL", self.pasa(1), v=1e7), papel_v("AAPLB", self.pasa(1), v=9e7), papel_v("GGAL", self.pasa(1), tipo="accion"), papel_v("POCO", self.pasa(1), v=1e3)])
        self.assertEqual([(f["ticker"], f["operable"]) for f in r["lista"]], [("AAPLB", True), ("POCO", False)])
        self.assertEqual(r["lista"][0]["otras_lineas"], ["AAPL"]); self.assertEqual(r["evaluados"], 3)

    def test_orden_el_cruce_mas_reciente_primero(self):
        r = self.listar([papel_v("VIEJO", self.pasa(2)), papel_v("HOY", self.pasa(0))], ruedas_cruce=3, dist2_pct=5)
        self.assertEqual([f["ticker"] for f in r["lista"]], ["HOY", "VIEJO"])

    def test_pocas_ruedas_no_se_aproxima(self):
        r = self.listar([papel_v("NUEVO", SUAVE[:20]), papel_v("A", self.pasa(1))])
        self.assertEqual((r["embudo"]["sin_historia"], r["evaluados"]), (1, 1))

    def test_sin_candidatos_queda_vacia_sin_bajar_filtros(self):
        r = self.listar([papel_v("RECTA", [100.0 + k for k in range(80)])])
        self.assertEqual((r["lista"], r["resumen"]["total"]), ([], 0))

    def test_el_listado_1_trae_el_vortex_como_informacion_sin_filtrar(self):
        r = macd.listado([papel_v("AAPL", A_PUNTO)], P, {"papeles": {}}, None)
        f = r["lista"][0]
        self.assertIn("vi_mas", f); self.assertIn("vortex_alcista", f)
        no = {"mas": 0.8, "menos": 1.1, "alcista": False, "ruedas": 0}
        with mock.patch.object(macd, "vortex", return_value=no):
            self.assertEqual(len(macd.listado([papel_v("AAPL", A_PUNTO)], P, {"papeles": {}}, None)["lista"]), 1)        # el Vortex no saca a nadie del listado 1


class Parametros(unittest.TestCase):
    def test_los_valores_de_fabrica_son_los_de_la_foto(self):
        self.assertEqual(pm.defectos(), {"macd_rapido": 12, "macd_lento": 26, "macd_senal": 9, "macd_dias": 2, "macd_dist_pct": 0.5, "macd_bajo_cero": 0, "macd_piso_millones": 1000,
                                         "macd2_dist_pct": 0.15, "macd2_ruedas": 3, "vortex_exigir": 1})
        self.assertEqual(macd.de_params(pm.defectos()), P)

    def test_los_numeros_de_fabrica_no_estan_escritos_en_el_codigo(self):
        with open(os.path.join(AQUI, "macd.py"), encoding="utf-8") as f:
            codigo = f.read()
        self.assertNotRegex(re.sub(r'""".*?"""', "", codigo, flags=re.S), r"\b(12|26)\b")        # los períodos 12/26/9 viven en config_macd.json

    def test_validacion(self):
        self.assertEqual(pm.leer("macd_dist_pct", "0,8"), 0.8)
        self.assertEqual(pm.leer("macd_piso_millones", "2.000"), 2000)
        self.assertEqual(pm.leer("macd2_dist_pct", "0,15"), 0.15)
        self.assertEqual(pm.leer("macd2_ruedas", "0"), 0)
        for clave, malo in (("macd2_dist_pct", "0"), ("macd2_dist_pct", "6"), ("macd2_ruedas", "21"), ("macd2_ruedas", "1,5"), ("vortex_exigir", "2")):
            with self.assertRaises(pm.ErrorParametro, msg=clave):
                pm.leer(clave, malo)
        for clave, malo in (("macd_rapido", "1"), ("macd_lento", "abc"), ("macd_dias", "11"), ("macd_dist_pct", "0"), ("macd_dist_pct", "50"), ("macd_bajo_cero", "2"), ("macd_senal", "9,5")):
            with self.assertRaises(pm.ErrorParametro, msg=clave):
                pm.leer(clave, malo)
        with self.assertRaises(pm.ErrorParametro):
            pm.validar({**pm.defectos(), "macd_rapido": 30, "macd_lento": 26})                    # la rápida tiene que ser menor que la lenta
        with self.assertRaises(pm.ErrorParametro):
            pm.validar({"macd_rapido": 12})                                                       # faltan

    def test_guardar_cargar_y_combinar(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "p.json")
            self.assertEqual(pm.cargar(ruta), pm.defectos())                                      # sin archivo: los de fábrica
            v, cambios = pm.combinar(pm.cargar(ruta), {"macd_dist_pct": "0,8", "macd_dias": "", "macd_lento": None})
            self.assertEqual(v["macd_dist_pct"], 0.8); self.assertEqual(list(cambios), ["macd_dist_pct"])
            pm.guardar(v, ruta)
            self.assertEqual(pm.cargar(ruta), v)
            with open(ruta, "w", encoding="utf-8") as f:
                f.write('{"macd_dias": 99}')
            with self.assertRaises(pm.ErrorParametro):
                pm.cargar(ruta)                                                                   # un archivo inválido no se corrige en silencio


class RelojFalso:
    fuente = "reloj de prueba"
    def __init__(self, ahora): self._a = ahora
    def sincronizar(self): pass
    def epoch(self): return self._a.timestamp()
    def ahora(self): return self._a


class Corrida(unittest.TestCase):
    """main() de punta a punta con BYMA y el reloj reemplazados (sin red)."""
    MARTES = datetime(2026, 10, 13, 18, 0, tzinfo=AR)

    def setUp(self):
        ini = self.MARTES.date() - timedelta(days=len(A_PUNTO) - 1)
        self.barras = {"T": barras(A_PUNTO, inicio=ini, v=5e7)}                                   # la última vela es la del martes 13/10
        self.dir = tempfile.TemporaryDirectory(); self.addCleanup(self.dir.cleanup)
        self.pfile = os.path.join(self.dir.name, "parametros_macd.json")
        self.guardados = []
        env = mock.patch.dict(os.environ, {"CLAVE_ACCESO": "una-clave-de-prueba-bien-larga"}); env.start(); self.addCleanup(env.stop)

    def correr(self, args, ahora=None):
        ahora = ahora or self.MARTES
        def guardar(fn, r, key, carpeta=None, etiqueta=None):
            self.guardados.append((fn, r, etiqueta)); return "archivo.json"
        patches = [mock.patch.object(gs.reloj, "Reloj", lambda: RelojFalso(ahora)), mock.patch.object(gs.conector, "universo", lambda: {"T": "cedear"}),
                   mock.patch.object(gs.gb, "bajar_historico", lambda e, c=None: (self.barras, [])), mock.patch.object(gs.gi, "filas_panel", lambda: {}),
                   mock.patch.object(gs.indices, "bajar_todos", lambda b, h=None: {"merval": None, "sp500_usd": None, "sp500_ars": None}),
                   mock.patch.object(gs.generar, "guardar", guardar), mock.patch.object(gs.generar, "derivar", lambda c, m: "k"),
                   mock.patch.object(gs.generar, "cargar_meta", lambda: {}), mock.patch.object(gs, "anotar", lambda t, n="warning": None),
                   mock.patch.object(sys, "argv", ["generar_sanmarino.py", "--parametros", self.pfile] + args)]
        for p in patches: p.start()
        try:
            gs.main()
        finally:
            for p in patches: p.stop()

    def test_la_corrida_programada_publica_la_lista(self):
        self.correr(["--programado"])
        fn, r, etiqueta = self.guardados[0]
        self.assertEqual(fn, "sanmarino"); self.assertIsNone(etiqueta); self.assertFalse(r.get("salteado"))
        self.assertEqual(r["contexto"]["origen"], "programada")
        self.assertEqual([f["ticker"] for f in r["lista"]], ["T"]); self.assertTrue(r["lista"][0]["operable"])
        self.assertEqual({e["clave"]: e["valor"] for e in r["parametros"]["editables"]}, pm.defectos())
        self.assertEqual(r["fecha_datos"], "2026-10-13")

    def test_si_nada_cumple_lo_dice_y_no_baja_filtros(self):
        self.barras["T"] = barras([100 + k for k in range(80)], inicio=self.MARTES.date() - timedelta(days=79), v=5e7)
        self.correr([])
        r = self.guardados[0][1]
        self.assertEqual(r["lista"], []); self.assertEqual(r["mensaje"], "Hoy ningún CEDEAR está a punto de cruzar")

    def test_el_informe_trae_el_listado_2_con_su_embudo_y_el_vortex(self):
        self.barras["T"] = barras_v(SUAVE[:74], self.MARTES.date() - timedelta(days=73))                         # cruzó hacia arriba hace 1 rueda, con el Vortex alcista
        self.correr(["--programado"])
        r = self.guardados[0][1]
        self.assertEqual(r["lista"], []); self.assertEqual([f["ticker"] for f in r["lista2"]], ["T"])
        f = r["lista2"][0]
        self.assertEqual(f["ruedas_desde_cruce"], 1); self.assertTrue(f["vortex_alcista"]); self.assertGreater(f["vi_mas"], f["vi_menos"])
        self.assertEqual(r["embudo2"]["vortex"], 1); self.assertEqual(r["resumen2"]["total"], 1)
        self.assertEqual((r["criterios"]["dist2_pct"], r["criterios"]["ruedas_cruce"], r["criterios"]["vortex_exigir"], r["criterios"]["vortex_periodo"]), (0.15, 3, True, 14))
        self.assertTrue(any(e["clave"] == "vortex_exigir" for e in r["parametros"]["editables"]))

    def test_sin_nada_el_listado_2_lo_dice(self):
        self.correr([])                                                                                         # la serie A_PUNTO todavía no cruzó
        r = self.guardados[0][1]
        self.assertEqual(r["lista2"], []); self.assertIn("despegó", r["mensaje2"])

    def test_los_parametros_del_listado_2_se_piden_y_quedan_guardados(self):
        self.correr(["--dist2", "0,3", "--ruedas-cruce", "5", "--vortex", "0"])
        v = {e["clave"]: e["valor"] for e in self.guardados[0][1]["parametros"]["editables"]}
        self.assertEqual((v["macd2_dist_pct"], v["macd2_ruedas"], v["vortex_exigir"]), (0.3, 5, 0))
        self.assertEqual(json.load(open(self.pfile, encoding="utf-8"))["macd2_ruedas"], 5)

    def test_programada_un_dia_sin_rueda_se_saltea_sin_fallar(self):
        self.correr(["--programado"], ahora=datetime(2026, 10, 14, 18, 0, tzinfo=AR))
        fn, r, etiqueta = self.guardados[0]
        self.assertEqual((fn, etiqueta), ("sanmarino", "SALTEADO")); self.assertTrue(r["salteado"]); self.assertIn("no hay datos de la rueda", r["motivo"])
        self.assertFalse(os.path.exists(self.pfile))

    def test_programada_atrasada_de_madrugada_publica_la_rueda_anterior_y_lo_avisa(self):
        self.correr(["--programado"], ahora=datetime(2026, 10, 14, 0, 15, tzinfo=AR))
        fn, r, etiqueta = self.guardados[0]
        self.assertEqual(fn, "sanmarino"); self.assertIsNone(etiqueta); self.assertFalse(r.get("salteado")); self.assertEqual(r["fecha_datos"], "2026-10-13")
        self.assertTrue(any("llegó con atraso" in x for x in r["avisos"]))
        self.assertEqual([f["ticker"] for f in r["lista"]], ["T"])

    def test_programada_en_plena_rueda_se_saltea(self):
        self.correr(["--programado"], ahora=datetime(2026, 10, 14, 14, 0, tzinfo=AR))
        self.assertEqual(self.guardados[0][2], "SALTEADO")

    def test_los_parametros_pedidos_se_usan_y_quedan_guardados(self):
        self.correr(["--dist", "0,3", "--dias", "3"])
        r = self.guardados[0][1]
        self.assertEqual(r["lista"], [])                                                          # con 0,3% la del ejemplo (0,44%) ya no entra
        v = {e["clave"]: e["valor"] for e in r["parametros"]["editables"]}
        self.assertEqual((v["macd_dist_pct"], v["macd_dias"]), (0.3, 3)); self.assertEqual(len(r["parametros"]["cambios"]), 2)
        self.assertEqual(pm.cargar(self.pfile)["macd_dist_pct"], 0.3)
        self.correr(["--programado"])                                                             # la siguiente parte de lo guardado
        self.assertEqual({e["clave"]: e["valor"] for e in self.guardados[1][1]["parametros"]["editables"]}["macd_dist_pct"], 0.3)

    def test_un_parametro_invalido_frena_la_corrida_y_no_guarda_nada(self):
        for malo in (["--rapido", "40"], ["--dias", "0"], ["--dist", "abc"], ["--bajo-cero", "3"]):
            with self.assertRaises(SystemExit) as c:
                self.correr(malo)
            self.assertIn("Parámetros inválidos", str(c.exception))
        self.assertEqual(self.guardados, []); self.assertFalse(os.path.exists(self.pfile))

    def test_el_informe_no_trae_nada_que_no_sea_de_la_lista(self):
        self.correr([])
        s = json.dumps(self.guardados[0][1])
        self.assertNotIn("CLAVE", s); self.assertNotIn("una-clave-de-prueba", s)


class ContrasenaYPagina(unittest.TestCase):
    def test_la_contrasena_de_cifrado_no_se_pisa_en_generar_sanmarino(self):
        # el 14/11 un bucle con la variable `clave` pisó la contraseña de generar_informe.py: acá la contraseña se llama `contrasena`, se asigna una vez y `clave` nunca se asigna
        with open(os.path.join(AQUI, "generar_sanmarino.py"), encoding="utf-8") as f:
            arbol = ast.parse(f.read())
        asignadas = {}
        for n in ast.walk(arbol):
            blancos = []
            if isinstance(n, ast.Assign): blancos = n.targets
            elif isinstance(n, (ast.AugAssign, ast.AnnAssign, ast.For, ast.comprehension, ast.NamedExpr)): blancos = [n.target]
            for b in blancos:
                for x in ast.walk(b):
                    if isinstance(x, ast.Name):
                        asignadas.setdefault(x.id, []).append(getattr(n, "lineno", 0))
        self.assertEqual(len(asignadas.get("contrasena", [])), 1, asignadas.get("contrasena"))
        self.assertNotIn("clave", asignadas)

    def setUp(self):
        with open(os.path.join(AQUI, "docs", "index.html"), encoding="utf-8") as f:
            self.html = f.read()

    def pdef(self):
        i = self.html.index("var PDEF_SM=") + len("var PDEF_SM=")
        return json.loads(self.html[i:self.html.index("];", i) + 1])

    def test_los_editables_de_la_pagina_son_los_de_parametros_macd_py(self):
        self.assertEqual([(p["k"], p["def"], p["min"], p["max"], p["ent"]) for p in self.pdef()],
                         [(e["clave"], e["defecto"], e["minimo"], e["maximo"], e["entero"]) for e in pm.EDITABLES])

    def test_las_entradas_del_workflow_son_las_de_la_pagina(self):
        with open(os.path.join(AQUI, ".github", "workflows", "sanmarino.yml"), encoding="utf-8") as f:
            wf = f.read()
        entradas = re.findall(r"(?m)^      (\w+):\s*\n\s+description", wf)
        self.assertLessEqual(len(entradas), 10)                                                    # tope de GitHub para un workflow manual
        self.assertEqual(sorted(entradas), sorted(p["wf"] for p in self.pdef()))
        self.assertIn("cron: '20 21 * * 1-5'", wf)                                                 # 18:20 de Argentina, lunes a viernes
        self.assertIn("CLAVE_ACCESO", wf); self.assertIn("generar_sanmarino.py", wf); self.assertIn("publicar_cambios.sh", wf)

    def test_el_guardado_incluye_los_parametros_de_san_marino(self):
        with open(os.path.join(AQUI, "publicar_cambios.sh"), encoding="utf-8") as f:
            self.assertIn("parametros_macd.json", f.read())

    def test_la_pestana_existe(self):
        self.assertIn('data-fn="sanmarino"', self.html); self.assertIn("pintarSanMarino", self.html)

    def test_la_pagina_distingue_un_permiso_sin_actions_de_uno_que_no_ve_el_repositorio(self):
        self.assertIn("function diagnosticarPermiso", self.html)
        self.assertIn("diagnosticarPermiso(gh,tok,r.status)", self.html)
        self.assertIn("no tiene acceso a este repositorio", self.html)

    def test_al_guardar_el_permiso_se_prueba_la_escritura_y_no_solo_la_lectura(self):
        """Un token con Actions en «Read-only» lee el workflow pero no puede lanzarlo: se prueba lanzando con una rama inexistente (422 = puede; no crea ninguna corrida)."""
        self.assertIn("function probarEscritura", self.html)
        self.assertIn("rama-de-prueba-inexistente", self.html)
        self.assertIn("probarEscritura(gh,t)", self.html)                                           # al guardar
        self.assertIn("probarEscritura(gh,tok)", self.html)                                         # al diagnosticar un 403
        self.assertIn("MSG_SOLO_LEE", self.html); self.assertIn("«Comportamiento»", self.html)     # el nombre que GitHub muestra traducido
        self.assertIn('t.slice(-4)', self.html)                                                     # se ve con qué token se está trabajando

    def test_la_pagina_dibuja_el_listado_2_y_el_vortex(self):
        for nombre in ("listado2SM", "tarjetaSM2", "vortexSM"):
            self.assertIn("function " + nombre, self.html)
        self.assertIn("r.lista2", self.html)                                                       # los informes anteriores no traen el listado 2: la página no se rompe


if __name__ == "__main__":
    unittest.main()
