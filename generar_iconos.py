"""Genera docs/icon-192.png y icon-512.png (fondo oscuro + 3 barras en descenso: semáforo VERDE/AMARILLO/ROJO).
Solo librería estándar. Contenido dentro del 70% central: sirve como ícono 'maskable' de Android."""
import struct, zlib

def png(n):
    bg, verde, amar, rojo = (14, 22, 33), (53, 179, 126), (224, 166, 75), (229, 84, 75)
    # barras (x0, x1, y_tope, color) en fracciones del lado; base común en 0.72
    barras = [(0.22, 0.38, 0.30, verde), (0.42, 0.58, 0.44, amar), (0.62, 0.78, 0.58, rojo)]
    base = 0.72
    filas = []
    for y in range(n):
        fila = bytearray([0])
        for x in range(n):
            px = bg
            fx, fy = x / n, y / n
            for x0, x1, top, col in barras:
                if x0 <= fx < x1 and top <= fy < base:
                    px = col
            fila += bytes(px)
        filas.append(bytes(fila))
    def chunk(tipo, datos):
        c = struct.pack(">I", len(datos)) + tipo + datos
        return c + struct.pack(">I", zlib.crc32(tipo + datos) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(b"".join(filas), 9)) + chunk(b"IEND", b""))

for n in (192, 512):
    open(f"docs/icon-{n}.png", "wb").write(png(n))
    print("docs/icon-%d.png" % n)
