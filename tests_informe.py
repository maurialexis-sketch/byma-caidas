"""Pruebas del informe diario de candidatos:  python tests_informe.py"""
import math
import unittest
from datetime import date, datetime, timedelta

import backtest as bt
import generar_informe as gi
import informe as inf
from tests_backtest import barras, serie_con_rango, N

AR = bt.AR
SUBE = [110.0, 118.0, 125.0, 128.0]          # la última rueda (cierre 132) rompe la resistencia ~130,4
PARAMS_MA3 = dict(bt.PARAMS, ma_larga=3, ma_corta=3)


def dos_regimenes(v=5e7, ultimo=132.0, previo=None):
    """Rango alto (picos ~160) y luego rango 100-130; la última rueda cierra en 'ultimo' (rompe el techo de ~130). Hay una resistencia a ~160."""
    cierres = previo if previo is not None else [140 + 20 * math.sin(k / 3.2) if k < 70 else 115 + 15 * math.sin(k / 3.2) for k in range(N)]
    return bt.Papel("T", "cedear", barras(cierres + SUBE + [ultimo], v=v))


def etiquetar(p, ticker, tipo="cedear"):
    p.ticker, p.tipo = ticker, tipo
    return p


class Filtros(unittest.TestCase):
    def test_una_ruptura_con_recorrido_y_rb_suficientes_es_candidata(self):
        e = inf.evaluar_papel(dos_regimenes())
        self.assertTrue(e["liquido"] and e["alcista"])
        self.assertTrue(e["ruptura"]["disparo"])
        self.assertTrue(129.0 < e["ruptura"]["nivel"] < 131.5)
        r = inf.candidatos([dos_regimenes()])
        self.assertEqual(r["total_candidatos"], 1)
        c = r["candidatos"][0]
        self.assertEqual(c["senal"], "RUPTURA")
        self.assertTrue(155 < c["resistencia"] < 165)
        self.assertGreaterEqual(c["recorrido_pct"], 10)
        self.assertGreaterEqual(c["rr"], 2)
        self.assertGreater(c["dist_ma_pct"], 0)
        self.assertEqual(c["soporte_nota"], "resistencia rota (ahora soporte)")

    def test_el_rb_y_el_recorrido_se_calculan_como_se_dice(self):
        c = inf.candidatos([dos_regimenes()])["candidatos"][0]
        stop = c["soporte"] * 0.99
        self.assertAlmostEqual(c["rr"], (c["resistencia"] - c["precio"]) / (c["precio"] - stop), places=1)
        self.assertAlmostEqual(c["recorrido_pct"], (c["resistencia"] / c["precio"] - 1) * 100, delta=0.05)
        self.assertAlmostEqual(c["riesgo_pct"], (c["precio"] - stop) / c["precio"] * 100, delta=0.05)

    def test_sin_resistencia_por_encima_no_pasa_aunque_rompa(self):
        p = etiquetar(bt.Papel("X", "cedear", barras(serie_con_rango() + SUBE + [132.0])), "X")          # un solo rango: nada por encima de 132
        e = inf.evaluar_papel(p)
        self.assertTrue(e["ruptura"]["disparo"]); self.assertIsNone(e["ruptura"]["resistencia"])
        r = inf.candidatos([p])
        self.assertEqual(r["total_candidatos"], 0)
        self.assertEqual([(x["ticker"], x["motivo"]) for x in r["cercanos"]], [("X", "sin resistencia por encima")])

    def test_sin_tendencia_alcista_no_pasa(self):
        previo = [260 + 10 * math.sin(k / 3.2) if k < 60 else 115 + 15 * math.sin(k / 3.2) for k in range(N)]     # 260/113 = 2,3: no es un split
        p = dos_regimenes(previo=previo)
        e = inf.evaluar_papel(p)
        self.assertTrue(e["ruptura"]["disparo"])
        self.assertFalse(e["alcista"])
        self.assertLess(e["dist_ma_pct"], 0)
        r = inf.candidatos([p])
        self.assertEqual(r["total_candidatos"], 0)
        self.assertEqual(next(f for f in r["embudo"] if f["clave"] == "tendencia")["acumulado"], 0)

    def test_sin_liquidez_no_entra_al_universo(self):
        p = dos_regimenes(v=1e5)
        self.assertFalse(inf.evaluar_papel(p)["liquido"])
        r = inf.candidatos([p])
        self.assertEqual((r["liquidos"], r["total_candidatos"]), (0, 0))

    def test_un_rebote_con_recorrido_corto_no_pasa(self):
        # tocó soporte y cerró en verde, pero la resistencia está a menos de 10%: no se baja la vara
        p = etiquetar(bt.Papel("R", "cedear", barras(serie_con_rango() + [106.5, 103.0, 100.5, 99.8, 101.5])), "R")
        e = inf.evaluar_papel(p, PARAMS_MA3)
        self.assertTrue(e["rebote"]["disparo"]); self.assertTrue(e["alcista"])
        self.assertLess(e["rebote"]["recorrido_pct"], 10)
        r = inf.candidatos([p], params=PARAMS_MA3)
        self.assertEqual(r["total_candidatos"], 0)
        self.assertEqual(r["cercanos"][0]["motivo"], "recorrido menor a 10%")
        self.assertEqual(r["cercanos"][0]["senal"], "REBOTE")

    def test_un_rebote_exige_cierre_en_verde(self):
        p = etiquetar(bt.Papel("R", "cedear", barras(serie_con_rango() + [106.5, 103.0, 100.5, 99.8, 99.5])), "R")      # cierra en rojo
        self.assertIsNone(inf.evaluar_papel(p, PARAMS_MA3)["rebote"])

    def test_la_senal_se_etiqueta(self):
        e = inf.evaluar_papel(dos_regimenes())
        self.assertEqual(inf.mejor_senal(e)[0], "RUPTURA")
        self.assertEqual(inf.candidatos([dos_regimenes()])["candidatos"][0]["senales_hoy"], ["RUPTURA"])

    def test_el_embudo_es_monotono_y_cuenta_cada_filtro(self):
        r = inf.candidatos([dos_regimenes(), dos_regimenes(v=1e5)])
        acum = [f["acumulado"] for f in r["embudo"] if f["clave"] in ("liquidez", "tendencia", "recorrido", "rr", "todos")]
        self.assertEqual(acum, [1, 1, 1, 1, 1])
        self.assertTrue(all(a >= b for a, b in zip(acum, acum[1:])))
        self.assertEqual(r["embudo"][0]["pasan_solos"], 1)
        self.assertEqual(r["embudo"][0]["tickers_solos"], ["T"])

    def test_papel_con_poco_historico_no_se_evalua(self):
        self.assertIsNone(inf.evaluar_papel(bt.Papel("N", "cedear", barras([100.0 + k * 0.1 for k in range(120)]))))


