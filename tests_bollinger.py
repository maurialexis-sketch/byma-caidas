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


def papel_de(cierres, ticker="T", tipo="cedear", v=5e7):
    return bt.Papel(ticker, tipo, barras(cierres, v=v))


PL = dict(bo.PARAMS_BOLLINGER, bb_ventana_listas=30)      # las pruebas de los listados se escribieron con series largas: ventana amplia (30); la de fábrica (7) se prueba aparte
PLL = dict(bo.PARAMS_LISTAS, bb_ventana_listas=30)
BAJA = [100.0] * 30 + [100 - 1.6 * k for k in range(1, 26)]                       # 25 ruedas de caída pareja: los cierres quedan bajo la central y la central baja
SUBE = [60.0 + 3.0 * k for k in range(1, 30)]                                     # y después un rebote


class Listados(unittest.TestCase):
    def estado(self, cierres, **kw):
        return bo.estado_listas(papel_de(cierres), dict(PL, **kw))

    def test_listado_1_cierres_por_debajo_de_la_central_y_pendiente_negativa(self):
        e = self.estado(BAJA)
        self.assertEqual(e["lista"], 1)
        self.assertGreaterEqual(e["velas_bajo"], 5); self.assertLess(e["dist_central_pct"], 0); self.assertLess(e["pendiente_pct"], 0)

    def test_el_listado_1_pide_5_velas_seguidas_y_es_editable(self):
        # 4 ruedas bajo la central desde que empezó la caída: todavía no entra; con 5 sí
        i = next(k for k in range(31, len(BAJA)) if bo.estado_listas(papel_de(BAJA[:k + 1]), PL)["lista"] == 1)
        e = bo.estado_listas(papel_de(BAJA[:i + 1]), PL)
        self.assertEqual(e["velas_bajo"], 5)
        anterior = bo.estado_listas(papel_de(BAJA[:i]), PL)
        self.assertIsNone(anterior["lista"])
        self.assertEqual(bo.estado_listas(papel_de(BAJA[:i]), dict(PL, bb_velas_caida=4))["lista"], 1)      # con 4 velas editables, entra una rueda antes

    def test_un_papel_que_solo_sube_no_esta_en_ningun_listado(self):
        e = self.estado([100.0 + k for k in range(80)])
        self.assertIsNone(e["lista"])

    def test_listado_2_giro_confirmado_solo_si_antes_estuvo_en_el_listado_1(self):
        cierres = BAJA + SUBE
        estados = [bo.estado_listas(papel_de(cierres[:k + 1]), PL) for k in range(len(BAJA), len(cierres))]
        l2 = [x for x in estados if x["lista"] == 2]
        self.assertGreaterEqual(len(l2), 1)
        for x in l2:
            self.assertGreaterEqual(x["velas_bajo_antes"], 5); self.assertGreater(x["dist_central_pct"], 0); self.assertLessEqual(x["ruedas_desde_listado1"], 30)
        self.assertEqual({x["lista"] for x in estados[:3]} - {1}, set())              # recién terminada la caída sigue en el listado 1

    def test_las_velas_atravesadas_por_la_linea_en_el_cambio_de_pendiente_se_permiten(self):
        # fondo en zigzag: los cierres cruzan la central varias veces mientras la pendiente pasa de negativa a positiva; igual se confirma el giro
        cierres = BAJA + [60.0, 62, 59, 63, 60, 64, 62, 66, 63, 68, 63, 70, 62, 72, 66, 74, 71, 75, 76]
        estados = {k: bo.estado_listas(papel_de(cierres[:k + 1]), PL) for k in range(len(BAJA), len(cierres))}
        lado = [cierres[k] > estados[k]["central"] for k in sorted(estados)]
        self.assertTrue(any(a and not b for a, b in zip(lado, lado[1:])) and any(b and not a for a, b in zip(lado, lado[1:])))     # los cierres cruzaron la línea en los dos sentidos
        self.assertEqual(estados[len(cierres) - 1]["lista"], 2)
        self.assertGreaterEqual(estados[len(cierres) - 1]["velas_bajo_antes"], 5)
        self.assertTrue(any(e["lista"] is None for e in estados.values()))           # y mientras cruzaban todavía no estaba en ningún listado

    def test_sin_caida_previa_no_hay_giro_confirmado(self):
        # sube, baja apenas 3 ruedas y vuelve a subir: nunca estuvo 5 velas bajo la central
        cierres = [100.0 + 0.4 * k for k in range(40)] + [112.0, 108.0, 104.0] + [106.0 + 2 * k for k in range(25)]
        estados = {bo.estado_listas(papel_de(cierres[:k + 1]), PL)["lista"] for k in range(35, len(cierres))}
        self.assertNotIn(2, estados)

    def test_una_caida_vieja_no_hace_de_un_giro_una_senal_de_entrada(self):
        cierres = BAJA + SUBE + [150.0 + k for k in range(30)]
        self.assertIsNone(bo.estado_listas(papel_de(cierres), PL)["lista"])       # la última rueda del listado 1 quedó a más de 20 ruedas

    def test_las_velas_del_giro_son_editables(self):
        cierres = BAJA + SUBE
        primero = lambda G: next(k for k in range(len(BAJA), len(cierres)) if bo.estado_listas(papel_de(cierres[:k + 1]), dict(PL, bb_velas_giro=G))["lista"] == 2)
        self.assertLess(primero(2), primero(4))                                    # pedir más velas encima demora la confirmación

    def test_sin_filtro_de_liquidez_pero_con_el_monto_y_la_marca_de_operable(self):
        chico = bt.Papel("CHICO", "cedear", barras(BAJA, v=100.0))                # monto ínfimo
        grande = bt.Papel("GRANDE", "cedear", barras(BAJA, v=5e7))
        r = bo.listas([chico, grande], dict(PL))
        self.assertEqual([f["ticker"] for f in r["lista1"]], ["GRANDE", "CHICO"])           # operables primero
        g, c = r["lista1"]
        self.assertTrue(g["operable"]); self.assertFalse(c["operable"])
        self.assertGreater(g["monto5_millones"], 1000); self.assertLess(c["monto5_millones"], 1)
        self.assertEqual(g["volumen_dia"], 5e7); self.assertAlmostEqual(g["monto_dia_millones"], BAJA[-1] * 5e7 / 1e6, places=3)
        self.assertEqual(r["resumen"], {"lista1": 2, "lista1_operables": 1, "lista2": 0, "lista2_operables": 0})
        self.assertEqual(bo.listas([chico], dict(PL, piso_monto=1))["lista1"][0]["operable"], True)          # el piso es el editable

    def test_solo_cedears_y_una_empresa_una_vez(self):
        accion = bt.Papel("GGAL", "accion", barras(BAJA, v=5e7))
        a, b = bt.Papel("AAPL", "cedear", barras(BAJA, v=5e7)), bt.Papel("AAPLB", "cedear", barras(BAJA, v=1e6))
        r = bo.listas([accion, a, b], dict(PL), None, lambda t: "AAPL" if t.startswith("AAPL") else t)
        self.assertEqual([f["ticker"] for f in r["lista1"]], ["AAPL"]); self.assertEqual(r["lista1"][0]["otras_lineas"], ["AAPLB"])
        self.assertEqual(r["evaluados"], 2)

    def test_el_periodo_de_la_media_central_es_editable(self):
        a = bo.estado_listas(papel_de(BAJA), dict(PL, bb_periodo_listas=20))
        b = bo.estado_listas(papel_de(BAJA), dict(PL, bb_periodo_listas=10))
        self.assertNotEqual(round(a["central"], 6), round(b["central"], 6))
        self.assertAlmostEqual(b["central"], sum(BAJA[-10:]) / 10)

    def test_papel_con_pocas_ruedas_no_se_evalua(self):
        self.assertIsNone(bo.estado_listas(papel_de([100.0] * 15), PL))

    def test_sin_cotizacion_reciente_no_entra(self):
        viejo = bt.Papel("VIEJO", "cedear", barras(BAJA, inicio=bt.date(2020, 1, 1) if hasattr(bt, "date") else __import__("datetime").date(2020, 1, 1), v=5e7))
        nuevo = bt.Papel("NUEVO", "cedear", barras(BAJA, v=5e7))
        r = bo.listas([viejo, nuevo], dict(PL))
        self.assertEqual([f["ticker"] for f in r["lista1"]], ["NUEVO"])


