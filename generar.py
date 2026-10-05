"""
generar.py — Corre la FUNCIÓN COMPRA (12:00) o VENTA (15:50) y publica el informe CIFRADO en docs/data.

    python generar.py compra [--esperar]     CLAVE_ACCESO en el entorno (en GitHub: un "secret")
    python generar.py venta  [--esperar]

--esperar: GitHub Actions larga los trabajos programados con atraso, así que el workflow arranca ~30 min antes
y este script espera hasta la hora exacta, medida con reloj.py (fuentes externas, no el reloj del servidor).
Si el trabajo arranca tarde, corre enseguida y el informe dice a qué hora corrió de verdad.

El informe se cifra (AES-256-GCM, clave derivada de CLAVE_ACCESO con PBKDF2-SHA256, 600.000 vueltas). Lo que queda
publicado en Pages es ilegible sin la clave; la página lo descifra en el celular y la clave nunca sale de ahí.
"""
import argparse, base64, hashlib, json, os, sys, time
from datetime import timedelta

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import caidas, config, conector, reloj

CARPETA = os.path.dirname(os.path.abspath(__file__))
DATOS = os.path.join(CARPETA, "docs", "data")
RANURAS = {"compra": (12, 0), "venta": (15, 50)}
ESPERA_MAX_MIN = 45        # no se espera más que esto (si el trabajo arranca muy temprano, corre igual)
ITERACIONES = 600_000
MIN_CLAVE = 12


def b64(b):
    return base64.b64encode(b).decode()


# ---------------------------------------------------------------- cifrado

def cargar_meta(carpeta=DATOS):
    """Parámetros públicos de la derivación (sal + vueltas). La sal se crea una vez y se reutiliza."""
    ruta = os.path.join(carpeta, "meta.json")
    if os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    os.makedirs(carpeta, exist_ok=True)
    meta = {"v": 1, "salt": b64(os.urandom(16)), "iter": ITERACIONES}
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(meta, f)
    return meta


def derivar(clave, meta):
    return hashlib.pbkdf2_hmac("sha256", clave.encode("utf-8"), base64.b64decode(meta["salt"]), meta["iter"], 32)


def cifrar(obj, key):
    iv = os.urandom(12)
    ct = AESGCM(key).encrypt(iv, json.dumps(obj, ensure_ascii=False).encode("utf-8"), None)   # ct incluye la etiqueta
    return {"v": 1, "iv": b64(iv), "ct": b64(ct)}


def descifrar(envoltorio, key):
    return json.loads(AESGCM(key).decrypt(base64.b64decode(envoltorio["iv"]), base64.b64decode(envoltorio["ct"]), None))


# ---------------------------------------------------------------- horario

def segundos_para_ranura(ahora, fn):
    """Segundos que faltan para la hora de `fn` si es en menos de ESPERA_MAX_MIN; si no (ya pasó o falta mucho), 0."""
    h, m = RANURAS[fn]
    resto = (ahora.replace(hour=h, minute=m, second=0, microsecond=0) - ahora).total_seconds()
    return resto if 0 < resto <= ESPERA_MAX_MIN * 60 else 0


def esperar_hasta(fn, rel):
    espera = segundos_para_ranura(rel.ahora(), fn)
    if espera:
        print(f"Esperando {espera / 60:.0f} min hasta las {RANURAS[fn][0]:02d}:{RANURAS[fn][1]:02d} (hora verificada)...", flush=True)
    while True:
        resto = segundos_para_ranura(rel.ahora(), fn)
        if resto <= 0:
            return
        time.sleep(min(resto, 20))


# ---------------------------------------------------------------- contexto del informe

def _hora(texto):
    """'HH:MM:SS' o 'HH:MM' -> (h, m, s); None si no se puede leer."""
    try:
        p = [int(x) for x in texto.split(":")]
        return (p + [0, 0])[:3] if 1 < len(p) <= 3 else None
    except ValueError:
        return None


def atraso_precios(datos, ahora):
    """(hora del último precio del panel 'HH:MM:SS', minutos de atraso). El panel gratuito de BYMA viene demorado ~20 min."""
    horas = [h for h in (_hora(d["fuente_precio"].split(" ", 1)[1]) for d in datos
                         if d["fuente_precio"].startswith("panel ")) if h]
    if not horas:
        return None, None
    h, m, s = max(horas)
    dato = ahora.replace(hour=h, minute=m, second=s, microsecond=0)
    return f"{h:02d}:{m:02d}:{s:02d}", max(0, round((ahora - dato).total_seconds() / 60))