class Lista(unittest.TestCase):
    def varios(self, n):
        out = []
        for k in range(n):
            out.append(etiquetar(dos_regimenes(ultimo=131.0 + k * 0.4), f"T{k}"))          # distinto precio -> distinto R/B
        return out

    def test_maximo_5_ordenados_por_rb_y_se_avisa_cuantos_mas_hay(self):
        r = inf.candidatos(self.varios(7))
        self.assertEqual(r["total_candidatos"], 7)
        self.assertEqual((len(r["candidatos"]), r["mas_candidatos"]), (5, 2))
        rr = [c["rr"] for c in r["candidatos"]]
        self.assertEqual(rr, sorted(rr, reverse=True))
        self.assertEqual(r["candidatos"][0]["ticker"], "T0")                              # el de menor precio tiene más recorrido y menos riesgo

    def test_una_empresa_una_vez_queda_la_linea_mas_liquida(self):
        a = etiquetar(dos_regimenes(v=5e7), "AAPL"); b = etiquetar(dos_regimenes(v=9e7), "AAPLB")
        r = inf.candidatos([a, b])
        self.assertEqual(r["total_candidatos"], 1)
        self.assertEqual(r["candidatos"][0]["ticker"], "AAPLB")
        self.assertEqual(r["candidatos"][0]["otras_lineas"], ["AAPL"])

    def test_lleva_el_sector(self):
        c = inf.candidatos([etiquetar(dos_regimenes(), "NVDA")])["candidatos"][0]
        self.assertEqual((c["grupo"], c["sector"], c["subsector"]), ("CEDEAR", "tecnologicas", "IA"))
        c = inf.candidatos([etiquetar(dos_regimenes(), "ZZZZ")])["candidatos"][0]
        self.assertEqual(c["sector"], "sin_clasificar")

    def test_ningun_candidato_dice_la_frase_exacta(self):
        class Rel:
            fuente = "prueba"
            def ahora(self): return datetime(2026, 10, 14, 10, 0, tzinfo=AR)
        res = inf.candidatos([dos_regimenes(v=1e5)])
        out = gi.armar(res, {}, date(2026, 10, 13), {"especies": 1, "con_datos": 1, "sin_respuesta": []}, Rel(), date(2026, 10, 14))
        self.assertEqual(out["mensaje"], "Hoy ningún activo cumple las condiciones")
        self.assertEqual(out["candidatos"], [])
        self.assertIn("no es una recomendación", out["aviso"].lower())
        self.assertIn("ruptura rindió mejor que el rebote", out["recordatorio"])

    def test_con_candidatos_no_hay_mensaje_de_ninguno(self):
        class Rel:
            fuente = "prueba"
            def ahora(self): return datetime(2026, 10, 14, 10, 0, tzinfo=AR)
        out = gi.armar(inf.candidatos([dos_regimenes()]), {}, date(2026, 10, 13), {"especies": 1, "con_datos": 1, "sin_respuesta": []}, Rel(), date(2026, 10, 14))
        self.assertIsNone(out["mensaje"])
        self.assertEqual(len(out["candidatos"]), 1)


