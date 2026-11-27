"""Pruebas de SAINT MARINO DÓLAR (universo del PDF, datos de Nueva York, calendario, parámetros propios, corrida de punta a punta, workflow y página):  python tests_dolar.py"""
import ast, json, math, os, re, sys, tempfile, unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock

import requests

import backtest as bt
import fuente_ny as ny
import generar_backtest as gb
import generar_backtest_dolar as gbd
import generar_sanmarino_dolar as gd
import sanmarino_bt as sb
import macd
import parametros_macd as pm
import parametros_macd_dolar as pd
from tests_backtest import barras
from tests_macd import ONDA, SUAVE, RelojFalso, barras_v

AQUI = os.path.dirname(os.path.abspath(__file__))
AR = bt.AR
UTC = timezone.utc


def leer(*ruta):
    with open(os.path.join(AQUI, *ruta), encoding="utf-8") as f:
        return f.read()


class Universo(unittest.TestCase):
    def setUp(self):
        self.items = ny.universo()

    def test_el_archivo_del_pdf_esta_completo_y_sin_repetidos(self):
        self.assertEqual(len(self.items), 269)
        self.assertEqual(sum(len(e["simbolos"]) for e in self.items), 272)                                  # las 272 líneas en dólares del PDF
        self.assertEqual(len({e["yahoo"] for e in self.items}), 269)
        for e in self.items:
            self.assertRegex(e["yahoo"], r"^[A-Z0-9]{1,6}(-[A-Z])?$", e)
            self.assertTrue(e["nombre"] and e["simbolos"], e)

    def test_las_lineas_son_las_de_dolares_y_cada_ticker_corresponde_a_su_linea(self):
        for e in self.items:
            for s in e["simbolos"]:
                self.assertTrue(s.endswith("D") or s == "GLDDB", s)
        por = {e["yahoo"]: e["simbolos"] for e in self.items}
        for yahoo, linea in (("AAPL", "AAPLD"), ("BRK-B", "BRKBD"), ("GOOGL", "GOGLD"), ("TS", "TEND"), ("TX", "TXRD"), ("WB", "WBOD"), ("PBR", "PETRD"), ("BAC", "BA.CD"), ("B", "B.D"), ("KO", "KOD")):
            self.assertIn(linea, por[yahoo], yahoo)
        self.assertEqual(sorted(por["BBD"]), ["BBDCD", "BBDD"])                                             # dos líneas, un solo subyacente: se evalúa una vez

    def test_los_emparejamientos_que_no_coincidian_se_corrigieron(self):
        for malo in ("ALA", "BBDC", "GOGL", "TEN", "TXR", "WBO", "ADGO", "BNG", "BRKB", "DISN", "PETR"):
            self.assertNotIn(malo, {e["yahoo"] for e in self.items}, malo)

    def test_un_archivo_con_repetidos_o_incompleto_se_rechaza(self):
        for items in ([{"yahoo": "A", "nombre": "a", "simbolos": ["AD"]}, {"yahoo": "A", "nombre": "a", "simbolos": ["AD"]}], [{"yahoo": "A", "nombre": "a", "simbolos": []}]):
            with tempfile.TemporaryDirectory() as d:
                ruta = os.path.join(d, "u.json")
                with open(ruta, "w", encoding="utf-8") as f:
                    json.dump({"items": items}, f)
                with self.assertRaises(ValueError):
                    ny.universo(ruta)


