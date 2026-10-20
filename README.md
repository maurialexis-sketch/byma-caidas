# Caídas BYMA en GitHub (Actions + Pages)

Corre solo en GitHub, sin tu PC: un trabajo programado calcula las caídas acumuladas del panel líder de BYMA
(en pesos, monto > 1.000 M), **cifra** el informe con tu clave y lo publica en una página que abrís desde el celular
y podés instalar como app.

- **COMPRA 12:00**: caída ≥3,5% en 2 días, ≥5% en 3, ≥7% en 4 (contra el cierre previo a la ventana), con tendencia,
  distancia al soporte y semáforo VERDE / AMARILLO / ROJO (verdes primero, con el conteo de cada color).
- **VENTA 15:50**: gancho listo (`caidas.funcion_venta` y `caidas.VENTA_DEFINIDA`). Mientras no esté definida no genera nada.
- **Hora de mercado**: `reloj.py` toma la mediana de Cloudflare, Google, Microsoft y BYMA. No usa el reloj del servidor.
- **Historial**: cada informe queda guardado (cifrado) en `docs/data`, con su fecha y hora. La página tiene un selector.

## Puesta en marcha (una sola vez)
1. Subir esta carpeta a un repositorio **público** de GitHub (Pages gratis lo exige).
2. Settings → Pages → *Source*: **GitHub Actions**.
3. Settings → Secrets and variables → Actions → **New repository secret**: nombre `CLAVE_ACCESO`, valor = tu clave
   (**mínimo 12 caracteres; usá una frase larga**, ver "Seguridad"). O desde una terminal: `gh secret set CLAVE_ACCESO`.
4. Actions → *Caidas BYMA* → **Run workflow** (compra) para generar el primer informe y publicar la página.
5. En el celular (Chrome): abrir `https://TU-USUARIO.github.io/NOMBRE-DEL-REPO/`, escribir la clave, menú ⋮ →
   **Instalar app** / *Agregar a la pantalla de inicio*. La clave queda derivada en ese dispositivo; "Cerrar sesión" la borra.

## Cómo funciona el horario
GitHub atrasa los trabajos programados (a veces 30 min o más). Por eso el workflow arranca ~30 min antes (11:30 y 15:20, hora
Argentina) y `generar.py --esperar` espera hasta las 12:00 / 15:50 exactas medidas con `reloj.py`. Si GitHub llega más tarde,
corre enseguida y el informe indica la hora real. Lunes a viernes; los feriados no se conocen (ver Limitaciones).
El botón del pie de la página ("Correr ahora") abre GitHub para lanzar una corrida a mano.

## Seguridad: qué es público y qué no
- **Público**: el código (reglas y umbrales incluidos), el calendario de corridas, y los archivos cifrados de `docs/data`
  (fecha, hora y nombre de archivo se ven; el contenido no).
- **Privado**: el contenido de los informes. Se cifra con AES-256-GCM; la clave se deriva de `CLAVE_ACCESO` con PBKDF2-SHA256
  (600.000 vueltas) y la descifra el navegador. La clave nunca viaja ni se guarda en texto.
- **Límite real**: como los archivos son públicos, cualquiera puede bajarlos e intentar adivinar la clave offline, sin que
  nada lo frene (un servidor sí podría bloquear intentos). Con una frase larga y aleatoria (5+ palabras o 16+ caracteres) es
  inviable; con una clave corta, no. Los datos de origen son públicos de BYMA, así que lo que se protege es tu selección y tus señales.

## Limitaciones
- **Los precios de BYMA vienen con ~20-25 min de atraso** (datos abiertos): el "precio de ahora" de las 12:00 es el de ~11:35.
  La página lo muestra y avisa si el atraso es anormal (más de 45 min).
- **No hay botón "ejecutar" propio**: una página estática no puede correr Python. "Correr ahora" lanza el workflow en GitHub.
- **Feriados**: sin calendario. Se avisa si el cierre previo del panel no coincide con el histórico en la mayoría de los papeles.
- **GitHub pausa los programados** si el repositorio está 60 días sin actividad (cada informe es un commit, lo que ayuda,
  pero no está garantizado). Si llega el aviso, se reactiva desde Actions.
