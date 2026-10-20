"""
parametros.py — Parámetros EDITABLES del informe de candidatos, y los FIJOS que no se pueden tocar.

Editables (cuatro, validados contra un rango; fuera de rango o con texto inválido el informe NO corre, no se corrige en silencio):
  piso_millones       Piso de liquidez: monto promedio de 5 ruedas, en millones de pesos           (hoy 1.000)
  media_ruedas        Largo de la media de tendencia, en ruedas                                    (hoy 200)
  recorrido_min_pct   Recorrido mínimo a la resistencia, en %                                      (hoy 10)
  rb_min              Relación riesgo/beneficio mínima                                             (hoy 2)
Fijos (estructura del cálculo de niveles; no hay forma de cambiarlos desde la página ni desde el workflow): ventana de 8 meses (168 ruedas),
2+ toques, tolerancia 2%, stop = soporte − 1%, 5 ruedas para el monto promedio.

Bandas de Bollinger (bollinger.py; valen para el BACKTEST de esa estrategia y para la señal 'Bollinger' del informe; también editables y guardados):
  bb_periodo (20), bb_desvios (2), bb_dias (3), bb_ventana (10), bb_magnitud_pct (1)  → la entrada;  bb_peso1/2/3 (1, 1, 1: reparto de los tramos de salida)  y  bb_stop (1 = sí).
Los valores quedan guardados en parametros.json (en la raíz del repositorio) cuando una corrida los cambia, y la corrida siguiente
(incluida la programada de las 18:00) parte de ellos.
"""
import json, os, re

import backtest as bt

ARCHIVO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "parametros.json")

EDITABLES = [
    {"clave": "piso_millones", "nombre": "Piso de liquidez", "detalle": "monto promedio de 5 ruedas, en millones de $", "unidad": "M $",
     "defecto": 1000, "minimo": 1, "maximo": 100000, "entero": True},
    {"clave": "media_ruedas", "nombre": "Largo de la media de tendencia", "detalle": "en ruedas; el cierre tiene que estar por encima", "unidad": "ruedas",
     "defecto": 200, "minimo": 20, "maximo": 400, "entero": True},
    {"clave": "recorrido_min_pct", "nombre": "Recorrido mínimo a la resistencia", "detalle": "distancia del precio a la resistencia, en %", "unidad": "%",
     "defecto": 10, "minimo": 1, "maximo": 100, "entero": False},
    {"clave": "rb_min", "nombre": "Relación riesgo/beneficio mínima", "detalle": "(resistencia − precio) ÷ (precio − stop)", "unidad": "",
     "defecto": 2, "minimo": 0.5, "maximo": 20, "entero": False},
]
EDITABLES += [
    {"clave": "bb_periodo", "nombre": "Bollinger · período de la media central", "detalle": "ruedas de la media y del desvío", "unidad": "ruedas",
     "defecto": 20, "minimo": 5, "maximo": 100, "entero": True},
    {"clave": "bb_desvios", "nombre": "Bollinger · desvíos de las bandas", "detalle": "las bandas son la central ± este número de desvíos", "unidad": "",
     "defecto": 2, "minimo": 0.5, "maximo": 4, "entero": False},
    {"clave": "bb_dias", "nombre": "Bollinger · días de pendiente positiva", "detalle": "ruedas seguidas con la central subiendo que confirman el giro", "unidad": "ruedas",
     "defecto": 3, "minimo": 1, "maximo": 10, "entero": True},
    {"clave": "bb_ventana", "nombre": "Bollinger · ventana de detección", "detalle": "ruedas en las que tiene que caber el patrón (bajada + giro)", "unidad": "ruedas",
     "defecto": 10, "minimo": 3, "maximo": 60, "entero": True},
    {"clave": "bb_magnitud_pct", "nombre": "Bollinger · magnitud mínima del giro", "detalle": "cuánto sube la central en esos días, en %", "unidad": "%",
     "defecto": 1, "minimo": 0, "maximo": 20, "entero": False},
    {"clave": "bb_peso1", "nombre": "Bollinger · tramo 1 (1.er toque de la banda superior)", "detalle": "peso relativo del tramo (1-1-1 = un tercio cada uno)", "unidad": "",
     "defecto": 1, "minimo": 0, "maximo": 100, "entero": True},
    {"clave": "bb_peso2", "nombre": "Bollinger · tramo 2 (2.º toque)", "detalle": "peso relativo del tramo", "unidad": "",
     "defecto": 1, "minimo": 0, "maximo": 100, "entero": True},
    {"clave": "bb_peso3", "nombre": "Bollinger · tramo 3 (la central gira a la baja)", "detalle": "peso relativo del tramo final", "unidad": "",
     "defecto": 1, "minimo": 0, "maximo": 100, "entero": True},
    {"clave": "bb_periodo_listas", "nombre": "Bollinger · listados: período de la media central", "detalle": "ruedas de la línea central de los dos listados (propio: no cambia la estrategia de Bollinger)", "unidad": "ruedas",
     "defecto": 20, "minimo": 2, "maximo": 100, "entero": True},
    {"clave": "bb_ventana_listas", "nombre": "Bollinger · listado 2: ruedas desde la caída", "detalle": "la caída (listado 1) tiene que haber terminado hace como máximo estas ruedas", "unidad": "ruedas",
     "defecto": 10, "minimo": 2, "maximo": 60, "entero": True},
    {"clave": "bb_velas_caida", "nombre": "Bollinger · listado 1: velas bajo la central", "detalle": "cierres seguidos por debajo de la central (con pendiente negativa) para entrar al listado «en caída»", "unidad": "velas",
     "defecto": 5, "minimo": 2, "maximo": 30, "entero": True},
    {"clave": "bb_velas_giro", "nombre": "Bollinger · listado 2: velas sobre la central", "detalle": "últimas ruedas con el cierre por encima de la central para el listado «cambio de pendiente»", "unidad": "velas",
     "defecto": 2, "minimo": 1, "maximo": 10, "entero": True},
    {"clave": "bb_stop", "nombre": "Bollinger · stop bajo la banda inferior", "detalle": "1 = un cierre bajo la banda inferior vende todo; 0 = sin stop", "unidad": "",
     "defecto": 1, "minimo": 0, "maximo": 1, "entero": True, "tipo": "si_no"},
]
for _e in EDITABLES:
    _e.setdefault("grupo", "bollinger" if _e["clave"].startswith("bb_") else "informe")
