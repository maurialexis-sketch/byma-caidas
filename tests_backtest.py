"""Pruebas del motor de backtest con series sintéticas:  python tests_backtest.py"""
import math, unittest
from datetime import date, datetime, timedelta
import backtest as bt

AR = bt.AR


def ts(d):
    return datetime(d.year, d.month, d.day, tzinfo=AR).timestamp()


def barras(cierres, inicio=date(2025, 1, 1), v=5e7, rango=0.004):
    """Velas diarias a partir de cierres: apertura = cierre previo, máx/mín = +-rango."""
    out, prev = [], cierres[0]
    for k, c in enumerate(cierres):
        o = prev
        out.append({"t": ts(inicio + timedelta(days=k)), "o": o, "h": max(o, c) * (1 + rango),
                    "l": min(o, c) * (1 - rango), "c": c, "v": v})
        prev = c
    return out


def papel_a_mano(o, h, l, c):
    """Papel con velas definidas a mano (para probar salidas)."""
    p = bt.Papel("X", "accion", barras([100.0] * len(c)))
    p.o, p.h, p.l, p.c = list(o), list(h), list(l), list(c)
    return p


class Razon(unittest.TestCase):
    def test_razones_enteras(self):
        for r in (2.0, 1.99, 3.02, 10.1, 0.5, 0.333):
            self.assertTrue(bt.es_razon_entera(r), r)
        for r in (1.0, 1.5, 0.4, 0.8, 1.2, 2.5):
            self.assertFalse(bt.es_razon_entera(r), r)

    def test_ajuste_de_split(self):
        p = bt.Papel("S", "cedear", barras([100.0] * 5 + [50.0] * 5))     # split 2:1
        self.assertEqual(len(p.ajustes), 1)
        self.assertEqual(p.ajustes[0]["tipo"], "split")
        self.assertAlmostEqual(p.c[0], 50.0)
        self.assertAlmostEqual(p.c[-1], 50.0)                              # serie continua
        self.assertAlmostEqual(p.monto[0], 100.0 * 5e7)                    # el monto usa el precio de la época

    def test_un_salto_grande_no_entero_no_se_toca(self):
        p = bt.Papel("R", "accion", barras([100.0] * 5 + [140.0] * 5))     # +40% real
        self.assertEqual(p.ajustes, [])
        self.assertAlmostEqual(p.c[0], 100.0)


class Salidas(unittest.TestCase):
    """Entrada en i=0 con soporte 100 -> stop 99; resistencia 120."""
    def base(self, **kw):
        n = 25
        d = {"o": [100.0] * n, "h": [101.0] * n, "l": [99.5] * n, "c": [100.0] * n}
        for k, v in kw.items():
            for idx, val in v.items():
                d[k][idx] = val
        return papel_a_mano(**d)

    def test_resistencia(self):
        self.assertEqual(bt.salida(self.base(h={3: 121.0}), 0, 120.0, 99.0), (3, 120.0, "resistencia"))

    def test_gap_arriba_sale_en_la_apertura(self):
        self.assertEqual(bt.salida(self.base(o={3: 125.0}, h={3: 126.0}), 0, 120.0, 99.0), (3, 125.0, "resistencia"))

    def test_stop(self):
        self.assertEqual(bt.salida(self.base(l={2: 98.0}), 0, 120.0, 99.0), (2, 99.0, "stop"))

    def test_gap_abajo_sale_en_la_apertura_peor_que_el_stop(self):
        self.assertEqual(bt.salida(self.base(o={2: 95.0}, l={2: 94.0}), 0, 120.0, 99.0), (2, 95.0, "stop"))

    def test_stop_y_resistencia_en_la_misma_vela_gana_el_stop(self):
        self.assertEqual(bt.salida(self.base(l={2: 98.0}, h={2: 125.0}), 0, 120.0, 99.0)[2], "stop")

    def test_tiempo_a_las_20_ruedas(self):
        self.assertEqual(bt.salida(self.base(c={20: 103.0}), 0, 120.0, 99.0), (20, 103.0, "tiempo"))

    def test_abierta_si_faltan_datos(self):
        p = papel_a_mano([100.0] * 6, [101.0] * 6, [99.5] * 6, [100.0] * 6)
        self.assertEqual(bt.salida(p, 0, 120.0, 99.0)[2], "abierta")