- BYMA limita el ritmo (503 intermitentes, más desde la nube): 3 papeles en paralelo con reintentos.

## Backtest de la estrategia base (pestaña BACKTEST)
Se lanza a pedido: Actions → **Backtest** → *Run workflow*. Baja el histórico de ~680 papeles (acciones y CEDEARs en pesos), corre
`backtest.py`, lo compara contra el Merval y publica el resultado cifrado en la misma página, con la misma clave.
- **Reglas fijas** (sin optimizar): entrada al cierre de un día verde en un papel que venía en caída (las mismas ventanas 3,5/5/7%),
  cuyo mínimo tocó un soporte de 8 meses; salida por resistencia de 8 meses, ruptura del soporte (−1%) o 20 ruedas; máximo 2
  posiciones, cada una con la mitad del efectivo libre; liquidez ≥ 1.000 M medida con los datos de cada época. Detalle en `backtest.py`.
- **Costos** (supuestos en `PARAMS`, no los de tu broker): 0,50% de comisión + 0,08% de derechos de mercado + 21% de IVA por lado
  (≈ 0,70% por lado). Impuesto a las ganancias: 0 (verificá tu caso con un contador; acá no está modelado).
- **Salida**: ganancia total ($ y %), profit factor, payoff, max drawdown (% y $), % de ganadoras, cantidad de trades, duración media,
  ganancia media por trade, retorno anual promedio y CAGR; año por año; lista de operaciones; curva de capital contra el Merval.
  Además, dos variantes informativas: 50% del patrimonio por posición y la base sin costos.
- **Límites de los datos**: BYMA entrega 2 años como máximo (se probó pedir más) y los soportes necesitan 8 meses previos, así que el
  tramo operable es de unos 16 meses. BYMA no publica el histórico del S&P MERVAL: se toma de Yahoo Finance (^MERV), cuyo último valor
  coincidió con el de BYMA. El universo son los papeles que cotizan hoy (sesgo de supervivencia) y el piso de 1.000 M es nominal.
- **Variantes** (Actions → Backtest → *Run workflow* → `variante`): `base` es la estrategia original; `filtro_tendencia` agrega UNA
  regla a la entrada: el cierre tiene que estar por encima de su media móvil de 200 ruedas (150 si el papel no tiene 200 de histórico).
  Esa corrida también corre la base con los mismos datos y publica la comparación lado a lado. Con el filtro apagado el motor
  reproduce la base exactamente. Cada corrida queda en el historial de la pestaña con su etiqueta.
- **Estrategia de ruptura al alza** (`ruptura.py`, separada de la de caídas): variante `ruptura`. Entra al cierre cuando un papel líquido, en
  tendencia alcista (cierre sobre su media de 200 ruedas; 150 si no hay 200), cierra por encima de una resistencia de 8 meses que el cierre
  anterior no había superado. Sale si vuelve a **cerrar** por debajo de esa resistencia (sin stop intradiario) o a las 20 ruedas. Misma
  gestión y costos. La corrida también ejecuta la de caídas con los mismos datos y publica la comparación contra el Merval.
- **Ruptura con trailing stop** (variante `ruptura_trailing`): UN solo cambio en la salida. Se reemplazan las 20 ruedas por un trailing del 15%:
  arranca 15% bajo el cierre de entrada, se recalcula cada día como 15% bajo el máximo cierre desde la compra, nunca baja, y se vende cuando el
  cierre lo toca (a ese cierre). Sin límite de días. Dos versiones: con el stop de ruptura como salida adicional, y solo trailing. Publica dos
  informes con la misma comparación contra la ruptura con salida por tiempo, la concentración de la ganancia (¿depende de 3 operaciones?) y la
  sensibilidad a la fecha de inicio. Sin salida por tiempo, las posiciones pueden quedar abiertas meses ocupando los 2 lugares: las abiertas se
  informan aparte y no entran en las métricas de operaciones cerradas.
