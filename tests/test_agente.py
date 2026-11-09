"""Pruebas de src/agente.py.

Uso:
    python -m unittest discover tests
"""

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agente import (  # noqa: E402
    ETIQUETA_NULO,
    ResultadoAnalisis,
    ResultadosAgente,
    _interpretar_forzar,
    _interpretar_unidades,
    agrupaciones_equivalentes,
    analizar,
    analizar_tiempo,
    clasificar_columnas,
    detectar_agrupaciones,
    elegir_analisis,
    escribir_informe,
    fechas_gemelas,
    filtrar_por_fecha,
    frecuencias,
    huecos_calendario,
    main,
    matriz_correlacion,
    priorizar_analisis,
    ranking_por_categoria,
    revisar_fechas,
    sugerir_corte,
)
from perfilar import cargar  # noqa: E402


def _como_texto(datos: dict) -> pd.DataFrame:
    """Simula un CSV leído sin inferir tipos."""
    return pd.DataFrame(datos, dtype=str)


def _por_columna(df: pd.DataFrame, **kwargs) -> dict:
    return {c.columna: c for c in clasificar_columnas(df, **kwargs)}


class TestClasificarColumnas(unittest.TestCase):
    def setUp(self):
        filas = 1_000
        self.df = _como_texto({
            # Fecha en formato ISO, con 100 valores que se repiten.
            "fecha": [str(d.date()) for d in pd.date_range("2024-01-01", periods=100)] * 10,
            # Medida numérica con decimales repetidos.
            "monto": [f"{(i % 300) * 1.5:.1f}" for i in range(filas)],
            # Texto repetido, pocos valores.
            "ciudad": [["Bogotá", "Cali", "Medellín", "Pasto", "Neiva"][i % 5] for i in range(filas)],
            # Texto repetido, más valores de los que caben en el informe.
            "barrio": [f"barrio_{i % 80}" for i in range(filas)],
            # Texto casi único por fila.
            "correo": [f"persona{i}@ejemplo.com" for i in range(filas)],
            # Dígitos con ceros a la izquierda.
            "municipio_dane": [f"{(i % 40) + 1:05d}" for i in range(filas)],
            # Numérica con nombre de código, sin ceros a la izquierda.
            "cliente_id": [str(1000 + i % 200) for i in range(filas)],
            # Enteros que no se repiten.
            "consecutivo": [str(i + 1) for i in range(filas)],
            # Constante.
            "pais": ["Colombia"] * filas,
            # Vacía.
            "notas": [None] * filas,
        })

    def test_tipo_rol_y_top_n_esperados(self):
        obtenido = {
            c.columna: (c.tipo, c.rol, c.mostrar_top_n)
            for c in clasificar_columnas(self.df)
        }
        self.assertEqual(
            obtenido,
            {
                "fecha": ("fecha", "agrupable", True),
                "monto": ("numero", "medible", True),
                "ciudad": ("texto", "agrupable", False),
                "barrio": ("texto", "agrupable", True),
                "correo": ("texto", "ignorar", True),
                "municipio_dane": ("codigo", "agrupable", False),
                "cliente_id": ("codigo", "agrupable", True),
                "consecutivo": ("numero", "medible", True),
                "pais": ("texto", "ignorar", False),
                "notas": ("texto", "ignorar", False),
            },
        )

    def test_codigo_agrupable_nunca_medible(self):
        # El caso de cod_dane: código con muchos valores, pero muy repetidos.
        df = _como_texto({"dane": [f"{i % 1100:05d}" for i in range(20_000)]})
        columna = _por_columna(df)["dane"]
        self.assertEqual((columna.tipo, columna.rol), ("codigo", "agrupable"))
        self.assertTrue(columna.mostrar_top_n)

    def test_codigo_casi_unico_se_ignora(self):
        df = _como_texto({"cedula_id": [str(1000 + i) for i in range(500)]})
        columna = _por_columna(df)["cedula_id"]
        self.assertEqual((columna.tipo, columna.rol), ("codigo", "ignorar"))

    def test_top_n_depende_del_numero_absoluto(self):
        # Mismo ratio bajo: el flag cambia solo al pasar de 50 únicos.
        con_50 = _como_texto({"c": [f"v{i % 50}" for i in range(10_000)]})
        con_51 = _como_texto({"c": [f"v{i % 51}" for i in range(10_000)]})
        self.assertFalse(_por_columna(con_50)["c"].mostrar_top_n)
        self.assertTrue(_por_columna(con_51)["c"].mostrar_top_n)

    def test_codigos_marcados_para_revisar(self):
        revisar = {c.columna for c in clasificar_columnas(self.df) if c.revisar}
        self.assertEqual(revisar, {"municipio_dane", "cliente_id"})

    def test_motivo_explica_ceros(self):
        motivo = _por_columna(self.df)["municipio_dane"].motivo_tipo
        self.assertIn("empiezan por cero", motivo)
        self.assertIn("'00001'", motivo)

    def test_ceros_en_texto_no_son_codigo(self):
        # Un '007' suelto en una columna de texto no la convierte en código.
        df = _como_texto({"nombre": ["007"] + [f"agente {i % 20}" for i in range(499)]})
        self.assertEqual(_por_columna(df)["nombre"].tipo, "texto")

    def test_nombre_por_palabra_completa(self):
        # 'candidatos' contiene 'id' como subcadena, pero no es un código.
        df = _como_texto({"candidatos": [str(i % 30) for i in range(500)]})
        self.assertEqual(_por_columna(df)["candidatos"].tipo, "numero")

    def test_cero_y_decimales_son_numeros(self):
        df = _como_texto({"tasa": ["0", "0.5", "0.25", "1", "0"] * 100})
        self.assertEqual(_por_columna(df)["tasa"].tipo, "numero")

    def test_cuatro_cifras_no_son_fecha(self):
        # pandas lee '1200' como el año 1200: un precio no debe volverse fecha.
        df = _como_texto({"precio": [str(1000 + i % 90 * 100) for i in range(500)]})
        self.assertEqual(_por_columna(df)["precio"].tipo, "numero")

    def test_ratio_alto_no_descarta_medidas_ni_fechas(self):
        df = _como_texto({
            "dia": [str(d.date()) for d in pd.date_range("2024-01-01", periods=365)],
            "ingreso": [f"{1000 + i * 1.37:.2f}" for i in range(365)],
        })
        columnas = _por_columna(df)
        self.assertEqual((columnas["dia"].tipo, columnas["dia"].rol), ("fecha", "agrupable"))
        self.assertEqual((columnas["ingreso"].tipo, columnas["ingreso"].rol), ("numero", "medible"))

    def test_ratio_alto_si_descarta_textos_y_codigos(self):
        df = _como_texto({
            "correo": [f"p{i}@ejemplo.com" for i in range(100)],
            "cedula_id": [f"{i:06d}" for i in range(100)],
        })
        columnas = _por_columna(df)
        self.assertEqual(columnas["correo"].rol, "ignorar")
        self.assertEqual((columnas["cedula_id"].tipo, columnas["cedula_id"].rol), ("codigo", "ignorar"))
        self.assertIn("identificador", columnas["correo"].motivo_rol)

    def test_constantes_y_vacias_siguen_ignoradas_en_cualquier_tipo(self):
        df = _como_texto({
            "numero_fijo": ["7"] * 50,
            "fecha_fija": ["2024-01-01"] * 50,
            "vacia": [None] * 50,
        })
        self.assertEqual({c.columna: c.rol for c in clasificar_columnas(df)}, {
            "numero_fijo": "ignorar", "fecha_fija": "ignorar", "vacia": "ignorar",
        })

    def test_detector_de_fechas_exige_forma_de_fecha(self):
        casos = {
            "iso": (["2024-01-15", "2024-02-20"], "fecha"),
            "con_barras": (["8/21/2015", "8/31/2015"], "fecha"),
            "con_hora": (["2024-01-15 10:30:00", "2024-02-20 11:00:00"], "fecha"),
            "con_mes": (["15-mar-2024", "20-abr-2024"], "texto"),
            "con_mes_ingles": (["15-Mar-2024", "20-Apr-2024"], "fecha"),
            "anio_mes": (["2024-01", "2024-02"], "fecha"),
            "rango_de_edad": (["18-25", "26-35"], "texto"),
            "fraccion": (["1/2", "3/4"], "texto"),
            "con_coma": (["texto, 25", "otro, 27"], "texto"),
            "espacios": (["Jan 5 2024", "Feb 6 2024"], "texto"),
        }
        for nombre, (valores, esperado) in casos.items():
            with self.subTest(nombre):
                df = _como_texto({"x": valores * 25})
                self.assertEqual(_por_columna(df)["x"].tipo, esperado)

    def test_forzar_tipo_recalcula_rol(self):
        columna = _por_columna(self.df, forzar={"cliente_id": {"tipo": "numero"}})["cliente_id"]
        self.assertEqual((columna.tipo, columna.rol), ("numero", "medible"))
        self.assertIn("forzado", columna.motivo_tipo)
        self.assertFalse(columna.revisar)

    def test_forzar_rol_conserva_tipo(self):
        columna = _por_columna(self.df, forzar={"monto": {"rol": "agrupable"}})["monto"]
        self.assertEqual((columna.tipo, columna.rol), ("numero", "agrupable"))
        self.assertIn("forzado", columna.motivo_rol)

    def test_forzar_valida_entradas(self):
        casos = [
            {"no_existe": {"rol": "ignorar"}},
            {"ciudad": {"tipo": "categoria"}},
            {"ciudad": {"rol": "sumar"}},
            {"ciudad": {"clase": "texto"}},
        ]
        for forzar in casos:
            with self.subTest(forzar=forzar), self.assertRaises(ValueError):
                clasificar_columnas(self.df, forzar=forzar)

    def test_forzar_no_permite_sumar_codigos(self):
        with self.assertRaises(ValueError):
            clasificar_columnas(self.df, forzar={"municipio_dane": {"rol": "medible"}})