class Vara(unittest.TestCase):
    def serie(self, dias, f):
        ini = date(2025, 1, 1)
        return [(ini + timedelta(days=i), f(i)) for i in range(dias)]

    def test_retorno_12_meses(self):
        s = self.serie(500, lambda i: 100.0 * (1 + i / 100))
        r, desde, hasta = inf.retorno_12m(s)
        self.assertEqual((hasta - desde).days, 365)
        self.assertAlmostEqual(r, (s[-1][1] / dict(s)[desde] - 1) * 100)

    def test_sin_historico_de_un_ano_no_se_inventa(self):
        self.assertIsNone(inf.retorno_12m(self.serie(200, lambda i: 100.0 + i)))
        self.assertIsNone(inf.retorno_12m(None))

    def test_la_vara_correcta_para_cada_candidato(self):
        class Rel:
            fuente = "prueba"
            def ahora(self): return datetime(2026, 10, 14, 10, 0, tzinfo=AR)
        refs = {"merval": self.serie(500, lambda i: 100.0 + i), "sp500_ars": self.serie(500, lambda i: 100.0 + 0.5 * i)}
        res = inf.candidatos([etiquetar(dos_regimenes(), "NVDA", "cedear"), etiquetar(dos_regimenes(), "GGAL", "accion")])
        out = gi.armar(res, refs, date(2026, 5, 15), {"especies": 2, "con_datos": 2, "sin_respuesta": []}, Rel(), date(2026, 10, 14))
        por = {c["ticker"]: c for c in out["candidatos"]}
        self.assertEqual(por["NVDA"]["vara_clave"], "sp500_ars")
        self.assertEqual(por["GGAL"]["vara_clave"], "merval")
        self.assertEqual(por["NVDA"]["vara_12m_pct"], out["vara"]["sp500_ars"]["retorno_12m_pct"])
        self.assertEqual(por["GGAL"]["vara_12m_pct"], out["vara"]["merval"]["retorno_12m_pct"])


