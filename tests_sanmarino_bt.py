"""Pruebas del backtest del listado 2 de San Marino (señales, salida, ausencia de mirada al futuro, coherencia con el listado, cartera y conexión con el generador):  python tests_sanmarino_bt.py"""
import math, os, random, unittest
from datetime import datetime, timedelta

import backtest as bt
import macd
import parametros_macd as pm
import sanmarino_bt as sb
from tests_backtest import barras
from tests_macd import SUAVE, barras_v

AQUI = os.path.dirname(os.path.abspath(__file__))
FIN = datetime(2026, 10, 13).date()


def papel(ticker, cierres, tipo="cedear", v=5e7, alcista=True, fin=FIN):
    ini = fin - timedelta(days=len(cierres) - 1)
    return bt.Papel(ticker, tipo, barras_v(cierres, ini, alcista, v), fin + timedelta(days=1))


def azar(n, semilla=7):
    """Una caminata al azar con máximos y mínimos propios (para comparar cálculos entre sí)."""
    r = random.Random(semilla)
    c, out = 100.0, []
    for _ in range(n):
        o = c
        c = max(1.0, c * (1 + r.uniform(-0.03, 0.03)))
        out.append({"o": o, "h": max(o, c) * (1 + r.uniform(0, 0.01)), "l": min(o, c) * (1 - r.uniform(0, 0.01)), "c": c})
    return out


class CalculoPorRueda(unittest.TestCase):
    """El backtest recorre cada papel con series calculadas una vez: tiene que dar lo mismo que calcular cada rueda con los datos hasta esa rueda."""

    def test_el_estado_del_macd_en_cada_rueda_es_el_mismo_con_la_serie_completa_o_con_los_datos_hasta_esa_rueda(self):
        mp = macd.de_params(pm.defectos())
        c = [x["c"] for x in azar(160)]
        s = macd.serie(c, mp["rapido"], mp["lento"], mp["senal"])
        for t in range(macd.ruedas_minimas(mp) - 1, len(c)):
            a, b = macd.estado_en(s, c, t, mp), macd.estado(c[:t + 1], mp)
            self.assertEqual(set(a), set(b))
            for k in a:
                if isinstance(a[k], float):
                    self.assertAlmostEqual(a[k], b[k], places=9, msg=(t, k))
                elif k != "hist_pct_ult":
                    self.assertEqual(a[k], b[k], (t, k))
        self.assertIsNone(macd.estado_en(s, c, macd.ruedas_minimas(mp) - 2, mp))

    def test_el_vortex_en_cada_rueda_es_el_mismo_con_la_serie_completa_o_con_los_datos_hasta_esa_rueda(self):
        v = azar(80)
        h, l, c = [x["h"] for x in v], [x["l"] for x in v], [x["c"] for x in v]
        vs = macd.vortex_serie(h, l, c, 14)
        for t in range(13, len(c)):
            a, b = macd.vortex_en(vs, t), macd.vortex(h[:t + 1], l[:t + 1], c[:t + 1], 14)
            if b is None:
                self.assertIsNone(a)
                continue
            self.assertAlmostEqual(a["mas"], b["mas"], places=12); self.assertAlmostEqual(a["menos"], b["menos"], places=12)
            self.assertEqual((a["alcista"], a["ruedas"]), (b["alcista"], b["ruedas"]))


