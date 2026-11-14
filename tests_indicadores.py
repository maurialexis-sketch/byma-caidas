"""Pruebas de los indicadores (medias móviles, Bollinger y derivadas):  python tests_indicadores.py"""
import json, math, os, tempfile, unittest
from datetime import date, timedelta

import backtest as bt
import bollinger as bo
import indicadores as ind
from tests_backtest import barras


def fechas(n, inicio=date(2025, 1, 1)):
    return [inicio + timedelta(days=k) for k in range(n)]


class Medias(unittest.TestCase):
    def test_la_media_es_vacia_hasta_tener_n_ruedas_y_despues_es_exacta(self):
        m = ind.sma([float(k) for k in range(1, 31)], 9)
        self.assertEqual(m[:8], [None] * 8)                                          # no se rellena ni se aproxima
        self.assertAlmostEqual(m[8], 5.0); self.assertAlmostEqual(m[-1], sum(range(22, 31)) / 9)

    def test_con_menos_ruedas_que_el_periodo_todo_queda_vacio(self):
        self.assertEqual(ind.sma([1.0] * 10, 50), [None] * 10)
        self.assertEqual(ind.sma([], 9), [])

    def test_coincide_con_la_media_del_motor_del_backtest(self):
        p = bt.Papel("T", "cedear", barras([100 + (k % 13) * 1.5 for k in range(260)]))
        m = ind.sma(p.c, 50)
        for i in (49, 120, 259):
            self.assertAlmostEqual(m[i], p.sma(i, 50), places=9)

    def test_las_bandas_son_las_de_la_estrategia_de_bollinger(self):
        c = [100 + 8 * math.sin(k / 3.0) + k * 0.1 for k in range(90)]
        central, sup, inf = ind.bandas(c, 20, 2.0)
        b = bo.bandas(c, 20, 2.0)
        self.assertEqual((central[:19], sup[:19], inf[:19]), ([None] * 19, [None] * 19, [None] * 19))
        for i in (19, 40, 89):
            self.assertAlmostEqual(central[i], b["c"][i], places=9); self.assertAlmostEqual(sup[i], b["s"][i], places=9); self.assertAlmostEqual(inf[i], b["i"][i], places=9)
        w = c[-20:]; m = sum(w) / 20
        self.assertAlmostEqual(sup[-1] - central[-1], 2 * math.sqrt(sum((x - m) ** 2 for x in w) / 20), places=9)