- **Grilla de la ruptura con solo trailing** (variante `grilla_ruptura`, `grilla.py`): 2/3/5 posiciones (cada una 1/N del patrimonio) cruzado con trailing
  15%/20%, en una sola pasada. Para cada celda mide la estabilidad: simula 17 días de arranque (uno por semana) y muestra la amplitud entre el mejor y el
  peor retorno, el peor arranque, cuántos dan ganancia y cuántos le ganan al Merval del mismo tramo. La más estable es la de menor amplitud (no la de más ganancia).
- **Ruptura con salida escalonada** (variante `ruptura_escalonada`, `escalonada.py`; estrategia NUEVA, no modifica las anteriores): MISMA entrada de la ruptura
  (el generador usa `ruptura.senales_ruptura`, y la corrida verifica que las entradas coincidan con las de la comparación). Salida por tramos sobre el precio de compra,
  evaluada con cierres: 40% de la posición al +10%, otro 40% al +15% y el 20% restante al +20% (un cierre que cruza varios escalones vende todos a ese cierre).
  Stop inicial: cierre a −8% o menos de la compra, antes de tocar el +10%, vende todo lo que quede. Desde el primer cierre en +10% el stop pasa a un trailing de 8%
  bajo el máximo cierre (nunca baja) y reemplaza al inicial. Sin límite de ruedas. Acciones enteras (el 40% se redondea hacia abajo; el último tramo vende el resto).
  Cartera de 3 posiciones de 1/3 del patrimonio; **cada venta parcial paga su costo** (≈0,70% de SU monto; no se modela un mínimo por orden del broker). El simulador
  de cartera por tramos es `escalonada.simular_escalonada` (el de siempre, `bt.simular`, no se tocó; `bt.correr` solo recibió un parámetro opcional `simulador`).
  El informe compara contra la ruptura con solo trailing 15% en 3 posiciones (misma cartera y costos) y contra la vara, y agrega una tabla de «Cuánto pesó la
  comisión» (costos pagados, órdenes, costo por operación completa y efecto sobre el retorno comparando con la misma corrida sin comisiones). Un cierre que cruza el stop
  se vende a ESE cierre, así que una pérdida puede superar el −8% (gaps). Pruebas: `python tests_escalonada.py` (19).
- **Índices de referencia y vara fija** (`indices.py`): el Merval y el S&P 500 se guardan solo como series de referencia, nunca como activos operables
  (no se convierten en papel ni generan señales). En TODO backtest, el índice del mercado correspondiente es la vara a superar: Merval para acciones,
  S&P 500 en pesos para CEDEARs y, en un universo mixto, el de mayor retorno. Si la estrategia no lo supera (empatar tampoco), el informe lo marca en rojo
  ("✗ no supera la vara") en el encabezado, en cada tabla comparativa y en una advertencia. BYMA no publica el histórico de ningún índice: el Merval y el
  S&P 500 en dólares salen de Yahoo Finance (^MERV, ^GSPC) y el **S&P 500 en pesos se aproxima con el CEDEAR SPY** (proxy: sigue al índice y al dólar, pero
  no es el índice). El S&P 500 en dólares se informa solo como dato, no forma la vara (moneda distinta).
- **Sectores** (`sectores.py`, `datos/sectores.json`): cada papel queda etiquetado con grupo (Merval / CEDEAR), sector y, para tecnológicas, subsector
  (IA, computadoras, satélites, otras). La clasificación es manual, está en un JSON editable y hay que revisarla; lo que no está queda 'sin_clasificar'.
  Las otras líneas de una misma empresa (AAPLB es AAPL) se cuentan como una. Filtro: `--grupo`, `--sector`, `--subsector` en `generar_backtest.py`
  (también como entradas del workflow); la vara se ajusta sola al grupo filtrado. `python sectores_resumen.py` cuenta cuántos papeles líquidos hay por sector.
