"""Pruebas de la fuente de respaldo de datos (data912 + Yahoo) y de su conexión con el conector y los generadores (sin red):  python tests_respaldo.py"""
import ast, os, unittest
from datetime import datetime
from unittest import mock

import requests

import backtest as bt
import conector, fuente_respaldo as fr, generar_informe as gi

AQUI = os.path.dirname(os.path.abspath(__file__))


def fila(fecha, c, v=1000, o=None, h=None, l=None):
    return {"date": fecha, "o": o or c, "h": h or c, "l": l or c, "c": c, "v": v}


def vivo(**precios):
    return [{"symbol": s, "c": c, "v": 100.0} for s, c in precios.items()]


class UniversoYLineas(unittest.TestCase):
    def test_se_descartan_las_lineas_en_dolares(self):
        p = {"AAPL": 29740.0, "AAPLD": 20.5, "AAPLC": 20.4, "ALUA": 796.0, "ALUAD": 0.505}
        self.assertEqual([s for s in p if not fr.es_linea_en_dolares(s, p)], ["AAPL", "ALUA"])

    def test_un_papel_que_termina_en_d_o_c_sin_base_es_de_pesos(self):
        p = {"COME": 100.0, "BYMAD": 50.0}                      # 'BYMA' no está en la lista: BYMAD no es la versión en dólares de nadie
        self.assertFalse(fr.es_linea_en_dolares("BYMAD", p))
        self.assertFalse(fr.es_linea_en_dolares("COME", p))

    def test_una_linea_con_precio_parecido_al_de_la_base_es_otro_papel_en_pesos(self):
        self.assertFalse(fr.es_linea_en_dolares("XYZD", {"XYZ": 1000.0, "XYZD": 900.0}))

    def test_base_sin_precio_hace_dudar_y_se_descarta_la_linea(self):
        self.assertTrue(fr.es_linea_en_dolares("XYZD", {"XYZ": 0, "XYZD": 5.0}))

    def test_universo_arma_tipos_y_filtra(self):
        resp = {"/live/arg_stocks": vivo(GGAL=4857.5, GGALD=3.3), "/live/arg_cedears": vivo(AAPL=29740.0, AAPLD=20.5, AAPLC=20.4, KO=9000.0)}
        with mock.patch.object(fr, "_get", side_effect=lambda ruta: resp[ruta]):
            self.assertEqual(fr.universo(), {"GGAL": "accion", "AAPL": "cedear", "KO": "cedear"})
        self.assertEqual(fr.TIPOS["GGAL"], "accion")

    def test_universo_vacio_o_malformado_falla(self):
        with mock.patch.object(fr, "_get", return_value=[]):
            with self.assertRaises(ValueError):
                fr.universo()
        with mock.patch.object(fr, "_get", return_value={"Error": "x"}):
            with self.assertRaises(ValueError):
                fr.universo()


class Velas(unittest.TestCase):
    def test_formato_igual_al_de_byma_medianoche_argentina(self):
        v = fr._velas([fila("2026-11-17", 100, 50, o=99, h=101, l=98)], 400, None)
        self.assertEqual(v, [{"t": int(datetime(2026, 11, 17, tzinfo=bt.AR).timestamp()), "o": 99.0, "h": 101.0, "l": 98.0, "c": 100.0, "v": 50}])
        self.assertEqual(datetime.fromtimestamp(v[0]["t"], bt.AR).date().isoformat(), "2026-11-17")

    def test_descarta_velas_en_cero_y_filas_rotas_y_ordena(self):
        filas = [fila("2026-11-17", 10), fila("2026-11-16", 0), {"date": "no-es-fecha", "o": 1, "h": 1, "l": 1, "c": 1}, {"o": 1}, fila("2026-11-13", 9)]
        self.assertEqual([datetime.fromtimestamp(b["t"], bt.AR).date().isoformat() for b in fr._velas(filas, 400, None)], ["2026-11-13", "2026-11-17"])

    def test_se_queda_con_las_ultimas_n_dias_y_respeta_el_corte(self):
        filas = [fila("2024-01-02", 5), fila("2026-11-01", 6), fila("2026-11-17", 7)]
        self.assertEqual(len(fr._velas(filas, 400, None)), 2)
        corte = int(datetime(2026, 11, 17, tzinfo=bt.AR).timestamp())
        self.assertEqual([b["c"] for b in fr._velas(filas, 400, corte)], [6.0])               # el corte descarta la de ese día en adelante

    def test_el_salto_de_razon_entera_lo_trata_papel_como_split(self):
        filas = [fila(f"2026-11-{d:02d}", c) for d, c in ((2, 1000), (3, 1010), (4, 101), (5, 102))]       # 10:1 entre el 3 y el 4
        p = bt.Papel("X", "cedear", fr._velas(filas, 400, None))
        self.assertEqual(p.ajustes[0]["razon"], 10.0)
        self.assertAlmostEqual(p.c[0], 100.0, places=6)