N = 200   # ruedas de la oscilación previa (el motor exige 168 de ventana completa)


def serie_con_rango():
    """N ruedas oscilando entre ~100 (soporte) y ~130 (resistencia)."""
    return [115 + 15 * math.sin(k / 3.2) for k in range(N)]


class Señales(unittest.TestCase):
    def armar(self, cola, v=5e7):
        return bt.Papel("T", "accion", barras(serie_con_rango() + cola, v=v))

    def cola_senal(self):
        # la serie previa termina en ~106; cae a ~99,8 en 4 ruedas (-6,3% a 3 días) tocando el soporte (~99,6); día verde en N+4
        return [106.5, 103.0, 100.5, 99.8, 101.5] + [104, 108, 112, 118, 125, 131]

    def test_detecta_caida_toque_y_dia_verde(self):
        p = self.armar(self.cola_senal())
        s, _ = bt.señales(p)
        e = [x for x in s if x["i"] == N + 4]
        self.assertTrue(e, "debería haber señal el día verde (índice N+4)")
        self.assertAlmostEqual(e[0]["precio"], 101.5, places=3)
        self.assertLess(e[0]["stop"], e[0]["soporte"])
        self.assertGreater(e[0]["resistencia"], e[0]["precio"])

    def test_sin_dia_verde_no_hay_senal(self):
        p = self.armar([106.5, 103.0, 100.5, 99.8, 99.5])                  # el último día cierra por debajo del anterior
        self.assertFalse([x for x in bt.señales(p)[0] if x["i"] == N + 4])

    def test_sin_liquidez_no_hay_senal(self):
        p = self.armar(self.cola_senal()[:5], v=1e5)                        # monto ~1e7, muy por debajo de 1.000 M
        self.assertEqual(bt.señales(p)[0], [])

    def test_no_mira_el_futuro(self):
        """Lo detectado hasta el día t no cambia si se recorta o se altera todo lo posterior."""
        cola = self.cola_senal()
        completo, _ = bt.señales(self.armar(cola))
        clave = lambda s, tope: [(x["fecha"], round(x["precio"], 6), round(x["soporte"], 6), round(x["resistencia"], 6))
                                 for x in s if x["i"] <= tope]
        for corte in (3, 5, 8):                                              # recorta la cola en distintos puntos
            parcial, _ = bt.señales(self.armar(cola[:corte]))
            self.assertEqual(clave(completo, N - 1 + corte), clave(parcial, N - 1 + corte))
        alterado, _ = bt.señales(self.armar(cola[:5] + [150.0, 61.0, 148.0, 59.0, 151.0, 60.0]))
        self.assertEqual(clave(completo, N + 4), clave(alterado, N + 4))
        self.assertTrue([x for x in completo if x["i"] == N + 4])


def senal_falsa(papel, i, monto5, precio=100.0, j=None, px_salida=110.0, motivo="resistencia"):
    j = j or i + 5
    return {"papel": papel, "i": i, "fecha": papel.f[i], "precio": precio, "soporte": 95.0, "resistencia": 120.0,
            "stop": 94.0, "monto5": monto5, "caida_dias": 2, "caida_pct": -4.0, "j": j, "f_salida": papel.f[j],
            "px_salida": px_salida, "motivo": motivo}