POR_CLAVE = {e["clave"]: e for e in EDITABLES}
SALIDA_BB = ["bb_peso1", "bb_peso2", "bb_peso3", "bb_stop", "bb_velas_caida", "bb_velas_giro", "bb_periodo_listas", "bb_ventana_listas"]      # viajan juntos en la entrada 'bb_otros' del workflow

FIJOS = [
    {"nombre": "Ventana de soportes y resistencias", "valor": "8 meses (168 ruedas)"},
    {"nombre": "Toques para formar una zona", "valor": "2 o más"},
    {"nombre": "Tolerancia de la zona", "valor": "2%"},
    {"nombre": "Stop", "valor": "soporte − 1%"},
    {"nombre": "Ruedas del monto promedio", "valor": "5"},
]


class ErrorParametro(ValueError):
    pass


def defectos():
    return {e["clave"]: e["defecto"] for e in EDITABLES}


def _rango(e):
    return f"{e['minimo']:g} a {e['maximo']:g}"


def leer(clave, texto):
    """Convierte lo que se escribió (texto o número) al valor del parámetro, o levanta ErrorParametro con un mensaje claro.
    Acepta coma o punto decimal. En los enteros, '1.000' es mil (punto de miles), no uno."""
    e = POR_CLAVE.get(clave)
    if e is None:
        raise ErrorParametro(f"'{clave}' no es un parámetro editable.")
    if isinstance(texto, bool):
        raise ErrorParametro(f"{e['nombre']}: valor inválido.")
    if isinstance(texto, (int, float)):
        v = float(texto)
    else:
        t = str(texto).strip().replace(" ", "")
        if e["entero"]:
            if re.fullmatch(r"\d{1,3}(\.\d{3})+", t):
                t = t.replace(".", "")
            if not re.fullmatch(r"\d+", t):
                raise ErrorParametro(f"{e['nombre']}: tiene que ser un número entero (sin decimales), por ejemplo {e['defecto']}. Recibido: '{texto}'.")
        elif not re.fullmatch(r"\d+([.,]\d+)?", t):
            raise ErrorParametro(f"{e['nombre']}: tiene que ser un número, por ejemplo {e['defecto']}. Recibido: '{texto}'.")
        v = float(t.replace(",", "."))
    if e["entero"] and v != int(v):
        raise ErrorParametro(f"{e['nombre']}: tiene que ser un número entero. Recibido: {texto}.")
    if not (e["minimo"] <= v <= e["maximo"]):
        raise ErrorParametro(f"{e['nombre']}: {v:g} está fuera del rango permitido ({_rango(e)}).")
    return int(v) if e["entero"] else v


def validar(valores):
    """Valida los cuatro valores (todos tienen que estar). Devuelve el diccionario limpio."""
    faltan = [c for c in POR_CLAVE if c not in valores]
    if faltan:
        raise ErrorParametro("Faltan parámetros: " + ", ".join(faltan))
    v = {c: leer(c, valores[c]) for c in POR_CLAVE}
    if v["bb_ventana"] < 2 * v["bb_dias"]:
        raise ErrorParametro(f"Bollinger: la ventana de detección ({v['bb_ventana']}) tiene que ser al menos el doble de los días de pendiente ({2 * v['bb_dias']}): "
                             "tienen que entrar la bajada y el giro.")
    if v["bb_ventana_listas"] < v["bb_velas_giro"]:
        raise ErrorParametro(f"Listados de Bollinger: las ruedas desde la caída ({v['bb_ventana_listas']}) tienen que ser al menos las velas de levantada ({v['bb_velas_giro']}): "
                             "si no, la caída no puede haber terminado antes de ellas.")
    if v["bb_peso1"] + v["bb_peso2"] + v["bb_peso3"] <= 0:
        raise ErrorParametro("Bollinger: al menos un tramo tiene que tener peso mayor que cero.")
    return v