class CalendarioNY(unittest.TestCase):
    def test_horario_de_verano_de_eeuu(self):
        self.assertFalse(ny.en_horario_de_verano(datetime(2026, 3, 8, 6, 59, tzinfo=UTC)))
        self.assertTrue(ny.en_horario_de_verano(datetime(2026, 3, 8, 7, 0, tzinfo=UTC)))                 # 2.º domingo de marzo, 2:00
        self.assertTrue(ny.en_horario_de_verano(datetime(2026, 11, 1, 5, 59, tzinfo=UTC)))
        self.assertFalse(ny.en_horario_de_verano(datetime(2026, 11, 1, 6, 0, tzinfo=UTC)))               # 1.er domingo de noviembre, 2:00
        self.assertTrue(ny.en_horario_de_verano(datetime(2026, 7, 1, tzinfo=UTC)))
        self.assertFalse(ny.en_horario_de_verano(datetime(2026, 1, 15, tzinfo=UTC)))

    def test_hora_de_nueva_york(self):
        self.assertEqual(ny.hora_ny(datetime(2026, 11, 26, 22, 36, tzinfo=AR)).strftime("%d/%m %H:%M"), "26/11 20:36")        # invierno: UTC-5 (Argentina UTC-3)
        self.assertEqual(ny.hora_ny(datetime(2026, 10, 13, 18, 0, tzinfo=AR)).strftime("%d/%m %H:%M"), "13/10 17:00")        # verano: UTC-4

    def test_sesion_y_rueda_esperada(self):
        h = lambda dia, hh, mm: datetime(2026, 10, dia, hh, mm, tzinfo=timezone(timedelta(hours=-4)))
        self.assertFalse(ny.sesion_cerrada_ny(h(14, 16, 29))); self.assertTrue(ny.sesion_cerrada_ny(h(14, 16, 30)))
        self.assertFalse(ny.sesion_cerrada_ny(h(17, 20, 0)))                                              # sábado
        self.assertEqual(ny.rueda_esperada_ny(h(14, 17, 0)), date(2026, 10, 14))                           # cerrada: la de hoy
        self.assertEqual(ny.rueda_esperada_ny(h(14, 0, 15)), date(2026, 10, 13))                           # de madrugada (corrida atrasada): la rueda anterior
        self.assertEqual(ny.rueda_esperada_ny(h(14, 9, 29)), date(2026, 10, 13))
        self.assertIsNone(ny.rueda_esperada_ny(h(14, 9, 30)))                                              # rueda en curso
        self.assertIsNone(ny.rueda_esperada_ny(h(14, 16, 29)))
        self.assertEqual(ny.rueda_esperada_ny(h(19, 3, 0)), date(2026, 10, 16))                            # lunes de madrugada: el viernes
        self.assertEqual(ny.rueda_esperada_ny(h(17, 3, 0)), date(2026, 10, 16))                            # sábado de madrugada: el viernes
        self.assertIsNone(ny.rueda_esperada_ny(h(17, 15, 0)))                                              # sábado a la tarde: nada que informar

    def test_corte_de_datos(self):
        h = lambda dia, hh, mm: datetime(2026, 10, dia, hh, mm, tzinfo=timezone(timedelta(hours=-4)))
        self.assertEqual(ny.corte_de_datos_ny(h(14, 12, 0)), date(2026, 10, 14))                           # rueda en curso: la vela de hoy no se usa
        self.assertEqual(ny.corte_de_datos_ny(h(14, 16, 30)), date(2026, 10, 15))
        self.assertEqual(ny.corte_de_datos_ny(h(17, 12, 0)), date(2026, 10, 18))                           # sábado


def respuesta(filas_ts, off=-18000, status=200):
    """Una respuesta de Yahoo con velas (ts, o, h, l, c, v)."""
    r = mock.Mock(status_code=status)
    r.json.return_value = {"chart": {"result": [{"meta": {"gmtoffset": off}, "timestamp": [x[0] for x in filas_ts],
                                                    "indicators": {"quote": [{"open": [x[1] for x in filas_ts], "high": [x[2] for x in filas_ts], "low": [x[3] for x in filas_ts],
                                                                              "close": [x[4] for x in filas_ts], "volume": [x[5] for x in filas_ts]}]}}]}}
    return r