def advertencias(datos, ahora):
    adv = []
    _, atraso = atraso_precios(datos, ahora)
    if atraso is not None and atraso > 45 and reloj.mercado_abierto(ahora):
        adv.append(f"Los precios del panel tienen {atraso} min de atraso (lo normal es ~20): BYMA puede estar demorado.")
    desfasados = sum(any(a.startswith("cierre previo panel") for a in d["alertas"]) for d in datos)
    if datos and desfasados >= max(2, len(datos) / 2):
        adv.append("El cierre previo del panel no coincide con el histórico en la mayoría de los papeles: "
                   "puede ser feriado o falta de rueda. Tomá el resultado con cuidado.")
    if ahora.weekday() >= 5:
        adv.append("Hoy no es día hábil.")
    return adv


# ---------------------------------------------------------------- publicación

def guardar(fn, r, key, carpeta=DATOS):
    """Escribe el informe cifrado y suma la entrada al índice (que solo dice fecha, hora y archivo)."""
    ahora = r["contexto"]["hora_mercado"]                      # 2026-10-05T12:01:10-03:00
    fecha, hora = ahora[:10], ahora[11:16]
    archivo = f"{fecha}-{hora.replace(':', '')}-{fn}.json"
    os.makedirs(carpeta, exist_ok=True)
    with open(os.path.join(carpeta, archivo), "w", encoding="utf-8") as f:
        json.dump(cifrar(r, key), f)
    ruta = os.path.join(carpeta, "indice.json")
    indice = []
    if os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as f:
            indice = json.load(f)
    indice = [e for e in indice if e["archivo"] != archivo] + [{"archivo": archivo, "fecha": fecha, "hora": hora, "funcion": fn}]
    indice.sort(key=lambda e: (e["fecha"], e["hora"]), reverse=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(indice, f, ensure_ascii=False)
    return archivo


def main():
    ap = argparse.ArgumentParser(description="Genera el informe cifrado de COMPRA o VENTA")
    ap.add_argument("funcion", choices=list(RANURAS))
    ap.add_argument("--esperar", action="store_true", help="esperar hasta la hora exacta de la función")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    clave = os.environ.get("CLAVE_ACCESO", "")
    if len(clave) < MIN_CLAVE:
        sys.exit(f"Falta CLAVE_ACCESO (mínimo {MIN_CLAVE} caracteres). Sin clave no se publica nada.")
    if a.funcion == "venta" and not caidas.VENTA_DEFINIDA:
        print("La función VENTA todavía no está definida: no se genera informe.")
        return

    rel = reloj.Reloj()
    conector.RELOJ = rel.epoch   # el histórico también se pide con la hora verificada
    rel.sincronizar()
    print(f"Hora de mercado: {rel.ahora().isoformat(timespec='seconds')} — {rel.fuente}; "
          f"reloj del servidor desviado {rel.desvio_servidor_s} s", flush=True)
    if a.esperar:
        esperar_hasta(a.funcion, rel)

    ahora = rel.ahora()
    datos, meta = caidas.cargar_datos(["lider"], config.PISO_MONTO, ahora)
    r = caidas.FUNCIONES[a.funcion](datos, meta, caidas.CERCA_SOPORTE) if a.funcion == "compra" \
        else caidas.FUNCIONES[a.funcion](datos, meta)
    hora_dato, atraso = atraso_precios(datos, ahora)
    r["contexto"] = {"hora_mercado": ahora.isoformat(timespec="seconds"), "fuente_hora": rel.fuente,
                     "mercado_abierto": reloj.mercado_abierto(ahora),
                     "origen": "programada" if a.esperar else "manual",
                     "hora_precios": hora_dato, "atraso_precios_min": atraso,
                     "advertencias": advertencias(datos, ahora)}
    archivo = guardar(a.funcion, r, derivar(clave, cargar_meta()))
    c = r["conteo"]
    print(f"{a.funcion.upper()} {r['generado']}: VERDE {c['VERDE']} · AMARILLO {c['AMARILLO']} · ROJO {c['ROJO']} "
          f"(con caída {r['con_caida']} de {r['universo']['liquidas']}). Guardado cifrado: docs/data/{archivo}")


if __name__ == "__main__":
    main()