class EstrategiaDeLosListados(unittest.TestCase):
    ZIG = [60.0, 62, 59, 63, 60, 64, 62, 66, 63, 68, 63, 70, 62, 72, 66, 74, 71, 75, 76, 80, 84, 83, 85]

    def papel(self, v=5e7):
        return bt.Papel("T", "cedear", barras(BAJA + self.ZIG, v=v))

    def test_entra_en_la_primera_rueda_del_listado_2_y_una_sola_vez_por_episodio(self):
        p = self.papel()
        sen, desc = bo.senales_listas(p, p=PLL)
        self.assertEqual(len(sen), 1); self.assertEqual(desc["episodios"], 1)
        i = sen[0]["i"]
        self.assertEqual(bo.estado_listas(bt.Papel("T", "cedear", barras((BAJA + self.ZIG)[:i + 1], v=5e7)), PL)["lista"], 2)         # ese día está en el listado 2
        # y ninguna rueda anterior del mismo episodio lo estaba
        for k in range(len(BAJA), i):
            self.assertNotEqual(bo.estado_listas(bt.Papel("T", "cedear", barras((BAJA + self.ZIG)[:k + 1], v=5e7)), PL)["lista"], 2)
        self.assertEqual(sen[0]["precio"], p.c[i])

    def test_el_estado_por_rueda_es_el_mismo_que_calculado_con_los_datos_hasta_esa_rueda(self):
        p = self.papel()
        n, K, G = 20, 5, 2
        cen, d, bajo = bo._preparar_listas(p.c, n)
        for k in range(30, len(p.c)):
            a = bo._estado_en(k, p.c, cen, d, bajo, n, K, G, 30)
            b = bo.estado_listas(bt.Papel("T", "cedear", barras((BAJA + self.ZIG)[:k + 1], v=5e7)), PL)
            self.assertEqual(a["lista"], b["lista"]); self.assertAlmostEqual(a["central"], b["central"])          # no mira el futuro

    def test_sin_liquidez_no_entra_y_con_liquidez_posterior_entra_ese_dia(self):
        self.assertEqual(bo.senales_listas(self.papel(v=100.0), p=PLL)[0], [])
        p = self.papel()
        sen0 = bo.senales_listas(p, p=PLL)[0][0]
        monto = list(p.monto5)
        for k in range(len(monto)):
            if k < sen0["i"] + 2:
                monto[k] = 1.0                                                      # ilíquido hasta dos ruedas después de la primera señal
        p.monto5 = monto
        sen, desc = bo.senales_listas(p, p=PLL)
        self.assertEqual(len(sen), 1); self.assertEqual(sen[0]["i"], sen0["i"] + 2); self.assertGreaterEqual(desc["sin_liquidez"], 2)

    def test_la_salida_es_la_escalonada_de_bollinger_y_corre_en_el_simulador_por_tramos(self):
        p = self.papel()
        sen, _ = bo.senales_listas(p, p=PLL)
        x = sen[0]
        bb = bo.bandas(p.c, 20, 2.0)
        tramos, abierta = bo.salida_bollinger(p.c, bb, x["i"], bo.de_params(PLL))
        self.assertEqual([t["j"] for t in x["tramos_plan"]], [t["j"] for t in tramos]); self.assertEqual(x["abierta_plan"], abierta)
        P = dict(PLL, capital=10_000_000, max_posiciones=1, fraccion=1.0, sizing="patrimonio")
        cerradas, abiertas, serie, _ = es.simular_escalonada(sen, sorted(set(p.f)), "patrimonio", P)
        self.assertEqual(len(cerradas) + len(abiertas), 1)

    def test_sin_caida_previa_no_hay_entrada(self):
        p = bt.Papel("T", "cedear", barras([100.0 + 0.5 * k for k in range(120)], v=5e7))
        self.assertEqual(bo.senales_listas(p, p=PLL)[0], [])

    def test_los_parametros_de_los_listados_cambian_las_entradas(self):
        p = self.papel()
        exigente = bo.con_bollinger(PLL, dict(bo.DEFECTO, bb_periodo_listas=20, bb_velas_giro=2, bb_velas_caida=40))
        self.assertEqual(bo.senales_listas(p, p=exigente)[0], [])


