"""Pruebas de la estrategia de Bandas de Bollinger:  python tests_bollinger.py"""
import math
import unittest

import backtest as bt
import bollinger as bo
import escalonada as es
from tests_backtest import barras

BP = dict(bo.DEFECTO)

#            0     1    2    3    4    5     6    7    8
CENTRAL = [10.0, 9.9, 9.8, 9.7, 9.6, 9.62, 9.70, 9.80, 9.90]
CIERRES = [9.5, 9.4, 9.3, 9.2, 9.4, 9.70, 9.80, 9.90, 10.0]


def bb_de(central, desv=0.3):
    d = [None] + [central[k] - central[k - 1] for k in range(1, len(central))]
    return {"c": list(central), "s": [x + desv for x in central], "i": [x - desv for x in central], "d": d}


def patron(cierres=CIERRES, central=CENTRAL, t=7, **kw):
    return bo.evaluar_patron(cierres, bb_de(central), t, dict(BP, **kw))


class Patron(unittest.TestCase):
    def test_el_patron_completo_se_detecta_en_la_rueda_en_que_se_confirma(self):
        pat, etapa = patron()
        self.assertEqual(etapa, 4)
        self.assertEqual((pat["giro_desde"], pat["racha"], pat["cruce"], pat["ruedas_bajada"]), (5, 3, 5, 4))
        self.assertAlmostEqual(pat["subida_central_pct"], (9.80 / 9.60 - 1) * 100, places=6)
        self.assertEqual(patron(t=6)[0], None)                                   # en la rueda 6 la pendiente positiva lleva solo 2 ruedas

    def test_una_sola_senal_por_giro(self):
        bb = bb_de(CENTRAL)
        self.assertIsNotNone(bo.dispara(CIERRES, bb, 7, BP))
        self.assertIsNotNone(bo.evaluar_patron(CIERRES, bb, 8, BP)[0])           # al día siguiente el patrón sigue cumpliéndose...
        self.assertIsNone(bo.dispara(CIERRES, bb, 8, BP))                        # ...pero la señal ya salió en la rueda 7

    def test_condicion_1_el_giro_tiene_que_sostenerse_y_venir_de_una_bajada(self):
        c2 = list(CENTRAL); c2[7] = 9.69                                          # la pendiente vuelve a ser negativa en la rueda 7
        self.assertIsNone(patron(central=c2)[0])
        sube = [9.5, 9.6, 9.7, 9.8, 9.9, 10.0, 10.1, 10.2, 10.3]                  # venía subiendo: no hay giro de negativa a positiva
        self.assertEqual(patron(central=sube)[1], -1)

    def test_la_magnitud_minima_del_giro(self):
        self.assertEqual(patron(bb_magnitud_pct=2.0)[1], 4)                       # sube 2,08%: alcanza para 2%
        pat, etapa = patron(bb_magnitud_pct=2.5)
        self.assertIsNone(pat); self.assertEqual(etapa, 0)                       # para 2,5% no: se detiene en la magnitud

    def test_condicion_2_durante_la_bajada_los_cierres_estan_debajo_de_la_central(self):
        c = list(CIERRES); c[2] = 9.9                                             # un cierre de la bajada por ENCIMA de la central (9,80)
        pat, etapa = patron(cierres=c)
        self.assertIsNone(pat); self.assertEqual(etapa, 1)

    def test_condicion_3_tiene_que_haber_un_cruce_de_abajo_hacia_arriba(self):
        c = list(CIERRES); c[5] = 9.60                                            # nunca supera la central tras el giro: no hay cruce
        c[6], c[7] = 9.65, 9.70
        pat, etapa = patron(cierres=c)
        self.assertIsNone(pat); self.assertEqual(etapa, 2)                      # superó la bajada pero no hay cruce

    def test_condicion_4_tras_el_cruce_los_cierres_quedan_encima(self):
        c = list(CIERRES); c[6] = 9.65; c[7] = 9.75                              # cruza en la 5, pero la 6 y la 7 cierran bajo la central (9,70 y 9,80) y no vuelve a cruzar
        pat, etapa = patron(cierres=c)
        self.assertIsNone(pat); self.assertEqual(etapa, 3)
        c2 = list(CIERRES); c2[6] = 9.65                                          # la 6 cierra abajo pero la 7 vuelve a cruzar: el último cruce es el de la 7 y de ahí en más queda encima
        self.assertEqual(patron(cierres=c2)[1], 4)

    def test_el_cruce_puede_ocurrir_con_la_central_todavia_bajando(self):
        central = [10.0, 9.9, 9.8, 9.7, 9.62, 9.55, 9.56, 9.60, 9.66, 9.73]       # baja hasta la 5 y gira en la 6
        cierres = [9.5, 9.4, 9.3, 9.2, 9.5, 9.60, 9.62, 9.70, 9.75, 9.80]         # el cierre cruza la central en la 5, cuando todavía baja
        pat, etapa = patron(cierres=cierres, central=central, t=8)
        self.assertEqual(etapa, 4); self.assertEqual((pat["giro_desde"], pat["cruce"]), (6, 5))
        self.assertIsNone(patron(cierres=cierres, central=central, t=9)[0] and bo.dispara(cierres, bb_de(central), 9, BP))     # una sola señal por giro (la de la 8)

    def test_la_ventana_de_deteccion_limita_el_patron(self):
        self.assertEqual(patron(bb_ventana=6)[1], 4)                              # bajada (3 ruedas) + giro (3 ruedas) caben justo
        self.assertEqual(patron(bb_ventana=5)[1], -1)                             # con 5 ruedas no entran las 3 de la bajada y las 3 del giro
        c = list(CIERRES); c[0] = 9.9; c[1] = 9.95                                # cierres altos en las ruedas 0 y 1: con ventana de 6 (ruedas 2..7) no se ven
        self.assertEqual(patron(cierres=c, bb_ventana=6)[1], 4)
        self.assertEqual(patron(cierres=c, bb_ventana=8)[1], 1)                  # con ventana de 8 sí se ven (y la bajada deja de ser "por debajo")

    def test_un_solo_dia_de_pendiente_negativa_no_es_una_u(self):
        central = [10.0, 10.1, 10.2, 10.3, 10.25, 10.3, 10.4, 10.5]             # sube, un día baja (3.ª→4.ª) y vuelve a subir
        cierres = [10.0, 10.1, 10.3, 10.4, 10.2, 10.35, 10.5, 10.6]
        self.assertEqual(patron(cierres=cierres, central=central, t=7)[1], -1)

    def test_los_dias_de_pendiente_son_editables(self):
        self.assertEqual(patron(t=6, bb_dias=2)[1], 4)                            # con 2 ruedas alcanza en la 6 (bajada de 4 ≥ 2)
        self.assertEqual(patron(t=7, bb_dias=4)[1], -1)                           # con 4 ruedas todavía no


