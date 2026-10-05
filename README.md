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

## Desarrollo local
```
set CLAVE_ACCESO=una-clave-de-prueba-larga
python generar.py compra          # genera docs/data/*.json cifrados
cd docs && python -m http.server 8766   # http://127.0.0.1:8766 (el descifrado necesita HTTPS o localhost)
python tests.py                   # pruebas de la lógica (sin red)
```
