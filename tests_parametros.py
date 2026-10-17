"""Pruebas de los parámetros editables y de la corrida programada del informe:  python tests_parametros.py"""
import json, math, os, re, sys, tempfile, unittest
from datetime import date, datetime, timedelta
from unittest import mock

import requests

import backtest as bt
import generar_informe as gi
import informe as inf
import parametros as pa
from tests_backtest import barras, N
from tests_informe import dos_regimenes, SUBE

AR = bt.AR


class Validacion(unittest.TestCase):
    def test_los_valores_de_fabrica_son_los_de_hoy(self):
        self.assertEqual(pa.defectos(), {"piso_millones": 1000, "media_ruedas": 200, "recorrido_min_pct": 10, "rb_min": 2, "bb_periodo": 20, "bb_desvios": 2, "bb_dias": 3,
                                         "bb_ventana": 10, "bb_magnitud_pct": 1, "bb_periodo_listas": 20, "bb_ventana_listas": 7, "bb_velas_caida": 5, "bb_velas_giro": 2, "bb_peso1": 1, "bb_peso2": 1, "bb_peso3": 1, "bb_stop": 1})
        p = pa.a_params(pa.defectos())
        self.assertEqual((p["piso_monto"], p["ma_larga"], p["ma_corta"], p["recorrido_min"], p["rb_min"]), (1_000_000_000, 200, 150, 0.10, 2.0))

    def test_acepta_coma_decimal_y_punto_de_miles_en_los_enteros(self):
        self.assertEqual(pa.leer("recorrido_min_pct", "12,5"), 12.5)
        self.assertEqual(pa.leer("rb_min", "1.5"), 1.5)
        self.assertEqual(pa.leer("piso_millones", "1.000"), 1000)           # mil, no uno
        self.assertEqual(pa.leer("piso_millones", "2500"), 2500)
        self.assertEqual(pa.leer("media_ruedas", 150), 150)

    def test_valores_invalidos_se_rechazan_sin_corregirlos(self):
        for clave, malo in (("piso_millones", "0"), ("piso_millones", "mil"), ("piso_millones", "1,5"), ("media_ruedas", "10"), ("media_ruedas", "500"),
                            ("media_ruedas", "200,5"), ("recorrido_min_pct", "0"), ("recorrido_min_pct", "150"), ("recorrido_min_pct", "-5"),
                            ("rb_min", "0"), ("rb_min", "50"), ("rb_min", "dos"), ("rb_min", "NaN"), ("rb_min", True)):
            with self.assertRaises(pa.ErrorParametro, msg=f"{clave}={malo!r}"):
                pa.leer(clave, malo)

    def test_los_parametros_de_estructura_no_se_pueden_editar(self):
        for clave in ("ventana_ruedas", "min_toques", "tol_zona", "stop_buffer", "ruedas_liquidez"):
            with self.assertRaises(pa.ErrorParametro):
                pa.leer(clave, 5)
        with self.assertRaises(pa.ErrorParametro):
            pa.combinar(pa.defectos(), {"ventana_ruedas": "100"})
        p = pa.a_params({**pa.defectos(), "media_ruedas": 100, "rb_min": 3})                 # cambiar los editables no toca la estructura
        for k in ("ventana_ruedas", "k_pivote", "min_toques", "tol_zona", "stop_buffer", "ruedas_liquidez"):
            self.assertEqual(p[k], bt.PARAMS[k])

    def test_combinar_deja_lo_guardado_si_no_se_pide_nada(self):
        g = {"piso_millones": 2000, "media_ruedas": 150, "recorrido_min_pct": 8, "rb_min": 1.5}
        v, cambios = pa.combinar(g, {"piso_millones": "", "media_ruedas": None, "recorrido_min_pct": "", "rb_min": ""})
        self.assertEqual((v, cambios), (g, {}))
        v, cambios = pa.combinar(g, {"rb_min": "3", "piso_millones": "2.000"})
        self.assertEqual(v["rb_min"], 3); self.assertEqual(v["piso_millones"], 2000)
        self.assertEqual(cambios, {"rb_min": (1.5, 3)})                                      # pedir lo mismo no es un cambio

    def test_guardar_y_cargar(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "parametros.json")
            self.assertEqual(pa.cargar(ruta), pa.defectos())                                # sin archivo: valores de fábrica
            nuevos = {**pa.defectos(), "piso_millones": 3000, "media_ruedas": 100, "recorrido_min_pct": 7.5, "rb_min": 1.2, "bb_dias": 4, "bb_ventana": 12, "bb_stop": 0}
            pa.guardar(nuevos, ruta)
            self.assertEqual(pa.cargar(ruta), nuevos)
            with open(ruta, "w", encoding="utf-8") as f:
                json.dump({"rb_min": 999}, f)
            with self.assertRaises(pa.ErrorParametro) as c:
                pa.cargar(ruta)
            self.assertIn("inválidos", str(c.exception))                                    # un archivo roto avisa, no se corrige solo
            with self.assertRaises(pa.ErrorParametro):
                pa.guardar({**pa.defectos(), "rb_min": 0}, ruta)                            # y no se guarda nada inválido

    def test_los_parametros_de_bollinger_tienen_rango_y_reglas_cruzadas(self):
        for clave, malo in (("bb_periodo", "2"), ("bb_periodo", "500"), ("bb_desvios", "0"), ("bb_desvios", "9"), ("bb_dias", "0"), ("bb_dias", "11"), ("bb_ventana", "2"),
                            ("bb_magnitud_pct", "-1"), ("bb_magnitud_pct", "50"), ("bb_peso1", "-1"), ("bb_peso1", "1,5"), ("bb_stop", "2"), ("bb_velas_caida", "1"), ("bb_velas_caida", "31"), ("bb_velas_giro", "0"), ("bb_velas_giro", "11"), ("bb_periodo_listas", "1"), ("bb_periodo_listas", "101"), ("bb_ventana_listas", "2"), ("bb_ventana_listas", "61")):
            with self.assertRaises(pa.ErrorParametro, msg=f"{clave}={malo!r}"):
                pa.leer(clave, malo)
        self.assertEqual(pa.leer("bb_desvios", "2,5"), 2.5)
        with self.assertRaises(pa.ErrorParametro) as c:
            pa.validar({**pa.defectos(), "bb_dias": 6, "bb_ventana": 10})                  # la bajada y el giro (6 + 6) no entran en 10 ruedas
        self.assertIn("doble", str(c.exception))
        self.assertEqual(pa.validar({**pa.defectos(), "bb_dias": 5, "bb_ventana": 10})["bb_dias"], 5)
        with self.assertRaises(pa.ErrorParametro):
            pa.validar({**pa.defectos(), "bb_peso1": 0, "bb_peso2": 0, "bb_peso3": 0})        # ningún tramo con peso

    def test_la_salida_de_bollinger_viaja_como_una_sola_entrada(self):
        self.assertEqual(pa.parsear_salida(""), {})
        self.assertEqual(pa.parsear_salida("2,1,1,no"), {"bb_peso1": "2", "bb_peso2": "1", "bb_peso3": "1", "bb_stop": "0"})
        self.assertEqual(pa.parsear_salida("1,1,1,1,7,3"), {"bb_peso1": "1", "bb_peso2": "1", "bb_peso3": "1", "bb_stop": "1", "bb_velas_caida": "7", "bb_velas_giro": "3"})
        self.assertEqual(pa.parsear_salida("1,1,1,1,7,3,9")["bb_periodo_listas"], "9")
        self.assertEqual(pa.parsear_salida("1,1,1,1,5,2,20,9")["bb_ventana_listas"], "9")
        self.assertEqual(pa.parsear_salida("1;1;1;si")["bb_stop"], "1")
        v, cambios = pa.combinar(pa.defectos(), pa.parsear_salida("3,2,1,0"))
        self.assertEqual((v["bb_peso1"], v["bb_peso2"], v["bb_peso3"], v["bb_stop"]), (3, 2, 1, 0)); self.assertEqual(len(cambios), 3)                                  # el peso 3 queda igual: pedir lo mismo no es un cambio
        with self.assertRaises(pa.ErrorParametro):
            pa.parsear_salida("1,1,1")
        with self.assertRaises(pa.ErrorParametro):
            pa.parsear_salida("1,1,1,1,5")

    def test_la_ventana_de_los_listados_tiene_que_alcanzar_para_las_caidas_y_la_levantada(self):
        with self.assertRaises(pa.ErrorParametro) as c:
            pa.validar({**pa.defectos(), "bb_ventana_listas": 6})                       # 5 caídas + 2 levantadas no entran en 6
        self.assertIn("ventana", str(c.exception))
        self.assertEqual(pa.validar({**pa.defectos(), "bb_ventana_listas": 7})["bb_ventana_listas"], 7)
        self.assertEqual(pa.validar({**pa.defectos(), "bb_velas_caida": 4, "bb_ventana_listas": 6})["bb_velas_caida"], 4)

    def test_los_parametros_de_bollinger_llegan_al_motor(self):
        bp = pa.bollinger_de({**pa.defectos(), "bb_peso1": 2, "bb_stop": 0, "bb_desvios": 2.5})
        self.assertEqual(bp, {"bb_periodo": 20, "bb_desvios": 2.5, "bb_dias": 3, "bb_ventana": 10, "bb_magnitud_pct": 1.0, "bb_pesos": [2, 1, 1], "bb_stop": False,
                              "bb_velas_caida": 5, "bb_velas_giro": 2, "bb_periodo_listas": 20, "bb_ventana_listas": 7})
        p = pa.a_params(pa.defectos())
        self.assertEqual((p["bb_periodo"], p["bb_pesos"], p["bb_stop"]), (20, [1, 1, 1], True))
        self.assertEqual(p["ventana_ruedas"], bt.PARAMS["ventana_ruedas"])                  # el informe sigue con la ventana de 8 meses de los niveles

    def test_la_descripcion_marca_lo_que_cambio(self):
        d = pa.descripcion({**pa.defectos(), "rb_min": 3})
        self.assertEqual([e["clave"] for e in d["editables"] if e["cambiado"]], ["rb_min"])
        self.assertTrue(any("168" in f["valor"] for f in d["fijos"]))


