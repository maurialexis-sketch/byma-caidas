#!/usr/bin/env bash
# Guarda en el repositorio lo que generó una corrida (informes cifrados y parámetros) sin perder nada si otra corrida guardó antes.
# Uso: bash publicar_cambios.sh "mensaje del commit"     (lo usan los tres workflows; escribe cambios=true/false en $GITHUB_OUTPUT)
# Si, después de varios intentos, no se pudo publicar, SALE CON ERROR (antes fallaba en silencio y el informe se perdía).
set -u
SALIDA="${GITHUB_OUTPUT:-/dev/null}"
RAMA="${RAMA:-main}"
git config user.name "caidas-bot"
git config user.email "actions@users.noreply.github.com"
git add docs/data
if [ -f parametros.json ]; then git add parametros.json; fi
if git diff --cached --quiet; then echo "cambios=false" >> "$SALIDA"; exit 0; fi
git commit -q -m "$1"
ok=0
for intento in 1 2 3 4 5; do
  git fetch -q origin "$RAMA"
  if ! git rebase "origin/$RAMA"; then
    # otra corrida guardó antes y tocó el mismo índice: se fusionan las entradas y se sigue
    if python fusionar_indice.py && GIT_EDITOR=true git rebase --continue; then :; else
      git rebase --abort 2>/dev/null
      sleep "${ESPERA:-5}"
      continue
    fi
  fi
  if git push -q origin "HEAD:$RAMA"; then ok=1; break; fi
  sleep "${ESPERA:-5}"
done
if [ "$ok" != 1 ]; then
  echo "::error::No se pudo guardar el informe en el repositorio después de 5 intentos"
  exit 1
fi
echo "cambios=true" >> "$SALIDA"