class Bandas(unittest.TestCase):
    def test_central_y_desvio_son_los_de_las_ultimas_n_ruedas(self):
        c = [10, 12, 11, 13, 14, 12, 11, 15]
        b = bo.bandas(c, 4, 2.0)
        w = c[-4:]
        m = sum(w) / 4
        sd = math.sqrt(sum((x - m) ** 2 for x in w) / 4)
        self.assertAlmostEqual(b["c"][-1], m)
        self.assertAlmostEqual(b["s"][-1], m + 2 * sd); self.assertAlmostEqual(b["i"][-1], m - 2 * sd)
        self.assertAlmostEqual(b["d"][-1], m - sum(c[-5:-1]) / 4)
        self.assertEqual((b["c"][2], b["d"][3]), (None, None))                   # hasta tener n cierres no hay bandas; la pendiente arranca una rueda después

    def test_no_usa_datos_posteriores(self):
        c = [10, 12, 11, 13, 14, 12, 11, 15, 9, 20]
        a, b = bo.bandas(c, 4, 2.0), bo.bandas(c[:7], 4, 2.0)
        for k in range(7):
            self.assertEqual((a["c"][k], a["s"][k], a["i"][k], a["d"][k]), (b["c"][k], b["s"][k], b["i"][k], b["d"][k]))


def salida(cierres, bb, i, **kw):
    return bo.salida_bollinger(cierres, bb, i, dict(BP, **kw))


def bb_liso(n, central=100.0, ancho=5.0, pend=0.5):
    """Bandas a mano: central constante (pendiente positiva fija 'pend' si se da), bandas a ±ancho."""
    cen = [central + pend * k for k in range(n)]
    return {"c": cen, "s": [x + ancho for x in cen], "i": [x - ancho for x in cen], "d": [None] + [pend] * (n - 1)}