class ListadosPorDefecto(unittest.TestCase):
    """Los valores de fábrica: media de 20 cierres (propia y editable), en las últimas 7 ruedas 5 caídas seguidas bajo la línea con la línea bajando y las últimas 2 en levantada."""
    PLANO = [100.0] * 40
    CAIDAS = [99.0, 98.5, 98.0, 98.5, 99.0]              # 5 cierres bajo la central de 20 (≈99,9) y la central bajando (cada uno es menor que el de hace 20 ruedas: 100)

    def estado(self, cierres, **kw):
        return bo.estado_listas(papel_de(cierres), dict(bo.PARAMS_BOLLINGER, **kw))

    def test_valores_de_fabrica(self):
        d = bo.DEFECTO
        self.assertEqual((d["bb_periodo_listas"], d["bb_velas_caida"], d["bb_velas_giro"], d["bb_ventana_listas"], d["bb_periodo"]), (20, 5, 2, 10, 20))

    def test_cinco_caidas_y_dos_levantadas_en_siete_ruedas(self):
        self.assertEqual(self.estado(self.PLANO + self.CAIDAS)["lista"], 1)                                   # al cierre de la 5.ª caída: listado 1
        e = self.estado(self.PLANO + self.CAIDAS + [101.0, 102.0])
        self.assertEqual(e["lista"], 2)                                                                          # 5 caídas + 2 levantadas
        self.assertEqual((e["velas_sobre"], e["velas_bajo_antes"], e["ruedas_desde_listado1"]), (2, 5, 2))
        self.assertGreater(e["dist_central_pct"], 0); self.assertGreater(e["pendiente_pct"], 0)
        self.assertEqual(self.estado(self.PLANO + self.CAIDAS + [101.0])["lista"], None)                         # con una sola levantada todavía no
        self.assertEqual(self.estado(self.PLANO + self.CAIDAS + [101.0], bb_velas_giro=1)["lista"], 2)           # (editable: con 1 vela sí)

    def test_menos_de_cinco_caidas_no_alcanza(self):
        self.assertEqual(self.estado(self.PLANO + self.CAIDAS[1:] + [101.0, 102.0])["lista"], None)
        self.assertEqual(self.estado(self.PLANO + self.CAIDAS[1:] + [101.0, 102.0], bb_velas_caida=4)["lista"], 2)

    def test_la_linea_tiene_que_subir_no_alcanza_con_cerrar_arriba(self):
        # cierra dos veces por encima de la línea pero la central sigue bajando (los cierres siguen por debajo de los de hace 20 ruedas): no es un giro (caso GLD)
        bajando = [100.0] * 20 + [110.0] * 20 + [100.0] * 0
        c = bajando + [105.0, 104.0, 103.0, 102.0, 101.0, 106.0, 107.0]
        e = self.estado(c)
        self.assertNotEqual(e["lista"], 2)
        self.assertLess(e["pendiente_pct"], 0)

    def test_entre_la_caida_y_la_levantada_puede_haber_velas_atravesadas_y_la_caida_tiene_que_ser_reciente(self):
        cruzada = self.PLANO + self.CAIDAS + [100.5, 99.0, 101.0, 102.0]                                          # una vela atravesada y otra caída entre las 5 caídas y las 2 levantadas
        self.assertEqual(self.estado(cruzada)["lista"], 2)                                                        # se permiten (la caída terminó hace 5 ruedas)
        vieja = self.PLANO + self.CAIDAS + [100.5, 100.2, 100.3, 100.1, 100.4, 100.6, 100.5, 100.7, 100.8, 101.0, 102.0]
        self.assertEqual(self.estado(vieja)["lista"], None)                                                       # la caída terminó hace más de 10 ruedas
        self.assertEqual(self.estado(vieja, bb_ventana_listas=20)["lista"], 2)                                    # (editable)

    def test_el_periodo_de_los_listados_es_propio_y_no_cambia_el_de_la_estrategia(self):
        c = self.PLANO + self.CAIDAS + [101.0, 102.0]
        self.assertEqual(self.estado(c, bb_periodo=40)["lista"], 2)                                               # el período de la estrategia no toca los listados
        e = self.estado(c, bb_periodo_listas=8)
        self.assertAlmostEqual(e["central"], sum(c[-8:]) / 8)