class Derivadas(unittest.TestCase):
    def serie(self, n=300):
        return [float(k) for k in range(1, n + 1)]                                    # una recta: las medias se calculan a mano

    def test_distancia_y_pendiente_de_cada_media(self):
        c = self.serie(); r = ind.calcular(c, fechas(len(c)))
        for n in (9, 50, 200):
            m = sum(c[-n:]) / n; previa = sum(c[-n - 5:-5]) / n
            self.assertAlmostEqual(r[f"mm{n}"], m, places=3)
            self.assertAlmostEqual(r[f"dist_mm{n}_pct"], (300 / m - 1) * 100, places=1)
            self.assertAlmostEqual(r[f"pend_mm{n}_pct"], (m / previa - 1) * 100, places=2)         # variación % de la media en 5 ruedas
        self.assertEqual((r["cierre"], r["ruedas"], r["fecha"]), (300.0, 300, str(fechas(300)[-1])))

    def test_con_pocas_ruedas_las_medias_largas_quedan_vacias_y_no_se_inventan_derivadas(self):
        c = self.serie(120); r = ind.calcular(c, fechas(120))
        self.assertIsNotNone(r["mm9"]); self.assertIsNotNone(r["mm50"])
        self.assertIsNone(r["mm200"]); self.assertIsNone(r["dist_mm200_pct"]); self.assertIsNone(r["pend_mm200_pct"])
        self.assertIsNone(r["tendencia_de_fondo"])                                                  # sin MM200 no hay tendencia de fondo
        self.assertFalse(r["cruces"]["mm50_mm200"]["hay_datos"]); self.assertTrue(r["cruces"]["mm9_mm50"]["hay_datos"])
        r2 = ind.calcular(self.serie(52), fechas(52))
        self.assertIsNotNone(r2["mm50"]); self.assertIsNone(r2["pend_mm50_pct"])                    # MM50 existe desde la rueda 50, pero hace 5 ruedas todavía no: pendiente vacía
        self.assertEqual(ind.calcular(self.serie(15), fechas(15))["bollinger"], {"central": None, "superior": None, "inferior": None})

    def test_tendencia_de_fondo_por_el_precio_contra_la_mm200(self):
        sube = [100.0] * 250 + [101.0]
        self.assertEqual(ind.calcular(sube, fechas(251))["tendencia_de_fondo"], "alcista")
        baja = [100.0] * 250 + [99.0]
        self.assertEqual(ind.calcular(baja, fechas(251))["tendencia_de_fondo"], "bajista")
        igual = [100.0] * 251
        self.assertEqual(ind.calcular(igual, fechas(251))["tendencia_de_fondo"], "neutra")

    def test_cruce_alcista_de_mm9_y_mm50_dentro_de_las_ultimas_10_ruedas(self):
        c = [120.0 - 0.4 * k for k in range(120)] + [72.0 + 3.0 * k for k in range(1, 26)]      # cae mucho y rebota fuerte: la MM9 pasa por encima de la MM50
        f = fechas(len(c))
        hallados = []
        for t in range(120, len(c)):
            x = ind.calcular(c, f, t)["cruces"]["mm9_mm50"]
            if x["tipo"]:
                hallados.append((t, x["tipo"], x["ruedas_atras"], x["fecha"]))
        self.assertTrue(hallados)
        t0, tipo, atras, fecha = hallados[0]
        self.assertEqual(tipo, "alcista"); self.assertEqual(atras, 0)                              # el día del cruce figura con 0 ruedas atrás
        self.assertEqual(fecha, str(f[t0]))
        ult = [h for h in hallados if h[0] == t0 + 9][0]
        self.assertEqual(ult[2], 9)                                                                 # 9 ruedas después sigue dentro de la ventana
        self.assertIsNone(ind.calcular(c, f, t0 + 10)["cruces"]["mm9_mm50"]["tipo"])                # a la 10.ª rueda posterior ya salió de la ventana

    def test_cruce_bajista(self):
        c = [50.0 + 0.5 * k for k in range(100)] + [100.0 - 4.0 * k for k in range(1, 20)]
        f = fechas(len(c))
        tipos = {ind.calcular(c, f, t)["cruces"]["mm9_mm50"]["tipo"] for t in range(100, len(c))}
        self.assertIn("bajista", tipos); self.assertNotIn("alcista", tipos)

    def test_sin_cruce_en_una_tendencia_pareja(self):
        c = [100.0 + 0.5 * k for k in range(260)]
        x = ind.calcular(c, fechas(260))["cruces"]
        self.assertEqual((x["mm9_mm50"]["tipo"], x["mm50_mm200"]["tipo"]), (None, None))
        self.assertTrue(x["mm50_mm200"]["hay_datos"])

    def test_ultimos_dias_para_comparar_contra_un_grafico(self):
        c = [100 + (k % 9) for k in range(260)]
        filas = ind.ultimos_dias(c, fechas(260), 5)
        self.assertEqual(len(filas), 5); self.assertEqual(filas[-1]["fecha"], str(fechas(260)[-1]))
        self.assertAlmostEqual(filas[-1]["mm9"], sum(c[-9:]) / 9, places=3)
        self.assertAlmostEqual(filas[-2]["mm200"], sum(c[-201:-1]) / 200, places=3)
        self.assertEqual(set(filas[0]), {"fecha", "cierre", "mm9", "mm50", "mm200", "bb_central", "bb_superior", "bb_inferior"})