class ConParametros(unittest.TestCase):
    """Los cuatro valores cambian de verdad el resultado (y los textos del informe)."""
    def correr(self, **cambios):
        v = {**pa.defectos(), **cambios}
        return inf.candidatos([dos_regimenes()], None, pa.a_params(v))

    def test_con_los_de_fabrica_el_resultado_es_el_de_siempre(self):
        self.assertEqual(self.correr()["total_candidatos"], 1)
        self.assertEqual(inf.candidatos([dos_regimenes()])["candidatos"][0]["rr"], self.correr()["candidatos"][0]["rr"])

    def test_un_piso_de_liquidez_mas_alto_deja_afuera_al_papel(self):
        self.assertEqual(self.correr(piso_millones=1000)["liquidos"], 1)
        r = self.correr(piso_millones=100000)
        self.assertEqual((r["liquidos"], r["total_candidatos"]), (0, 0))
        self.assertIn("100.000 M", r["embudo"][0]["nombre"])

    def test_una_media_mas_larga_que_el_historico_saca_la_tendencia(self):
        self.assertEqual(self.correr(media_ruedas=50)["total_candidatos"], 1)
        r = self.correr(media_ruedas=400)                                                   # el papel tiene ~205 ruedas: no hay media de 400 ni de 300
        self.assertEqual(r["total_candidatos"], 0)
        self.assertIn("media de 400", r["embudo"][1]["nombre"])

    def test_un_recorrido_minimo_mayor_deja_la_senal_como_cercana(self):
        base = self.correr()["candidatos"][0]["recorrido_pct"]
        r = self.correr(recorrido_min_pct=base + 5)
        self.assertEqual(r["total_candidatos"], 0)
        self.assertEqual(r["cercanos"][0]["motivo"], f"recorrido menor a {(base + 5):g}%".replace(".", ","))
        self.assertTrue(self.correr(recorrido_min_pct=max(1, base - 1))["total_candidatos"] == 1)

    def test_un_rb_minimo_mayor_deja_la_senal_como_cercana(self):
        rr = self.correr()["candidatos"][0]["rr"]
        r = self.correr(rb_min=math.ceil(rr) + 1)
        self.assertEqual(r["total_candidatos"], 0)
        self.assertTrue(r["cercanos"][0]["motivo"].startswith("R/B menor a"))

    def test_el_filtro_no_se_afloja_si_el_valor_queda_justo_en_el_limite(self):
        c = self.correr()["candidatos"][0]
        self.assertEqual(self.correr(recorrido_min_pct=c["recorrido_pct"] - 0.0001)["total_candidatos"], 1)
        self.assertEqual(self.correr(recorrido_min_pct=c["recorrido_pct"] + 0.01)["total_candidatos"], 0)