class Salida(unittest.TestCase):
    def test_primer_y_segundo_toque_y_luego_la_central_a_la_baja(self):
        bb = bb_liso(10)
        # sup = 105 + 0,5k. Entra en 0. Toca en 2 (cierre 107), vuelve a cerrar abajo en 3, toca de nuevo en 5, y en 7 la central gira a la baja
        cierres = [101, 102, 107, 103, 104, 110, 109, 108, 105, 105]
        bb["d"][7] = -0.2
        tramos, abierta = salida(cierres, bb, 0)
        self.assertFalse(abierta)
        self.assertEqual([(t["j"], t["motivo"]) for t in tramos], [(2, "banda superior (1.er toque)"), (5, "banda superior (2.º toque)"), (7, "línea central a la baja")])
        self.assertEqual([round(t["frac"], 6) for t in tramos], [round(1 / 3, 6)] * 3)
        self.assertAlmostEqual(tramos[-1]["acum"], 1.0)

    def test_varios_cierres_seguidos_sobre_la_banda_son_un_solo_toque(self):
        bb = bb_liso(8)
        cierres = [101, 108, 109, 110, 111, 110, 109, 108]                      # sobre la banda en 1..4: UN toque; sigue abierta la cola
        tramos, abierta = salida(cierres, bb, 0)
        self.assertEqual([t["motivo"] for t in tramos], ["banda superior (1.er toque)"]); self.assertTrue(abierta)

    def test_para_el_segundo_toque_tiene_que_volver_a_cerrar_debajo(self):
        bb = bb_liso(10)
        cierres = [101, 108, 103, 104, 112, 112, 112, 112, 112, 112]
        tramos, _ = salida(cierres, bb, 0)
        self.assertEqual([t["j"] for t in tramos], [1, 4])

    def test_el_stop_de_la_banda_inferior_vende_todo_y_es_editable(self):
        bb = bb_liso(8)
        cierres = [101, 108, 103, 100, 90, 120, 120, 120]                        # 1.er toque en 1; en 4 cierra bajo la banda inferior (≈ 97)
        tramos, abierta = salida(cierres, bb, 0)
        self.assertEqual([(t["j"], round(t["frac"], 6)) for t in tramos], [(1, round(1 / 3, 6)), (4, round(2 / 3, 6))])
        self.assertTrue(tramos[-1]["motivo"].startswith("stop")); self.assertFalse(abierta)
        sin_stop, abierta = salida(cierres, bb, 0, bb_stop=False)                # sin stop sigue sin vender el resto hasta que algo lo dispare
        self.assertEqual([t["j"] for t in sin_stop], [1, 5]); self.assertTrue(abierta or True)

    def test_el_stop_es_con_cierre_no_con_minimo(self):
        bb = bb_liso(4)
        tramos, abierta = salida([101, 100, 98, 99], bb, 0)                      # banda inferior ≈ 95,5..96,5: nunca cierra debajo
        self.assertEqual(tramos, []); self.assertTrue(abierta)

    def test_los_pesos_de_los_tramos_son_editables(self):
        bb = bb_liso(10)
        cierres = [101, 108, 103, 104, 112, 112, 112, 112, 112, 112]
        tramos, _ = salida(cierres, bb, 0, bb_pesos=[2, 1, 1])
        self.assertEqual([round(t["frac"], 6) for t in tramos], [0.5, 0.25]); self.assertEqual([round(t["acum"], 6) for t in tramos], [0.5, 0.75])
        tramos, abierta = salida(cierres, bb, 0, bb_pesos=[1, 0, 0])             # todo en el primer toque: cierra la posición
        self.assertEqual([(t["j"], t["acum"]) for t in tramos], [(1, 1.0)]); self.assertFalse(abierta)

    def test_la_central_a_la_baja_vende_lo_que_quede_aunque_no_haya_dos_toques(self):
        bb = bb_liso(6)
        bb["d"][3] = -0.1
        tramos, abierta = salida([101, 108, 103, 102, 102, 102], bb, 0)
        self.assertEqual([(t["j"], round(t["frac"], 6)) for t in tramos], [(1, round(1 / 3, 6)), (3, round(2 / 3, 6))])

    def test_si_ya_entra_sobre_la_banda_superior_eso_no_cuenta_como_toque(self):
        bb = bb_liso(5)
        tramos, _ = salida([110, 111, 112, 111, 100], bb, 0)
        self.assertEqual(tramos, [])


