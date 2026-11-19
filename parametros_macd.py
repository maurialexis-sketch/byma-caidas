"""
parametros_macd.py — Parámetros EDITABLES de la pestaña SAN MARINO (MACD). Mismas reglas que parametros.py: validados contra un rango; fuera de rango o con texto inválido la corrida NO corre
y no guarda nada (no se corrige en silencio). Los valores de fábrica salen de config_macd.json (no están escritos acá) y los últimos usados quedan en parametros_macd.json (se commitea con
el informe, y la corrida siguiente —incluida la automática— parte de ellos).

  macd_rapido / macd_lento / macd_senal   Períodos del MACD (12 / 26 / 9): EMA rápida, EMA lenta y EMA de la señal.
  macd_dias                               Ruedas seguidas con el histograma subiendo (las dos líneas acercándose).
  macd_dist_pct                           Distancia máxima entre el MACD y la señal, en % del precio.
  macd_bajo_cero                          1 = además el MACD tiene que estar por debajo de cero; 0 = sin esa condición.
  macd_piso_millones                      Piso de liquidez para marcar «operable» (no descarta papeles: los de menos monto quedan como «solo señal»).
  macd2_dist_pct                          LISTADO 2: hasta cuánto por encima de la señal puede estar el MACD (en % del precio) para considerar que «despegó».
  macd2_ruedas                            LISTADO 2: cuántas ruedas atrás, como máximo, pudo haber cruzado hacia arriba (0 = hoy).
  vortex_exigir                           LISTADO 2: 1 = además el indicador Vortex tiene que confirmar (VI+ > VI−); 0 = sin esa condición (el Vortex se muestra igual).
"""
import json, os

import macd
import parametros
from parametros import ErrorParametro

ARCHIVO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "parametros_macd.json")
_C = macd.cargar()

EDITABLES = [
    {"clave": "macd_rapido", "nombre": "Período de la EMA rápida", "detalle": "ruedas de la media exponencial rápida del MACD", "unidad": "ruedas",
     "defecto": _C["rapido"], "minimo": 2, "maximo": 100, "entero": True},
    {"clave": "macd_lento", "nombre": "Período de la EMA lenta", "detalle": "ruedas de la media exponencial lenta del MACD (mayor que la rápida)", "unidad": "ruedas",
     "defecto": _C["lento"], "minimo": 3, "maximo": 200, "entero": True},
    {"clave": "macd_senal", "nombre": "Período de la señal", "detalle": "ruedas de la media exponencial del MACD (la línea roja)", "unidad": "ruedas",
     "defecto": _C["senal"], "minimo": 2, "maximo": 100, "entero": True},
    {"clave": "macd_dias", "nombre": "Ruedas con el histograma subiendo", "detalle": "ruedas seguidas, terminando hoy, en que el MACD se acerca a la señal", "unidad": "ruedas",
     "defecto": _C["dias_subiendo"], "minimo": 1, "maximo": 10, "entero": True},
    {"clave": "macd_dist_pct", "nombre": "Distancia máxima a la señal", "detalle": "|MACD − señal| como % del precio: qué tan cerca tiene que estar de cruzar", "unidad": "%",
     "defecto": _C["distancia_max_pct"], "minimo": 0.01, "maximo": 10, "entero": False},
    {"clave": "macd_bajo_cero", "nombre": "Exigir MACD bajo cero", "detalle": "1 = el MACD también tiene que estar por debajo de cero; 0 = cualquier nivel", "unidad": "",
     "defecto": int(_C["exigir_bajo_cero"]), "minimo": 0, "maximo": 1, "entero": True, "tipo": "si_no"},
    {"clave": "macd_piso_millones", "nombre": "Piso de liquidez para «operable»", "detalle": "monto promedio de 5 ruedas, en millones de $ (no descarta: marca «solo señal»)", "unidad": "M $",
     "defecto": _C["piso_millones"], "minimo": 1, "maximo": 100000, "entero": True},
    {"clave": "macd2_dist_pct", "nombre": "Listado 2: separación máxima sobre la señal", "detalle": "MACD − señal como % del precio: cuánto pudo alejarse del cruce y seguir contando", "unidad": "%",
     "defecto": _C["cruce2_distancia_max_pct"], "minimo": 0.01, "maximo": 5, "entero": False},
    {"clave": "macd2_ruedas", "nombre": "Listado 2: ruedas desde el cruce", "detalle": "cuántas ruedas atrás, como máximo, cruzó hacia arriba (0 = cruzó hoy)", "unidad": "ruedas",
     "defecto": _C["cruce2_ruedas"], "minimo": 0, "maximo": 20, "entero": True},
    {"clave": "vortex_exigir", "nombre": "Listado 2: exigir confirmación del Vortex", "detalle": "1 = VI+ tiene que estar por encima de VI− (el Vortex confirma el cruce); 0 = no se exige", "unidad": "",
     "defecto": int(_C["vortex_exigir"]), "minimo": 0, "maximo": 1, "entero": True, "tipo": "si_no"},
]
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