class Salteo(unittest.TestCase):
    MARTES = datetime(2026, 10, 13, 18, 0, tzinfo=AR)

    def motivo(self, ahora=None, ref=date(2026, 10, 13), esp=100, con=95, vol=1.0):
        return gi.motivo_de_salteo(ahora or self.MARTES, ref, esp, con, vol)

    def test_dia_normal_no_se_saltea(self):
        self.assertIsNone(self.motivo())

    def test_dia_sin_rueda_se_saltea_y_dice_cual_fue_la_ultima(self):
        m = self.motivo(ref=date(2026, 10, 12))
        self.assertIn("feriado", m); self.assertIn("12/10/2026", m)

    def test_otros_motivos(self):
        self.assertIn("fuera de la hora", self.motivo(ahora=datetime(2026, 10, 13, 16, 0, tzinfo=AR)))
        self.assertIn("fuera de la hora", self.motivo(ahora=datetime(2026, 10, 17, 18, 0, tzinfo=AR)))      # sábado
        self.assertIn("no devolvió datos", self.motivo(ref=None))
        self.assertIn("solo 40 de 100", self.motivo(con=40))
        self.assertIn("incompleta", self.motivo(vol=0.2))

    def test_el_registro_de_salteo(self):
        class Rel:
            fuente = "prueba"
            def ahora(self): return TestMain.MARTES
        out = gi.armar_salteado("motivo X", Rel(), pa.defectos(), date(2026, 10, 12))
        self.assertTrue(out["salteado"]); self.assertEqual(out["motivo"], "motivo X"); self.assertEqual(out["fecha_datos"], "2026-10-12")
        self.assertEqual(out["contexto"]["origen"], "programada"); self.assertIn("editables", out["parametros"])