class DatosDeYahoo(unittest.TestCase):
    def ts(self, y, m, d, hora=14, minuto=30):
        return int(datetime(y, m, d, hora, minuto, tzinfo=UTC).timestamp())            # 9:30 de Nueva York en invierno

    def test_la_fecha_es_la_de_nueva_york_y_la_vela_va_a_la_medianoche_de_argentina(self):
        filas = [(self.ts(2026, 11, 24), 10, 11, 9, 10.5, 1000), (self.ts(2026, 11, 25), 10.5, 12, 10, 11, 2000)]
        with mock.patch.object(ny._http, "get", return_value=respuesta(filas)):
            v = ny.get_daily_ohlc("AAA", 400)
        self.assertEqual([datetime.fromtimestamp(x["t"], AR).date().isoformat() for x in v], ["2026-11-24", "2026-11-25"])
        self.assertEqual(v[1], {"t": int(datetime(2026, 11, 25, tzinfo=AR).timestamp()), "o": 10.5, "h": 12.0, "l": 10.0, "c": 11.0, "v": 2000})

    def test_velas_incompletas_o_en_cero_se_descartan_y_el_corte_saca_el_dia(self):
        filas = [(self.ts(2026, 11, 23), None, 11, 9, 10, 1), (self.ts(2026, 11, 24), 10, 11, 9, 0, 1), (self.ts(2026, 11, 25), 10, 11, 9, 10.5, 5), (self.ts(2026, 11, 27), 10, 11, 9, 10.7, 6)]
        with mock.patch.object(ny._http, "get", return_value=respuesta(filas)):
            v = ny.get_daily_ohlc("AAA", 400, corte_ts=int(datetime(2026, 11, 27, tzinfo=AR).timestamp()))
        self.assertEqual([x["c"] for x in v], [10.5])

    def test_ticker_que_yahoo_no_tiene_da_lista_vacia(self):
        with mock.patch.object(ny._http, "get", return_value=mock.Mock(status_code=404)):
            self.assertEqual(ny.get_daily_ohlc("XXXX", 400), [])
        r = mock.Mock(status_code=200); r.json.return_value = {"chart": {"result": []}}
        with mock.patch.object(ny._http, "get", return_value=r):
            self.assertEqual(ny.get_daily_ohlc("XXXX", 400), [])

    def test_si_yahoo_no_responde_falla_en_voz_alta_despues_de_reintentar(self):
        with mock.patch.object(ny._http, "get", return_value=mock.Mock(status_code=429)) as g, mock.patch.object(ny.time, "sleep"):
            with self.assertRaises(requests.ConnectionError):
                ny.get_daily_ohlc("AAA", 400)
        self.assertEqual(g.call_count, ny.REINTENTOS * 2)                                              # dos servidores por intento


class LiquidezDeLasLineasD(unittest.TestCase):
    ITEMS = [{"yahoo": "AAA", "nombre": "a", "simbolos": ["AAAD"]}, {"yahoo": "BBD", "nombre": "b", "simbolos": ["BBDCD", "BBDD"]}, {"yahoo": "ZZZ", "nombre": "z", "simbolos": ["ZZZD"]}]

    def test_usa_la_linea_con_mas_monto_y_omite_las_que_no_estan(self):
        filas = [{"symbol": "AAAD", "c": 20.0, "v": 5000}, {"symbol": "BBDCD", "c": 4.0, "v": 1000}, {"symbol": "BBDD", "c": 4.0, "v": 30000}]
        with mock.patch.object(ny.fr, "_get", return_value=filas):
            r = ny.liquidez_cedears(self.ITEMS)
        self.assertEqual(r["AAA"], {"monto_dia": 100000.0, "volumen_dia": 5000.0, "linea": "AAAD"})
        self.assertEqual((r["BBD"]["linea"], r["BBD"]["monto_dia"]), ("BBDD", 120000.0))
        self.assertNotIn("ZZZ", r)

    def test_si_data912_no_responde_no_se_inventa_liquidez(self):
        with mock.patch.object(ny.fr, "_get", side_effect=requests.ConnectionError("x")):
            self.assertEqual(ny.liquidez_cedears(self.ITEMS), {})
        with mock.patch.object(ny.fr, "_get", return_value={"Error": "x"}):
            self.assertEqual(ny.liquidez_cedears(self.ITEMS), {})

    def test_el_listado_acepta_una_liquidez_propia(self):
        pa = bt.Papel("AAA", "cedear", barras_v(SUAVE[:74], date(2026, 10, 13) - timedelta(days=73)), date(2026, 10, 14))
        p = pd.de_params(pd.defectos())
        sin = macd.listado2([pa], p, {"papeles": {}}, None)["lista"][0]                                 # lo de siempre: sale del propio papel
        self.assertIn("monto_dia_millones", sin)
        liq = lambda x: {"monto_dia": 250000.0, "volumen_dia": 9000.0, "operable": True, "extra": {"linea_d": "AAAD"}}
        f = macd.listado2([pa], p, {"papeles": {}}, None, liq)["lista"][0]
        self.assertEqual((f["monto_dia_millones"], f["volumen_dia"], f["operable"], f["linea_d"]), (0.25, 9000.0, True, "AAAD"))
        nada = macd.listado2([pa], p, {"papeles": {}}, None, lambda x: {"monto_dia": None, "volumen_dia": None, "operable": False})["lista"][0]
        self.assertEqual((nada["monto_dia_millones"], nada["volumen_dia"], nada["operable"]), (None, None, False))


