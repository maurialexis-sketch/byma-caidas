# Caídas BYMA — guía para Claude Code

Herramienta de análisis de acciones y CEDEARs de BYMA en pesos. Corre en GitHub Actions y se publica en GitHub Pages (`docs/`), con los informes **cifrados**. El README tiene el detalle de cada estrategia.

## Reglas de trabajo (las pidió el dueño del proyecto)
- **Una sola cosa por experimento.** No optimizar parámetros para que un resultado salga bien. Mostrar los datos honestos, incluso cuando la estrategia pierde o no le gana al índice.
- **Toda estrategia se compara contra la vara** (Merval para acciones, S&P 500 en pesos para CEDEARs; en universo mixto, el mayor) y con los costos de siempre (≈0,70% por lado). Informar siempre cantidad de operaciones y el resultado sin las 3 mejores.
- **No bajar un filtro para llenar una lista.** Si nada cumple, la página lo dice.
- **Nunca pedir ni escribir la clave de acceso en el chat, en el código, en commits ni en logs.** Vive solo en el secreto `CLAVE_ACCESO` de GitHub. No imprimir tickers ni resultados de los informes en los logs de Actions (el repositorio es público; el contenido de los informes está cifrado a propósito).
- No subir informes descifrados ni archivos de prueba (`--solo-claro`) al repositorio.
- Las cifras y los nombres de papeles de los informes son datos de BYMA con ~20 min de atraso; BYMA entrega como máximo ~2 años de histórico.

## Cómo está armado
- `conector.py`, `config.py`: acceso a BYMA. `backtest.py`: motor de backtest. Estrategias: `ruptura.py`, `grilla.py`, `escalonada.py`, `bollinger.py`.
- `indicadores.py` + `config_indicadores.json`: medias móviles y Bollinger (los períodos NO van escritos en el código).
- `informe.py` / `generar_informe.py`: informe de candidatos. `generar_backtest.py`: todas las variantes de backtest.
- `parametros.py` + `parametros.json`: parámetros editables del informe y de Bollinger (se guardan al correr).
- `docs/index.html`: la página (un solo archivo, JS sin librerías, tiene que verse bien en celular). `docs/data/`: informes cifrados.
- Workflows en `.github/workflows/`: `informe.yml` (a demanda y L-V 18:00), `backtest.yml` (a demanda), `caidas.yml` (compra/venta). Guardan con `publicar_cambios.sh`.

## Antes de dar algo por terminado
1. Correr **todas** las pruebas, una por una (`python <nombre>.py`):
   `tests_publicar`, `tests_indicadores`, `tests_parametros`, `tests_bollinger`, `tests_escalonada`, `tests_informe`, `tests_backtest`, `tests_ruptura`, `tests_indices`, `tests_sectores` y `tests`. Deben pasar todas.
2. Si se toca `docs/index.html`, revisar que el JS no tenga errores de sintaxis y que se vea bien en pantalla de celular.
3. Si se agrega un parámetro editable: `parametros.py` es la fuente; la página repite sus valores y una prueba verifica que coincidan. GitHub permite **10 entradas como máximo** en un workflow manual (ya están usadas: se agrupan en `bb_otros`).
4. Actualizar el README con lo que cambió y por qué.

## Cosas que ya nos mordieron
- Un nombre de archivo o ticker no puede pisar a otro: los informes llevan fecha, hora y función en el nombre.
- Dos workflows lanzados juntos chocan en `indice.json`: por eso se guarda con `publicar_cambios.sh` (fusiona el índice y falla en voz alta si no puede).
- Los saltos de precio de razón entera (2:1, 3:1) se tratan como splits en `Papel`: cuidado con los datos de prueba.
- Si una lógica no da lo que el dueño espera (por ejemplo un papel que "debería" aparecer), mostrar día por día por qué, no forzar la regla.
- En `generar_informe.py` la variable `clave` es la contraseña de cifrado: no usarla como variable de bucle ni reasignarla (el 14/11 un `for clave, ...` hizo que dos informes se cifraran con la palabra 'lista2' y nadie pudiera abrirlos). Una prueba en `tests_informe.py` lo vigila. `verificar_informes.py` (workflow «Verificar informes») dice qué informes publicados abre la clave guardada en GitHub, sin imprimir contenido.
