"""Pruebas de la lógica sin red:  python tests.py"""
import json, os, tempfile, unittest
from datetime import datetime
import generar, reloj

AR = reloj.AR
def t(y, m, d, h, mi, s=0): return datetime(y, m, d, h, mi, s, tzinfo=AR)

class Cifrado(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(); self.meta = generar.cargar_meta(self.dir)
    def test_ida_y_vuelta(self):
        k = generar.derivar("una clave larga de prueba", self.meta)
        obj = {"papeles": [{"ticker": "GGAL", "caida_pct": -5.2}], "txt": "ñandú ⚠"}
        self.assertEqual(generar.descifrar(generar.cifrar(obj, k), k), obj)
    def test_clave_equivocada_no_descifra(self):
        k, mala = generar.derivar("una clave larga de prueba", self.meta), generar.derivar("otra clave distinta!!", self.meta)
        env = generar.cifrar({"x": 1}, k)
        with self.assertRaises(Exception): generar.descifrar(env, mala)
    def test_lo_publicado_no_contiene_el_texto(self):
        k = generar.derivar("una clave larga de prueba", self.meta)
        self.assertNotIn("GGAL", json.dumps(generar.cifrar({"ticker": "GGAL"}, k)))
    def test_iv_distinto_cada_vez(self):
        k = generar.derivar("una clave larga de prueba", self.meta)
        self.assertNotEqual(generar.cifrar({"a": 1}, k)["iv"], generar.cifrar({"a": 1}, k)["iv"])
    def test_la_sal_se_crea_una_vez(self):
        self.assertEqual(generar.cargar_meta(self.dir)["salt"], self.meta["salt"])
        self.assertEqual(self.meta["iter"], 600_000)

class Espera(unittest.TestCase):
    def test_espera_hasta_las_12(self):
        self.assertEqual(generar.segundos_para_ranura(t(2026, 10, 5, 11, 30), "compra"), 1800)
        self.assertEqual(generar.segundos_para_ranura(t(2026, 10, 5, 11, 59, 30), "compra"), 30)
    def test_si_ya_paso_no_espera(self):
        self.assertEqual(generar.segundos_para_ranura(t(2026, 10, 5, 12, 0, 1), "compra"), 0)   # el trabajo llegó tarde
        self.assertEqual(generar.segundos_para_ranura(t(2026, 10, 5, 12, 25), "compra"), 0)
    def test_no_espera_si_falta_mucho(self):
        self.assertEqual(generar.segundos_para_ranura(t(2026, 10, 5, 10, 0), "compra"), 0)       # 2 h antes
    def test_venta(self):
        self.assertEqual(generar.segundos_para_ranura(t(2026, 10, 5, 15, 20), "venta"), 1800)

class Indice(unittest.TestCase):
    def informe(self, hora): return {"contexto": {"hora_mercado": f"2026-10-05T{hora}:00-03:00"}}
    def test_historial_ordenado_y_sin_duplicar(self):
        d = tempfile.mkdtemp(); k = generar.derivar("una clave larga de prueba", generar.cargar_meta(d))
        generar.guardar("compra", self.informe("12:01:10"), k, d)
        generar.guardar("compra", self.informe("14:30:00"), k, d)
        generar.guardar("compra", self.informe("12:01:40"), k, d)          # mismo minuto: pisa el archivo
        ind = json.load(open(os.path.join(d, "indice.json"), encoding="utf-8"))
        self.assertEqual([e["hora"] for e in ind], ["14:30", "12:01"])
        self.assertEqual(ind[1]["archivo"], "2026-10-05-1201-compra.json")
        self.assertEqual(set(ind[0]), {"archivo", "fecha", "hora", "funcion"})   # el índice no revela resultados
    def test_hora_del_panel_sin_segundos_o_ilegible(self):
        datos = [{"fuente_precio": "panel 11:37"}, {"fuente_precio": "panel 11:20:15"}, {"fuente_precio": "panel basura"}, {"fuente_precio": "panel"}]
        self.assertEqual(generar.atraso_precios(datos, t(2026, 10, 5, 12, 1)), ("11:37:00", 24))
    def test_atraso_y_advertencias(self):
        datos = [{"fuente_precio": "panel 11:37:29", "alertas": []}, {"fuente_precio": "panel 11:20:00", "alertas": []}]
        self.assertEqual(generar.atraso_precios(datos, t(2026, 10, 5, 12, 1)), ("11:37:29", 24))
        viejos = [{"fuente_precio": "panel 11:00:00", "alertas": []}]
        self.assertTrue(any("atraso" in a for a in generar.advertencias(viejos, t(2026, 10, 5, 12, 0))))

if __name__ == "__main__":
    unittest.main(verbosity=1)