class TestCargarComoTexto(unittest.TestCase):
    def setUp(self):
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        self.ruta = Path(carpeta.name) / "prueba.csv"
        self.ruta.write_text("codigo,cantidad\n05001,10\n08001,20\n", encoding="utf-8")

    def test_por_defecto_sigue_infiriendo_tipos(self):
        df = cargar(self.ruta)
        self.assertEqual(df["codigo"].tolist(), [5001, 8001])
        self.assertEqual(df["cantidad"].tolist(), [10, 20])

    def test_como_texto_conserva_los_ceros(self):
        df = cargar(self.ruta, como_texto=True)
        self.assertEqual(df["codigo"].tolist(), ["05001", "08001"])
        self.assertEqual(df["cantidad"].tolist(), ["10", "20"])


class TestDecimalesConComa(unittest.TestCase):
    def setUp(self):
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        self.ruta = Path(carpeta.name) / "datos.csv"

    def _cargar(self, contenido: str, **kwargs) -> pd.DataFrame:
        self.ruta.write_text(contenido, encoding="utf-8")
        return cargar(self.ruta, **kwargs)

    def test_punto_de_miles_y_coma_decimal(self):
        df = self._cargar("c;m\na;19.312,7\nb;27,25\nc;1.000.000,5\nd;300\ne;1.500\n")
        self.assertEqual(df["m"].tolist(), [19312.7, 27.25, 1000000.5, 300.0, 1500.0])
        self.assertEqual(list(df.attrs["decimales_coma"]), ["m"])

    def test_como_texto_lo_deja_listo_para_clasificar(self):
        df = self._cargar("c;m\na;19.312,7\nb;27,25\n", como_texto=True)
        self.assertEqual(df["m"].tolist(), ["19312.7", "27.25"])

    def test_nulos_se_conservan(self):
        df = self._cargar("c;m\na;1,5\nb;\nc;2,5\n", como_texto=True)
        self.assertTrue(pd.isna(df["m"].iloc[1]))
        self.assertEqual(df["m"].iloc[2], "2.5")

    def test_comas_de_tres_digitos_son_ambiguas(self):
        df = self._cargar('c,m\na,"1,234"\nb,"12,500"\n', como_texto=True)
        self.assertEqual(df["m"].tolist(), ["1,234", "12,500"])
        self.assertEqual(list(df.attrs["decimales_ambiguos"]), ["m"])
        self.assertEqual(df.attrs["decimales_coma"], {})

    def test_tres_digitos_con_miles_no_son_ambiguos(self):
        df = self._cargar("c;m\na;1.234,500\nb;2,500\n")
        self.assertEqual(df["m"].tolist(), [1234.5, 2.5])

    def test_punto_decimal_ingles_no_se_toca(self):
        df = self._cargar("c,m\na,1.234\nb,2.5\n")
        self.assertEqual(df["m"].tolist(), [1.234, 2.5])
        self.assertEqual(df.attrs["decimales_coma"], {})

    def test_texto_con_comas_no_se_toca(self):
        df = self._cargar('c,m\na,"Cali, Valle"\nb,"Pasto, Nariño"\n')
        self.assertEqual(df["m"].tolist(), ["Cali, Valle", "Pasto, Nariño"])
        self.assertEqual(df.attrs["decimales_coma"], {})

    def test_columna_mayormente_texto_no_se_convierte(self):
        filas = "".join(f"a;texto {i}\n" for i in range(10)) + "b;27,25\n"
        df = self._cargar(f"c;m\n{filas}", como_texto=True)
        self.assertEqual(df["m"].iloc[-1], "27,25")


class TestFechasMezcladas(unittest.TestCase):
    def test_zonas_horarias_mezcladas_no_rompen_la_clasificacion(self):
        df = _como_texto({
            "momento": ["2024-01-01T10:00:00+01:00", "2024-01-02T10:00:00-05:00"] * 50,
        })
        self.assertEqual(_por_columna(df)["momento"].tipo, "fecha")


