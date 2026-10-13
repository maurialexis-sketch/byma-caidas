"""Pruebas de los índices de referencia y la vara fija:  python tests_indices.py"""
import unittest
from datetime import date, timedelta

import backtest as bt
import generar_backtest as gb
import indices as ix
import ruptura as rp
from tests_backtest import barras, serie_con_rango
from tests_ruptura import SUBE, papel


def serie(inicio, valores):
    return [(inicio + timedelta(days=i), v) for i, v in enumerate(valores)]


class Catalogo(unittest.TestCase):
    def test_ningun_indice_es_operable(self):
        self.assertTrue(ix.INDICES)
        for k, v in ix.INDICES.items():
            self.assertIs(v["operable"], False, k)

    def test_estan_los_dos_indices_pedidos(self):
        self.assertIn("merval", ix.INDICES)
        self.assertTrue({"sp500_ars", "sp500_usd"} <= set(ix.INDICES))

    def test_un_indice_no_puede_ser_un_papel(self):
        for nombre in ("^MERV", "^GSPC", "MERVAL", "S&P500"):
            self.assertTrue(ix.es_indice(nombre), nombre)
        self.assertFalse(ix.es_indice("GGAL"))
        self.assertFalse(ix.es_indice("SPY"))      # el CEDEAR SPY es un ETF operable; el índice es otra cosa

    def test_la_vara_por_grupo(self):
        self.assertEqual(ix.claves_vara("Merval"), ["merval"])
        self.assertEqual(ix.claves_vara("CEDEAR"), ["sp500_ars"])
        self.assertEqual(set(ix.claves_vara("mixto")), {"merval", "sp500_ars"})
        self.assertEqual(set(ix.claves_vara()), {"merval", "sp500_ars"})            # por defecto: mixto
        self.assertNotIn("sp500_usd", ix.claves_vara("mixto"))                      # el dólar solo se informa (moneda distinta)

    def test_grupo_de_universo(self):
        class T:
            def __init__(self, tipo): self.tipo = tipo
        self.assertEqual(ix.grupo_de_universo([T("accion"), T("accion")]), "Merval")
        self.assertEqual(ix.grupo_de_universo([T("cedear")]), "CEDEAR")
        self.assertEqual(ix.grupo_de_universo([T("accion"), T("cedear")]), "mixto")


class Evaluar(unittest.TestCase):
    def test_supera_solo_si_rinde_mas_que_la_vara(self):
        v = ix.evaluar(50.0, {"merval": 40.0, "sp500_ars": 30.0}, ["merval", "sp500_ars"])
        self.assertTrue(v["supera"]); self.assertEqual(v["clave"], "merval"); self.assertAlmostEqual(v["diferencia_pp"], 10.0)

    def test_en_un_universo_mixto_manda_el_indice_que_mas_rindio(self):
        v = ix.evaluar(50.0, {"merval": 40.0, "sp500_ars": 77.0}, ["merval", "sp500_ars"])
        self.assertFalse(v["supera"]); self.assertEqual(v["clave"], "sp500_ars"); self.assertAlmostEqual(v["diferencia_pp"], -27.0)

    def test_empatar_no_es_superar(self):
        self.assertFalse(ix.evaluar(40.0, {"merval": 40.0}, ["merval"])["supera"])

    def test_perder_contra_un_indice_que_cae_tampoco_alcanza_si_el_resultado_es_peor(self):
        self.assertFalse(ix.evaluar(-15.0, {"merval": -5.0}, ["merval"])["supera"])
        self.assertTrue(ix.evaluar(-3.0, {"merval": -5.0}, ["merval"])["supera"])      # perder menos que el índice sí supera la vara

    def test_sin_referencia_no_se_afirma_nada(self):
        self.assertIsNone(ix.evaluar(10.0, {}, ["merval"]))
        self.assertIsNone(ix.evaluar(10.0, {"merval": None}, ["merval"]))

    def test_ignora_los_indices_que_no_forman_la_vara(self):
        v = ix.evaluar(10.0, {"merval": 5.0, "sp500_usd": 500.0}, ["merval"])
        self.assertTrue(v["supera"])