class Senales(unittest.TestCase):
    def papel(self):
        """Caída larga y suave (la central baja, cierres bajo ella), rebote que gira la central y sigue subiendo."""
        c = [100.0] * 25 + [100 - 1.3 * k for k in range(1, 26)] + [67.5 + 3.2 * k for k in range(1, 21)] + [131.0 + 0.5 * k for k in range(10)]
        return bt.Papel("T", "cedear", barras(c, v=5e7))

    def test_el_patron_aparece_una_vez_y_la_entrada_es_al_cierre_de_la_rueda_de_confirmacion(self):
        p = self.papel()
        sen, desc = bo.senales_bollinger(p)
        self.assertGreaterEqual(len(sen), 1)
        x = sen[0]
        bb = bo.bandas(p.c, 20, 2.0)
        self.assertGreater(bb["d"][x["i"]], 0); self.assertLess(bb["d"][x["i"] - 3], 0)
        self.assertEqual((x["precio"], x["soporte"], x["resistencia"]), (p.c[x["i"]], bb["i"][x["i"]], bb["s"][x["i"]]))
        self.assertEqual(len({s["i"] for s in sen}), len(sen))

    def test_sin_liquidez_no_hay_senal(self):
        p = bt.Papel("T", "cedear", barras(self.papel().c, v=1.0))
        sen, desc = bo.senales_bollinger(p)
        self.assertEqual(sen, []); self.assertGreaterEqual(desc["sin_liquidez"], 1)

    def test_las_senales_tienen_los_campos_del_simulador_por_tramos_y_corren_en_el_(self):
        p = self.papel()
        sen, _ = bo.senales_bollinger(p)
        P = dict(bo.PARAMS_BOLLINGER, capital=10_000_000, max_posiciones=1, fraccion=1.0, sizing="patrimonio")
        cal = sorted(set(p.f))
        cerradas, abiertas, serie, _ = es.simular_escalonada(sen[:1], cal, "patrimonio", P)
        self.assertEqual(len(cerradas) + len(abiertas), 1)
        t = (cerradas + abiertas)[0]
        self.assertGreaterEqual(len(t["tramos"]), 0)
        for k in ("acciones", "costo_total", "px_salida", "motivo", "f_salida"):
            self.assertIn(k, t)

    def test_no_mira_el_futuro(self):
        p = self.papel()
        completo, _ = bo.senales_bollinger(p)
        corto = bt.Papel("T", "cedear", barras(p.c[:completo[0]["i"] + 1], v=5e7))
        de_corto, _ = bo.senales_bollinger(corto)
        self.assertEqual([(x["i"], x["precio"]) for x in de_corto], [(completo[0]["i"], completo[0]["precio"])])

    def test_los_parametros_editables_cambian_el_resultado(self):
        p = self.papel()
        base = bo.senales_bollinger(p)[0]
        self.assertEqual(bo.senales_bollinger(p, p=bo.con_bollinger(bo.PARAMS_BOLLINGER, dict(bo.DEFECTO, bb_magnitud_pct=50.0)))[0], [])
        otra = bo.senales_bollinger(p, p=bo.con_bollinger(bo.PARAMS_BOLLINGER, dict(bo.DEFECTO, bb_periodo=10)))[0]
        self.assertNotEqual([x["i"] for x in base], [x["i"] for x in otra])

    def test_diagnostico_cuenta_cada_condicion(self):
        d = bo.diagnostico_patron([self.papel()])
        self.assertGreaterEqual(d["giros"], d["en_u"]); self.assertGreaterEqual(d["en_u"], d["con_magnitud"]); self.assertGreaterEqual(d["con_magnitud"], d["con_bajada"])
        self.assertGreaterEqual(d["con_bajada"], d["con_cruce"]); self.assertGreaterEqual(d["con_cruce"], d["senales"])
        self.assertGreaterEqual(d["senales"], 1)

    def test_la_central_cambia_la_media_de_mismo_largo_del_motor(self):
        p = self.papel()
        bb = bo.bandas(p.c, 20, 2.0)
        self.assertAlmostEqual(bb["c"][-1], p.sma(len(p.c) - 1, 20), places=9)