class TestHuecosYFechas(unittest.TestCase):
    def test_tramos_de_dias_faltantes(self):
        fechas = pd.Series(pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-06", "2024-01-08"]))
        huecos = huecos_calendario(fechas)
        self.assertEqual(huecos["dias_faltantes"], 4)
        self.assertEqual(huecos["rango_dias"], 8)
        self.assertEqual(huecos["tramos"]["desde"].tolist(), ["2024-01-03", "2024-01-07"])
        self.assertEqual(huecos["tramos"]["dias"].tolist(), [3, 1])

    def test_meses_completos_faltantes(self):
        fechas = pd.Series(pd.to_datetime(["2024-01-31", "2024-04-01"]))
        self.assertEqual(huecos_calendario(fechas)["meses_faltantes"], ["2024-02", "2024-03"])

    def test_calendario_completo_no_reporta_huecos(self):
        fechas = pd.Series(pd.date_range("2024-01-01", periods=60))
        huecos = huecos_calendario(fechas)
        self.assertEqual(huecos["dias_faltantes"], 0)
        self.assertEqual(huecos["meses_faltantes"], [])

    def test_fechas_futuras(self):
        df = pd.DataFrame({"f": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-03-01"])})
        resultado = revisar_fechas(df, "f", hoy=pd.Timestamp("2024-01-15"))
        texto = " ".join(resultado.advertencias)
        self.assertIn("1 filas tienen fecha posterior", texto)
        self.assertIn("2024-03-01", texto)

    def test_sin_fechas_futuras(self):
        df = pd.DataFrame({"f": pd.to_datetime(["2024-01-01", "2024-01-02"])})
        resultado = revisar_fechas(df, "f", hoy=pd.Timestamp("2024-01-15"))
        self.assertEqual(resultado.advertencias, [])
        self.assertIn("Ninguna fecha es posterior", " ".join(resultado.descripciones))


class TestAnalizarTiempo(unittest.TestCase):
    def setUp(self):
        self.df = _como_texto({
            "f": ["2023-01-05", "2023-01-20", "2023-03-02", "2024-01-05", None],
            "v": ["10", "20", "5", "100", "999"],
        })

    def _tablas(self, resultado):
        return (
            resultado.tablas["evolucion_f_v_mes"],
            resultado.tablas["evolucion_f_v_anio"],
        )

    def test_agrega_por_mes_y_anio(self):
        por_mes, por_anio = self._tablas(analizar_tiempo(self.df, "f", "v"))
        self.assertEqual(por_anio["periodo"].tolist(), ["2023", "2024"])
        self.assertEqual(por_anio["suma"].tolist(), [35, 100])
        self.assertEqual(por_anio["filas"].tolist(), [3, 1])
        fila_enero = por_mes[por_mes["periodo"] == "2023-01"].iloc[0]
        self.assertEqual((fila_enero["suma"], fila_enero["media"], fila_enero["dias_con_datos"]), (30, 15, 2))

    def test_excluye_y_registra_filas_sin_fecha(self):
        resultado = analizar_tiempo(self.df, "f", "v")
        _, por_anio = self._tablas(resultado)
        self.assertEqual(por_anio["suma"].sum(), 135)
        self.assertIn("Excluí 1 filas sin fecha válida", " ".join(resultado.decisiones))

    def test_reporta_huecos(self):
        texto = " ".join(analizar_tiempo(self.df, "f", "v").advertencias)
        self.assertIn("días entre la primera y la última fecha", texto)
        self.assertIn("2023-02", texto)

    def test_describe_extremos_sin_interpretar(self):
        texto = " ".join(analizar_tiempo(self.df, "f", "v").descripciones)
        self.assertIn("el máximo de la suma de `v` es 100 en 2024", texto)
        self.assertIn("el mínimo es 35 en 2023", texto)


class TestRanking(unittest.TestCase):
    def setUp(self):
        # 'a' tiene más filas, pero 'b' tiene más suma.
        self.df = _como_texto({
            "c": ["a", "a", "a", "b", None],
            "v": ["1", "1", "1", "100", "7"],
        })

    def test_filas_suma_media_por_grupo(self):
        tabla = ranking_por_categoria(self.df, "c", "v").tablas["ranking_c_v"]
        self.assertEqual(tabla["grupo"].tolist(), ["b", ETIQUETA_NULO, "a"])
        self.assertEqual(tabla["suma"].tolist(), [100, 7, 3])
        self.assertEqual(tabla["filas"].tolist(), [1, 1, 3])
        self.assertEqual(tabla["media"].tolist(), [100, 7, 1])

    def test_advierte_si_los_tops_difieren(self):
        texto = " ".join(ranking_por_categoria(self.df, "c", "v").advertencias)
        self.assertIn("son distintos", texto)
        self.assertIn("por filas es 'a'; por suma, 'b'", texto)

    def test_no_advierte_si_los_tops_coinciden(self):
        df = _como_texto({"c": ["a", "a", "b"], "v": ["10", "10", "1"]})
        self.assertEqual(ranking_por_categoria(df, "c", "v").advertencias, [])

    def test_marca_recorte_solo_con_el_flag(self):
        con_flag = ranking_por_categoria(self.df, "c", "v", mostrar_top_n=True)
        sin_flag = ranking_por_categoria(self.df, "c", "v")
        self.assertIn("ranking_c_v", con_flag.recortar)
        self.assertEqual(sin_flag.recortar, set())

    def test_codigo_conserva_ceros(self):
        df = _como_texto({"dane": ["05001", "05001", "08001"], "v": ["1", "2", "3"]})
        tabla = ranking_por_categoria(df, "dane", "v").tablas["ranking_dane_v"]
        self.assertEqual(sorted(tabla["grupo"]), ["05001", "08001"])

    def test_registra_nulos_de_la_medida(self):
        df = _como_texto({"c": ["a", "a", "b"], "v": ["1", None, "3"]})
        resultado = ranking_por_categoria(df, "c", "v")
        self.assertIn("1 filas sin valor", " ".join(resultado.decisiones))
        fila_a = resultado.tablas["ranking_c_v"].set_index("grupo").loc["a"]
        self.assertEqual((fila_a["filas"], fila_a["suma"], fila_a["media"]), (2, 1, 1))

    def test_columna_llamada_suma_no_choca(self):
        df = _como_texto({"suma": ["a", "b"], "v": ["1", "2"]})
        self.assertEqual(len(ranking_por_categoria(df, "suma", "v").tablas["ranking_suma_v"]), 2)


class TestCorrelacion(unittest.TestCase):
    def test_no_calcula_con_una_sola_columna(self):
        df = _como_texto({"x": ["1", "2", "3"]})
        resultado = matriz_correlacion(df, ["x"])
        self.assertEqual(resultado.tablas, {})
        self.assertIn("No calculé", " ".join(resultado.decisiones))

    def test_pearson_y_aviso_de_causalidad(self):
        df = _como_texto({"x": ["1", "2", "3", "4"], "y": ["2", "4", "6", "8"], "z": ["1", "9", "2", "7"]})
        resultado = matriz_correlacion(df, ["x", "y", "z"])
        tabla = resultado.tablas["correlacion"].set_index("r de Pearson")
        self.assertAlmostEqual(tabla.loc["x", "y"], 1.0)
        self.assertIn("`x` y `y` se mueven juntas", " ".join(resultado.descripciones))
        self.assertIn("no implica causalidad", " ".join(resultado.advertencias))

    def test_sin_pares_destacados(self):
        df = _como_texto({"x": ["1", "2", "3", "4"], "y": ["1", "-1", "-1", "1"]})
        resultado = matriz_correlacion(df, ["x", "y"])
        self.assertIn("Ningún par", " ".join(resultado.descripciones))


class TestFrecuencias(unittest.TestCase):
    def test_conteo_porcentaje_y_nulos(self):
        df = _como_texto({"c": ["a", "a", "b", None]})
        tabla = frecuencias(df, "c").tablas["frecuencias_c"]
        self.assertEqual(tabla["valor"].tolist(), ["a", ETIQUETA_NULO, "b"])
        self.assertEqual(tabla["conteo"].tolist(), [2, 1, 1])
        self.assertEqual(tabla["porcentaje"].tolist(), [50.0, 25.0, 25.0])

    def test_marca_recorte_con_el_flag(self):
        df = _como_texto({"c": ["a", "b"]})
        self.assertIn("frecuencias_c", frecuencias(df, "c", mostrar_top_n=True).recortar)


class TestElegirAnalisis(unittest.TestCase):
    def _clasificacion(self, datos):
        return clasificar_columnas(_como_texto(datos))

    def test_sin_medibles_solo_frecuencias(self):
        planes, elegidos, descartados = elegir_analisis(self._clasificacion({"c": ["a", "b"] * 10}))
        self.assertEqual([p[0] for p in planes], ["frecuencias"])
        self.assertTrue(any("Frecuencias de `c`" in e for e in elegidos))
        self.assertTrue(any(d.startswith("Ranking por categoría") for d in descartados))

    def test_nunca_mide_un_codigo(self):
        planes, _, _ = elegir_analisis(self._clasificacion({
            "dane": ["05001", "08001"] * 10,
            "v": ["1", "2", "3", "4"] * 5,
        }))
        self.assertEqual(
            [(p[0], p[1].columna, p[2].columna) for p in planes],
            [("ranking", "dane", "v")],
        )

    def test_fecha_ignorada_se_explica(self):
        # Solo una fecha constante o vacía queda ignorada.
        _, _, descartados = elegir_analisis(self._clasificacion({
            "dia": ["2024-01-01"] * 30,
            "v": ["1", "2", "3"] * 10,
        }))
        self.assertTrue(any("`dia` quedó con rol ignorar" in d for d in descartados))


def _resultados_de_prueba(analisis):
    return ResultadosAgente(
        archivo="x.csv",
        filas=100,
        columnas=2,
        fecha_ejecucion="2026-01-01 10:00",
        perfil="PERFIL\nCALIDAD DE DATOS\n\n  - aviso de prueba\n\nVARIABLES NUMÉRICAS\n\nv 1 2",
        avisos_conversion=[],
        chequeos=[],
        clasificacion=clasificar_columnas(_como_texto({"c": ["a", "b"] * 5, "v": ["1", "2"] * 5})),
        elegidos=["elegido de prueba"],
        descartados=["descartado de prueba"],
        analisis=analisis,
    )


class TestEscribirInforme(unittest.TestCase):
    def _escribir(self, analisis):
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        ruta = Path(carpeta.name) / "informe.md"
        escribir_informe(_resultados_de_prueba(analisis), ruta)
        return ruta.read_text(encoding="utf-8")

    def test_tiene_las_siete_secciones_en_orden(self):
        texto = self._escribir([])
        posiciones = [
            texto.index(seccion)
            for seccion in (
                "## 1. Resumen",
                "## 2. Calidad de datos",
                "## 3. Clasificación de columnas",
                "## 4. Análisis elegidos y descartados",
                "## 5. Resultados",
                "## 6. Límites",
                "## 7. Anexo",
            )
        ]
        self.assertEqual(posiciones, sorted(posiciones))

    def test_calidad_toma_solo_el_bloque_del_perfil(self):
        texto = self._escribir([])
        seccion = texto[texto.index("## 2.") : texto.index("## 3.")]
        self.assertIn("aviso de prueba", seccion)
        self.assertNotIn("VARIABLES NUMÉRICAS", seccion)

    def test_recorta_a_10_primeras_y_5_ultimas(self):
        tabla = pd.DataFrame({"grupo": [f"g{i:03d}" for i in range(100)], "suma": range(100)})
        analisis = ResultadoAnalisis(nombre="r", tablas={"t": tabla}, recortar={"t"}, archivos={"t": "t.csv"})
        texto = self._escribir([analisis])
        self.assertIn("| g009 |", texto)
        self.assertNotIn("| g010 |", texto)
        self.assertNotIn("| g094 |", texto)
        self.assertIn("| g095 |", texto)
        self.assertIn("85 filas omitidas", texto)
        self.assertIn("[t.csv](t.csv)", texto)

    def test_sin_recorte_muestra_todo(self):
        tabla = pd.DataFrame({"grupo": [f"g{i:03d}" for i in range(30)], "suma": range(30)})
        texto = self._escribir([ResultadoAnalisis(nombre="r", tablas={"t": tabla})])
        self.assertIn("| g015 |", texto)
        self.assertNotIn("omitidas", texto)

    def test_decimales_uniformes_y_formato_espanol(self):
        tabla = pd.DataFrame({"grupo": ["a", "b"], "filas": [1234, 2], "media": [1.0, 1.94]})
        texto = self._escribir([ResultadoAnalisis(nombre="r", tablas={"t": tabla})])
        self.assertIn("| a | 1.234 | 1,00 |", texto)
        self.assertIn("| b | 2 | 1,94 |", texto)

    def test_escapa_barras_en_valores(self):
        tabla = pd.DataFrame({"grupo": ["a|b"], "suma": [1]})
        self.assertIn("a\\|b", self._escribir([ResultadoAnalisis(nombre="r", tablas={"t": tabla})]))


class TestAnalizar(unittest.TestCase):
    def setUp(self):
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        self.carpeta = Path(carpeta.name)

    def _csv(self, contenido: str) -> Path:
        ruta = self.carpeta / "datos.csv"
        ruta.write_text(contenido, encoding="utf-8")
        return ruta

    def _completo(self) -> Path:
        filas = ["fecha,dane,ciudad,ventas,costo"]
        for i in range(200):
            dia = f"2024-{(i % 3) + 1:02d}-{(i % 20) + 1:02d}"
            filas.append(f"{dia},{(i % 4) + 1:05d},{'ABC'[i % 3]},{i % 37},{(i % 37) * 2}")
        return self._csv("\n".join(filas) + "\n")

    def test_flujo_completo(self):
        ruta = self._completo()
        original = ruta.read_bytes()
        informe = analizar(ruta, self.carpeta / "salida", todo=True)
        texto = informe.read_text(encoding="utf-8")

        self.assertEqual(informe.parent, self.carpeta / "salida" / "datos")
        generados = {p.name for p in (informe.parent / "tablas").iterdir()}
        self.assertTrue({
            "evolucion_fecha_ventas_anio.csv",
            "evolucion_fecha_ventas_mes.csv",
            "ranking_dane_ventas.csv",
            "ranking_ciudad_costo.csv",
            "correlacion.csv",
        } <= generados)
        self.assertTrue(informe.exists())
        self.assertFalse(any(n.startswith("frecuencias") for n in generados))
        self.assertIn("Frecuencias: solo se usan", texto)
        self.assertIn("no implica causalidad", texto)
        # El archivo de entrada no se toca.
        self.assertEqual(ruta.read_bytes(), original)

    def test_codigo_conserva_ceros_en_el_csv(self):
        informe = analizar(self._completo(), self.carpeta / "salida", todo=True)
        tabla = pd.read_csv(informe.parent / "tablas" / "ranking_dane_ventas.csv", dtype=str)
        self.assertIn("00001", tabla["grupo"].tolist())

    def test_sin_numericas_usa_frecuencias(self):
        ruta = self._csv("ciudad,color\n" + "A,rojo\nB,azul\nA,azul\n" * 10)
        informe = analizar(ruta, self.carpeta / "salida")
        self.assertTrue((informe.parent / "tablas" / "frecuencias_ciudad.csv").exists())
        self.assertIn("Ranking por categoría: no hay columna medible", informe.read_text(encoding="utf-8"))

    def test_serie_diaria_conserva_su_evolucion(self):
        # Una fila por día: la fecha es casi única, pero sigue siendo agrupable.
        filas = "\n".join(
            f"{d.date()},{1000 + i * 1.5}" for i, d in enumerate(pd.date_range("2024-01-01", periods=90))
        )
        informe = analizar(self._csv(f"dia,valor\n{filas}\n"), self.carpeta / "salida")
        self.assertTrue((informe.parent / "tablas" / "evolucion_dia_valor_mes.csv").exists())
        self.assertTrue((informe.parent / "grafico_evolucion_dia_valor.png").exists())

    def test_decimales_con_coma_de_punta_a_punta(self):
        filas = ["fecha;ciudad;monto;tasa"]
        for i in range(120):
            filas.append(f"2023-{i % 12 + 1:02d}-15;{'AB'[i % 2]};{i % 7 + 1}.234,{i % 10};{i % 30},{i % 89 + 10}")
        informe = analizar(self._csv("\n".join(filas) + "\n"), self.carpeta / "salida", todo=True)
        texto = informe.read_text(encoding="utf-8")
        self.assertIn("| `monto` | numero | medible |", texto)
        self.assertIn("| `tasa` | numero | medible |", texto)
        self.assertIn("tenían punto de miles y coma decimal", texto)
        tabla = pd.read_csv(informe.parent / "tablas" / "ranking_ciudad_monto.csv")
        # Cada fila vale (i % 7 + 1) * 1000 + 234 + (i % 10) / 10.
        esperado = sum((i % 7 + 1) * 1000 + 234 + (i % 10) / 10 for i in range(120))
        self.assertAlmostEqual(tabla["suma"].sum(), esperado, places=4)

    def test_coma_ambigua_avisa_y_no_convierte(self):
        filas = "\n".join(f"{'AB'[i % 2]},\"{i % 9 + 1},{i % 900 + 100}\"" for i in range(60))
        texto = analizar(self._csv(f"c,x\n{filas}\n"), self.carpeta / "salida").read_text(encoding="utf-8")
        self.assertIn("son ambiguos", texto)
        self.assertNotIn("| `x` | numero |", texto)

    def test_frecuencias_llevan_grafico(self):
        ruta = self._csv("ciudad,color\n" + "A,rojo\nB,azul\nA,azul\n" * 10)
        informe = analizar(ruta, self.carpeta / "salida")
        self.assertTrue((informe.parent / "grafico_frecuencias_ciudad.png").exists())
        self.assertIn("](grafico_frecuencias_ciudad.png)", informe.read_text(encoding="utf-8"))

    def test_forzar_llega_a_la_clasificacion(self):
        informe = analizar(
            self._completo(),
            self.carpeta / "salida",
            forzar={"ventas": {"rol": "ignorar"}},
        )
        self.assertFalse((informe.parent / "tablas" / "correlacion.csv").exists())

    def test_se_niega_a_escribir_en_data_raw(self):
        with self.assertRaises(ValueError):
            analizar(self._completo(), self.carpeta / "data" / "raw")
        self.assertFalse((self.carpeta / "data").exists())

    def test_csv_sin_filas(self):
        informe = analizar(self._csv("a,b\n"), self.carpeta / "salida")
        self.assertIn("No se ejecutó ningún análisis", informe.read_text(encoding="utf-8"))

    def test_archivo_inexistente(self):
        with self.assertRaises(FileNotFoundError):
            analizar(self.carpeta / "no_existe.csv", self.carpeta / "salida")

    def test_interpretar_forzar(self):
        self.assertEqual(
            _interpretar_forzar(["a.b.tipo=numero", "a.b.rol=medible"]),
            {"a.b": {"tipo": "numero", "rol": "medible"}},
        )
        with self.assertRaises(ValueError):
            _interpretar_forzar(["columna=numero"])


def _fechas(*rangos) -> pd.Series:
    """Serie de fechas a partir de pares (inicio, fin)."""
    return pd.Series(pd.concat([pd.Series(pd.date_range(i, f)) for i, f in rangos], ignore_index=True))


class TestSugerirCorte(unittest.TestCase):
    HOY = pd.Timestamp("2026-06-01")

    def _corte(self, fechas, hoy=None):
        return sugerir_corte(fechas, huecos_calendario(fechas), hoy if hoy is not None else self.HOY)

    def test_huecos_al_final_cortan_en_el_ultimo_mes_completo(self):
        fechas = _fechas(("2024-01-01", "2026-01-02"), ("2026-02-01", "2026-02-02"), ("2026-03-01", "2026-03-02"))
        corte = self._corte(fechas)
        self.assertEqual(corte["hasta"], pd.Timestamp("2025-12-31"))
        self.assertIsNone(corte["desde"])
        self.assertEqual(corte["filas_excluidas"], 6)

    def test_huecos_al_inicio_cortan_con_desde(self):
        fechas = _fechas(("2020-01-01", "2020-01-02"), ("2020-02-01", "2020-02-02"), ("2020-03-01", "2022-12-31"))
        corte = self._corte(fechas)
        self.assertEqual(corte["desde"], pd.Timestamp("2020-03-01"))
        self.assertIsNone(corte["hasta"])

    def test_un_hueco_aislado_no_justifica_un_corte(self):
        fechas = _fechas(("2020-01-01", "2023-06-14"), ("2023-06-16", "2025-12-31"))
        self.assertIsNone(self._corte(fechas))

    def test_datos_semanales_no_dan_corte(self):
        self.assertIsNone(self._corte(pd.Series(pd.date_range("2020-01-01", "2025-12-31", freq="7D"))))

    def test_fechas_futuras_sin_huecos_cortan_en_hoy(self):
        corte = self._corte(_fechas(("2026-01-01", "2026-07-01")))
        self.assertEqual(corte["hasta"], self.HOY)
        self.assertIn("posteriores al día de ejecución", corte["motivos"][0])

    def test_sin_problemas_no_hay_corte(self):
        self.assertIsNone(self._corte(_fechas(("2024-01-01", "2024-12-31"))))


class TestFiltrarPorFecha(unittest.TestCase):
    def setUp(self):
        self.df = pd.DataFrame({
            "f": pd.to_datetime(["2024-01-01", "2024-06-30 18:00", "2024-07-01", None], format="mixed"),
            "v": [1, 2, 3, 4],
        })

    def test_extremos_incluidos_aunque_tengan_hora(self):
        filtrado, _ = filtrar_por_fecha(self.df, "f", hasta=pd.Timestamp("2024-06-30"))
        self.assertEqual(filtrado["v"].tolist(), [1, 2])

    def test_desde(self):
        filtrado, _ = filtrar_por_fecha(self.df, "f", desde=pd.Timestamp("2024-07-01"))
        self.assertEqual(filtrado["v"].tolist(), [3])

    def test_describe_lo_excluido(self):
        _, texto = filtrar_por_fecha(self.df, "f", hasta=pd.Timestamp("2024-06-30"))
        self.assertIn("hasta 2024-06-30", texto)
        self.assertIn("1 filas fuera del rango", texto)
        self.assertIn("1 filas sin fecha válida", texto)


class TestDetectarAgrupaciones(unittest.TestCase):
    def _fusion(self) -> pd.DataFrame:
        # 20 nombres con 22 códigos: 'Dos' tiene dos códigos y 'Tres' tiene tres.
        nombres = [f"n{i}" for i in range(18)] + ["Dos", "Dos", "Tres", "Tres", "Tres"]
        codigos = [f"{i:05d}" for i in range(len(nombres))]
        return _como_texto({"nombre": nombres * 5, "codigo": codigos * 5})

    def test_detecta_la_fusion_y_da_ejemplos(self):
        resultado = detectar_agrupaciones(self._fusion(), ["nombre", "codigo"])
        self.assertEqual(len(resultado.advertencias), 1)
        aviso = resultado.advertencias[0]
        self.assertIn("Agrupar por `nombre` puede estar mezclando", aviso)
        self.assertIn("2 de 20 valores", aviso)
        self.assertIn("'Tres' (3 valores: 00020, 00021, 00022)", aviso)
        self.assertIn("Sugerencia: agrupar por `codigo`", aviso)
        self.assertEqual(list(resultado.avisos_por_columna), ["nombre"])

    def test_limita_a_tres_ejemplos(self):
        nombres = [f"n{i}" for i in range(46)] + ["a", "a", "b", "b", "c", "c", "d", "d"]
        df = _como_texto({"nombre": nombres, "codigo": [str(i) for i in range(len(nombres))]})
        aviso = detectar_agrupaciones(df, ["nombre", "codigo"]).advertencias[0]
        self.assertIn("'a'", aviso)
        self.assertIn("'c'", aviso)
        self.assertNotIn("'d'", aviso)

    def test_acorta_los_valores_de_cada_ejemplo(self):
        nombres = [f"n{i}" for i in range(44)] + ["muchos"] * 6
        df = _como_texto({"nombre": nombres, "codigo": [f"c{i}" for i in range(50)]})
        aviso = detectar_agrupaciones(df, ["nombre", "codigo"]).advertencias[0]
        self.assertIn("'muchos' (6 valores: c44, c45, c46, c47 y 2 más)", aviso)

    def test_tabla_completa_de_afectados_solo_en_csv(self):
        resultado = detectar_agrupaciones(self._fusion(), ["nombre", "codigo"])
        tabla = resultado.tablas["agrupaciones_nombre_codigo"]
        self.assertEqual(tabla["valor"].tolist(), ["Tres", "Dos"])
        self.assertIn("agrupaciones_nombre_codigo", resultado.solo_csv)

    def test_jerarquia_no_avisa(self):
        # Cada departamento tiene varios municipios: no es una fusión.
        df = _como_texto({
            "departamento": [f"d{i % 4}" for i in range(40)],
            "municipio": [f"m{i}" for i in range(40)],
        })
        self.assertEqual(detectar_agrupaciones(df, ["departamento", "municipio"]).advertencias, [])

    def test_columnas_independientes_no_avisan(self):
        df = _como_texto({
            "genero": [["F", "M", "X"][i % 3] for i in range(120)],
            "edad": [["a", "b", "c", "d"][i % 4] for i in range(120)],
        })
        resultado = detectar_agrupaciones(df, ["genero", "edad"])
        self.assertEqual(resultado.advertencias, [])
        self.assertIn("En 1 pares", " ".join(resultado.decisiones))

    def test_nulos_no_cuentan_como_valor(self):
        df = self._fusion()
        df.loc[0, "codigo"] = None
        self.assertEqual(len(detectar_agrupaciones(df, ["nombre", "codigo"]).advertencias), 1)

    def test_mismos_unicos_se_omite(self):
        df = _como_texto({"a": ["x", "y"] * 5, "b": ["1", "2"] * 5})
        resultado = detectar_agrupaciones(df, ["a", "b"])
        self.assertIn("Omití 1 pares", " ".join(resultado.decisiones))

    def test_una_sola_columna(self):
        resultado = detectar_agrupaciones(self._fusion(), ["nombre"])
        self.assertIn("hacen falta 2", " ".join(resultado.decisiones))


class TestInformeCalidadUnificada(unittest.TestCase):
    def setUp(self):
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        self.carpeta = Path(carpeta.name)

    def _seccion_2(self, contenido: str, **kwargs) -> str:
        ruta = self.carpeta / "datos.csv"
        ruta.write_text(contenido, encoding="utf-8")
        texto = analizar(ruta, self.carpeta / "salida", **kwargs).read_text(encoding="utf-8")
        return texto[texto.index("## 2.") : texto.index("## 3.")]

    def test_sin_hallazgos_lo_dice(self):
        filas = "\n".join(
            f"2024-01-{d:02d},{'ab'[i % 2]},{i % 3}" for i in range(60) for d in [i % 28 + 1]
        )
        seccion = self._seccion_2(f"f,c,v\n{filas}\n")
        self.assertIn("No hay problemas de calidad", seccion)
        self.assertNotIn("Sin problemas evidentes", seccion)

    def test_un_solo_listado_con_perfilar_y_chequeos(self):
        # Duplicados (perfilar) y un hueco grande al final (chequeo de fechas).
        filas = [f"{d.date()},a,{i % 3}" for i, d in enumerate(pd.date_range("2024-01-01", periods=400))]
        filas += ["2025-06-01,b,1", "2025-06-01,b,1"]
        seccion = self._seccion_2("f,c,v\n" + "\n".join(filas * 3) + "\n")
        self.assertEqual(seccion.count("### Hallazgos"), 1)
        self.assertIn("**perfilar():**", seccion)
        self.assertIn("filas duplicadas", seccion)
        self.assertIn("**Fechas de `f`:**", seccion)
        self.assertNotIn("Sin problemas evidentes", seccion)
        self.assertNotIn("CALIDAD DE DATOS", seccion)


class TestFiltroYSugerencia(unittest.TestCase):
    def setUp(self):
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        self.carpeta = Path(carpeta.name)
        # 2024 completo más un tramo roto: solo los días 1 y 2 de marzo a mayo de 2025.
        dias = list(pd.date_range("2024-01-01", "2025-01-02"))
        for mes in (3, 4, 5):
            dias += [pd.Timestamp(2025, mes, 1), pd.Timestamp(2025, mes, 2)]
        lineas = ["fecha,c,v"] + [f"{d.date()},{'ab'[i % 2]},{i % 5}" for i, d in enumerate(dias * 3)]
        self.ruta = self.carpeta / "datos.csv"
        self.ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")
        self.total_filas = len(lineas) - 1

    def _informe(self, **kwargs) -> tuple[Path, str]:
        informe = analizar(self.ruta, self.carpeta / "salida", **kwargs)
        return informe, informe.read_text(encoding="utf-8")

    def test_sugiere_el_comando_exacto_sin_excluir_nada(self):
        informe, texto = self._informe(todo=True)
        self.assertIn("Sugerencia, no aplicada", texto)
        self.assertIn(f"--hasta 2024-12-31 --salida", texto)
        self.assertIn("No excluí nada", texto)
        # Sin filtro, todas las filas siguen en los resultados.
        tabla = pd.read_csv(informe.parent / "tablas" / "ranking_c_v.csv")
        self.assertEqual(tabla["filas"].sum(), self.total_filas)
        self.assertEqual(informe.parent.name, "datos")

    def test_el_comando_sugerido_funciona_y_limpia_los_hallazgos(self):
        informe, texto = self._informe(hasta="2024-12-31", todo=True)
        self.assertEqual(informe.parent.name, "datos_hasta_2024-12-31")
        self.assertIn("**Filtro aplicado por el analista:**", texto)
        self.assertIn("No hay problemas de calidad", texto)
        self.assertNotIn("Sugerencia, no aplicada", texto)
        self.assertEqual(pd.read_csv(informe.parent / "tablas" / "ranking_c_v.csv")["filas"].sum(), 366 * 3)

    def test_el_informe_filtrado_no_pisa_el_completo(self):
        completo, _ = self._informe()
        filtrado, _ = self._informe(hasta="2024-12-31")
        self.assertNotEqual(completo, filtrado)
        self.assertTrue(completo.exists())

    def test_sin_filtro_lo_declara(self):
        _, texto = self._informe()
        self.assertIn("Filtro por fecha: no excluí ninguna fila", texto)

    def test_el_comando_conserva_opciones_y_cita_rutas_con_espacios(self):
        ruta = self.carpeta / "con espacio.csv"
        ruta.write_bytes(self.ruta.read_bytes())
        texto = analizar(ruta, self.carpeta / "salida", forzar={"c": {"rol": "ignorar"}}).read_text(encoding="utf-8")
        self.assertIn(f'"{ruta}" --hasta 2024-12-31', texto)
        self.assertIn("--forzar c.rol=ignorar", texto)

    def test_fecha_de_filtro_invalida(self):
        with self.assertRaises(ValueError):
            self._informe(hasta="31/12/2024")

    def test_desde_posterior_a_hasta(self):
        with self.assertRaises(ValueError):
            self._informe(desde="2025-01-01", hasta="2024-01-01")

    def test_filtro_que_no_deja_filas(self):
        with self.assertRaises(ValueError):
            self._informe(desde="2030-01-01")
        self.assertFalse((self.carpeta / "salida").exists())

    def test_filtro_sin_columna_de_fecha(self):
        ruta = self.carpeta / "sin_fecha.csv"
        ruta.write_text("c,v\n" + "a,1\nb,2\na,1\n" * 10, encoding="utf-8")
        with self.assertRaises(ValueError):
            analizar(ruta, self.carpeta / "salida", hasta="2024-12-31")

    def test_varias_fechas_exigen_elegir_columna(self):
        ruta = self.carpeta / "dos_fechas.csv"
        filas = "\n".join(f"2024-01-{i % 9 + 1:02d},2024-02-{i % 7 + 1:02d},{i % 4}" for i in range(50))
        ruta.write_text(f"inicio,fin,v\n{filas}\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            analizar(ruta, self.carpeta / "salida", hasta="2024-01-05")
        informe = analizar(ruta, self.carpeta / "salida", hasta="2024-01-05", columna_fecha="inicio")
        self.assertIn("`inicio` hasta 2024-01-05", informe.read_text(encoding="utf-8"))

    def test_aviso_de_agrupacion_llega_al_ranking(self):
        ruta = self.carpeta / "fusion.csv"
        nombres = [f"n{i}" for i in range(18)] + ["Dos", "Dos"]
        # Cada código se repite en varias filas para que el ratio no lo descarte.
        filas = "\n".join(f"{n},{i % 20:05d},{i % 7}" for i, n in enumerate(nombres * 5))
        ruta.write_text(f"nombre,codigo,v\n{filas}\n", encoding="utf-8")
        texto = analizar(ruta, self.carpeta / "salida", todo=True).read_text(encoding="utf-8")
        seccion_5 = texto[texto.index("## 5.") : texto.index("## 6.")]
        ranking = seccion_5[seccion_5.index("### Ranking de `nombre`") :]
        # El aviso va una sola vez, en la sección 2; el ranking solo lo cita.
        self.assertIn("Aplica lo dicho en la sección 2: H", ranking)
        self.assertEqual(texto.count("puede estar mezclando"), 1)


class TestAtributos(unittest.TestCase):
    def _df(self, filas_por_entidad=10):
        ids = [str(1000 + i) for i in range(20)]
        return _como_texto({
            "peaje_id": ids * filas_por_entidad,
            "lat": [f"{i * 0.5 + 3:.2f}" for i in range(20)] * filas_por_entidad,
            "trafico": [str(i % 13) for i in range(20 * filas_por_entidad)],
        })

    def test_un_valor_por_entidad_es_atributo(self):
        columnas = _por_columna(self._df())
        self.assertEqual(columnas["lat"].rol, "atributo")
        self.assertEqual(columnas["lat"].entidad, "peaje_id")
        self.assertIn("un solo valor por cada valor de `peaje_id`", columnas["lat"].motivo_rol)
        self.assertEqual(columnas["trafico"].rol, "medible")

    def test_una_fecha_no_cuenta_como_entidad(self):
        # Una tasa de cambio tiene un valor por día, pero es una medida que evoluciona.
        dias = [str(d.date()) for d in pd.date_range("2024-01-01", periods=20)]
        df = _como_texto({
            "dia": dias * 10,
            "tasa": [f"{4000 + i * 3}" for i in range(20)] * 10,
        })
        self.assertEqual(_por_columna(df)["tasa"].rol, "medible")

    def test_pocas_filas_por_entidad_no_bastan(self):
        # Con 2 filas por entidad, un solo valor puede ser coincidencia.
        self.assertEqual(_por_columna(self._df(filas_por_entidad=2))["lat"].rol, "medible")

    def test_forzar_medible_se_respeta(self):
        columnas = _por_columna(self._df(), forzar={"lat": {"rol": "medible"}})
        self.assertEqual(columnas["lat"].rol, "medible")
        self.assertIsNone(columnas["lat"].entidad)

    def test_solo_un_numero_puede_ser_atributo(self):
        with self.assertRaises(ValueError):
            clasificar_columnas(self._df(), forzar={"peaje_id": {"rol": "atributo"}})

    def test_atributo_no_entra_en_ningun_analisis(self):
        planes, _, descartados = elegir_analisis(clasificar_columnas(self._df()))
        columnas = {p[2].columna for p in planes if p[0] == "ranking"}
        self.assertEqual(columnas, {"trafico"})
        self.assertFalse(any(p[0] == "correlacion" for p in planes))
        self.assertTrue(any(d.startswith("`lat` queda fuera") for d in descartados))


def _plan(datos: dict, todo: bool = False):
    df = _como_texto(datos)
    clasificacion = clasificar_columnas(df)
    planes, elegidos, _ = elegir_analisis(clasificacion)
    # Como en analizar(): la prioridad recibe los datos ya convertidos.
    tipado = df.copy()
    for c in clasificacion:
        if c.tipo == "numero":
            tipado[c.columna] = pd.to_numeric(df[c.columna])
        elif c.tipo == "fecha":
            tipado[c.columna] = pd.to_datetime(df[c.columna])
    return priorizar_analisis(tipado, clasificacion, planes, elegidos, todo=todo), clasificacion


class TestPrioridad(unittest.TestCase):
    def test_fechas_gemelas_conserva_la_mas_temprana(self):
        df = pd.DataFrame({
            "inicio": pd.to_datetime(["2024-01-01", "2024-02-01", "2024-03-01"]),
            "fin": pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-31"]),
        })
        self.assertEqual(fechas_gemelas(df, ["inicio", "fin"]), {"fin": "inicio"})

    def test_fechas_de_meses_distintos_no_son_gemelas(self):
        df = pd.DataFrame({
            "pedido": pd.to_datetime(["2024-01-15", "2024-02-15", "2024-03-15"]),
            "entrega": pd.to_datetime(["2024-03-01", "2024-04-01", "2024-05-01"]),
        })
        self.assertEqual(fechas_gemelas(df, ["pedido", "entrega"]), {})

    def test_agrupaciones_casi_uno_a_uno_conservan_la_mas_fina(self):
        nombres = [f"n{i}" for i in range(19)] + ["n0"]
        df = _como_texto({"nombre": nombres * 5, "codigo": [f"c{i}" for i in range(20)] * 5})
        clasificacion = clasificar_columnas(df)
        self.assertEqual(agrupaciones_equivalentes(df, clasificacion), {"nombre": "codigo"})

    def test_jerarquia_no_es_equivalente(self):
        df = _como_texto({
            "departamento": [f"d{i % 4}" for i in range(400)],
            "municipio": [f"m{i % 40}" for i in range(400)],
        })
        self.assertEqual(agrupaciones_equivalentes(df, clasificar_columnas(df)), {})

    def test_medida_casi_constante_solo_deja_resumen(self):
        prioridad, _ = _plan({
            "c": [f"g{i % 4}" for i in range(400)],
            "evasores": ["0"] * 396 + ["1", "2", "3", "4"],
        })
        self.assertEqual([p for p in prioridad.planes if p[0] == "ranking"], [])
        self.assertIn("99,0 %", prioridad.resumenes[0].descripciones[0])
        self.assertTrue(any("casi constante" in o["motivo"] for o in prioridad.omitidos))

    def test_omite_rankings_con_eta2_bajo_y_lo_dice(self):
        # `v` no depende de `ruido`, y sí de `fuerte`.
        prioridad, _ = _plan({
            "fuerte": [f"g{i % 4}" for i in range(1000)],
            "ruido": [f"r{i % 7}" for i in range(1000)],
            "v": [str((i % 4) * 100 + i % 7) for i in range(1000)],
        })
        grupos = [p[1].columna for p in prioridad.planes if p[0] == "ranking"]
        self.assertEqual(grupos, ["fuerte"])
        omitido = next(o for o in prioridad.omitidos if "ruido" in o["analisis"])
        self.assertIn("η² ajustado menor", omitido["motivo"])

    def test_tope_de_rankings_por_medida(self):
        datos = {f"c{k}": [f"g{i % (k + 2)}" for i in range(1200)] for k in range(5)}
        datos["v"] = [str(sum((i % (k + 2)) * 10 for k in range(5)) + i % 11) for i in range(1200)]
        prioridad, _ = _plan(datos)
        self.assertEqual(len([p for p in prioridad.planes if p[0] == "ranking"]), 3)
        self.assertTrue(any("tope de 3" in o["motivo"] for o in prioridad.omitidos))

    def test_todo_desactiva_la_prioridad(self):
        prioridad, _ = _plan({
            "ruido": [f"r{i % 7}" for i in range(1000)],
            "v": [str(i % 5) for i in range(1000)],
        }, todo=True)
        self.assertEqual(len([p for p in prioridad.planes if p[0] == "ranking"]), 1)
        self.assertEqual(prioridad.omitidos, [])


class TestInformeSinRepeticiones(unittest.TestCase):
    def setUp(self):
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        self.carpeta = Path(carpeta.name)
        # Dos fechas gemelas, un atributo, un par casi 1:1 y dos medidas con señal.
        filas = ["desde,hasta,codigo,nombre,lat,ventas,costo"]
        for i in range(600):
            mes = i % 12 + 1
            grupo = i % 12
            nombre = "Repetido" if grupo in (0, 1) else f"n{grupo}"
            filas.append(
                f"2024-{mes:02d}-01,2024-{mes:02d}-28,{grupo:03d},{nombre},{grupo * 0.5 + 3:.1f},"
                f"{grupo * 100 + i % 7},{grupo * 40 + i % 5}"
            )
        self.ruta = self.carpeta / "datos.csv"
        self.ruta.write_text("\n".join(filas) + "\n", encoding="utf-8")

    def _texto(self, **kwargs) -> tuple[Path, str]:
        informe = analizar(self.ruta, self.carpeta / "salida", **kwargs)
        return informe, informe.read_text(encoding="utf-8")

    def test_usa_una_sola_fecha_gemela_y_lo_explica(self):
        informe, texto = self._texto()
        self.assertIn("`hasta` es gemela de `desde`", texto)
        self.assertNotIn("Evolución de `ventas` por `hasta`", texto[texto.index("## 5.") :])
        self.assertTrue((informe.parent / "tablas" / "evolucion_desde_ventas_anio.csv").exists())
        self.assertFalse((informe.parent / "tablas" / "evolucion_hasta_ventas_anio.csv").exists())

    def test_atributo_fuera_de_correlacion_y_de_graficos(self):
        informe, texto = self._texto()
        self.assertEqual(
            pd.read_csv(informe.parent / "tablas" / "correlacion.csv").columns.tolist(),
            ["r de Pearson", "ventas", "costo"],
        )
        self.assertFalse(any("lat" in p.name for p in informe.parent.glob("*.png")))
        self.assertIn("| `lat` | numero | atributo |", texto)
        self.assertIn("--forzar lat.rol=medible", texto)

    def test_ranking_lleva_la_etiqueta_de_su_equivalente(self):
        informe, _ = self._texto()
        tabla = pd.read_csv(informe.parent / "tablas" / "ranking_codigo_ventas.csv", dtype=str)
        self.assertEqual(tabla.columns[:2].tolist(), ["grupo", "etiqueta"])
        self.assertFalse((informe.parent / "tablas" / "ranking_nombre_ventas.csv").exists())

    def test_advertencia_repetida_va_una_sola_vez(self):
        _, texto = self._texto()
        self.assertEqual(texto.count("puede estar mezclando"), 1)
        seccion_5 = texto[texto.index("## 5.") : texto.index("## 6.")]
        self.assertIn("Aplica lo dicho en la sección 2: H", seccion_5)

    def test_decisiones_comunes_van_en_un_solo_bloque(self):
        _, texto = self._texto()
        seccion_5 = texto[texto.index("## 5.") : texto.index("## 6.")]
        self.assertIn("### Cómo leer las tablas", seccion_5)
        self.assertEqual(seccion_5.count("Ordené por suma"), 1)

    def test_omitidos_con_comando_para_verlos(self):
        _, texto = self._texto()
        self.assertIn("### Omitidos por prioridad", texto)
        self.assertRegex(texto, r"python src/agente\.py .*--todo")

    def test_todo_genera_lo_omitido_pero_nunca_atributos(self):
        informe, _ = self._texto(todo=True)
        self.assertTrue((informe.parent / "tablas" / "evolucion_hasta_ventas_anio.csv").exists())
        self.assertTrue((informe.parent / "tablas" / "ranking_nombre_ventas.csv").exists())
        self.assertFalse(list((informe.parent / "tablas").glob("*_lat*")))

    def test_inserta_cada_grafico_en_el_markdown(self):
        informe, texto = self._texto()
        pngs = {p.name for p in informe.parent.glob("*.png")}
        self.assertTrue(pngs)
        for nombre in pngs:
            self.assertIn(f"]({nombre})", texto)

    def test_una_corrida_nueva_borra_resultados_viejos_del_agente(self):
        informe, _ = self._texto(todo=True)
        ajeno = informe.parent / "notas.txt"
        ajeno.write_text("mío", encoding="utf-8")
        _, _ = self._texto()
        self.assertFalse((informe.parent / "tablas" / "evolucion_hasta_ventas_anio.csv").exists())
        self.assertTrue(ajeno.exists())

    def test_unidad_acepta_formato_y_rechaza_el_invalido(self):
        self.assertEqual(_interpretar_unidades(["t=vehículos"]), {"t": "vehículos"})
        with self.assertRaises(ValueError):
            _interpretar_unidades(["sin_igual"])


class TestMain(unittest.TestCase):
    def setUp(self):
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        self.carpeta = Path(carpeta.name)
        self.ruta = self.carpeta / "datos.csv"
        self.ruta.write_text("c,v\n" + "a,1\nb,2\na,1\n" * 10, encoding="utf-8")

    def _main(self, *argumentos):
        with patch.object(sys, "argv", ["agente.py", *map(str, argumentos)]), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return main()

    def test_genera_el_informe(self):
        self.assertEqual(self._main(self.ruta, "--salida", self.carpeta / "s"), 0)
        self.assertTrue((self.carpeta / "s" / "datos" / "informe.md").exists())

    def test_forzar_desde_la_linea_de_comandos(self):
        self.assertEqual(self._main(self.ruta, "--salida", self.carpeta / "s", "--forzar", "v.rol=ignorar"), 0)
        self.assertFalse((self.carpeta / "s" / "datos" / "ranking_c_v.csv").exists())

    def test_errores_devuelven_1(self):
        self.assertEqual(self._main(self.carpeta / "no_existe.csv"), 1)
        self.assertEqual(self._main(self.ruta, "--salida", self.carpeta / "data" / "raw"), 1)
        self.assertEqual(self._main(self.ruta, "--forzar", "v.tipo=inventado"), 1)
        self.assertEqual(self._main(self.ruta, "--hasta", "no-es-fecha"), 1)

    def test_filtro_desde_la_linea_de_comandos(self):
        ruta = self.carpeta / "con_fecha.csv"
        ruta.write_text("f,c,v\n" + "2024-01-01,a,1\n2024-01-02,b,2\n2024-02-01,a,3\n" * 5, encoding="utf-8")
        self.assertEqual(self._main(ruta, "--salida", self.carpeta / "s", "--hasta", "2024-01-31", "--todo"), 0)
        tabla = pd.read_csv(self.carpeta / "s" / "con_fecha_hasta_2024-01-31" / "tablas" / "ranking_c_v.csv")
        self.assertEqual(tabla["filas"].sum(), 10)


if __name__ == "__main__":
    unittest.main()