def cargar(ruta=ARCHIVO):
    """Los valores guardados; si todavía no hay archivo, los de fábrica. Un archivo inválido NO se corrige: se avisa."""
    if not os.path.exists(ruta):
        return defectos()
    with open(ruta, encoding="utf-8") as f:
        guardados = json.load(f)
    try:
        return validar({**defectos(), **guardados})
    except ErrorParametro as ex:
        raise ErrorParametro(f"El archivo {os.path.basename(ruta)} tiene valores inválidos ({ex}). Corregilo o borralo para volver a los valores de fábrica.")


def guardar(valores, ruta=ARCHIVO):
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(validar(valores), f, ensure_ascii=False, indent=1)
        f.write("\n")


def combinar(guardados, pedidos):
    """Parte de los valores guardados y aplica los que se pidieron (los vacíos o None quedan como estaban). Devuelve (valores, cambios)."""
    valores = dict(guardados)
    cambios = {}
    for c, t in (pedidos or {}).items():
        if t is None or (isinstance(t, str) and not t.strip()):
            continue
        v = leer(c, t)
        if v != valores[c]:
            cambios[c] = (valores[c], v)
        valores[c] = v
    return valores, cambios


def parsear_salida(texto):
    """'1,1,1,1,5,2' → {'bb_peso1','bb_peso2','bb_peso3','bb_stop','bb_velas_caida','bb_velas_giro'}: los tres pesos de los tramos, el stop (1/0, si/no) y las velas de los dos
    listados. Se aceptan solo los cuatro primeros (peso1,peso2,peso3,stop). Vacío → {} (no se pide cambio)."""
    t = (texto or "").strip()
    if not t:
        return {}
    partes = [x.strip() for x in re.split(r"[,;]", t)]
    if len(partes) not in (4, 6, 7, 8):
        raise ErrorParametro(f"Lo otro de Bollinger va como 'peso1,peso2,peso3,stop,velas_caida,velas_giro,periodo_listados,ventana_listados' (por ejemplo 1,1,1,1,5,2,20,10; se aceptan los 4, 6 o 7 primeros); recibido: '{texto}'.")
    if partes[3].lower() in ("si", "sí", "s", "true"):
        partes[3] = "1"
    elif partes[3].lower() in ("no", "n", "false"):
        partes[3] = "0"
    return dict(zip(SALIDA_BB, partes))


def bollinger_de(valores):
    """Los parámetros de Bollinger (con el nombre que usa bollinger.py) a partir de los valores guardados."""
    v = validar(valores)
    return {"bb_periodo": v["bb_periodo"], "bb_desvios": float(v["bb_desvios"]), "bb_dias": v["bb_dias"], "bb_ventana": v["bb_ventana"],
            "bb_magnitud_pct": float(v["bb_magnitud_pct"]), "bb_pesos": [v["bb_peso1"], v["bb_peso2"], v["bb_peso3"]], "bb_stop": bool(v["bb_stop"]),
            "bb_velas_caida": v["bb_velas_caida"], "bb_velas_giro": v["bb_velas_giro"], "bb_periodo_listas": v["bb_periodo_listas"], "bb_ventana_listas": v["bb_ventana_listas"]}


def a_params(valores):
    """Diccionario de parámetros para informe.candidatos (copia de bt.PARAMS con los editables aplicados). La media corta es 3/4 de la larga
    (150 con 200): se usa para los papeles que todavía no tienen tantas ruedas de histórico."""
    v = validar(valores)
    return dict(bt.PARAMS, piso_monto=v["piso_millones"] * 1e6, ma_larga=v["media_ruedas"], ma_corta=max(10, round(v["media_ruedas"] * 0.75)),
                recorrido_min=v["recorrido_min_pct"] / 100, rb_min=float(v["rb_min"]), **bollinger_de(v))


def descripcion(valores):
    """Lo que se muestra en el informe: cada editable con su valor, el de fábrica y si fue cambiado; y los fijos."""
    v = validar(valores)
    return {"editables": [{"clave": e["clave"], "nombre": e["nombre"], "detalle": e["detalle"], "unidad": e["unidad"], "valor": v[e["clave"]],
                           "defecto": e["defecto"], "cambiado": v[e["clave"]] != e["defecto"], "minimo": e["minimo"], "maximo": e["maximo"],
                           "entero": e["entero"], "grupo": e["grupo"], "tipo": e.get("tipo", "numero")} for e in EDITABLES],
            "fijos": FIJOS}