class Parametros(unittest.TestCase):
    def test_los_valores_de_fabrica_son_los_de_san_marino_salvo_el_piso(self):
        d, s = pd.defectos(), pm.defectos()
        self.assertEqual(d.pop("dolar_piso_miles"), 100); s.pop("macd_piso_millones")
        self.assertEqual(d, s)
        self.assertEqual(len(pd.EDITABLES), 10)

    def test_el_piso_en_miles_de_dolares_pasa_a_millones_para_el_listado(self):
        self.assertEqual(pd.de_params(pd.defectos())["piso_millones"], 0.1)
        self.assertEqual(pd.de_params(dict(pd.defectos(), dolar_piso_miles=2500))["piso_millones"], 2.5)

    def test_validacion_y_guardado_propio(self):
        self.assertEqual(pd.leer("dolar_piso_miles", "2.500"), 2500)
        for clave, malo in (("dolar_piso_miles", "0"), ("dolar_piso_miles", "1,5"), ("macd_dias", "11"), ("vortex_exigir", "2"), ("macd2_ruedas", "21")):
            with self.assertRaises(pd.ErrorParametro, msg=clave):
                pd.leer(clave, malo)
        with self.assertRaises(pd.ErrorParametro):
            pd.validar(dict(pd.defectos(), macd_rapido=30))
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "p.json")
            self.assertEqual(pd.cargar(ruta), pd.defectos())
            v, cambios = pd.combinar(pd.cargar(ruta), {"dolar_piso_miles": "300", "macd_dias": ""})
            self.assertEqual(list(cambios), ["dolar_piso_miles"])
            pd.guardar(v, ruta)
            self.assertEqual(pd.cargar(ruta)["dolar_piso_miles"], 300)
        self.assertNotEqual(pd.ARCHIVO, pm.ARCHIVO)                                                      # no pisa los valores de San Marino

    def test_la_descripcion_marca_lo_cambiado(self):
        e = {x["clave"]: x for x in pd.descripcion(dict(pd.defectos(), dolar_piso_miles=300))["editables"]}
        self.assertTrue(e["dolar_piso_miles"]["cambiado"]); self.assertFalse(e["macd_rapido"]["cambiado"]); self.assertEqual(e["dolar_piso_miles"]["unidad"], "mil US$")


