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
P = {"rapido": 12, "lento": 26, "senal": 9, "dias": 2, "dist_pct": 0.5, "bajo_cero": False, "piso_millones": 1000}
ONDA = [100 + 10 * math.sin(k / 6.0) for k in range(300)]          # una onda: el MACD sube y baja alrededor de su señal
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


class Parametros(unittest.TestCase):
    def test_los_valores_de_fabrica_son_los_de_la_foto(self):
        self.assertEqual(pm.defectos(), {"macd_rapido": 12, "macd_lento": 26, "macd_senal": 9, "macd_dias": 2, "macd_dist_pct": 0.5, "macd_bajo_cero": 0, "macd_piso_millones": 1000})
        self.assertEqual(macd.de_params(pm.defectos()), P)

    def test_los_numeros_de_fabrica_no_estan_escritos_en_el_codigo(self):
        with open(os.path.join(AQUI, "macd.py"), encoding="utf-8") as f:
            codigo = f.read()
        self.assertNotRegex(re.sub(r'""".*?"""', "", codigo, flags=re.S), r"\b(12|26)\b")        # los períodos 12/26/9 viven en config_macd.json

    def test_validacion(self):
        self.assertEqual(pm.leer("macd_dist_pct", "0,8"), 0.8)
        self.assertEqual(pm.leer("macd_piso_millones", "2.000"), 2000)
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

    def test_programada_un_dia_sin_rueda_se_saltea_sin_fallar(self):
        self.correr(["--programado"], ahora=datetime(2026, 10, 14, 18, 0, tzinfo=AR))
        fn, r, etiqueta = self.guardados[0]
        self.assertEqual((fn, etiqueta), ("sanmarino", "SALTEADO")); self.assertTrue(r["salteado"]); self.assertIn("no hay datos de la rueda", r["motivo"])
        self.assertFalse(os.path.exists(self.pfile))

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


if __name__ == "__main__":
    unittest.main()