class Senales(unittest.TestCase):
    def setUp(self):
        self.p = sb.parametros(pm.defectos())
        s = macd.serie(SUAVE, 12, 26, 9)
        self.t0 = next(i for i in range(60, 120) if s["hist"][i] > 0 and s["hist"][i - 1] <= 0)       # el MACD cruza hacia arriba en la rueda 72
        self.t1 = next(i for i in range(self.t0 + 1, 150) if s["hist"][i] <= 0)                       # y vuelve a cruzar hacia abajo en la 91
        self.assertEqual((self.t0, self.t1), (72, 91))

    def senales(self, pa, **kw):
        return sb.senales_sanmarino2(pa, p=dict(self.p, **kw))

    def test_entra_en_la_primera_rueda_del_listado_2_y_sale_al_cierre_del_cruce_hacia_abajo(self):
        pa = papel("A", SUAVE[:self.t1 + 5])
        out, desc = self.senales(pa)
        self.assertEqual(len(out), 1)                                                                 # el cruce cumple varias ruedas seguidas (72 y 73): una sola señal
        x = out[0]
        self.assertEqual((x["i"], x["j"], x["motivo"]), (self.t0, self.t1, sb.MOTIVO_SALIDA))
        self.assertEqual((x["precio"], x["px_salida"]), (pa.c[self.t0], pa.c[self.t1]))                # entrada y salida al cierre
        self.assertEqual((x["fecha"], x["f_salida"]), (pa.f[self.t0], pa.f[self.t1]))
        self.assertEqual(desc["episodios"], 1)

    def test_si_los_datos_terminan_antes_de_la_salida_queda_abierta_al_ultimo_cierre(self):
        pa = papel("A", SUAVE[:self.t1 - 3])
        x = self.senales(pa)[0][0]
        self.assertEqual((x["motivo"], x["j"], x["px_salida"]), ("abierta", len(pa.c) - 1, pa.c[-1]))

    def test_coherencia_con_el_listado_cada_senal_es_un_papel_que_estaba_en_el_listado_2_ese_dia(self):
        pa = papel("A", SUAVE[:self.t1 + 5])
        for t in range(36, len(pa.c)):
            corte = bt.Papel("A", "cedear", barras_v(SUAVE[:t + 1], FIN - timedelta(days=len(SUAVE[:t + 1]) - 1)), FIN + timedelta(days=1))
            en_lista = bool(macd.listado2([corte], self.p["sm"], {"papeles": {}}, None)["lista"])
            en_senal = any(x["i"] == t for x in self.senales(pa, piso_monto=0)[0]) or (t == self.t0 + 1)   # (la rueda 73 también está en el listado: no da otra señal porque es el mismo cruce)
            if t in (self.t0, self.t0 + 1):
                self.assertTrue(en_lista, t)
            self.assertTrue(en_lista or not en_senal, t)

    def test_sin_mirar_el_futuro_las_entradas_no_cambian_si_se_corta_la_serie(self):
        completa = papel("A", SUAVE[:150])
        e_completa = [(x["i"], x["precio"]) for x in self.senales(completa)[0]]
        for corte in (80, 95, 120):
            parcial = bt.Papel("A", "cedear", barras_v(SUAVE[:corte], FIN - timedelta(days=corte - 1)), FIN + timedelta(days=1))
            e_parcial = [(x["i"], x["precio"]) for x in self.senales(parcial)[0]]
            self.assertEqual(e_parcial, [e for e in e_completa if e[0] < corte], corte)

    def test_un_papel_ilíquido_no_entra_pero_si_gana_liquidez_en_el_mismo_cruce_entra_ese_dia(self):
        pa = papel("A", SUAVE[:self.t1 + 5], v=1e3)
        out, desc = self.senales(pa)
        self.assertEqual(out, []); self.assertGreaterEqual(desc["sin_liquidez"], 1); self.assertEqual(desc["episodios"], 1)
        # el monto promedio de 5 ruedas pasa el piso recién en la rueda t0+1: entra ese día
        pa2 = papel("A", SUAVE[:self.t1 + 5], v=1e3)
        for k in range(self.t0 - 3, len(pa2.c)):
            pa2.monto5[k] = 0.0 if k <= self.t0 else 5e9
        out, desc = self.senales(pa2)
        self.assertEqual([x["i"] for x in out], [self.t0 + 1]); self.assertEqual(desc["sin_liquidez"], 1)

    def test_solo_cedears(self):
        self.assertEqual(self.senales(papel("GGAL", SUAVE[:self.t1 + 5], tipo="accion"))[0], [])

    def test_el_vortex_bajista_bloquea_la_entrada_y_apagarlo_la_permite(self):
        pa = papel("A", SUAVE[:self.t1 + 5], alcista=False)
        self.assertEqual(self.senales(pa)[0], [])
        p2 = sb.parametros(dict(pm.defectos(), vortex_exigir=0))
        self.assertEqual(len(sb.senales_sanmarino2(pa, p=p2)[0]), 1)

    def test_con_pocas_ruedas_no_hay_senales(self):
        self.assertEqual(self.senales(papel("A", SUAVE[:30]))[0], [])