class Corrida(unittest.TestCase):
    """main() de punta a punta con Yahoo, data912 y el reloj reemplazados (sin red)."""
    MARTES = datetime(2026, 10, 13, 18, 0, tzinfo=AR)                                    # 17:00 en Nueva York (horario de verano): la rueda ya cerró

    def setUp(self):
        fin = date(2026, 10, 13)
        self.items = [{"yahoo": "AAA", "nombre": "Empresa AAA", "simbolos": ["AAAD"]}, {"yahoo": "BBB", "nombre": "Empresa BBB", "simbolos": ["BBBD"]}]
        self.barras = {"AAA": barras_v(SUAVE[:74], fin - timedelta(days=73)),                   # cruzó hacia arriba hace 1 rueda con el Vortex alcista: listado 2
                       "BBB": barras_v(ONDA[:71], fin - timedelta(days=70))}                    # a 0,44% de cruzar: listado 1
        self.liq = {"AAA": {"monto_dia": 500000.0, "volumen_dia": 20000.0, "linea": "AAAD"}, "BBB": {"monto_dia": 40000.0, "volumen_dia": 900.0, "linea": "BBBD"}}
        self.dir = tempfile.TemporaryDirectory(); self.addCleanup(self.dir.cleanup)
        self.pfile = os.path.join(self.dir.name, "p.json")
        self.guardados = []
        env = mock.patch.dict(os.environ, {"CLAVE_ACCESO": "una-clave-de-prueba-bien-larga"}); env.start(); self.addCleanup(env.stop)

    def correr(self, args, ahora=None, liq=None, barras=None, serie_sp=True):
        ahora = ahora or self.MARTES
        b = self.barras if barras is None else barras
        def guardar(fn, r, key, carpeta=None, etiqueta=None):
            self.guardados.append((fn, r, etiqueta)); return "archivo.json"
        sp = [(date(2025, 1, 1) + timedelta(days=k), 100.0 + k * 0.1) for k in range(400)] if serie_sp else None
        patches = [mock.patch.object(gd.reloj, "Reloj", lambda: RelojFalso(ahora)), mock.patch.object(gd.ny, "universo", lambda ruta=None: self.items),
                   mock.patch.object(gd.ny, "get_daily_ohlc", lambda t, d=400, c=None: b.get(t, [])), mock.patch.object(gd.ny, "liquidez_cedears", lambda items: self.liq if liq is None else liq),
                   mock.patch.object(gd.indices, "bajar_yahoo", lambda s: sp), mock.patch.object(gd.generar, "guardar", guardar), mock.patch.object(gd.generar, "derivar", lambda c, m: "k"),
                   mock.patch.object(gd.generar, "cargar_meta", lambda: {}), mock.patch.object(gd, "anotar", lambda t, n="warning": None),
                   mock.patch.object(sys, "argv", ["generar_sanmarino_dolar.py", "--parametros", self.pfile] + args)]
        for p in patches: p.start()
        try:
            gd.main()
        finally:
            for p in patches: p.stop()

    def test_la_corrida_programada_publica_los_dos_listados_con_datos_de_nueva_york(self):
        self.correr(["--programado"])
        fn, r, etiqueta = self.guardados[0]
        self.assertEqual((fn, etiqueta, r["funcion"], r["moneda"]), ("sanmarinodolar", None, "sanmarinodolar", "USD")); self.assertFalse(r.get("salteado"))
        self.assertEqual([f["ticker"] for f in r["lista"]], ["BBB"]); self.assertEqual([f["ticker"] for f in r["lista2"]], ["AAA"])
        a = r["lista2"][0]
        self.assertEqual((a["nombre"], a["linea_d"], a["operable"], a["ruedas_desde_cruce"], a["vortex_alcista"]), ("Empresa AAA", "AAAD", True, 1, True))
        self.assertEqual(a["monto_dia_millones"], 0.5)
        self.assertFalse(r["lista"][0]["operable"])                                                       # US$ 40 mil: por debajo del piso de 100 mil
        self.assertEqual(r["fecha_datos"], "2026-10-13"); self.assertEqual(r["datos"]["fuente"], ny.NOMBRE); self.assertEqual(r["piso_millones"], 0.1)
        self.assertIn("sp500_usd", r["vara"])                                                              # la vara de esta pantalla es el S&P 500 en dólares
        self.assertEqual({e["clave"]: e["valor"] for e in r["parametros"]["editables"]}, pd.defectos())
        self.assertEqual(r["contexto"]["origen"], "programada"); self.assertEqual(r["universo"]["especies"], 2)

    def test_sin_dato_de_liquidez_nada_se_marca_operable_y_se_avisa(self):
        self.correr(["--programado"], liq={})
        r = self.guardados[0][1]
        self.assertFalse(any(f["operable"] for f in r["lista"] + r["lista2"])); self.assertTrue(any("operable" in x for x in r["avisos"]))
        self.assertTrue(all(f["monto_dia_millones"] is None for f in r["lista2"]))

    def test_sin_el_indice_de_referencia_el_informe_sale_igual_y_lo_dice(self):
        self.correr(["--programado"], serie_sp=False)
        r = self.guardados[0][1]
        self.assertEqual(r["vara"], {}); self.assertTrue(any("índice de referencia" in x for x in r["avisos"]))

    def test_un_feriado_de_nueva_york_se_saltea_sin_fallar(self):
        fin = date(2026, 10, 12)                                                                          # Yahoo no trae la rueda del 13: la última es la del 12
        b = {"AAA": barras_v(SUAVE[:74], fin - timedelta(days=73)), "BBB": barras_v(ONDA[:71], fin - timedelta(days=70))}
        self.correr(["--programado"], barras=b)
        fn, r, etiqueta = self.guardados[0]
        self.assertEqual((fn, etiqueta, r["funcion"]), ("sanmarinodolar", "SALTEADO", "sanmarinodolar")); self.assertIn("rueda de Nueva York", r["motivo"]); self.assertIn("12/10/2026", r["motivo"])
        self.assertFalse(os.path.exists(self.pfile))                                                      # un salteo no toca los parámetros guardados

    def test_con_la_rueda_en_curso_se_saltea(self):
        self.correr(["--programado"], ahora=datetime(2026, 10, 13, 12, 0, tzinfo=AR))                     # 11:00 en Nueva York
        self.assertEqual(self.guardados[0][2], "SALTEADO"); self.assertIn("en curso", self.guardados[0][1]["motivo"])

    def test_corrida_atrasada_de_madrugada_informa_la_rueda_anterior_y_lo_avisa(self):
        self.correr(["--programado"], ahora=datetime(2026, 10, 14, 2, 15, tzinfo=AR))                     # 01:15 en Nueva York del miércoles
        r = self.guardados[0][1]
        self.assertFalse(r.get("salteado")); self.assertEqual(r["fecha_datos"], "2026-10-13"); self.assertTrue(any("llegó con atraso" in x for x in r["avisos"]))

    def test_menos_de_la_mitad_de_los_papeles_con_datos_se_saltea(self):
        self.correr(["--programado"], barras={"AAA": self.barras["AAA"]}, ahora=self.MARTES)
        self.assertFalse(self.guardados[0][1].get("salteado"))                                            # 1 de 2 es justo la mitad: sale
        self.items.extend({"yahoo": f"X{k}", "nombre": f"x{k}", "simbolos": [f"X{k}D"]} for k in range(4))
        self.correr(["--programado"], barras={"AAA": self.barras["AAA"]})
        self.assertEqual(self.guardados[1][2], "SALTEADO"); self.assertIn("1 de 6", self.guardados[1][1]["motivo"])

    def test_la_manual_sin_datos_falla_y_con_yahoo_vacio_no_inventa(self):
        with self.assertRaises(SystemExit):
            self.correr([], barras={})
        self.assertEqual(self.guardados, [])

    def test_los_parametros_pedidos_se_usan_y_quedan_guardados(self):
        self.correr(["--piso", "600", "--dist2", "0,3", "--vortex", "0", "--ruedas-cruce", "5"])
        r = self.guardados[0][1]
        v = {e["clave"]: e["valor"] for e in r["parametros"]["editables"]}
        self.assertEqual((v["dolar_piso_miles"], v["macd2_dist_pct"], v["vortex_exigir"], v["macd2_ruedas"]), (600, 0.3, 0, 5))
        self.assertFalse(any(f["operable"] for f in r["lista2"]))                                         # con piso de US$ 600 mil, los US$ 500 mil ya no alcanzan
        self.assertEqual(json.load(open(self.pfile, encoding="utf-8"))["dolar_piso_miles"], 600)

    def test_parametros_invalidos_no_corren(self):
        with self.assertRaises(SystemExit):
            self.correr(["--piso", "0"])
        self.assertEqual(self.guardados, [])