class DosNiveles(unittest.TestCase):
    def setUp(self):
        fr.TIPOS.clear(); fr.TIPOS.update({"AAPL": "cedear", "NU": "cedear"})
        fr.ORIGEN.update({"data912": 0, "yahoo": 0})

    def test_usa_data912_si_lo_tiene(self):
        with mock.patch.object(fr, "_get", return_value=[fila("2026-11-17", 5)]), mock.patch.object(fr, "_yahoo", side_effect=AssertionError("no debía ir a Yahoo")):
            self.assertEqual(len(fr.get_daily_ohlc("AAPL")), 1)
        self.assertEqual(fr.ORIGEN, {"data912": 1, "yahoo": 0})

    def test_si_data912_no_lo_tiene_va_a_yahoo(self):
        with mock.patch.object(fr, "_get", return_value={"Error": "Nahh no tengo ese ticker loko"}), mock.patch.object(fr, "_yahoo", return_value=[fila("2026-11-17", 7)]):
            self.assertEqual(fr.get_daily_ohlc("NU")[0]["c"], 7.0)
        self.assertEqual(fr.ORIGEN, {"data912": 0, "yahoo": 1})

    def test_si_data912_se_cae_va_a_yahoo(self):
        with mock.patch.object(fr, "_get", side_effect=requests.ConnectionError("x")), mock.patch.object(fr, "_yahoo", return_value=[fila("2026-11-17", 7)]):
            self.assertEqual(len(fr.get_daily_ohlc("NU")), 1)

    def test_si_ninguna_lo_tiene_devuelve_vacio_y_si_ninguna_responde_falla(self):
        with mock.patch.object(fr, "_get", return_value={"Error": "x"}), mock.patch.object(fr, "_yahoo", return_value=[]):
            self.assertEqual(fr.get_daily_ohlc("NU"), [])
        with mock.patch.object(fr, "_get", return_value={"Error": "x"}), mock.patch.object(fr, "_yahoo", side_effect=requests.ConnectionError("x")):
            with self.assertRaises(requests.ConnectionError):
                fr.get_daily_ohlc("NU")

    def test_ticker_fuera_del_universo(self):
        with self.assertRaises(KeyError):
            fr.get_daily_ohlc("NOEXISTE")

    def test_rangos_de_yahoo(self):
        self.assertEqual([fr._rango_yahoo(d) for d in (16, 90, 400, 800)], ["1mo", "3mo", "2y", "5y"])


class ConexionConElConector(unittest.TestCase):
    def setUp(self):
        self.guardado = (conector.FUENTE, conector.USAR_RESPALDO, dict(conector.VELA_PANEL))
        conector.FUENTE = "byma"; conector.USAR_RESPALDO = True

    def tearDown(self):
        conector.FUENTE, conector.USAR_RESPALDO = self.guardado[0], self.guardado[1]
        conector.VELA_PANEL.clear(); conector.VELA_PANEL.update(self.guardado[2])

    def test_si_byma_responde_no_se_toca_el_respaldo(self):
        with mock.patch.object(conector, "_universo_byma", return_value={"GGAL": "accion"}), mock.patch.object(fr, "universo", side_effect=AssertionError("no debía usarse")):
            self.assertEqual(conector.universo(), {"GGAL": "accion"})
        self.assertEqual(conector.FUENTE, "byma")

    def test_si_byma_no_responde_pasa_al_respaldo_y_el_historico_sale_de_ahi(self):
        with mock.patch.object(conector, "_universo_byma", side_effect=requests.ConnectTimeout("x")), mock.patch.object(fr, "universo", return_value={"AAPL": "cedear"}), \
                mock.patch.object(conector, "log"):
            self.assertEqual(conector.universo(), {"AAPL": "cedear"})
        self.assertEqual(conector.FUENTE, "respaldo")
        with mock.patch.object(fr, "get_daily_ohlc", return_value=["velas"]) as g, mock.patch.object(conector, "_get", side_effect=AssertionError("no debía pedir a BYMA")):
            self.assertEqual(conector.get_daily_ohlc("AAPL", 400), ["velas"])
        g.assert_called_once_with("AAPL", 400, conector.CORTE_TS)

    def test_una_respuesta_que_no_es_json_tambien_activa_el_respaldo(self):
        with mock.patch.object(conector, "_universo_byma", side_effect=ValueError("no es json")), mock.patch.object(fr, "universo", return_value={"A": "cedear"}), mock.patch.object(conector, "log"):
            conector.universo()
        self.assertEqual(conector.FUENTE, "respaldo")

    def test_sin_permiso_de_respaldo_la_falla_sale_como_antes(self):
        conector.USAR_RESPALDO = False
        with mock.patch.object(conector, "_universo_byma", side_effect=requests.ConnectTimeout("x")):
            with self.assertRaises(requests.ConnectTimeout):
                conector.universo()
        self.assertEqual(conector.FUENTE, "byma")

    def test_si_tambien_falla_el_respaldo_la_excepcion_sale_y_no_se_cambia_de_fuente(self):
        with mock.patch.object(conector, "_universo_byma", side_effect=requests.ConnectTimeout("x")), mock.patch.object(fr, "universo", side_effect=requests.ConnectionError("y")), \
                mock.patch.object(conector, "log"):
            with self.assertRaises(requests.ConnectionError):
                conector.universo()
        self.assertEqual(conector.FUENTE, "byma")