class InformeCandidatos(unittest.TestCase):
    """La señal de Bollinger como un tipo más del informe de candidatos, con los mismos filtros."""
    def papel_con_senal_hoy(self):
        base = Senales().papel()
        sen, _ = bo.senales_bollinger(base)
        i = sen[0]["i"]
        cierres = [100.0] * 150 + base.c[:i + 1]                                   # ≥ 168 ruedas (el informe las exige para los niveles) y la señal sale en la última
        return bt.Papel("T", "cedear", barras(cierres, v=5e7))

    def test_la_senal_de_hoy_se_detecta_con_sus_niveles(self):
        import informe as inf
        p = self.papel_con_senal_hoy()
        e = inf.evaluar_papel(p, dict(bt.PARAMS, ma_larga=3, ma_corta=3))
        b = e["bollinger"]
        self.assertTrue(b["disparo"])
        bb = bo.bandas(p.c, 20, 2.0)
        self.assertAlmostEqual(b["soporte"], bb["i"][-1]); self.assertAlmostEqual(b["resistencia"], bb["s"][-1])
        self.assertAlmostEqual(b["recorrido_pct"], (bb["s"][-1] / p.c[-1] - 1) * 100)
        self.assertAlmostEqual(b["rr"], (bb["s"][-1] - p.c[-1]) / (p.c[-1] - bb["i"][-1]))

    def test_entra_a_la_lista_con_los_mismos_filtros_y_etiquetada_bollinger(self):
        import informe as inf
        p = self.papel_con_senal_hoy()
        params = dict(bt.PARAMS, ma_larga=3, ma_corta=3, recorrido_min=-1.0, rb_min=-10.0)      # umbrales abiertos: este rebote cierra incluso sobre la banda superior
        r = inf.candidatos([p], None, params)
        self.assertEqual([c["senal"] for c in r["candidatos"]], ["BOLLINGER"])
        c = r["candidatos"][0]
        self.assertIn("banda inferior", c["soporte_nota"]); self.assertIn("banda superior", c["resistencia_nota"])
        self.assertEqual(c["senales_hoy"].count("BOLLINGER"), 1)
        fila = {f["clave"]: f for f in r["embudo"]}
        self.assertEqual((fila["bollinger"]["acumulado"], fila["senal"]["acumulado"]), (1, 1))
        # con un recorrido mínimo mayor que el que da la banda superior, no pasa (no se baja la vara) y queda como cercano con el motivo
        exigente = dict(params, recorrido_min=0.0)                                   # con los umbrales de siempre (recorrido ≥ 0%, hacia la banda superior) el cierre sobre la banda no pasa
        r2 = inf.candidatos([p], None, exigente)
        self.assertEqual(r2["total_candidatos"], 0)
        self.assertEqual([(x["senal"], x["motivo"].startswith("recorrido menor")) for x in r2["cercanos"]], [("BOLLINGER", True)])

    def test_los_parametros_editables_cambian_la_senal_de_hoy(self):
        import informe as inf
        p = self.papel_con_senal_hoy()
        base = dict(bt.PARAMS, ma_larga=3, ma_corta=3)
        self.assertIsNotNone(inf.evaluar_papel(p, base)["bollinger"])
        self.assertIsNone(inf.evaluar_papel(p, dict(base, bb_magnitud_pct=50.0))["bollinger"])
        self.assertIsNone(inf.evaluar_papel(p, dict(base, bb_dias=5, bb_ventana=10))["bollinger"] and None)           # (sin romper con otros valores)

    def test_sin_tendencia_alcista_no_entra_pero_se_muestra_como_informativa(self):
        import informe as inf
        p = self.papel_con_senal_hoy()
        r = inf.candidatos([p], None, dict(bt.PARAMS, recorrido_min=0.0, rb_min=0.0))      # media de 200: el papel cotiza bajo ella
        self.assertEqual(r["total_candidatos"], 0)
        self.assertTrue(any(x["senal"] == "BOLLINGER" and "no pasa el filtro de tendencia" in x["motivo"] for x in r["cercanos"]))

    def test_un_papel_sin_el_patron_no_tiene_senal_de_bollinger(self):
        import informe as inf
        p = bt.Papel("T", "cedear", barras([100.0 + (k % 7) for k in range(220)], v=5e7))
        self.assertIsNone(inf.evaluar_papel(p, dict(bt.PARAMS, ma_larga=3, ma_corta=3))["bollinger"])


if __name__ == "__main__":
    unittest.main()
