"""Pruebas del guardado de las corridas en el repositorio (que dos corridas casi simultáneas no pierdan nada):  python tests_publicar.py"""
import json, os, shutil, subprocess, tempfile, unittest

import fusionar_indice as fi

AQUI = os.path.dirname(os.path.abspath(__file__))
TIENE_BASH = shutil.which("bash") is not None and shutil.which("git") is not None


def e(archivo, fecha="2026-11-14", hora="11:00", fn="informe", etiqueta=None):
    x = {"archivo": archivo, "fecha": fecha, "hora": hora, "funcion": fn}
    if etiqueta:
        x["etiqueta"] = etiqueta
    return x


class Fusion(unittest.TestCase):
    def test_une_sin_repetir_y_ordena_de_la_mas_nueva_a_la_mas_vieja(self):
        a = [e("a.json", hora="11:38"), e("v.json", fecha="2026-11-13", hora="22:00")]
        b = [e("b.json", hora="11:41", fn="backtest", etiqueta="Ruptura"), e("a.json", hora="11:38")]
        r = fi.fusionar(a, b)
        self.assertEqual([x["archivo"] for x in r], ["b.json", "a.json", "v.json"])
        self.assertEqual(r[0]["etiqueta"], "Ruptura")

    def test_si_una_lista_esta_vacia_queda_la_otra(self):
        self.assertEqual(fi.fusionar([], [e("a.json")]), [e("a.json")])
        self.assertEqual(fi.fusionar([e("a.json")], []), [e("a.json")])


def git(cwd, *args, **kw):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)


@unittest.skipUnless(TIENE_BASH, "hace falta bash y git")
class GuardadoConcurrente(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory(); self.addCleanup(self.d.cleanup)
        self.origen = os.path.join(self.d.name, "origen.git")
        git(self.d.name, "init", "-q", "--bare", "-b", "main", self.origen)
        sem = os.path.join(self.d.name, "semilla")
        git(self.d.name, "clone", "-q", self.origen, sem)
        os.makedirs(os.path.join(sem, "docs", "data"))
        with open(os.path.join(sem, "docs", "data", "indice.json"), "w", encoding="utf-8") as f:
            json.dump([e("base.json", fecha="2026-11-13", hora="18:00")], f)
        with open(os.path.join(sem, "docs", "data", "base.json"), "w") as f:
            f.write("{}")
        for n in ("fusionar_indice.py", "publicar_cambios.sh"):
            shutil.copy(os.path.join(AQUI, n), sem)
        git(sem, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A"); git(sem, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base"); git(sem, "push", "-q", "origin", "HEAD:main")
        self.a, self.b = os.path.join(self.d.name, "A"), os.path.join(self.d.name, "B")
        git(self.d.name, "clone", "-q", self.origen, self.a); git(self.d.name, "clone", "-q", self.origen, self.b)

    def corrida(self, repo, archivo, hora, fn, extra=None):
        """Simula una corrida: agrega su entrada al índice y su archivo de datos, y publica con el script."""
        ruta = os.path.join(repo, "docs", "data", "indice.json")
        with open(ruta, encoding="utf-8") as f:
            idx = json.load(f)
        idx = [e(archivo, hora=hora, fn=fn)] + idx
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(idx, f)
        with open(os.path.join(repo, "docs", "data", archivo), "w") as f:
            f.write("{}")
        for k, v in (extra or {}).items():
            with open(os.path.join(repo, k), "w") as f:
                f.write(v)
        salida = os.path.join(repo, "salida.txt")
        env = {**os.environ, "GITHUB_OUTPUT": salida, "ESPERA": "0"}
        r = subprocess.run(["bash", "publicar_cambios.sh", f"corrida {archivo}"], cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        return r

    def indice_publicado(self):
        r = git(self.d.name, "--git-dir", self.origen, "show", "main:docs/data/indice.json")
        return json.loads(r.stdout)

    def test_dos_corridas_que_guardan_casi_a_la_vez_no_se_pisan(self):
        r1 = self.corrida(self.b, "informe.json", "11:38", "informe")          # la que guarda primero
        self.assertEqual(r1.returncode, 0, r1.stderr)
        r2 = self.corrida(self.a, "backtest.json", "11:41", "backtest")        # la segunda parte de un índice viejo: conflicto en indice.json
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        self.assertEqual([x["archivo"] for x in self.indice_publicado()], ["backtest.json", "informe.json", "base.json"])
        for n in ("informe.json", "backtest.json"):
            self.assertEqual(git(self.d.name, "--git-dir", self.origen, "cat-file", "-e", f"main:docs/data/{n}").returncode, 0)       # los dos archivos de datos están
        with open(os.path.join(self.a, "salida.txt")) as f:
            self.assertIn("cambios=true", f.read())

    def test_tres_corridas_seguidas_sobre_un_indice_viejo(self):
        C = os.path.join(self.d.name, "C"); git(self.d.name, "clone", "-q", self.origen, C)
        self.assertEqual(self.corrida(self.a, "a.json", "10:00", "informe").returncode, 0)
        self.assertEqual(self.corrida(self.b, "b.json", "10:05", "backtest").returncode, 0)
        self.assertEqual(self.corrida(C, "c.json", "10:10", "compra").returncode, 0)
        self.assertEqual({x["archivo"] for x in self.indice_publicado()}, {"a.json", "b.json", "c.json", "base.json"})

    def test_los_parametros_guardados_de_la_ultima_corrida_se_conservan_si_chocan(self):
        self.assertEqual(self.corrida(self.b, "i.json", "11:00", "informe", {"parametros.json": '{"rb_min": 3}'}).returncode, 0)
        r = self.corrida(self.a, "j.json", "11:05", "backtest", {"parametros.json": '{"rb_min": 4}'})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads(git(self.d.name, "--git-dir", self.origen, "show", "main:parametros.json").stdout), {"rb_min": 4})

    def test_sin_cambios_no_hace_nada(self):
        env = {**os.environ, "GITHUB_OUTPUT": os.path.join(self.a, "salida.txt"), "ESPERA": "0"}
        r = subprocess.run(["bash", "publicar_cambios.sh", "nada"], cwd=self.a, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        self.assertEqual(r.returncode, 0)
        with open(os.path.join(self.a, "salida.txt")) as f:
            self.assertIn("cambios=false", f.read())

    def test_si_no_puede_publicar_falla_en_voz_alta_en_vez_de_perder_el_informe(self):
        # un conflicto en un archivo que no es el índice no se puede fusionar solo: tiene que salir con error
        for repo, texto, hora in ((self.b, "uno", "11:00"), (self.a, "dos", "11:05")):
            r = self.corrida(repo, f"x{hora}.json", hora, "informe", {os.path.join("docs", "data", "meta.json"): texto})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("No se pudo guardar", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