class BacktestDolar(unittest.TestCase):
    """El backtest del listado 2 de Saint Marino Dólar: parámetros, señales sin filtro de liquidez y la corrida completa con Yahoo y el reloj reemplazados (sin red)."""
    FIN = date(2026, 10, 13)

    def test_parametros_en_dolares_y_sin_filtro_de_liquidez(self):
        p = sb.parametros(pd.defectos(), dolar=True)
        self.assertEqual((p["capital"], p["moneda"], p["piso_monto"], p["estrategia"]), (100_000, "USD", 0, "sanmarinodolar_listado2"))
        self.assertEqual((p["max_posiciones"], p["sizing"]), (3, "patrimonio")); self.assertAlmostEqual(p["fraccion"], 1 / 3)
        self.assertEqual(p["sm"]["piso_millones"], 0.1); self.assertEqual(p["ventana_ruedas"], macd.ruedas_minimas(p["sm"]))
        q = sb.parametros(pm.defectos())                                                            # el de San Marino no cambia: pesos, piso de 1.000 M
        self.assertEqual((q["capital"], q["piso_monto"], q.get("moneda")), (10_000_000, 1e9, None))
        with self.assertRaises(pd.ErrorParametro):
            sb.parametros(dict(pd.defectos(), macd_rapido=40), dolar=True)

    def test_un_papel_de_poco_monto_entra_porque_no_hay_filtro_de_liquidez(self):
        pa = bt.Papel("A", "cedear", barras_v(SUAVE[:100], self.FIN - timedelta(days=99), v=1), self.FIN + timedelta(days=1))
        self.assertEqual(len(sb.senales_sanmarino2(pa, p=sb.parametros(pd.defectos(), dolar=True))[0]), 1)
        self.assertEqual(sb.senales_sanmarino2(pa, p=sb.parametros(pm.defectos()))[0], [])          # con el piso de pesos de San Marino, no

    def correr(self, extra=None):
        items = [{"yahoo": f"T{k}", "nombre": f"Empresa {k}", "simbolos": [f"T{k}D"]} for k in range(4)]
        b = {f"T{k}": barras_v(SUAVE[k:150 + k] if k < 2 else SUAVE[:150], self.FIN - timedelta(days=149), v=5e7) for k in range(4)}
        sp = [(date(2026, 5, 1) + timedelta(days=k), 100.0 + k * 0.05) for k in range(150)]
        liq = {"T0": {"monto_dia": 500000.0, "volumen_dia": 1.0, "linea": "T0D"}, "T1": {"monto_dia": 1000.0, "volumen_dia": 1.0, "linea": "T1D"}}
        ahora = datetime(2026, 10, 13, 18, 0, tzinfo=AR)
        with tempfile.TemporaryDirectory() as d:
            salida, pfile = os.path.join(d, "r.json"), os.path.join(d, "p.json")
            patches = [mock.patch.object(gbd.reloj, "Reloj", lambda: RelojFalso(ahora)), mock.patch.object(gbd.ny, "universo", lambda ruta=None: items),
                       mock.patch.object(gbd.ny, "get_daily_ohlc", lambda t, dias=400, corte=None: b.get(t, [])), mock.patch.object(gbd.ny, "liquidez_cedears", lambda it: liq),
                       mock.patch.object(gbd.indices, "bajar_yahoo", lambda s: sp), mock.patch.dict(os.environ, {"CLAVE_ACCESO": "una-clave-de-prueba-bien-larga"}),
                       mock.patch.object(sys, "argv", ["generar_backtest_dolar.py", "--solo-claro", salida, "--parametros", pfile] + (extra or []))]
            for p in patches:
                p.start()
            try:
                gbd.main()
            finally:
                for p in patches:
                    p.stop()
                bt.fijar_referencias({}, [])
            with open(salida, encoding="utf-8") as f:
                return json.load(f)

    def test_la_corrida_completa_publica_un_informe_en_dolares_contra_el_sp500(self):
        r = self.correr()
        self.assertEqual((r["funcion"], r["moneda"], r["estrategia"], r["etiqueta"]), ("backtest", "USD", "sanmarino", gbd.ETIQUETA))
        self.assertEqual((r["parametros"]["capital"], r["parametros"]["moneda"]), (100_000, "USD")); self.assertEqual(r["fuente_datos"], ny.NOMBRE)
        self.assertEqual(r["vara"]["clave"], "sp500_usd"); self.assertEqual(r["referencias"]["sp500_usd"]["moneda"], "USD"); self.assertIn("vara", r["equity"])
        self.assertGreaterEqual(r["metricas"]["trades"], 1)
        c = r["comparacion_sanmarino"]
        self.assertIsNone(c["sin_filtro_liquidez"]); self.assertEqual(c["senales_una_por_una"]["sin_filtro_liquidez"], {})        # sin filtro: no hay una versión «sin filtro» distinta
        self.assertIn("Saint Marino Dólar", c["regla"]); self.assertIn("SIN filtro de liquidez", c["regla"]); self.assertIn("no se probó ninguna otra", c["regla"])
        txt = " ".join(r["advertencias"])
        self.assertIn("NO HAY FILTRO DE LIQUIDEZ", txt); self.assertIn("Bull Market", txt); self.assertNotIn("Merval", txt); self.assertNotIn("1.000 millones", txt)

    def test_la_variante_informativa_usa_solo_los_papeles_que_hoy_operan(self):
        so = self.correr()["comparacion_sanmarino"]["solo_operables_hoy"]
        self.assertEqual((so["n_papeles"], so["piso_usd"]), (1, 100000.0))                          # solo T0 supera US$ 100 mil hoy
        self.assertIsNotNone(so["resumen"])

    def test_los_porcentajes_del_resumen_usan_el_capital_de_la_corrida(self):
        r = self.correr()
        con = r["comparacion_sanmarino"]["principal"]["concentracion"]
        self.assertAlmostEqual(con["sin_top3_pct_capital"], con["sin_top3"] / 100_000 * 100, delta=0.01)    # antes se dividía por el capital en pesos (10 M)
        self.assertLessEqual(r["comparacion_sanmarino"]["principal"]["ocupacion_media"], 3.0)           # nunca más posiciones que lugares

    def test_parametros_invalidos_no_corren_y_sin_clave_no_publica(self):
        with mock.patch.object(sys, "argv", ["generar_backtest_dolar.py"]), mock.patch.dict(os.environ, {"CLAVE_ACCESO": ""}):
            with self.assertRaises(SystemExit):
                gbd.main()
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "p.json")
            with open(ruta, "w", encoding="utf-8") as f:
                json.dump({"macd_dias": 99}, f)
            with mock.patch.object(sys, "argv", ["generar_backtest_dolar.py", "--solo-claro", os.path.join(d, "r.json"), "--parametros", ruta]):
                with self.assertRaises(SystemExit):
                    gbd.main()

    def test_workflow_y_pagina(self):
        wf = leer(".github", "workflows", "backtestdolar.yml")
        self.assertIn("workflow_dispatch:", wf); self.assertNotIn("inputs:", wf); self.assertNotIn("schedule:", wf)
        for frag in ("generar_backtest_dolar.py", "python tests_dolar.py", "python tests_sanmarino_bt.py", "group: caidas", "CLAVE_ACCESO", "publicar_cambios.sh"):
            self.assertIn(frag, wf)
        html = leer("docs", "index.html")
        for frag in ("MONEDA_BT", "r.equity.vara?esc(r.equity.vara.nombre)", "solo_operables_hoy", '(USD?"Saint Marino Dólar":"San Marino")'):
            self.assertIn(frag, html)
        self.assertIn('MONEDA_BT="$";', html)                                                          # se restablece al cambiar de pestaña


