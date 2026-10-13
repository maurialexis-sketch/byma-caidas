"""Pruebas de la clasificación por sectores y su filtro:  python tests_sectores.py"""
import unittest
from datetime import date, timedelta

import sectores as sc

DATOS = sc.cargar()


class P:
    """Papel mínimo para las pruebas: ticker, tipo, fechas y monto promedio de 5 ruedas."""
    def __init__(self, ticker, tipo, monto5, inicio=date(2025, 7, 1)):
        self.ticker, self.tipo, self.monto5 = ticker, tipo, monto5
        self.f = [inicio + timedelta(days=i) for i in range(len(monto5))]


class Datos(unittest.TestCase):
    def test_la_taxonomia_es_la_pedida(self):
        self.assertEqual(sc.GRUPOS["Merval"], ("energeticas", "bancos", "otros"))
        self.assertEqual(sc.GRUPOS["CEDEAR"], ("energeticas", "tecnologicas", "ETF", "bancos", "alimentarias", "otros"))
        self.assertEqual(sc.SUBSECTORES["tecnologicas"], ("IA", "computadoras", "satelites", "otras"))

    def test_cada_papel_clasificado_usa_una_categoria_valida(self):
        for t, e in DATOS["papeles"].items():
            self.assertIn(e["sector"], sc.GRUPOS[e["grupo"]], t)
            if e["sector"] == "tecnologicas":
                self.assertIn(e["subsector"], sc.SUBSECTORES["tecnologicas"], t)
            else:
                self.assertNotIn("subsector", e, t)

    def test_las_variantes_apuntan_a_una_empresa_clasificada_y_no_se_clasifican_dos_veces(self):
        for v, base in DATOS["subyacente"].items():
            self.assertIn(base, DATOS["papeles"], v)
            self.assertNotIn(v, DATOS["papeles"], v)


class Etiquetas(unittest.TestCase):
    def test_etiquetas_conocidas(self):
        e = sc.etiquetar("GGAL", "accion", DATOS); self.assertEqual((e["grupo"], e["sector"], e["clasificado"]), ("Merval", "bancos", True))
        e = sc.etiquetar("NVDA", "cedear", DATOS); self.assertEqual((e["grupo"], e["sector"], e["subsector"]), ("CEDEAR", "tecnologicas", "IA"))
        e = sc.etiquetar("SATL", "cedear", DATOS); self.assertEqual((e["sector"], e["subsector"]), ("tecnologicas", "satelites"))
        e = sc.etiquetar("SPY", "cedear", DATOS); self.assertEqual(e["sector"], "ETF")
        e = sc.etiquetar("KO", "cedear", DATOS); self.assertEqual(e["sector"], "alimentarias")
        e = sc.etiquetar("VIST", "cedear", DATOS); self.assertEqual((e["grupo"], e["sector"]), ("CEDEAR", "energeticas"))   # el grupo sale del panel

    def test_una_variante_hereda_la_etiqueta_de_su_empresa(self):
        e = sc.etiquetar("AAPLB", "cedear", DATOS)
        self.assertEqual((e["sector"], e["subsector"], e["subyacente"]), ("tecnologicas", "computadoras", "AAPL"))
        self.assertEqual(sc.etiquetar("GGALB", "accion", DATOS)["subyacente"], "GGAL")

    def test_lo_desconocido_queda_sin_clasificar_pero_con_grupo(self):
        e = sc.etiquetar("ZZZZ", "cedear", DATOS)
        self.assertEqual((e["grupo"], e["sector"], e["clasificado"]), ("CEDEAR", "sin_clasificar", False))
        self.assertEqual(sc.etiquetar("ZZZZ", "accion", DATOS)["grupo"], "Merval")