class AvisoEnElInforme(unittest.TestCase):
    def tearDown(self):
        conector.FUENTE = "byma"

    def test_con_byma_no_hay_aviso(self):
        conector.FUENTE = "byma"; datos = {}
        self.assertEqual(gi.avisos_de_fuente(datos), []); self.assertEqual(datos, {})

    def test_con_respaldo_el_informe_lo_dice_con_los_conteos(self):
        conector.FUENTE = "respaldo"; datos = {}
        fr.ORIGEN.update({"data912": 216, "yahoo": 275})
        avisos = gi.avisos_de_fuente(datos)
        self.assertEqual(datos["fuente"], {"nombre": "respaldo", "data912": 216, "yahoo": 275})
        self.assertIn("BYMA no respondió", avisos[0]); self.assertIn("216", avisos[0]); self.assertIn("275", avisos[0])

    def test_los_generadores_no_piden_el_panel_de_byma_con_el_respaldo(self):
        for archivo in ("generar_informe.py", "generar_sanmarino.py"):
            src = open(os.path.join(AQUI, archivo), encoding="utf-8").read()
            self.assertIn('conector.FUENTE != "respaldo"', src, archivo)
            self.assertIn("avisos_de_fuente(datos)", src, archivo)


class Estructura(unittest.TestCase):
    def test_el_respaldo_no_importa_el_conector_ni_backtest(self):          # evita un import circular (backtest importa conector)
        arbol = ast.parse(open(os.path.join(AQUI, "fuente_respaldo.py"), encoding="utf-8").read())
        modulos = {n.names[0].name for n in ast.walk(arbol) if isinstance(n, ast.Import)} | {n.module for n in ast.walk(arbol) if isinstance(n, ast.ImportFrom)}
        self.assertFalse({"conector", "backtest", "config"} & modulos)

    def test_los_workflows_de_informe_y_san_marino_corren_estas_pruebas(self):
        for wf in ("informe.yml", "sanmarino.yml"):
            self.assertIn("python tests_respaldo.py", open(os.path.join(AQUI, ".github", "workflows", wf), encoding="utf-8").read(), wf)


class PublicacionDeLaPagina(unittest.TestCase):
    def test_todos_los_workflows_reintentan_si_falla_el_despliegue_de_la_pagina(self):
        """GitHub falló al leer el artefacto de la página el 18/11 y el 20/11 (el informe quedaba guardado pero no se veía): cada despliegue se reintenta una vez."""
        carpeta = os.path.join(AQUI, ".github", "workflows")
        for nombre in sorted(os.listdir(carpeta)):
            with open(os.path.join(carpeta, nombre), encoding="utf-8") as f:
                t = f.read()
            if "deploy-pages" not in t:
                continue
            self.assertEqual(t.count("actions/deploy-pages@v4"), 2, nombre)                       # el intento y el reintento
            self.assertIn("continue-on-error: true", t, nombre)                                    # el primero puede fallar sin tirar el trabajo
            self.assertIn("if: steps.d.outcome == 'failure'", t, nombre)                           # el reintento solo corre si el primero falló
            self.assertIn("steps.d.outputs.page_url || steps.d2.outputs.page_url", t, nombre)


if __name__ == "__main__":
    unittest.main(verbosity=1)