- **Informe diario de candidatos** (`informe.py`, `generar_informe.py`, pestaña CANDIDATOS; workflow *Informe diario*, a demanda y automático): NO es un backtest ni una
  recomendación, es un filtro para decidir mirando el gráfico. Sobre la última rueda cerrada y el universo líquido (monto ≥ 1.000 M) muestra, como máximo 5 y
  ordenados por R/B, los papeles que cumplen TODO: cierre sobre la media de 200 ruedas (150 si no hay 200), señal RUPTURA (cierre sobre una resistencia de
  8 meses que el cierre anterior no había superado) o REBOTE (mínimo sobre un soporte de 8 meses y cierre en verde), recorrido ≥ 10% a la resistencia más
  cercana por encima y R/B ≥ 2 con stop = soporte − 1% (en una ruptura, el soporte es la resistencia recién rota). Arriba va la vara: cuánto rindió en 12 meses
  el índice correcto (S&P 500 en pesos para CEDEARs, Merval para acciones). Si nada cumple, dice «Hoy ningún activo cumple las condiciones»: no se baja
  ningún filtro para llenar la lista. Muestra cuántos pasan cada filtro y, aparte e informativamente, los que tienen señal pero no llegan.
- **Parámetros editables del informe** (`parametros.py`, `parametros.json`): cuatro valores se cambian sin tocar código, desde la pestaña CANDIDATOS (sección
  «Parámetros del informe»): piso de liquidez (monto promedio de 5 ruedas, hoy 1.000 M), largo de la media de tendencia (hoy 200 ruedas; 3/4 de ese largo si el
  papel no tiene tantas), recorrido mínimo a la resistencia (hoy 10%) y R/B mínimo (hoy 2). Cada uno tiene un rango permitido; fuera de rango o con texto
  inválido la corrida NO se hace y no se guarda nada (no se corrige en silencio). **No son editables** (estructura del cálculo de niveles): ventana de 8 meses
  (168 ruedas), 2+ toques, tolerancia 2%, stop = soporte − 1% y las 5 ruedas del monto. Si una corrida sale bien, los valores quedan guardados en
  `parametros.json` y las siguientes (incluida la automática) parten de ahí. Cada informe muestra arriba con qué parámetros se generó (y cuáles cambió).
  Un archivo `parametros.json` roto avisa y frena la corrida; borrándolo se vuelve a los valores de fábrica.
- **Ejecución del informe**: (1) **a demanda**: botón «▶ Correr ahora» en la pestaña CANDIDATOS. Una página estática no puede ejecutar nada, así que el
  botón le pide a GitHub que lance el workflow con los valores del formulario; eso necesita un permiso que se crea UNA vez (token *fine-grained* de ESTE
  repositorio, solo «Actions: Read and write») y se guarda sin cifrar en ese navegador («Cerrar sesión» lo borra). Sin permiso, la misma pantalla explica cómo
  crearlo, y también se puede lanzar a mano en Actions → *Informe diario* → *Run workflow* (ahí están los mismos cuatro valores). (2) **Automático**: lunes a
  viernes a las 18:00 de Argentina (`cron: '0 21 * * 1-5'`, UTC). Esa corrida usa `--programado`: si hoy no hubo rueda (feriado, sin operaciones, BYMA todavía no
  publicó), si BYMA no responde, si respondió menos de la mitad de las especies o si la rueda parece incompleta, **no falla ni publica un informe con datos
  viejos**: guarda un aviso cifrado (aparece en el historial de la pestaña como «SALTEADO», con el motivo y un botón al último informe válido) y deja una
  anotación en la corrida de GitHub. No hay calendario de feriados: se detecta porque no hay datos de la rueda del día. Una corrida manual nunca se saltea.