class Pagina(unittest.TestCase):
    """La página repite los valores y rangos de los cuatro editables (para validar antes de lanzar): tienen que ser los de parametros.py."""
    def setUp(self):
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "index.html"), encoding="utf-8") as f:
            self.html = f.read()

    def test_los_editables_de_la_pagina_son_los_de_parametros_py(self):
        i = self.html.index("var PDEF=") + len("var PDEF=")
        pdef = json.loads(self.html[i:self.html.index("];", i) + 1])
        self.assertEqual([(p["k"], p["def"], p["min"], p["max"], p["ent"]) for p in pdef],
                         [(e["clave"], e["defecto"], e["minimo"], e["maximo"], e["entero"]) for e in pa.EDITABLES])

    def test_la_estructura_no_se_puede_editar_desde_la_pagina(self):
        for fijo in ("ventana_ruedas", "min_toques", "tol_zona", "stop_buffer", "k_pivote"):
            self.assertNotIn(fijo, self.html)

    def test_los_nombres_de_entradas_del_workflow_son_los_de_la_pagina(self):
        base = os.path.dirname(os.path.abspath(__file__))
        i = self.html.index("var PDEF=") + len("var PDEF=")
        pdef = json.loads(self.html[i:self.html.index("];", i) + 1])
        wfs = {p["wf"] for p in pdef}
        self.assertEqual(sorted(p["pos"] for p in pdef if p.get("pos") is not None), [0, 1, 2, 3, 4, 5, 6, 7])        # peso1, peso2, peso3, stop, las velas, el período y la ventana de los listados viajan juntos en bb_otros
        for nombre in ("informe", "backtest"):
            with open(os.path.join(base, ".github", "workflows", nombre + ".yml"), encoding="utf-8") as f:
                wf = f.read()
            entradas = re.findall(r"(?m)^      (\w+):\s*\n\s+description", wf)
            self.assertLessEqual(len(entradas), 10, nombre)                                                  # tope de entradas de workflow_dispatch
            for w in wfs if nombre == "informe" else {x for x in wfs if x.startswith("bb_")}:
                self.assertIn(w, entradas, f"{nombre}: falta la entrada {w}")
        self.assertIn("inputsWorkflow", self.html)
        with open(os.path.join(base, ".github", "workflows", "informe.yml"), encoding="utf-8") as f:
            self.assertIn("cron: '0 21 * * 1-5'", f.read())                                                  # 18:00 de Argentina, lunes a viernes


