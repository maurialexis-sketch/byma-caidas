"""
reloj.py — Hora de mercado verificada (Argentina, UTC-3 fijo, sin horario de verano).

NO usa el reloj del servidor como fuente: pregunta en paralelo a varias fuentes externas independientes
(Cloudflare, Google, Microsoft y la propia BYMA) y toma la mediana. Entre sincronizaciones avanza con el reloj
monotónico (que no se corrige ni salta), no con la hora del sistema.
Si no puede verificar la hora, levanta RelojError: es preferible no correr a correr con la hora equivocada.
"""
import email.utils, threading, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

AR = timezone(timedelta(hours=-3))
BYMA = "https://open.bymadata.com.ar/vanoms-be-core/rest/api/bymadata/free/leading-equity"
# (nombre, url, método). BYMA contesta 405 a un GET, pero la cabecera Date viene igual.
FUENTES = [("Cloudflare", "https://www.cloudflare.com/cdn-cgi/trace", "GET"),
           ("Google", "https://www.google.com/generate_204", "GET"),
           ("BYMA", BYMA, "GET"),
           ("Microsoft", "https://www.microsoft.com/", "HEAD")]
RESINCRONIZAR_S = 600      # se vuelve a verificar cada 10 min
VENCE_S = 3600             # si no se pudo verificar en 1 h, no se confía en la hora
MAX_DISPERSION_S = 5       # las fuentes que difieren más de esto de la mediana se descartan


class RelojError(RuntimeError):
    pass


def _leer(fuente):
    """(nombre, epoch estimado de 'ahora') o None. Compensa la mitad de la latencia de ida y vuelta."""
    nombre, url, metodo = fuente
    t0 = time.time()
    try:
        req = urllib.request.Request(url, method=metodo, headers={"User-Agent": "caidas-byma/1.0"})
        try:
            r = urllib.request.urlopen(req, timeout=8)
            cabeceras, cuerpo = r.headers, r.read(4000)
        except urllib.error.HTTPError as e:      # 405 y similares igual traen la hora
            cabeceras, cuerpo = e.headers, b""
        rtt = time.time() - t0
        for linea in cuerpo.decode("utf-8", "replace").splitlines():
            if linea.startswith("ts="):          # Cloudflare: hora con decimales
                return nombre, float(linea[3:]) + rtt / 2
        fecha = cabeceras.get("Date")
        if fecha:                                 # resolución de 1 s: se toma el medio del segundo
            return nombre, email.utils.parsedate_to_datetime(fecha).timestamp() + 0.5 + rtt / 2
    except Exception:
        pass
    return None


class Reloj:
    def __init__(self):
        self._lock = threading.Lock()
        self._base = None            # epoch verificado - monotónico en el momento de sincronizar
        self._sync = None            # monotónico de la última sincronización buena
        self.fuentes, self.dispersion_s, self.desvio_servidor_s = [], None, None

    def sincronizar(self):
        with ThreadPoolExecutor(len(FUENTES)) as ex:
            lecturas = [x for x in ex.map(_leer, FUENTES) if x]
        if not lecturas:
            raise RelojError("ninguna fuente de hora respondió")
        mediana = sorted(e for _, e in lecturas)[len(lecturas) // 2]
        validas = [(n, e) for n, e in lecturas if abs(e - mediana) <= MAX_DISPERSION_S]
        epochs = sorted(e for _, e in validas)
        verificado = epochs[len(epochs) // 2]
        with self._lock:
            self._base, self._sync = verificado - time.monotonic(), time.monotonic()
            self.fuentes = [n for n, _ in validas]
            self.dispersion_s = round(epochs[-1] - epochs[0], 2)
            self.desvio_servidor_s = round(time.time() - verificado, 1)

    def _asegurar(self):
        edad = None if self._sync is None else time.monotonic() - self._sync
        if edad is not None and edad < RESINCRONIZAR_S:
            return
        try:
            self.sincronizar()
        except RelojError:
            if edad is None or edad > VENCE_S:
                raise RelojError("no se pudo verificar la hora de mercado con fuentes externas")

    def epoch(self):
        self._asegurar()
        return time.monotonic() + self._base

    def ahora(self):
        return datetime.fromtimestamp(self.epoch(), AR)

    @property
    def fuente(self):
        if not self.fuentes:
            return "sin verificar"
        return f"mediana de {', '.join(self.fuentes)} (dispersión {self.dispersion_s} s)"


def mercado_abierto(ahora, apertura=(10, 30), cierre=(17, 0)):
    """Horario estimado de rueda (lunes a viernes; se vieron operaciones desde las 10:37). No sabe de feriados:
    eso lo marca el servidor con los datos."""
    if ahora.weekday() >= 5:
        return False
    return ahora.replace(hour=apertura[0], minute=apertura[1], second=0, microsecond=0) <= ahora < \
        ahora.replace(hour=cierre[0], minute=cierre[1], second=0, microsecond=0)