class Parametros(unittest.TestCase):
    def test_usa_los_valores_de_san_marino_y_la_cartera_de_tres_posiciones(self):
        p = sb.parametros(pm.defectos())
        self.assertEqual((p["max_posiciones"], p["sizing"], p["estrategia"]), (3, "patrimonio", sb.ESTRATEGIA))
        self.assertAlmostEqual(p["fraccion"], 1 / 3)
        self.assertEqual(p["ventana_ruedas"], macd.ruedas_minimas(p["sm"])); self.assertEqual(p["piso_monto"], 1_000_000_000)
        v = dict(pm.defectos(), macd_piso_millones=2000, macd2_dist_pct=0.3, vortex_exigir=0)
        q = sb.parametros(v)
        self.assertEqual((q["piso_monto"], q["sm"]["dist2_pct"], q["sm"]["vortex_exigir"]), (2_000_000_000, 0.3, False))

    def test_valores_invalidos_no_se_corrigen_en_silencio(self):
        with self.assertRaises(pm.ErrorParametro):
            sb.parametros(dict(pm.defectos(), macd_rapido=40))

    def test_la_regla_dice_lo_que_se_uso(self):
        t = sb.regla(sb.parametros(pm.defectos()))
        for frag in ("12/26/9", "3 ruedas", "0,15%", "Vortex de 14", "1.000 M", "no se probó ninguna otra"):
            self.assertIn(frag, t)
        self.assertIn("el Vortex no se exige", sb.regla(sb.parametros(dict(pm.defectos(), vortex_exigir=0))))


class Cartera(unittest.TestCase):
    def test_la_corrida_completa_es_aritmetica_a_mano(self):
        p = sb.parametros(pm.defectos())
        pa = papel("A", SUAVE[:100])
        res = bt.correr([pa], None, p, generar=sb.senales_sanmarino2)
        self.assertEqual(res["senales_total"], 1)
        t = res["base"]["cerradas"][0]
        lado = bt.costo_lado(p)
        acciones = math.floor(p["capital"] / 3 / (pa.c[72] * (1 + lado)))
        costo = acciones * pa.c[72] * (1 + lado)
        pnl = acciones * pa.c[91] * (1 - lado) - costo
        self.assertEqual(t["acciones"], acciones); self.assertAlmostEqual(t["costo_total"], costo, places=6); self.assertAlmostEqual(t["pnl"], pnl, places=6)
        self.assertAlmostEqual(res["base"]["serie"][-1][1], p["capital"] + pnl, places=4)                 # la única operación está cerrada: el patrimonio final es capital + resultado

    def test_con_mas_de_tres_senales_el_mismo_dia_entran_tres(self):
        p = sb.parametros(pm.defectos())
        papeles = [papel(f"P{k}", SUAVE[:100], v=5e7 + k * 1e6) for k in range(5)]
        res = bt.correr(papeles, None, p, generar=sb.senales_sanmarino2)
        self.assertEqual(res["senales_total"], 5)
        self.assertEqual(len(res["base"]["cerradas"]) + len(res["base"]["abiertas"]), 3); self.assertEqual(res["base"]["desc"]["sin_lugar"], 2)
        self.assertEqual(sorted(x["papel"].ticker for x in res["base"]["cerradas"]), ["P2", "P3", "P4"])    # entran los de mayor monto operado


class ConexionConElGenerador(unittest.TestCase):
    def test_la_variante_esta_en_el_generador_y_en_el_workflow(self):
        gen = open(os.path.join(AQUI, "generar_backtest.py"), encoding="utf-8").read()
        wf = open(os.path.join(AQUI, ".github", "workflows", "backtest.yml"), encoding="utf-8").read()
        self.assertIn('"sanmarino_listado2"', gen); self.assertIn("sanmarino_listado2", wf); self.assertIn("python tests_sanmarino_bt.py", wf)
        self.assertIn("comparacion_sanmarino", gen)

    def test_el_backtest_no_agrega_entradas_al_workflow_que_ya_esta_en_el_tope(self):
        import re
        wf = open(os.path.join(AQUI, ".github", "workflows", "backtest.yml"), encoding="utf-8").read()
        self.assertLessEqual(len(re.findall(r"(?m)^      (\w+):\s*\n\s+description", wf)), 10)

    def test_la_pagina_dibuja_el_panel_del_backtest(self):
        html = open(os.path.join(AQUI, "docs", "index.html"), encoding="utf-8").read()
        for nombre in ("comparacionSMBT", "reglasSanMarino"):
            self.assertIn("function " + nombre, html)
        self.assertIn("r.comparacion_sanmarino", html)


if __name__ == "__main__":
    unittest.main(verbosity=1)