class EnElBacktest(unittest.TestCase):
    def setUp(self):
        bt.fijar_referencias({}, [])

    def tearDown(self):
        bt.fijar_referencias({}, [])

    def correr(self, refs, vara):
        bt.fijar_referencias(refs, vara)
        pa = papel(SUBE + [133.0] * 30)
        return bt.correr([pa], refs.get("merval"), rp.PARAMS_RUPTURA, generar=rp.senales_ruptura), pa

    def test_las_referencias_se_alinean_al_calendario_y_no_son_papeles(self):
        inicio = date(2025, 1, 1)
        refs = {"merval": serie(inicio, [100.0 + i for i in range(260)]), "sp500_ars": serie(inicio, [100.0 * 1.01 ** i for i in range(260)])}
        res, pa = self.correr(refs, ["merval", "sp500_ars"])
        self.assertEqual(set(res["referencias"]), {"merval", "sp500_ars"})
        for k, v in res["referencias"].items():
            self.assertEqual(v["serie"][0][1], bt.PARAMS["capital"])               # se normaliza al capital inicial
            self.assertEqual(len(v["serie"]), len(res["base"]["serie"]))           # mismo calendario que la estrategia
        self.assertFalse(any(isinstance(v, bt.Papel) for v in bt.REFERENCIAS.values()))
        self.assertTrue(all(isinstance(v, list) for v in bt.REFERENCIAS.values()))  # series sueltas, no papeles

    def test_la_vara_es_el_indice_de_mayor_retorno_entre_los_de_la_vara(self):
        inicio = date(2025, 1, 1)
        refs = {"merval": serie(inicio, [100.0 + i for i in range(260)]), "sp500_ars": serie(inicio, [100.0 * 1.01 ** i for i in range(260)]),
                "sp500_usd": serie(inicio, [100.0 * 1.05 ** i for i in range(260)])}                 # el más alto, pero no forma la vara
        res, _ = self.correr(refs, ["merval", "sp500_ars"])
        v = bt.vara_de(res)
        self.assertEqual(v["clave"], "sp500_ars")
        self.assertGreater(v["retorno_pct"], res["referencias"]["merval"]["metricas"]["retorno_total_pct"])
        self.assertIn("sp500_usd", res["referencias"])                                              # se informa igual

    def test_sin_referencias_no_hay_vara(self):
        res, _ = self.correr({}, [])
        self.assertIsNone(bt.vara_de(res))
        self.assertEqual(res["referencias"], {})

    def test_el_resumen_de_cada_estrategia_lleva_la_vara_y_la_marca(self):
        inicio = date(2025, 1, 1)
        refs = {"merval": serie(inicio, [100.0 + 0.001 * i for i in range(260)]), "sp500_ars": serie(inicio, [100.0 + 0.001 * i for i in range(260)])}
        res, _ = self.correr(refs, ["merval", "sp500_ars"])
        r = gb.resumen(res)
        self.assertIsNotNone(r["vara"])
        self.assertEqual(r["vara"]["supera"], r["ganancia_total_pct"] > r["vara"]["retorno_pct"])
        self.assertEqual(r["vara"]["diferencia_pp"], round(r["ganancia_total_pct"] - r["vara"]["retorno_pct"], 2))
        # una vara imposible de superar se marca como NO superada
        refs2 = {"merval": serie(inicio, [100.0 * 1.02 ** i for i in range(260)])}
        res2, _ = self.correr(refs2, ["merval"])
        self.assertFalse(gb.resumen(res2)["vara"]["supera"])

    def test_el_informe_completo_advierte_cuando_no_supera_la_vara(self):
        inicio = date(2025, 1, 1)
        refs = {"merval": serie(inicio, [100.0 * 1.02 ** i for i in range(260)])}
        res, pa = self.correr(refs, ["merval"])

        class Rel:
            fuente = "prueba"
            def ahora(self): return __import__("datetime").datetime(2026, 1, 1, tzinfo=bt.AR)
        out = gb.resultado_json(res, {"papeles": [pa], "especies": 1}, [], [], date(2026, 1, 1), Rel(), rp.PARAMS_RUPTURA)
        self.assertFalse(out["vara"]["supera"])
        self.assertTrue(out["advertencias"][0].startswith("NO SUPERA LA VARA"))
        self.assertEqual(out["referencias"]["merval"]["operable"], False)
        self.assertTrue(out["referencias"]["merval"]["es_vara"])

    def test_sin_referencia_el_informe_lo_dice_y_no_inventa_una_vara(self):
        res, pa = self.correr({}, [])

        class Rel:
            fuente = "prueba"
            def ahora(self): return __import__("datetime").datetime(2026, 1, 1, tzinfo=bt.AR)
        out = gb.resultado_json(res, {"papeles": [pa], "especies": 1}, [], [], date(2026, 1, 1), Rel(), rp.PARAMS_RUPTURA)
        self.assertIsNone(out["vara"])
        self.assertTrue(any("No hay índice de referencia" in a for a in out["advertencias"]))


if __name__ == "__main__":
    unittest.main(verbosity=1)