class Cartera(unittest.TestCase):
    def setUp(self):
        self.p1 = bt.Papel("A", "accion", barras([100.0] * 60))
        self.p2 = bt.Papel("B", "accion", barras([100.0] * 60))
        self.p3 = bt.Papel("C", "accion", barras([100.0] * 60))
        self.cal = sorted(self.p1.f)

    def test_mitad_del_efectivo_y_costos(self):
        cerr, _, _, _ = bt.simular([senal_falsa(self.p1, 10, 3e9), senal_falsa(self.p2, 10, 2e9)], self.cal, "efectivo")
        lado = bt.costo_lado()
        a1 = math.floor(0.5 * 1e7 / (100 * (1 + lado)))
        self.assertEqual(cerr[0]["acciones"], a1)                                              # 1ª: 50% del efectivo
        resto = 1e7 - a1 * 100 * (1 + lado)
        self.assertEqual(cerr[1]["acciones"], math.floor(0.5 * resto / (100 * (1 + lado))))     # 2ª: 50% del resto
        self.assertAlmostEqual(cerr[0]["pnl"], a1 * 110 * (1 - lado) - a1 * 100 * (1 + lado), places=4)

    def test_variante_patrimonio_usa_mitad_del_total(self):
        cerr, _, _, _ = bt.simular([senal_falsa(self.p1, 10, 3e9), senal_falsa(self.p2, 10, 2e9)], self.cal, "patrimonio")
        # 50% del total cada una; la 2ª es apenas menor porque el patrimonio ya pagó las comisiones de la 1ª
        self.assertAlmostEqual(cerr[0]["acciones"] / cerr[1]["acciones"], 1.0, delta=0.01)
        self.assertGreater(cerr[1]["acciones"], 0.49 * 1e7 / 100.7)

    def test_maximo_dos_posiciones_y_prioridad_por_monto(self):
        sig = [senal_falsa(self.p1, 10, 1e9), senal_falsa(self.p2, 10, 5e9), senal_falsa(self.p3, 10, 3e9)]
        cerr, _, _, desc = bt.simular(sig, self.cal, "efectivo")
        self.assertEqual(sorted(t["papel"].ticker for t in cerr), ["B", "C"])                   # entran las de mayor monto
        self.assertEqual(desc["sin_lugar"], 1)

    def test_no_duplica_un_papel_en_cartera(self):
        cerr, _, _, desc = bt.simular([senal_falsa(self.p1, 10, 3e9), senal_falsa(self.p1, 12, 3e9, j=17)], self.cal)
        self.assertEqual(len(cerr), 1)
        self.assertEqual(desc["ya_en_cartera"], 1)

    def test_libera_el_lugar_el_dia_de_salida(self):
        sig = [senal_falsa(self.p1, 10, 3e9, j=15), senal_falsa(self.p2, 10, 3e9, j=15), senal_falsa(self.p3, 15, 3e9, j=20)]
        cerr, _, _, _ = bt.simular(sig, self.cal)
        self.assertEqual(len(cerr), 3)                                                          # C entra el día en que salen A y B

    def test_posicion_abierta_queda_fuera_de_las_cerradas(self):
        s = senal_falsa(self.p1, 55, 3e9, j=59, motivo="abierta", px_salida=100.0)
        cerr, ab, _, _ = bt.simular([s], self.cal)
        self.assertEqual((len(cerr), len(ab)), (0, 1))

    def test_impuesto_a_las_ganancias_solo_sobre_ganancias(self):
        p = dict(bt.PARAMS, imp_ganancias=0.15)
        con, _, _, _ = bt.simular([senal_falsa(self.p1, 10, 3e9)], self.cal, "efectivo", p)
        sin, _, _, _ = bt.simular([senal_falsa(self.p1, 10, 3e9)], self.cal, "efectivo")
        self.assertAlmostEqual(con[0]["pnl"], sin[0]["pnl"] * 0.85, places=4)
        perd, _, _, _ = bt.simular([senal_falsa(self.p1, 10, 3e9, px_salida=90.0, motivo="stop")], self.cal, "efectivo", p)
        sin_imp, _, _, _ = bt.simular([senal_falsa(self.p1, 10, 3e9, px_salida=90.0, motivo="stop")], self.cal, "efectivo")
        self.assertLess(perd[0]["pnl"], 0)
        self.assertAlmostEqual(perd[0]["pnl"], sin_imp[0]["pnl"], places=6)                     # una pérdida no se grava


