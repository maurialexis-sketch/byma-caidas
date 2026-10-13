"""
parametros.py — Parámetros EDITABLES del informe de candidatos, y los FIJOS que no se pueden tocar.

Editables (cuatro, validados contra un rango; fuera de rango o con texto inválido el informe NO corre, no se corrige en silencio):
  piso_millones       Piso de liquidez: monto promedio de 5 ruedas, en millones de pesos           (hoy 1.000)
  media_ruedas        Largo de la media de tendencia, en ruedas                                    (hoy 200)
  recorrido_min_pct   Recorrido mínimo a la resistencia, en %                                      (hoy 10)
  rb_min              Relación riesgo/beneficio mínima                                             (hoy 2)
Fijos (estructura del cálculo de niveles; no hay forma de cambiarlos desde la página ni desde el workflow): ventana de 8 meses (168 ruedas),
2+ toques, tolerancia 2%, stop = soporte − 1%, 5 ruedas para el monto promedio.

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
POR_CLAVE = {e["clave"]: e for e in EDITABLES}

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
    return {c: leer(c, valores[c]) for c in POR_CLAVE}


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


def a_params(valores):
    """Diccionario de parámetros para informe.candidatos (copia de bt.PARAMS con los editables aplicados). La media corta es 3/4 de la larga
    (150 con 200): se usa para los papeles que todavía no tienen tantas ruedas de histórico."""
    v = validar(valores)
    return dict(bt.PARAMS, piso_monto=v["piso_millones"] * 1e6, ma_larga=v["media_ruedas"], ma_corta=max(10, round(v["media_ruedas"] * 0.75)),
                recorrido_min=v["recorrido_min_pct"] / 100, rb_min=float(v["rb_min"]))


def descripcion(valores):
    """Lo que se muestra en el informe: cada editable con su valor, el de fábrica y si fue cambiado; y los fijos."""
    v = validar(valores)
    return {"editables": [{"clave": e["clave"], "nombre": e["nombre"], "detalle": e["detalle"], "unidad": e["unidad"], "valor": v[e["clave"]],
                           "defecto": e["defecto"], "cambiado": v[e["clave"]] != e["defecto"], "minimo": e["minimo"], "maximo": e["maximo"],
                           "entero": e["entero"]} for e in EDITABLES],
            "fijos": FIJOS}