class Corte(unittest.TestCase):
    def ahora(self, y, m, d, h, mi): return datetime(y, m, d, h, mi, tzinfo=AR)

    def test_durante_la_rueda_no_se_usa_la_vela_de_hoy(self):
        self.assertEqual(gi.corte_de_datos(self.ahora(2026, 10, 14, 12, 0)), date(2026, 10, 14))
        self.assertEqual(gi.corte_de_datos(self.ahora(2026, 10, 14, 10, 0)), date(2026, 10, 14))
        self.assertEqual(gi.corte_de_datos(self.ahora(2026, 10, 14, 17, 29)), date(2026, 10, 14))

    def test_cerrada_la_rueda_o_en_fin_de_semana_se_usa_la_ultima_vela(self):
        self.assertEqual(gi.corte_de_datos(self.ahora(2026, 10, 14, 17, 30)), date(2026, 10, 15))
        self.assertEqual(gi.corte_de_datos(self.ahora(2026, 10, 17, 12, 0)), date(2026, 10, 18))      # sábado


class DatosDelDia(unittest.TestCase):
    """Fecha de referencia única y vela de hoy armada con el panel."""
    HOY = date(2026, 10, 13)

    def vela(self, d, c, v=1e6):
        return {"t": int(datetime(d.year, d.month, d.day, tzinfo=AR).timestamp()), "o": c, "h": c * 1.01, "l": c * 0.99, "c": c, "v": v}

    def barras_hasta(self, ult, n=30, c=100.0):
        return [self.vela(ult - timedelta(days=n - 1 - k), c) for k in range(n)]

    def fila(self, previo=100.0, trade=102.0, vol=2e6):
        return {"previousClosingPrice": previo, "trade": trade, "closingPrice": trade, "tradeVolume": vol, "openingPrice": 100.5,
                "tradingHighPrice": 103.0, "tradingLowPrice": 99.0}

    def universo(self, n, coherentes):
        ayer = self.HOY - timedelta(days=1)
        barras = {f"T{k}": self.barras_hasta(ayer) for k in range(n)}
        filas = {f"T{k}": self.fila(previo=100.0 if k < coherentes else 90.0) for k in range(n)}
        return barras, filas

    def test_se_arma_la_vela_de_hoy_con_el_panel_si_es_coherente(self):
        barras, filas = self.universo(30, 30)
        barras, info = gi.completar_con_panel(barras, filas, self.HOY)
        self.assertTrue(info["usada"]); self.assertEqual((info["agregadas"], info["coherentes"], info["revisados"]), (30, 30, 30))
        v = barras["T0"][-1]
        self.assertEqual(datetime.fromtimestamp(v["t"], AR).date(), self.HOY)
        self.assertEqual((v["o"], v["h"], v["l"], v["c"], v["v"]), (100.5, 103.0, 99.0, 102.0, 2e6))
        self.assertTrue(v["l"] <= min(v["o"], v["c"]) and v["h"] >= max(v["o"], v["c"]))

    def test_si_el_panel_no_coincide_con_el_historico_no_se_arma_nada(self):
        barras, filas = self.universo(30, 10)                      # solo 1 de cada 3 coincide: parece feriado o datos de otro día
        antes = {t: len(b) for t, b in barras.items()}
        barras, info = gi.completar_con_panel(barras, filas, self.HOY)
        self.assertFalse(info["usada"]); self.assertIn("coherente", info["motivo"])
        self.assertEqual({t: len(b) for t, b in barras.items()}, antes)

    def test_solo_se_agrega_a_los_coherentes_y_que_operaron(self):
        barras, filas = self.universo(30, 28)                      # 28 de 30 coinciden (93%): se usa, pero solo en esos
        filas["T0"]["tradeVolume"] = 0                             # no operó hoy
        barras, info = gi.completar_con_panel(barras, filas, self.HOY)
        self.assertTrue(info["usada"])
        self.assertEqual(len(barras["T0"]), 30)                    # sin operaciones hoy: no se inventa vela
        self.assertEqual(len(barras["T29"]), 30)                   # incoherente: tampoco
        self.assertEqual(len(barras["T1"]), 31)

    def test_si_el_historico_ya_trae_hoy_no_se_toca(self):
        barras = {f"T{k}": self.barras_hasta(self.HOY) for k in range(30)}
        filas = {f"T{k}": self.fila() for k in range(30)}
        barras, info = gi.completar_con_panel(barras, filas, self.HOY)
        self.assertEqual(info["agregadas"], 0)
        self.assertTrue(all(len(b) == 30 for b in barras.values()))

    def test_con_pocos_papeles_no_se_confia_en_el_panel(self):
        barras, filas = self.universo(5, 5)
        self.assertFalse(gi.completar_con_panel(barras, filas, self.HOY)[1]["usada"])

    def papeles(self, fechas):
        return [bt.Papel(f"T{k}", "cedear", self.barras_hasta(f)) for k, f in enumerate(fechas)]

    def test_fecha_de_referencia_es_la_de_la_mayoria(self):
        d9, d13 = date(2026, 10, 9), date(2026, 10, 13)
        self.assertEqual(gi.fecha_de_referencia(self.papeles([d9] * 7 + [d13] * 2)), d9)        # unos pocos con otra fecha no la cambian
        self.assertEqual(gi.fecha_de_referencia(self.papeles([d9] * 3 + [d13] * 3)), d13)       # empate: la más reciente
        self.assertIsNone(gi.fecha_de_referencia([]))

    def test_sesion_cerrada(self):
        self.assertTrue(gi.sesion_cerrada(datetime(2026, 10, 13, 17, 30, tzinfo=AR)))
        self.assertTrue(gi.sesion_cerrada(datetime(2026, 10, 13, 21, 0, tzinfo=AR)))
        self.assertFalse(gi.sesion_cerrada(datetime(2026, 10, 13, 17, 29, tzinfo=AR)))
        self.assertFalse(gi.sesion_cerrada(datetime(2026, 10, 17, 21, 0, tzinfo=AR)))           # sábado: no hay rueda

    def test_volumen_relativo_detecta_una_rueda_incompleta(self):
        normal = [bt.Papel(f"N{k}", "cedear", self.barras_hasta(self.HOY, c=100.0)) for k in range(5)]
        self.assertAlmostEqual(gi.volumen_relativo(normal, 1e6), 1.0)
        incompleta = []
        for k in range(5):
            b = self.barras_hasta(self.HOY); b[-1]["v"] = 1e5                                   # la última, a un décimo
            incompleta.append(bt.Papel(f"I{k}", "cedear", b))
        self.assertLess(gi.volumen_relativo(incompleta, 1e6), gi.VOLUMEN_MIN)

    def test_no_se_avisa_nada_si_el_historico_ya_traia_la_rueda_de_hoy(self):
        barras = {f"T{k}": self.barras_hasta(self.HOY) for k in range(30)}
        info = gi.completar_con_panel(barras, {f"T{k}": self.fila() for k in range(30)}, self.HOY)[1]
        self.assertEqual(info["revisados"], 0)
        self.assertIsNone(gi.aviso_vela_de_hoy(info))

    def test_el_aviso_dice_lo_que_paso(self):
        barras, filas = self.universo(30, 30)
        self.assertIn("se armó con el panel", gi.aviso_vela_de_hoy(gi.completar_con_panel(barras, filas, self.HOY)[1]))
        barras, filas = self.universo(30, 5)
        self.assertIn("no permitió armarla", gi.aviso_vela_de_hoy(gi.completar_con_panel(barras, filas, self.HOY)[1]))

    def test_los_avisos_viajan_en_el_informe(self):
        class Rel:
            fuente = "prueba"
            def ahora(self): return datetime(2026, 10, 14, 10, 0, tzinfo=AR)
        res = inf.candidatos([dos_regimenes()])
        out = gi.armar(res, {}, date(2026, 10, 13), {"especies": 1, "con_datos": 1, "sin_respuesta": []}, Rel(), date(2026, 10, 14), ["aviso uno"], {"fecha_referencia": "2026-10-13"})
        self.assertEqual(out["avisos"], ["aviso uno"]); self.assertEqual(out["datos"]["fecha_referencia"], "2026-10-13")


if __name__ == "__main__":
    unittest.main(verbosity=1)