class Metricas(unittest.TestCase):
    def test_formulas(self):
        d0 = date(2025, 1, 1)
        serie = [(d0 + timedelta(days=k), e) for k, e in enumerate([100, 110, 90, 95, 120])]
        dd = bt.max_drawdown(serie)
        self.assertAlmostEqual(dd["pct"], (110 - 90) / 110 * 100)
        self.assertAlmostEqual(dd["monto"], 20)
        pa = bt.Papel("A", "accion", barras([100.0] * 10))
        cerr = [{"pnl": 300.0, "pnl_pct": 3.0, "fecha": d0, "f_salida": d0 + timedelta(days=4), "i": 0, "j": 3, "papel": pa},
                {"pnl": -100.0, "pnl_pct": -1.0, "fecha": d0, "f_salida": d0 + timedelta(days=2), "i": 0, "j": 2, "papel": pa},
                {"pnl": 100.0, "pnl_pct": 1.0, "fecha": d0, "f_salida": d0 + timedelta(days=6), "i": 0, "j": 5, "papel": pa}]
        cap = bt.PARAMS["capital"]
        m = bt.metricas(cerr, [(d0, cap), (d0 + timedelta(days=365), cap * 1.10)])
        self.assertAlmostEqual(m["profit_factor"], 400 / 100)
        self.assertAlmostEqual(m["payoff_ratio"], 200 / 100)
        self.assertAlmostEqual(m["ganadores_pct"], 2 / 3 * 100)
        self.assertEqual(m["trades"], 3)
        self.assertAlmostEqual(m["duracion_media_dias"], 4.0)
        self.assertAlmostEqual(m["ganancia_media_trade"], 100.0)
        self.assertAlmostEqual(m["ganancia_total_pct"], 10.0)
        self.assertAlmostEqual(m["cagr_pct"], 10.0, delta=0.1)