- **Estrategia de Bandas de Bollinger** (`bollinger.py`; variante `bollinger` del backtest y señal «Bollinger» del informe de CANDIDATOS; una sola detección para las dos).
  Bandas: central = media de `bb_periodo` cierres (20), ± `bb_desvios` desvíos (2). **Entrada** (al cierre; todo junto): (1) la central venía con pendiente negativa y gira a positiva
  `bb_dias` ruedas seguidas (3) subiendo al menos `bb_magnitud_pct` (1%) en esas ruedas; (2) durante la bajada los cierres estaban por debajo de la central; (3) dentro de las últimas
  `bb_ventana` ruedas (10) hay un cruce de abajo hacia arriba; (4) desde ese cruce los cierres quedan encima de la central. Una señal por giro. **Salida** por tramos con cierres (reparto
  1-1-1 editable): tramo 1 en el primer toque de la banda superior, tramo 2 en el segundo (un toque es un episodio: hay que volver a cerrar debajo de la banda para que cuente otro),
  tramo 3 cuando la central gira a pendiente negativa (se vende TODO lo que quede); **stop** (editable, `bb_stop`): cierre bajo la banda inferior vende todo. Misma cartera (3 posiciones de 1/3),
  mismos costos y mismo simulador por tramos que la ruptura escalonada. **Lecturas mías, porque el pedido no las fija**: (a) para que sea una U, la bajada tiene que haber durado al menos
  `bb_dias` ruedas (con un solo día de pendiente negativa casi cualquier subida cuenta como «giro»); por eso la ventana tiene que ser al menos el doble de `bb_dias`; (b) el cruce puede ocurrir con
  la central todavía bajando (la central es una media y gira después que el precio; exigir que los cierres de toda la bajada estén debajo hasta el giro no deja casi ninguna señal);
  (c) «toque» y stop se miden con cierres, no con máximos intradiarios. **Backtest**: recorre todo el historial (las bandas necesitan ~33 ruedas, no 8 meses), **sin filtro de tendencia**; compara
  contra la ruptura con solo trailing 15% (3 posiciones) y contra la vara, y como la ruptura arranca más tarde también muestra la misma Bollinger solo en el período de la ruptura; incluye
  cuánto pesó la comisión, cómo terminaron las operaciones, qué descarta cada condición y la sensibilidad al día de arranque. **CANDIDATOS**: es un tipo más (`BOLLINGER`) con los mismos filtros
  de liquidez, tendencia, recorrido y R/B; el recorrido va hasta la banda superior y el stop es la banda inferior (R/B = (banda sup. − precio) ÷ (precio − banda inf.)). Las señales de hoy que no pasan
  el filtro de tendencia se listan aparte como informativas. Los nueve parámetros (cinco de la entrada, tres pesos de los tramos y el stop) son editables y se guardan en `parametros.json`
  junto con los del informe: en CANDIDATOS desde el formulario, y en el backtest con las entradas `bb_*` del workflow (lo demás va junto: `bb_otros` = `peso1,peso2,peso3,stop,velas_caida,velas_giro`).
  Pruebas: `python tests_bollinger.py` (69).
- **Listados de Bollinger en CANDIDATOS** (`bollinger.estado_listas` / `bollinger.listas`, `informe.listas_bollinger`): dos listados de CEDEARs en pesos, **sin el filtro de liquidez** de
  1.000 M (en caída el volumen baja), con el monto de cada papel (promedio de 5 ruedas, monto y volumen de la última rueda) y la marca **OPERABLE** (monto promedio de 5 ruedas ≥ el piso de
  liquidez editable) o **SOLO SEÑAL**; operables primero. **Listado 1 (en caída)**: al menos `bb_velas_caida` (5) cierres seguidos, terminando en la última rueda, por debajo de la línea central
  (media de `bb_periodo` cierres, 20) y la central con pendiente negativa. **Listado 2 (giro confirmado)**: los últimos `bb_velas_giro` (2) cierres por encima de la central y la central con
  pendiente positiva esas ruedas, solo si antes el papel estuvo en el Listado 1; entre el cambio de pendiente se permiten velas atravesadas por la línea. **Lectura mía**: «antes» = en las
  últimas `bb_periodo` ruedas (sin un límite, un papel que cayó hace un año figuraría como giro para siempre). Una empresa figura una vez. Los papeles que no cotizaron en la última rueda
  (muchos CEDEARs de poco volumen no operan todos los días) no se pueden evaluar y se cuentan aparte. Las velas de los dos listados y el período son editables (formulario de CANDIDATOS; en el
  workflow viajan en `bb_otros` = `peso1,peso2,peso3,stop,velas_caida,velas_giro`; el período en `bb_periodo`). Los listados son filtros, no recomendaciones.
