"""
fusionar_indice.py — Resuelve un conflicto de `git rebase` en docs/data/indice.json (y en parametros.json) cuando dos corridas (informe, backtest, compra) guardan casi a la vez.

Cada corrida agrega SU propia entrada al índice y su propio archivo de datos (los nombres de archivo no se pisan), así que el único conflicto posible es el del índice: se resuelve con la
UNIÓN de las entradas de las dos versiones (sin repetir archivos), ordenadas de la más nueva a la más vieja. En un rebase, la etapa 2 es la rama de destino (lo que ya estaba publicado) y la
etapa 3 es la corrida que se está guardando. parametros.json (valores editables guardados) se queda con el de la corrida que se está guardando.
Sale con código 0 si dejó todo resuelto y 1 si hay algún otro conflicto que no sabe resolver.
"""
import json, subprocess, sys

INDICE = "docs/data/indice.json"
PARAMETROS = "parametros.json"


def fusionar(a, b):
    """Unión de dos listas de entradas del índice (por archivo), de la más nueva a la más vieja."""
    por_archivo = {}
    for e in list(a) + list(b):
        por_archivo[e["archivo"]] = e
    return sorted(por_archivo.values(), key=lambda e: (e["fecha"], e["hora"]), reverse=True)


def _etapa(n, ruta):
    r = subprocess.run(["git", "show", f":{n}:{ruta}"], capture_output=True, text=True, encoding="utf-8")
    return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else []


def _conflictos():
    r = subprocess.run(["git", "diff", "--name-only", "--diff-filter=U"], capture_output=True, text=True, encoding="utf-8")
    return [x for x in r.stdout.splitlines() if x.strip()]


def main():
    pendientes = _conflictos()
    otros = [x for x in pendientes if x not in (INDICE, PARAMETROS)]
    if otros:
        print("Conflicto que no sé resolver:", ", ".join(otros), file=sys.stderr)
        return 1
    if INDICE in pendientes:
        union = fusionar(_etapa(2, INDICE), _etapa(3, INDICE))
        with open(INDICE, "w", encoding="utf-8") as f:
            json.dump(union, f, ensure_ascii=False)
        subprocess.run(["git", "add", INDICE], check=True)
        print(f"{INDICE}: fusionado ({len(union)} entradas)")
    if PARAMETROS in pendientes:
        subprocess.run(["git", "checkout", "--theirs", PARAMETROS], check=True)
        subprocess.run(["git", "add", PARAMETROS], check=True)
        print(f"{PARAMETROS}: se queda con el de esta corrida")
    return 0


if __name__ == "__main__":
    sys.exit(main())
