"""Consultas reutilizables sobre la base de delitos.

Todas las funciones devuelven un DataFrame y reciben una conexión DuckDB
creada con `conectar()`, que ya deja la vista `d` lista y excluye 2026.

Uso desde un notebook:

    from consultas import conectar, top_municipios
    con = conectar()
    top_municipios(con, "Hurto personas")
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

# Las fechas de 2026 tienen el día y el mes intercambiados (ver
# reports/perfil_v_delitos.md). Se excluyen por defecto.
CORTE_FECHA = "2026-01-01"


def conectar(
    ruta_csv: str | Path = "data/raw/v_delitos.csv",
    incluir_2026: bool = False,
) -> duckdb.DuckDBPyConnection:
    """Abre una conexión con la vista `d` lista para consultar.

    Por defecto excluye 2026, cuyas fechas están corruptas. Pasa
    `incluir_2026=True` solo si vas a trabajar sobre ese problema.
    """
    con = duckdb.connect()
    filtro = "" if incluir_2026 else f"WHERE fecha < DATE '{CORTE_FECHA}'"
    con.sql(f"CREATE VIEW d AS SELECT * FROM read_csv('{ruta_csv}') {filtro}")
    return con


def top_municipios(
    con: duckdb.DuckDBPyConnection,
    tipo: str | None = None,
    limite: int = 10,
) -> pd.DataFrame:
    """Municipios con más casos.

    Agrupa por `cod_dane`, no por nombre: hay nombres de municipio repetidos
    en varios departamentos (Barbosa, Villanueva, Granada...) y agrupar por
    nombre los suma como si fueran uno solo.
    """
    filtro = f"WHERE tipo = '{tipo}'" if tipo else ""
    return con.sql(
        f"""
        SELECT
            cod_dane,
            any_value(departamento) AS departamento,
            any_value(municipio)    AS municipio,
            SUM(cantidad)::BIGINT   AS casos
        FROM d
        {filtro}
        GROUP BY cod_dane
        ORDER BY casos DESC
        LIMIT {limite}
        """
    ).df()


def serie_anual(
    con: duckdb.DuckDBPyConnection,
    tipo: str | None = None,
    departamento: str | None = None,
) -> pd.DataFrame:
    """Casos por año, para ver la evolución en el tiempo.

    Recuerda que 2020 fue año de confinamientos: no leas el crecimiento
    2020-2023 como una tendencia natural.
    """
    condiciones = []
    if tipo:
        condiciones.append(f"tipo = '{tipo}'")
    if departamento:
        condiciones.append(f"departamento = '{departamento}'")
    filtro = ("WHERE " + " AND ".join(condiciones)) if condiciones else ""

    return con.sql(
        f"""
        SELECT YEAR(fecha) AS anio, SUM(cantidad)::BIGINT AS casos
        FROM d
        {filtro}
        GROUP BY anio
        ORDER BY anio
        """
    ).df()


def comparar_anios(
    con: duckdb.DuckDBPyConnection,
    anio_base: int,
    anio_final: int,
    tipo: str | None = None,
) -> pd.DataFrame:
    """Variación por departamento entre dos años.

    Devuelve el cambio absoluto y porcentual, ordenado de mayor subida a
    mayor caída.
    """
    filtro = f"AND tipo = '{tipo}'" if tipo else ""
    return con.sql(
        f"""
        WITH base AS (
            SELECT departamento, SUM(cantidad) AS casos
            FROM d WHERE YEAR(fecha) = {anio_base} {filtro}
            GROUP BY departamento
        ),
        final AS (
            SELECT departamento, SUM(cantidad) AS casos
            FROM d WHERE YEAR(fecha) = {anio_final} {filtro}
            GROUP BY departamento
        )
        SELECT
            b.departamento,
            b.casos::BIGINT AS casos_{anio_base},
            f.casos::BIGINT AS casos_{anio_final},
            (f.casos - b.casos)::BIGINT AS cambio,
            ROUND((f.casos - b.casos) * 100.0 / b.casos, 1) AS cambio_pct
        FROM base b
        JOIN final f USING (departamento)
        ORDER BY cambio_pct DESC
        """
    ).df()


def homonimos(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Nombres de municipio que existen en más de un departamento.

    Sirve para comprobar cuánto se infla un total si se agrupa por nombre
    en vez de por `cod_dane`.
    """
    return con.sql(
        """
        SELECT
            municipio,
            COUNT(DISTINCT cod_dane)       AS municipios_distintos,
            list(DISTINCT departamento)    AS departamentos,
            SUM(cantidad)::BIGINT          AS casos_sumados
        FROM d
        GROUP BY municipio
        HAVING COUNT(DISTINCT cod_dane) > 1
        ORDER BY casos_sumados DESC
        """
    ).df()


def tipos_disponibles(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Lista los tipos de delito con su volumen, para saber qué pedir."""
    return con.sql(
        """
        SELECT tipo, SUM(cantidad)::BIGINT AS casos
        FROM d GROUP BY tipo ORDER BY casos DESC
        """
    ).df()