- **Backtest de la estrategia de los dos listados** (variante `bollinger_listas`, `bollinger.senales_listas`): entrada al cierre de la primera rueda en que un CEDEAR está en el Listado 2
  (giro confirmado tras el Listado 1; una señal por episodio de caída, identificado por la última rueda en que estuvo en el Listado 1), con liquidez (monto promedio de 5 ruedas ≥ 1.000 M:
  los listados sacan ese filtro para MOSTRAR las señales, pero para operar hace falta; si el papel gana liquidez más adelante en el mismo episodio entra ese día) y la salida escalonada de
  Bollinger. Usa el mismo estado por rueda que los listados de CANDIDATOS (una prueba verifica que no mira el futuro). Corre sobre **CEDEARs solamente**, y TODAS las comparaciones (Bollinger en U,
  ruptura escalonada, ruptura solo trailing 15%, ruptura a 20 ruedas, caídas base) se corren sobre ese mismo universo y el mismo período, con la vara = S&P 500 en pesos; por eso sus cifras
  difieren de los paneles originales (que mezclaban acciones y CEDEARs: con el universo mixto, las señales de papeles más líquidos —acciones argentinas— ocupaban los 3 lugares de la cartera). Muestra
  también, como informativo y NO operable, la misma estrategia sin filtro de liquidez, la sensibilidad al día de arranque y las señales una por una.
- **Ajuste de los listados (valores de fábrica nuevos)**: la media central de los listados pasó a ser **de 5 cierres** y tiene su propio parámetro editable, `bb_periodo_listas`, independiente del
  `bb_periodo` (20) de la estrategia de Bollinger y de su señal en la lista de candidatos (así cambiar uno no mueve al otro). El Listado 2 pasó a **1 vela** (`bb_velas_giro` = 1): la última vela cierra por
  encima de la central con la central de pendiente positiva (se mantiene la pendiente positiva porque el título del listado es «cambio de pendiente de negativa a positiva»), y solo si en las últimas
  `bb_periodo_listas` ruedas (5) el papel estuvo en el Listado 1. Listado 1 sigue en 5 o más velas seguidas bajo la central con pendiente negativa. En el workflow, el período viaja como séptimo campo de
  `bb_otros` (`peso1,peso2,peso3,stop,velas_caida,velas_giro,periodo_listados`). El backtest `bollinger_listas` publicado antes se corrió con media de 20 y 2 velas; con los valores nuevos habría que volver a correrlo.
- **Listados de Bollinger: media de 20 y regla de la ventana de 7 ruedas** (reemplaza el ajuste anterior de media 5 / 1 vela): la media de los listados vuelve a **20** (`bb_periodo_listas`, propia y
  editable). **Listado 1**: 5 o más velas seguidas con el cierre bajo la central y la central con pendiente negativa. **Listado 2**: «en las últimas `bb_ventana_listas` ruedas (7) mínimo 5 caídas y las últimas 2
  en levantada»: el papel estuvo en el Listado 1 (el episodio entero dentro de la ventana) y las últimas `bb_velas_giro` (2) velas cierran por encima de la central con la central de pendiente positiva esas
  ruedas. Con la ventana justa (7 = 5 + 2) son exactamente 5 caídas seguidas de 2 levantadas, sin velas atravesadas; una ventana más grande (por ejemplo 9) las permite. Validación: la ventana tiene que ser
  al menos caídas + levantadas. En el workflow, la ventana es el octavo campo de `bb_otros` (`peso1,peso2,peso3,stop,velas_caida,velas_giro,periodo_listados,ventana_listados`). Con media de 20 la central
  tarda en girar (su pendiente es (cierre de hoy − cierre de hace 20 ruedas) ÷ 20), por eso el Listado 2 queda con pocos papeles.