class Filtro(unittest.TestCase):
    def setUp(self):
        self.pap = [P(t, "accion", [0]) for t in ("GGAL", "BMA", "YPFD", "ALUA")] + \
                   [P(t, "cedear", [0]) for t in ("NVDA", "AAPL", "AAPLB", "SATL", "SPY", "KO", "JPM", "XOM", "ZZZZ")]

    def t(self, **kw):
        return sorted(p.ticker for p in sc.filtrar(self.pap, datos=DATOS, **kw))

    def test_filtra_por_grupo_sector_y_subsector(self):
        self.assertEqual(self.t(grupo="Merval"), ["ALUA", "BMA", "GGAL", "YPFD"])
        self.assertEqual(self.t(grupo="Merval", sector="bancos"), ["BMA", "GGAL"])
        self.assertEqual(self.t(grupo="CEDEAR", sector="tecnologicas", subsector="IA"), ["NVDA"])
        self.assertEqual(self.t(grupo="CEDEAR", sector="tecnologicas", subsector="computadoras"), ["AAPL", "AAPLB"])   # incluye la variante
        self.assertEqual(self.t(sector="bancos"), ["BMA", "GGAL", "JPM"])                                                # cruza grupos
        self.assertEqual(self.t(sector="ETF"), ["SPY"])

    def test_no_distingue_mayusculas_ni_acentos(self):
        self.assertEqual(self.t(sector="Energéticas"), self.t(sector="energeticas"))
        self.assertEqual(self.t(sector="ENERGETICAS", grupo="cedear"), ["XOM"])
        self.assertEqual(self.t(sector="tecnológicas", subsector="SATÉLITES"), ["SATL"])

    def test_sin_filtro_devuelve_todo_y_sin_coincidencias_devuelve_vacio(self):
        self.assertEqual(len(self.t()), len(self.pap))
        self.assertEqual(self.t(sector="alimentarias", grupo="Merval"), [])
        self.assertEqual(self.t(sector="sin_clasificar"), ["ZZZZ"])


class Conteo(unittest.TestCase):
    def test_cuenta_especies_y_empresas_y_liquidez(self):
        piso = 1e9
        pap = [P("AAPL", "cedear", [2e9, 2e9, 2e9]),             # líquida hoy y siempre
               P("AAPLB", "cedear", [2e9, 2e9, 0.0]),            # variante: líquida antes, no hoy
               P("IBM", "cedear", [0.0, 0.0, 0.0]),              # computadoras, nunca líquida
               P("NVDA", "cedear", [2e9, 0.0, 2e9])]             # IA
        filas = {(f["grupo"], f["sector"], f["subsector"]): f for f in sc.contar(pap, piso, DATOS)}
        comp = filas[("CEDEAR", "tecnologicas", "computadoras")]
        self.assertEqual((comp["especies"], comp["empresas"]), (3, 2))                      # AAPL, AAPLB, IBM -> 2 empresas
        self.assertEqual((comp["liquidas_hoy"], comp["empresas_liquidas_hoy"]), (1, 1))     # solo AAPL hoy
        self.assertEqual((comp["liquidas_alguna_vez"], comp["empresas_liquidas_alguna_vez"]), (2, 1))   # AAPL y AAPLB: 1 empresa
        self.assertEqual(comp["promedio_diario"], 1.0)                                      # cada día hay 1 empresa líquida (AAPL)
        ia = filas[("CEDEAR", "tecnologicas", "IA")]
        self.assertAlmostEqual(ia["promedio_diario"], 2 / 3, places=2)                      # NVDA líquida 2 de 3 días

    def test_aparecen_todos_los_sectores_aunque_esten_vacios(self):
        filas = sc.contar([], 1e9, DATOS)
        claves = {(f["grupo"], f["sector"], f["subsector"]) for f in filas}
        self.assertIn(("CEDEAR", "alimentarias", None), claves)
        self.assertIn(("CEDEAR", "tecnologicas", "satelites"), claves)
        self.assertIn(("Merval", "bancos", None), claves)


if __name__ == "__main__":
    unittest.main(verbosity=1)