class Configuracion(unittest.TestCase):
    def escribir(self, d, contenido):
        ruta = os.path.join(d, "c.json")
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(contenido, f)
        return ruta

    def test_la_configuracion_del_repositorio_es_la_pedida(self):
        c = ind.cargar()
        self.assertEqual(c["mm_periodos"], [9, 50, 200]); self.assertEqual(c["bollinger"], {"periodo": 20, "desvios": 2})
        self.assertEqual((c["pendiente_ruedas"], c["cruces_ventana"], c["tendencia_de_fondo_mm"]), (5, 10, 200))

    def test_los_periodos_salen_de_la_configuracion_no_del_codigo(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = self.escribir(d, {"mm_periodos": [3, 5, 8], "bollinger": {"periodo": 6, "desvios": 1.5}, "pendiente_ruedas": 2, "cruces_ventana": 4,
                                     "cruces_pares": [[3, 5]], "tendencia_de_fondo_mm": 8, "historico_dias": 900})
            cfg = ind.cargar(ruta)
            c = [10.0 + k % 4 for k in range(40)]
            r = ind.calcular(c, fechas(40), None, cfg)
            self.assertEqual({k for k in r if k.startswith("mm")}, {"mm3", "mm5", "mm8"})
            self.assertAlmostEqual(r["mm8"], sum(c[-8:]) / 8, places=3)
            self.assertEqual(list(r["cruces"]), ["mm3_mm5"])
            central, sup, inf = ind.bandas(c, 6, 1.5)
            self.assertAlmostEqual(r["bollinger"]["superior"], sup[-1], places=3)

    def test_una_configuracion_invalida_se_rechaza(self):
        base = {"mm_periodos": [9, 50, 200], "bollinger": {"periodo": 20, "desvios": 2}, "pendiente_ruedas": 5, "cruces_ventana": 10, "cruces_pares": [[9, 50]], "tendencia_de_fondo_mm": 200}
        with tempfile.TemporaryDirectory() as d:
            for malo in ({**base, "mm_periodos": []}, {**base, "mm_periodos": [9, "x"]}, {**base, "bollinger": {"periodo": 20}}, {**base, "cruces_pares": [[9, 77]]},
                         {**base, "tendencia_de_fondo_mm": 100}):
                with self.assertRaises(ValueError):
                    ind.cargar(self.escribir(d, malo))
                ind._CACHE.clear()


class EnElInforme(unittest.TestCase):
    def papel(self):
        from tests_informe import dos_regimenes
        return dos_regimenes()                                                          # 205 ruedas, cierra rompiendo una resistencia: es candidato

    def test_las_columnas_y_las_filas_planas_tienen_el_mismo_largo_y_salen_de_la_configuracion(self):
        p = self.papel(); r = ind.de_papel(p)
        cols = ind.columnas()
        fila = ind.fila_plana("T", "cedear", r, 1234.56, True, "candidato")
        self.assertEqual(len(cols), len(fila))
        d = dict(zip(cols, fila))
        self.assertEqual((d["ticker"], d["en_lista"], d["operable"], d["monto_5_ruedas_millones"]), ("T", "candidato", 1, 1234.6))
        for n in (9, 50, 200):
            self.assertIn(f"mm{n}", d); self.assertIn(f"dist_mm{n}_pct", d); self.assertIn(f"pend_mm{n}_5r_pct", d)
        self.assertIn("bb20_central", d); self.assertIn("cruce_mm9_mm50", d); self.assertIn("cruce_mm50_mm200_ruedas_atras", d)
        self.assertIsNone(d["mm200"] if len(p.c) < 200 else None)

    def test_un_papel_con_menos_de_200_ruedas_deja_la_mm200_vacia_en_la_fila(self):
        p = bt.Papel("C", "cedear", barras([100 + (k % 7) for k in range(120)]))
        d = dict(zip(ind.columnas(), ind.fila_plana("C", "cedear", ind.de_papel(p), 10.0, False, None)))
        self.assertIsNone(d["mm200"]); self.assertIsNone(d["dist_mm200_pct"]); self.assertIsNone(d["tendencia_de_fondo"])
        self.assertIsNotNone(d["mm50"])

    def test_el_informe_trae_las_columnas_y_los_candidatos_llevan_sus_indicadores(self):
        import generar_informe as gi
        import informe as inf

        class Rel:
            fuente = "prueba"
            def ahora(self): return __import__("datetime").datetime(2026, 11, 13, 18, 0, tzinfo=bt.AR)
        p = self.papel(); p.ticker = "T"
        res = inf.candidatos([p])
        self.assertEqual(res["total_candidatos"], 1)
        cfg = ind.cargar()
        r = ind.de_papel(p, cfg)
        indic = {"config": cfg, "columnas": ind.columnas(cfg), "filas": [ind.fila_plana("T", "cedear", r, 5000.0, True, "candidato", cfg)], "por_ticker": {"T": r}}
        out = gi.armar(res, {}, p.f[-1], {"especies": 1, "con_datos": 1, "sin_respuesta": []}, Rel(), p.f[-1], [], {}, None, "manual", None, None, indic)
        self.assertEqual(out["indicadores"]["columnas"], ind.columnas(cfg)); self.assertEqual(len(out["indicadores"]["filas"]), 1)
        self.assertEqual(out["indicadores"]["config"]["mm_periodos"], [9, 50, 200])
        self.assertEqual(out["candidatos"][0]["indicadores"]["mm9"], r["mm9"])
        # y solo es información: los candidatos son los mismos con o sin indicadores
        sin = gi.armar(res, {}, p.f[-1], {"especies": 1, "con_datos": 1, "sin_respuesta": []}, Rel(), p.f[-1], [], {}, None, "manual", None, None, None)
        self.assertEqual([c["ticker"] for c in out["candidatos"]], [c["ticker"] for c in sin["candidatos"]])


class FiltroMM200DeLaRuptura(unittest.TestCase):
    def senales(self, papel, **cambios):
        import ruptura as rp
        p = dict(rp.PARAMS_TRAILING_SOLO, **cambios)
        return rp.senales_ruptura(papel, p=p)

    def papel_alcista(self):
        from tests_informe import dos_regimenes
        return dos_regimenes()

    def papel_bajista(self):
        from tests_informe import dos_regimenes
        previo = [260 + 10 * math.sin(k / 3.2) if k < 60 else 115 + 15 * math.sin(k / 3.2) for k in range(200)]       # rompe el techo pero cotiza bajo su media de 200
        return dos_regimenes(previo=previo)

    def test_sin_filtro_entra_aunque_cotice_bajo_la_mm200_y_con_filtro_no(self):
        p = self.papel_bajista()
        self.assertEqual(self.senales(p, tendencia="mm_estricta")[0], [])
        s, desc = self.senales(p, tendencia="mm_estricta")
        self.assertGreaterEqual(desc["bajo_media"], 1)
        self.assertGreaterEqual(len(self.senales(p, tendencia="ninguna")[0]), 1)
        self.assertEqual(self.senales(p)[0], [])                                          # la de siempre (MM200 con respaldo) tampoco entra

    def test_con_filtro_y_precio_sobre_la_mm200_entra_igual_que_sin_filtro(self):
        p = self.papel_alcista()
        a = [(x["i"], x["precio"]) for x in self.senales(p, tendencia="ninguna")[0]]
        b = [(x["i"], x["precio"]) for x in self.senales(p, tendencia="mm_estricta", ma_larga=100)[0]]
        self.assertTrue(a); self.assertEqual(a, b)

    def test_sin_200_ruedas_la_media_queda_vacia_y_el_papel_no_entra_ni_se_aproxima(self):
        p = self.papel_alcista()                                                         # 205 ruedas: la MM300 todavía no existe
        s, desc = self.senales(p, tendencia="mm_estricta", ma_larga=300, ma_corta=100)
        self.assertEqual(s, []); self.assertGreaterEqual(desc["sin_datos_mm"], 1)
        self.assertGreaterEqual(len(self.senales(p, ma_larga=300, ma_corta=100)[0]), 1)  # el modo de siempre sí usa el respaldo de MM100
        self.assertGreaterEqual(len(self.senales(p, tendencia="ninguna", ma_larga=300, ma_corta=100)[0]), 1)

    def test_el_modo_por_defecto_no_cambio(self):
        import ruptura as rp
        self.assertNotIn("tendencia", rp.PARAMS_TRAILING_SOLO); self.assertNotIn("tendencia", rp.PARAMS_RUPTURA)


if __name__ == "__main__":
    unittest.main()