class Estructura(unittest.TestCase):
    def test_la_contrasena_se_asigna_una_sola_vez_y_no_hay_variable_clave(self):
        for archivo in ("generar_sanmarino_dolar.py", "generar_backtest_dolar.py"):
            self.contrasena_una_vez(archivo)

    def contrasena_una_vez(self, archivo):
        arbol = ast.parse(leer(archivo))
        asignadas = {}
        for n in ast.walk(arbol):
            blancos = []
            if isinstance(n, ast.Assign): blancos = n.targets
            elif isinstance(n, (ast.AugAssign, ast.AnnAssign, ast.For, ast.comprehension, ast.NamedExpr)): blancos = [n.target]
            for b in blancos:
                for x in ast.walk(b):
                    if isinstance(x, ast.Name):
                        asignadas.setdefault(x.id, []).append(getattr(n, "lineno", 0))
        self.assertEqual(len(asignadas.get("contrasena", [])), 1); self.assertNotIn("clave", asignadas)

    def test_fuente_ny_no_importa_el_conector_ni_backtest(self):                                          # backtest importa el conector: import circular
        arbol = ast.parse(leer("fuente_ny.py"))
        modulos = {n.names[0].name for n in ast.walk(arbol) if isinstance(n, ast.Import)} | {n.module for n in ast.walk(arbol) if isinstance(n, ast.ImportFrom)}
        self.assertFalse({"conector", "backtest", "config"} & modulos)

    def test_el_guardado_incluye_los_parametros_de_saint_marino_dolar(self):
        self.assertIn("parametros_macd_dolar.json", leer("publicar_cambios.sh"))


