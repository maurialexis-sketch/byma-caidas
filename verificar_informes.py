"""Diagnostico: prueba si la clave del secreto CLAVE_ACCESO abre cada informe publicado. Solo imprime nombre de archivo y si abrio (el contenido nunca se imprime)."""
import json, os, sys
import generar

meta = generar.cargar_meta()
key = generar.derivar(os.environ["CLAVE_ACCESO"], meta)
with open(os.path.join(generar.DATOS, "indice.json"), encoding="utf-8") as f:
    indice = json.load(f)
malos = 0
for e in indice[:int(sys.argv[1]) if len(sys.argv) > 1 else 12]:
    ruta = os.path.join(generar.DATOS, e["archivo"])
    try:
        with open(ruta, encoding="utf-8") as f:
            env = json.load(f)
        generar.descifrar(env, key)
        estado = "ABRE"
    except Exception as ex:
        estado = "NO ABRE (" + type(ex).__name__ + ")"
        malos += 1
    print(e["fecha"], e["hora"], e["funcion"], os.path.getsize(ruta), estado)
print("fallan:", malos)