class RelojFalso:
    fuente = "reloj de prueba"
    def __init__(self, ahora): self._a = ahora
    def sincronizar(self): pass
    def epoch(self): return self._a.timestamp()
    def ahora(self): return self._a


class TestMain(unittest.TestCase):
    """main() de punta a punta con BYMA y el reloj reemplazados (sin red)."""
    MARTES = datetime(2026, 10, 13, 18, 0, tzinfo=AR)

    def setUp(self):
        n = N + len(SUBE) + 1
        ini = (self.MARTES.date() - timedelta(days=n - 1))
        cierres = [140 + 20 * math.sin(k / 3.2) if k < 70 else 115 + 15 * math.sin(k / 3.2) for k in range(N)] + SUBE + [132.0]
        self.barras = {"T": barras(cierres, inicio=ini, v=5e7)}                              # la última vela es la del martes 13/10
        self.dir = tempfile.TemporaryDirectory(); self.addCleanup(self.dir.cleanup)
        self.pfile = os.path.join(self.dir.name, "parametros.json")
        self.guardados = []
        self.env = mock.patch.dict(os.environ, {"CLAVE_ACCESO": "una-clave-de-prueba-bien-larga"}); self.env.start(); self.addCleanup(self.env.stop)

    def correr(self, args, ahora=None, universo=None, error_universo=None):
        ahora = ahora or self.MARTES
        def uni():
            if error_universo:
                raise error_universo
            return universo if universo is not None else {"T": "cedear"}
        def guardar(fn, r, key, carpeta=None, etiqueta=None):
            self.guardados.append((fn, r, etiqueta)); return "archivo.json"
        patches = [mock.patch.object(gi.reloj, "Reloj", lambda: RelojFalso(ahora)), mock.patch.object(gi.conector, "universo", uni),
                   mock.patch.object(gi.gb, "bajar_historico", lambda e, c=None: (self.barras, [])), mock.patch.object(gi, "filas_panel", lambda: {}),
                   mock.patch.object(gi.indices, "bajar_todos", lambda b, h=None: {"merval": None, "sp500_usd": None, "sp500_ars": None}),
                   mock.patch.object(gi.generar, "guardar", guardar), mock.patch.object(gi.generar, "derivar", lambda c, m: "k"),
                   mock.patch.object(gi.generar, "cargar_meta", lambda: {}), mock.patch.object(gi, "anotar", lambda t, n="warning": None),
                   mock.patch.object(sys, "argv", ["generar_informe.py", "--parametros", self.pfile] + args)]
        for p in patches: p.start()
        try:
            gi.main()
        finally:
            for p in patches: p.stop()

    def test_corrida_programada_normal_publica_el_informe(self):
        self.correr(["--programado"])
        fn, r, etiqueta = self.guardados[0]
        self.assertIsNone(etiqueta); self.assertFalse(r.get("salteado"))
        self.assertEqual(r["contexto"]["origen"], "programada"); self.assertEqual(r["total_candidatos"], 1)
        self.assertEqual({e["clave"]: e["valor"] for e in r["parametros"]["editables"]}, pa.defectos())
        self.assertEqual({e["clave"]: e["grupo"] for e in r["parametros"]["editables"]}["bb_stop"], "bollinger")

    def test_programada_un_dia_sin_rueda_se_saltea_sin_fallar(self):
        miercoles = datetime(2026, 10, 14, 18, 0, tzinfo=AR)                                # BYMA no trae la rueda del 14: feriado o sin publicar
        self.correr(["--programado"], ahora=miercoles)                                      # no levanta excepciones
        fn, r, etiqueta = self.guardados[0]
        self.assertEqual(etiqueta, "SALTEADO"); self.assertTrue(r["salteado"]); self.assertIn("no hay datos de la rueda", r["motivo"])
        self.assertFalse(os.path.exists(self.pfile))                                        # un salteo no toca los parámetros guardados

    def test_programada_con_byma_caida_se_saltea_sin_fallar(self):
        self.correr(["--programado"], error_universo=requests.ConnectionError("sin red"))
        self.assertEqual(self.guardados[0][2], "SALTEADO"); self.assertIn("universo", self.guardados[0][1]["motivo"])
        self.correr(["--programado"], universo={})
        self.assertEqual(self.guardados[1][2], "SALTEADO")

    def test_manual_con_byma_caida_si_falla(self):
        with self.assertRaises(requests.ConnectionError):
            self.correr([], error_universo=requests.ConnectionError("sin red"))
        self.assertEqual(self.guardados, [])

    def test_manual_en_dia_sin_rueda_publica_con_aviso(self):
        miercoles = datetime(2026, 10, 14, 18, 0, tzinfo=AR)
        self.correr([], ahora=miercoles)
        r = self.guardados[0][1]
        self.assertFalse(r.get("salteado")); self.assertTrue(any("BYMA todavía no la publicó" in x for x in r["avisos"]))

    def test_los_parametros_pedidos_se_usan_y_quedan_guardados(self):
        self.correr(["--piso", "2.000", "--rb", "2,5"])
        r = self.guardados[0][1]
        v = {e["clave"]: e["valor"] for e in r["parametros"]["editables"]}
        self.assertEqual((v["piso_millones"], v["rb_min"], v["media_ruedas"]), (2000, 2.5, 200))
        self.assertEqual(len(r["parametros"]["cambios"]), 2)
        self.assertIn("2.000 M", r["filtros"][0]["nombre"])
        self.assertEqual(pa.cargar(self.pfile), {**pa.defectos(), "piso_millones": 2000, "rb_min": 2.5})
        # la corrida siguiente (p. ej. la programada de las 18:00) parte de lo guardado
        self.correr(["--programado"])
        v2 = {e["clave"]: e["valor"] for e in self.guardados[1][1]["parametros"]["editables"]}
        self.assertEqual(v2, {**pa.defectos(), "piso_millones": 2000, "rb_min": 2.5})
        self.assertEqual(self.guardados[1][1]["parametros"]["cambios"], [])

    def test_los_parametros_de_bollinger_se_piden_y_se_guardan_desde_el_informe(self):
        self.correr(["--bb-periodo", "10", "--bb-desvios", "2,5", "--bb-dias", "2", "--bb-ventana", "8", "--bb-magnitud", "0,5", "--bb-otros", "2,1,1,0,7,3,12,10"])
        r = self.guardados[0][1]
        v = {e["clave"]: e["valor"] for e in r["parametros"]["editables"]}
        self.assertEqual((v["bb_periodo"], v["bb_desvios"], v["bb_dias"], v["bb_ventana"], v["bb_magnitud_pct"], v["bb_peso1"], v["bb_stop"]), (10, 2.5, 2, 8, 0.5, 2, 0))
        self.assertEqual((v["bb_velas_caida"], v["bb_velas_giro"], v["bb_periodo_listas"]), (7, 3, 12))
        self.assertEqual(v["bb_ventana_listas"], 10)
        self.assertEqual(pa.cargar(self.pfile)["bb_periodo"], 10)
        self.assertTrue(any("Bollinger" in x for x in r["parametros"]["cambios"]))

    def test_un_parametro_invalido_frena_la_corrida_y_no_guarda_nada(self):
        for malo in (["--rb", "0"], ["--media", "5"], ["--piso", "abc"], ["--recorrido", "500"], ["--bb-dias", "7"], ["--bb-otros", "1,1"], ["--bb-desvios", "0"]):
            with self.assertRaises(SystemExit) as c:
                self.correr(malo)
            self.assertIn("Parámetros inválidos", str(c.exception))
        self.assertEqual(self.guardados, []); self.assertFalse(os.path.exists(self.pfile))

    def test_si_se_pide_un_cambio_pero_la_corrida_se_saltea_no_se_guarda(self):
        self.correr(["--programado", "--rb", "3"], ahora=datetime(2026, 10, 14, 18, 0, tzinfo=AR))
        self.assertEqual(self.guardados[0][2], "SALTEADO"); self.assertFalse(os.path.exists(self.pfile))


if __name__ == "__main__":
    unittest.main()