class Workflow(unittest.TestCase):
    def pdef(self):
        html = leer("docs", "index.html")
        i = html.index("var PDEF_SD=") + len("var PDEF_SD=")
        return json.loads(html[i:html.index("];", i) + 1])

    def test_los_editables_de_la_pagina_son_los_de_parametros_macd_dolar_py(self):
        self.assertEqual([(p["k"], p["def"], p["min"], p["max"], p["ent"]) for p in self.pdef()], [(e["clave"], e["defecto"], e["minimo"], e["maximo"], e["entero"]) for e in pd.EDITABLES])

    def test_las_entradas_del_workflow_son_las_de_la_pagina(self):
        wf = leer(".github", "workflows", "sanmarinodolar.yml")
        entradas = re.findall(r"(?m)^      (\w+):\s*\n\s+description", wf)
        self.assertLessEqual(len(entradas), 10)                                                           # tope de GitHub para un workflow manual
        self.assertEqual(sorted(entradas), sorted(p["wf"] for p in self.pdef()))
        self.assertIn("cron: '30 21 * * 1-5'", wf)                                                        # 21:30 UTC: siempre después del cierre de Nueva York (21:00 UTC en invierno)
        for frag in ("CLAVE_ACCESO", "generar_sanmarino_dolar.py", "publicar_cambios.sh", "python tests_dolar.py", "group: caidas"):
            self.assertIn(frag, wf)
        for p in self.pdef():
            self.assertIn("inputs." + p["wf"], wf)

    def test_la_pagina_tiene_la_pestana_y_su_panel(self):
        html = leer("docs", "index.html")
        for frag in ('data-fn="sanmarinodolar"', 'id="params-sd"', "function prepararSD", "function inputsSD", "MODO_USD", 'fn==="sanmarino"||fn==="sanmarinodolar"?pintarSanMarino'):
            self.assertIn(frag, html)
        self.assertIn("workflows/\"+(fn===\"informe\"?\"informe\":fn===\"sanmarino\"?\"sanmarino\":fn===\"sanmarinodolar\"?\"sanmarinodolar\"", html)


if __name__ == "__main__":
    unittest.main(verbosity=1)