class FiltroTendencia(unittest.TestCase):
    """Cambio único: el cierre debe cotizar por encima de su media de 200 ruedas (150 si no hay 200 de histórico)."""
    CHICO = dict(bt.PARAMS, filtro_tendencia=True, ma_larga=6, ma_corta=3)

    def papel(self, cierres):
        return bt.Papel("F", "accion", barras([float(x) for x in cierres]))

    def test_media_movil_incluye_el_cierre_del_dia_y_nada_posterior(self):
        p = self.papel([100, 110, 120, 130, 140, 150, 160])
        self.assertAlmostEqual(p.sma(2, 3), 110.0)          # (100+110+120)/3
        self.assertAlmostEqual(p.sma(5, 6), 125.0)          # (100..150)/6
        self.assertIsNone(p.sma(1, 3))                      # faltan datos

    def test_usa_la_media_de_150_si_no_hay_200_ruedas(self):
        # i=4 (5 ruedas < 6): corre la media corta (3)
        self.assertTrue(bt.sobre_la_media(self.papel([120, 100, 100, 100, 104]), 4, self.CHICO))    # 104 > (100+100+104)/3 = 101,33
        self.assertFalse(bt.sobre_la_media(self.papel([100, 100, 100, 120, 108]), 4, self.CHICO))   # 108 < (100+120+108)/3 = 109,33

    def test_usa_la_media_de_200_cuando_ya_hay_200_ruedas(self):
        # i=5 (6 ruedas >= 6): corre la media larga (6). Cierre 106: arriba de la corta (103,33) pero NO de la larga (106,67)
        p = self.papel([130, 100, 100, 100, 104, 106])
        self.assertAlmostEqual(p.sma(5, 3), 103.3333333, places=5)
        self.assertAlmostEqual(p.sma(5, 6), 106.6666667, places=5)
        self.assertFalse(bt.sobre_la_media(p, 5, self.CHICO))          # con la corta daría True: se usa la larga
        self.assertTrue(bt.sobre_la_media(self.papel([100, 100, 100, 100, 104, 110]), 5, self.CHICO))   # 110 > 102,33

    def test_igual_a_la_media_no_cuenta_como_por_encima(self):
        self.assertFalse(bt.sobre_la_media(self.papel([100] * 6), 5, self.CHICO))

    def test_valores_reales_por_defecto(self):
        self.assertEqual((bt.PARAMS["ma_larga"], bt.PARAMS["ma_corta"], bt.PARAMS["filtro_tendencia"]), (200, 150, False))

    def test_bloquea_la_entrada_bajo_la_media_y_la_cuenta(self):
        cola = [106.5, 103.0, 100.5, 99.8, 101.5]
        papel = bt.Papel("T", "accion", barras(serie_con_rango() + cola))
        sin_filtro, d0 = bt.señales(papel)
        self.assertTrue([x for x in sin_filtro if x["i"] == N + 4])
        self.assertEqual(d0["bajo_media"], 0)
        con_filtro, d1 = bt.señales(papel, p=dict(bt.PARAMS, filtro_tendencia=True))     # SMA200 ~115 > 101,5
        self.assertFalse([x for x in con_filtro if x["i"] == N + 4])
        self.assertGreaterEqual(d1["bajo_media"], 1)

    def test_deja_entrar_si_cotiza_por_encima(self):
        cola = [106.5, 103.0, 100.5, 99.8, 101.5]
        papel = bt.Papel("T", "accion", barras(serie_con_rango() + cola))
        p = dict(bt.PARAMS, filtro_tendencia=True, ma_larga=3, ma_corta=3)               # SMA3 = 100,6 < 101,5
        s, d = bt.señales(papel, p=p)
        self.assertTrue([x for x in s if x["i"] == N + 4])

    def test_el_filtro_solo_saca_senales_no_cambia_precios_ni_niveles(self):
        cola = [106.5, 103.0, 100.5, 99.8, 101.5] + [104, 108, 112, 118, 125, 131]
        papel = bt.Papel("T", "accion", barras(serie_con_rango() + cola))
        base, _ = bt.señales(papel)
        filtradas, _ = bt.señales(papel, p=dict(bt.PARAMS, filtro_tendencia=True, ma_larga=3, ma_corta=3))
        clave = lambda s: {(x["fecha"], x["precio"], x["soporte"], x["resistencia"], x["f_salida"], x["px_salida"], x["motivo"]) for x in s}
        self.assertTrue(clave(filtradas) <= clave(base))                                 # subconjunto exacto de la base

    def test_diagnostico_reparte_las_senales_de_la_base_sin_perder_ninguna(self):
        cola = [106.5, 103.0, 100.5, 99.8, 101.5] + [104, 108, 112, 118, 125, 131]
        papel = bt.Papel("T", "accion", barras(serie_con_rango() + cola))
        total = len(bt.señales(papel)[0])
        for p in (dict(bt.PARAMS, filtro_tendencia=True), dict(bt.PARAMS, filtro_tendencia=True, ma_larga=3, ma_corta=3)):
            d = bt.diagnostico_filtro([papel], p)
            self.assertEqual(d["pasan"]["n"] + d["eliminadas"]["n"], total)
        d = bt.diagnostico_filtro([papel], dict(bt.PARAMS, filtro_tendencia=True))
        self.assertEqual(d["pasan"]["n"], len([x for x in bt.señales(papel, p=dict(bt.PARAMS, filtro_tendencia=True))[0]]))

    def test_el_filtro_no_mira_el_futuro(self):
        cola = [106.5, 103.0, 100.5, 99.8, 101.5] + [104, 108, 112, 118, 125, 131]
        p = dict(bt.PARAMS, filtro_tendencia=True, ma_larga=3, ma_corta=3)
        completo, _ = bt.señales(bt.Papel("T", "accion", barras(serie_con_rango() + cola)), p=p)
        parcial, _ = bt.señales(bt.Papel("T", "accion", barras(serie_con_rango() + cola[:5])), p=p)
        alterado, _ = bt.señales(bt.Papel("T", "accion", barras(serie_con_rango() + cola[:5] + [150.0, 61.0, 148.0, 59.0, 151.0, 60.0])), p=p)
        clave = lambda s: [(x["fecha"], round(x["precio"], 6)) for x in s if x["i"] <= N + 4]
        self.assertEqual(clave(completo), clave(parcial))
        self.assertEqual(clave(completo), clave(alterado))
        self.assertTrue(clave(completo))


if __name__ == "__main__":
    unittest.main(verbosity=1)
