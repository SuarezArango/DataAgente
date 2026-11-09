"""Perfilado de calidad de datos.

Primer paso obligatorio al recibir cualquier dataset nuevo: antes de analizar
hay que saber con qué se está trabajando.

Uso:
    python src/perfilar.py "data/raw/mi_dataset.csv"
    python src/perfilar.py "data/raw/mi_dataset.csv" --guardar
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

# Formato de Colombia y casi toda Latinoamérica: punto de miles, coma decimal.
PATRON_COMA_DECIMAL = r"[+-]?(?:\d{1,3}(?:\.\d{3})+|\d+),\d+"
PATRON_SOLO_MILES = r"[+-]?\d{1,3}(?:\.\d{3})+"
PATRON_ENTERO = r"[+-]?\d+"
PATRON_COMA_TRES_DIGITOS = r"[+-]?\d+,\d{3}"
MINIMO_DECIMAL_COMA = 0.95


def normalizar_decimales_coma(df: pd.DataFrame, como_texto: bool = False) -> pd.DataFrame:
    """Convierte a número las columnas escritas como '19.312,7' o '27,25'.

    Lo que hizo queda en df.attrs: "decimales_coma" (columna -> ejemplo original) y
    "decimales_ambiguos" (columna -> ejemplo sin convertir). Una columna cuyas comas
    siempre llevan 3 dígitos y sin puntos no se toca: '1,234' puede ser 1234 o 1,234.
    Un '1.234' sin ninguna coma en la columna tampoco: puede ser un decimal inglés.
    """
    convertidas: dict[str, str] = {}
    ambiguas: dict[str, str] = {}

    for columna in columnas_texto(df):
        texto = df[columna].astype("string").str.strip()
        valores = texto.dropna()
        valores = valores[valores != ""]
        if valores.empty:
            continue
        con_coma = valores.str.fullmatch(PATRON_COMA_DECIMAL)
        if not con_coma.any():
            continue
        solo_miles = valores.str.fullmatch(PATRON_SOLO_MILES)
        validos = con_coma | solo_miles | valores.str.fullmatch(PATRON_ENTERO)
        if validos.mean() < MINIMO_DECIMAL_COMA:
            continue

        comas = valores[con_coma]
        if (
            not solo_miles.any()
            and not comas.str.contains(".", regex=False).any()
            and comas.str.fullmatch(PATRON_COMA_TRES_DIGITOS).all()
        ):
            ambiguas[str(columna)] = str(comas.iloc[0])
            continue

        convertidas[str(columna)] = str(comas.iloc[0])
        normalizados = (
            valores[validos].str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
        )
        nueva = df[columna].astype(object)
        nueva.loc[normalizados.index] = normalizados.astype(object)
        # Con como_texto sigue como texto, para que el agente lo clasifique igual
        # que cualquier otra columna. Lo que no encajó queda intacto.
        df[columna] = nueva.astype("str") if como_texto else pd.to_numeric(nueva, errors="coerce")

    df.attrs["decimales_coma"] = convertidas
    df.attrs["decimales_ambiguos"] = ambiguas
    if convertidas:
        print(f"Decimales con coma convertidos a número en: {', '.join(convertidas)}")
    return df


def cargar(ruta: Path, como_texto: bool = False) -> pd.DataFrame:
    """Lee un CSV o Excel y devuelve un DataFrame.

    Prueba varias codificaciones y separadores, porque los datasets reales
    rara vez vienen en UTF-8 con comas. Convierte los números con punto de miles
    y coma decimal; ver normalizar_decimales_coma().

    Con `como_texto=True` no infiere tipos y todo llega como texto, para poder
    distinguir '05001' de 5001.
    """
    tipo_dato = str if como_texto else None

    if ruta.suffix.lower() in {".xlsx", ".xls"}:
        return normalizar_decimales_coma(pd.read_excel(ruta, dtype=tipo_dato), como_texto)

    for codificacion in ("utf-8", "latin-1"):
        for separador in (",", ";", "\t"):
            try:
                df = pd.read_csv(ruta, encoding=codificacion, sep=separador, dtype=tipo_dato)
            except (UnicodeDecodeError, pd.errors.ParserError):
                continue
            # Si quedó todo en una sola columna, el separador no era el correcto.
            if df.shape[1] > 1:
                print(f"Leído con codificacion={codificacion} separador='{separador}'")
                return normalizar_decimales_coma(df, como_texto)

    raise ValueError(
        f"No se pudo leer {ruta.name}. Revisa la codificación y el separador."
    )


def columnas_texto(df: pd.DataFrame) -> list:
    """Columnas de texto o categóricas.

    Se seleccionan por exclusión para funcionar igual en pandas 2 y 3, donde
    el texto cambió de dtype 'object' a 'str'.
    """
    numericas_y_fechas = df.select_dtypes(
        include=["number", "datetime", "datetimetz", "timedelta", "bool"]
    ).columns
    return [columna for columna in df.columns if columna not in numericas_y_fechas]


def resumen_general(df: pd.DataFrame) -> str:
    filas, columnas = df.shape
    memoria_mb = df.memory_usage(deep=True).sum() / 1_048_576
    return (
        "RESUMEN GENERAL\n"
        f"  Filas:    {filas:,}\n"
        f"  Columnas: {columnas}\n"
        f"  Memoria:  {memoria_mb:.1f} MB\n"
    )


def resumen_columnas(df: pd.DataFrame) -> str:
    lineas = ["COLUMNAS", ""]
    cabecera = f"  {'columna':<28} {'tipo':<12} {'nulos':>10} {'únicos':>10}"
    lineas.append(cabecera)
    lineas.append("  " + "-" * (len(cabecera) - 2))

    total = len(df)
    for columna in df.columns:
        nulos = int(df[columna].isna().sum())
        pct = (nulos / total * 100) if total else 0.0
        unicos = int(df[columna].nunique(dropna=True))
        nombre = str(columna)[:27]
        tipo = str(df[columna].dtype)[:11]
        lineas.append(
            f"  {nombre:<28} {tipo:<12} {nulos:>6} ({pct:>3.0f}%) {unicos:>10,}"
        )
    return "\n".join(lineas) + "\n"


def problemas_de_calidad(df: pd.DataFrame) -> str:
    """Señala lo que hay que decidir antes de analizar."""
    avisos: list[str] = []
    total = len(df)

    duplicados = int(df.duplicated().sum())
    if duplicados:
        pct = duplicados / total * 100 if total else 0
        avisos.append(f"{duplicados:,} filas duplicadas ({pct:.1f}%)")

    # Columnas enteramente vacías: no aportan nada.
    vacias = [c for c in df.columns if df[c].isna().all()]
    if vacias:
        avisos.append(f"Columnas totalmente vacías: {', '.join(map(str, vacias))}")

    # Columnas con un solo valor: constantes, tampoco aportan.
    constantes = [
        c for c in df.columns if df[c].nunique(dropna=True) == 1 and c not in vacias
    ]
    if constantes:
        avisos.append(f"Columnas con un solo valor: {', '.join(map(str, constantes))}")

    # Nulos severos.
    severos = [
        f"{c} ({df[c].isna().sum() / total * 100:.0f}%)"
        for c in df.columns
        if total and df[c].isna().sum() / total > 0.3
    ]
    if severos:
        avisos.append(f"Más del 30% de nulos en: {', '.join(severos)}")

    # Texto que parece fecha sin convertir.
    for columna in columnas_texto(df):
        muestra = df[columna].dropna().astype(str).head(20)
        if muestra.empty:
            continue
        if muestra.str.match(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}").mean() > 0.8:
            avisos.append(f"'{columna}' parece fecha pero está como texto")

    # Categorías que difieren solo por mayúsculas o espacios.
    for columna in columnas_texto(df):
        serie = df[columna].dropna().astype(str)
        if serie.empty or serie.nunique() > 200:
            continue
        if serie.nunique() > serie.str.strip().str.lower().nunique():
            avisos.append(
                f"'{columna}' tiene categorías repetidas por mayúsculas o espacios"
            )

    if not avisos:
        return "CALIDAD DE DATOS\n  Sin problemas evidentes.\n"

    lineas = ["CALIDAD DE DATOS", ""]
    lineas += [f"  - {aviso}" for aviso in avisos]
    return "\n".join(lineas) + "\n"


def resumen_numerico(df: pd.DataFrame) -> str:
    # Se omiten las columnas vacías: no tienen estadísticas que reportar.
    numericas = df.select_dtypes(include="number").dropna(axis=1, how="all")
    if numericas.empty:
        return ""
    descripcion = numericas.describe().T[["min", "mean", "50%", "max"]]
    descripcion.columns = ["min", "media", "mediana", "max"]
    return "VARIABLES NUMÉRICAS\n\n" + descripcion.to_string(
        float_format=lambda valor: f"{valor:,.2f}"
    ) + "\n"


def perfilar(df: pd.DataFrame, nombre: str) -> str:
    bloques = [
        f"PERFIL DE: {nombre}",
        "=" * 60,
        "",
        resumen_general(df),
        resumen_columnas(df),
        problemas_de_calidad(df),
        resumen_numerico(df),
    ]
    return "\n".join(bloque for bloque in bloques if bloque is not None)


def main() -> int:
    parser = argparse.ArgumentParser(description="Perfila un dataset.")
    parser.add_argument("ruta", help="Ruta al CSV o Excel")
    parser.add_argument(
        "--guardar",
        action="store_true",
        help="Guarda el perfil en reports/",
    )
    args = parser.parse_args()

    ruta = Path(args.ruta)
    if not ruta.exists():
        print(f"No existe el archivo: {ruta}", file=sys.stderr)
        return 1

    df = cargar(ruta)
    perfil = perfilar(df, ruta.name)
    print(perfil)

    if args.guardar:
        destino = Path("reports") / f"perfil_{ruta.stem}.txt"
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(perfil, encoding="utf-8")
        print(f"Perfil guardado en {destino}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