- **Listado 2 según el patrón pedido (reemplaza la versión anterior)**: todo dentro de las últimas `bb_ventana_listas` ruedas (7), en este orden: (1) fase de caída = las primeras ruedas de la ventana con el
  cierre bajo la central de 20 y la central con pendiente negativa, al menos `bb_velas_caida` (5); (2) giro confirmado = las ÚLTIMAS `bb_velas_giro` (2) ruedas con el cierre sobre la central. Ya NO se exige
  pendiente positiva (con media de 20 la central tarda en girar) ni un «haber estado en el Listado 1» aparte: la fase de caída es esa condición. Con la ventana justa (7 = 5 + 2) son exactamente 5 caídas
  seguidas de 2 levantadas; con una ventana mayor las caídas pueden estar separadas por velas atravesadas por la línea. **Validación con JD.com (CEDEAR)**, cierres reales hasta el 13/10: JD cumple el patrón
  de 7 ruedas el 08/10 (5 caídas del 30/09 al 06/10 + 07/10 y 08/10 por encima), pero el 13/10 ya llevaba 4 cierres por encima y solo 3 caídas dentro de las últimas 7 ruedas, por eso con ventana de 7 NO figura
  ese día; con ventana de 9 figura el 08/10, 09/10 y 13/10 (pendiente todavía negativa) y el 14/10 sale porque cierra bajo la central. Hay una prueba con esos cierres (`CasoJD` en `tests_bollinger.py`).
- **Listado 2: regla corregida tras el caso JD.com (reemplaza la de «todo dentro de 7 ruedas»)**: la versión de 7 ruedas exigía que las 5 caídas entraran DENTRO de las últimas 7 y dejaba afuera
  a JD.com (el 13/10 ya llevaba 4 cierres arriba; hoy 3 seguidos arriba con la pendiente ya subiendo y la caída terminada el 06/10, ocho ruedas atrás). Ahora: (1) el papel estuvo en el Listado 1 (5 o más
  velas seguidas bajo la central de 20 con la central bajando) y esa caída terminó hace `bb_ventana_listas` ruedas o menos (10, editable; ahora significa «ruedas desde la caída»), y (2) las últimas
  `bb_velas_giro` (2) ruedas cierran por encima de la central. Entre una cosa y otra puede haber velas atravesadas; no se exige pendiente positiva. Hay pruebas con los cierres reales de JD hasta el 19/10:
  figura el 08/10, 09/10 y 13/10, sale el 14/10 (cierra bajo la línea), y vuelve el 16/10 y 19/10; con 7 ruedas desde la caída ya no entra el 19/10. La validación del rango cambió: las ruedas desde la caída
  tienen que ser al menos las velas de levantada.
- **Listado 2: la línea central tiene que estar en alza (corrección)**: ahora exige, todo junto, (1) la central con pendiente POSITIVA hoy, (2) AL MENOS `bb_velas_giro` (2) cierres seguidos por encima de la central
  terminando hoy (no importa cuántos más: se muestra la cantidad real) y (3) el cambio de pendiente: el papel estuvo antes en el Listado 1 (5 o más velas seguidas bajo la central con la central bajando) hace
  `bb_ventana_listas` (10) ruedas o menos; entre la caída y los cierres por encima puede haber velas atravesadas. La versión anterior no exigía la pendiente positiva y dejaba entrar papeles con la central todavía
  bajando (por ejemplo JD el 13/10, que cerraba encima pero con la línea cayendo: ahora no figura ese día; sí el 08/10, 09/10, 16/10 y 19/10). Pruebas con los cierres reales de JD y casos de línea no en alza.
- Pruebas: `python tests_parametros.py` (32: validación y guardado de parámetros, que cada uno cambie el resultado, salteo de la corrida programada y que
  la página y el workflow estén alineados), `python tests_backtest.py` (32: reglas de salida, costos, cartera, métricas, filtro de tendencia, que no mire el futuro) y
  `python tests_ruptura.py` (39: ruptura, tendencia, stops, trailing, cartera, grilla), `python tests_indices.py` (17: índices no operables, vara y su marca en rojo) `python tests_sectores.py` (11: clasificación y filtro) y `python tests_informe.py` (31: filtros del informe, lista, vara y frase de «ninguno»).

## Desarrollo local
```
set CLAVE_ACCESO=una-clave-de-prueba-larga
python generar.py compra          # genera docs/data/*.json cifrados
cd docs && python -m http.server 8766   # http://127.0.0.1:8766 (el descifrado necesita HTTPS o localhost)
python tests.py                   # pruebas de la lógica (sin red)
```