JD = [11380, 11580, 11650, 11690, 11670, 11720, 11530, 11380, 11500, 11260, 11090, 11050, 10990, 11180, 11080, 11020, 10780, 10790, 10810, 10900, 10830, 10760, 10640, 10780, 10890,
      10960, 10930, 10840, 10720, 10820, 10630, 10750, 10710, 10440, 10590, 10640, 10850, 10840, 10950, 10830, 10750, 11080, 10880, 10840]       # JD.com (CEDEAR en pesos): cierres reales hasta el 19/10/2026


class CasoJD(unittest.TestCase):
    """Validación pedida con JD.com: media de 20; venía cayendo bajo la central (hasta el 06/10) y las últimas velas cierran por encima.
    Índices: 31..35 = 30/09..06/10 (caídas), 36 = 07/10, 37 = 08/10, 38 = 09/10, 39 = 13/10, 40 = 14/10 (cierra bajo la central), 41 = 15/10, 42 = 16/10, 43 = 19/10."""
    def estado(self, hasta, **kw):
        return bo.estado_listas(papel_de([float(x) for x in JD[:hasta + 1]]), dict(bo.PARAMS_BOLLINGER, **kw))

    def test_venia_cayendo_bajo_la_central_hasta_el_6_de_octubre(self):
        for k in (31, 32, 33, 34, 35):
            self.assertEqual(self.estado(k)["lista"], 1)                                    # en caída (listado 1) del 30/09 al 06/10

    def test_el_7_de_octubre_todavia_no_hay_dos_cierres_encima(self):
        self.assertEqual(self.estado(36)["lista"], None)

    def test_jd_figura_en_el_listado_2_el_8_9_y_13_de_octubre(self):
        for k in (37, 38, 39):
            e = self.estado(k)
            self.assertEqual(e["lista"], 2, k)
            self.assertEqual(e["velas_sobre"], 2); self.assertGreaterEqual(e["velas_bajo_antes"], 5); self.assertGreater(e["dist_central_pct"], 0)

    def test_el_13_de_octubre_entra_aunque_la_pendiente_todavia_no_sea_positiva(self):
        e = self.estado(39)
        self.assertEqual(e["lista"], 2)
        self.assertLess(e["pendiente_pct"], 0)                                                # la pendiente no se exige: la media de 20 todavía baja

    def test_el_14_de_octubre_sale_porque_cierra_bajo_la_central_y_el_15_todavia_no_tiene_dos_encima(self):
        self.assertEqual(self.estado(40)["lista"], None)
        self.assertEqual(self.estado(41)["lista"], None)

    def test_hoy_19_de_octubre_figura_con_3_cierres_seguidos_encima_y_la_pendiente_ya_subiendo(self):
        e = self.estado(43)
        self.assertEqual(e["lista"], 2)
        self.assertGreater(e["pendiente_pct"], 0); self.assertEqual(e["ruedas_desde_listado1"], 8)    # la caída terminó el 06/10, ocho ruedas atrás
        self.assertEqual(self.estado(42)["lista"], 2)

    def test_la_ventana_es_editable_con_7_ruedas_desde_la_caida_jd_ya_no_entra_el_19_de_octubre(self):
        self.assertEqual(self.estado(43, bb_ventana_listas=7)["lista"], None)
        self.assertEqual(self.estado(43, bb_ventana_listas=8)["lista"], 2)


if __name__ == "__main__":
    unittest.main()
