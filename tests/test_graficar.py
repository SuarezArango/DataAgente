"""Pruebas de src/graficar.py.

Uso:
    python -m unittest discover tests
"""

import sys
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from graficar import (  # noqa: E402
    RESOLUCION,
    graficar_correlacion,
    graficar_evolucion,
    graficar_frecuencias,
    graficar_ranking,
    graficar_resultado,
)


@dataclass
class Resultado:
    datos_grafico: dict | None = None
    tablas: dict = field(default_factory=dict)


def _mensual() -> pd.DataFrame:
    return pd.DataFrame({
        "periodo": [str(p) for p in pd.period_range("2024-01", periods=12, freq="M")],
        "suma": [100, 120, 90, 140, 160, 150, 170, 180, 130, 110, 40, 30],
        "dias_con_datos": [31] * 10 + [2, 2],
    })


def _ranking(grupos: int = 30) -> pd.DataFrame:
    return pd.DataFrame({
        "grupo": [f"g{i}" for i in range(grupos)],
        "suma": [1000 - i * 10 for i in range(grupos)],
    })


def _matriz() -> pd.DataFrame:
    return pd.DataFrame({
        "r de Pearson": ["a", "b"],
        "a": [1.0, -0.3],
        "b": [-0.3, 1.0],
    })


class TestGraficar(unittest.TestCase):
    def setUp(self):
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        self.carpeta = Path(carpeta.name)

    def _dpi(self, ruta: Path) -> float:
        with Image.open(ruta) as imagen:
            return imagen.info["dpi"][0]

    def test_evolucion_genera_png_a_150_dpi(self):
        ruta = self.carpeta / "e.png"
        self.assertTrue(graficar_evolucion(_mensual(), "f", "v", ruta))
        self.assertAlmostEqual(self._dpi(ruta), RESOLUCION, delta=1)

    def test_evolucion_necesita_al_menos_dos_periodos(self):
        ruta = self.carpeta / "e.png"
        self.assertFalse(graficar_evolucion(_mensual().head(1), "f", "v", ruta))
        self.assertFalse(ruta.exists())

    def test_ranking_genera_png_a_150_dpi(self):
        ruta = self.carpeta / "r.png"
        self.assertTrue(graficar_ranking(_ranking(), "c", "v", ruta, unidad="vehículos"))
        self.assertAlmostEqual(self._dpi(ruta), RESOLUCION, delta=1)

    def test_ranking_de_un_solo_grupo_no_se_grafica(self):
        self.assertFalse(graficar_ranking(_ranking(1), "c", "v", self.carpeta / "r.png"))

    def test_ranking_acepta_etiquetas_y_valores_negativos(self):
        tabla = pd.DataFrame({
            "grupo": ["a", "b", "c"],
            "etiqueta": ["Nombre A", None, "Nombre muy largo " * 6],
            "suma": [50, -20, 10],
        })
        self.assertTrue(graficar_ranking(tabla, "c", "v", self.carpeta / "r.png"))

    def test_frecuencias_genera_png_a_150_dpi(self):
        ruta = self.carpeta / "f.png"
        tabla = pd.DataFrame({
            "valor": [f"v{i}" for i in range(30)],
            "conteo": [100 - i for i in range(30)],
            "porcentaje": [3.3] * 30,
        })
        self.assertTrue(graficar_frecuencias(tabla, "c", ruta))
        self.assertAlmostEqual(self._dpi(ruta), RESOLUCION, delta=1)

    def test_frecuencias_de_un_solo_valor_no_se_grafican(self):
        tabla = pd.DataFrame({"valor": ["a"], "conteo": [5], "porcentaje": [100.0]})
        self.assertFalse(graficar_frecuencias(tabla, "c", self.carpeta / "f.png"))

    def test_correlacion_genera_png_a_150_dpi(self):
        ruta = self.carpeta / "c.png"
        self.assertTrue(graficar_correlacion(_matriz(), ruta))
        self.assertAlmostEqual(self._dpi(ruta), RESOLUCION, delta=1)

    def test_correlacion_acepta_valores_nulos(self):
        tabla = _matriz().astype({"a": float})
        tabla.loc[1, "a"] = float("nan")
        self.assertTrue(graficar_correlacion(tabla, self.carpeta / "c.png"))


class TestGraficarResultado(unittest.TestCase):
    def setUp(self):
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        self.carpeta = Path(carpeta.name)

    def _ranking(self) -> Resultado:
        return Resultado(
            datos_grafico={"tipo": "ranking", "tabla": "t", "grupo": "c", "medida": "v", "columnas": ["v"]},
            tablas={"t": _ranking()},
        )

    def test_grafica_cada_tipo_de_analisis(self):
        evolucion = Resultado(
            datos_grafico={"tipo": "tiempo", "tabla": "t", "fecha": "f", "medida": "v", "columnas": ["v"]},
            tablas={"t": _mensual()},
        )
        correlacion = Resultado(
            datos_grafico={"tipo": "correlacion", "tabla": "t", "columnas": ["a", "b"]},
            tablas={"t": _matriz()},
        )
        nombres = [
            graficar_resultado(r, {}, self.carpeta) for r in (evolucion, self._ranking(), correlacion)
        ]
        self.assertEqual(
            nombres,
            ["grafico_evolucion_f_v.png", "grafico_ranking_c_v.png", "grafico_correlacion.png"],
        )

    def test_nunca_grafica_un_atributo(self):
        self.assertIsNone(graficar_resultado(self._ranking(), {"v": "atributo"}, self.carpeta))
        correlacion = Resultado(
            datos_grafico={"tipo": "correlacion", "tabla": "t", "columnas": ["a", "b"]},
            tablas={"t": _matriz()},
        )
        self.assertIsNone(graficar_resultado(correlacion, {"b": "atributo"}, self.carpeta))
        self.assertEqual(list(self.carpeta.glob("*.png")), [])

    def test_sin_datos_de_grafico_no_grafica(self):
        self.assertIsNone(graficar_resultado(Resultado(), {}, self.carpeta))

    def test_no_repite_nombres_de_archivo(self):
        usados: set[str] = set()
        primero = graficar_resultado(self._ranking(), {}, self.carpeta, usados=usados)
        segundo = graficar_resultado(self._ranking(), {}, self.carpeta, usados=usados)
        self.assertNotEqual(primero, segundo)
        self.assertEqual(len(list(self.carpeta.glob("*.png"))), 2)


if __name__ == "__main__":
    unittest.main()
