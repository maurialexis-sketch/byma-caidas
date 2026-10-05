# Pegá acá lo que imprime descubrir_endpoint.py

# URL base del datafeed (lo que va ANTES de "?"), normalmente termina en /history
UDF_BASE = "https://open.bymadata.com.ar/vanoms-be-core/rest/api/bymadata/free/chart/historical-series/history"

# Formato del símbolo que espera el datafeed.
# Probá "{ticker}" primero; si no, "BYMA:{ticker}" u otro que veas en las llamadas.
SYMBOL_FMT = "{ticker} 24HS"   # descubierto: el datafeed usa "GGAL 24HS"

# Headers opcionales si el endpoint los exige (User-Agent, Referer, etc.)
HEADERS = {}

# ---- Modo masivo (universo líquido) ----
# Paneles de BYMA Data que definen el universo (se piden por POST, solo 24hs)
PANEL_BASE = "https://open.bymadata.com.ar/vanoms-be-core/rest/api/bymadata/free/"
PANELES = {"leading-equity": "accion", "general-equity": "accion", "cedears": "cedear"}

# Piso de liquidez: monto operado promedio diario en pesos
PISO_MONTO = 1_000_000_000   # 1.000 millones
RUEDAS_LIQUIDEZ = 5          # promedio de las últimas N ruedas
WORKERS = 3                  # descargas en paralelo: BYMA da 503 intermitentes desde la nube (fase 1)
