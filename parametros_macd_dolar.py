"""
parametros_macd_dolar.py — Parámetros EDITABLES de la pestaña SAINT MARINO DÓLAR. Son los mismos de San Marino (parametros_macd.py: MACD, ruedas, distancia, listado 2 y Vortex, con los mismos valores
de fábrica) salvo el piso de liquidez, que acá se mide en miles de US$ y sobre la línea D del CEDEAR en BYMA. Valores propios: se guardan en parametros_macd_dolar.json (no pisan los de San Marino).
Mismas reglas que parametros.py: fuera de rango o con texto inválido la corrida NO corre y no guarda nada.

  dolar_piso_miles   Piso de liquidez para marcar «operable»: US$ (en miles) que se operaron HOY en la línea D del CEDEAR en BYMA (data912, foto del día). No descarta papeles: los de menos monto quedan «solo señal».
"""
import json, os

import macd
import parametros
import parametros_macd as base
from parametros import ErrorParametro

ARCHIVO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "parametros_macd_dolar.json")
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config_macd_dolar.json"), encoding="utf-8") as _f:
    _D = json.load(_f)

PISO = {"clave": "dolar_piso_miles", "nombre": "Piso de liquidez del CEDEAR en dólares", "detalle": "miles de US$ operados hoy en la línea D del CEDEAR en BYMA (no descarta: marca «solo señal»)",
        "unidad": "mil US$", "defecto": _D["piso_miles_usd"], "minimo": 1, "maximo": 1000000, "entero": True}
EDITABLES = [PISO if e["clave"] == "macd_piso_millones" else dict(e) for e in base.EDITABLES]
POR_CLAVE = {e["clave"]: e for e in EDITABLES}


def defectos():
    return {e["clave"]: e["defecto"] for e in EDITABLES}


def leer(clave, texto):
    return parametros.leer(clave, texto, POR_CLAVE)


def validar(valores):
    """Valida todos los valores (tienen que estar todos). Devuelve el diccionario limpio."""
    faltan = [c for c in POR_CLAVE if c not in valores]
    if faltan:
        raise ErrorParametro("Faltan parámetros: " + ", ".join(faltan))
    v = {c: leer(c, valores[c]) for c in POR_CLAVE}
    if v["macd_rapido"] >= v["macd_lento"]:
        raise ErrorParametro(f"MACD: el período rápido ({v['macd_rapido']}) tiene que ser menor que el lento ({v['macd_lento']}).")
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


def descripcion(valores):
    """Lo que se muestra en el informe: cada editable con su valor, el de fábrica y si fue cambiado."""
    v = validar(valores)
    return {"editables": [{"clave": e["clave"], "nombre": e["nombre"], "detalle": e["detalle"], "unidad": e["unidad"], "valor": v[e["clave"]], "defecto": e["defecto"],
                           "cambiado": v[e["clave"]] != e["defecto"], "minimo": e["minimo"], "maximo": e["maximo"], "entero": e["entero"], "tipo": e.get("tipo", "numero")}
                          for e in EDITABLES]}


def de_params(valores):
    """Los parámetros con el nombre que usa macd.py. El piso (miles de US$) se pasa a «millones» (0,1 = US$ 100.000) porque macd.py mide el piso en millones de la moneda del papel."""
    v = dict(valores)
    v["macd_piso_millones"] = v.pop("dolar_piso_miles") / 1000.0
    return macd.de_params(v)
