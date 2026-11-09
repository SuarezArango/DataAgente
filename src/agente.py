"""Orquestador de DataAgente.

Recibe cualquier CSV, lo perfila, decide qué análisis tienen sentido según
los tipos de columna que encuentre y escribe un informe que explica cada
decisión. No sabe nada del dominio: solo describe lo que calcula.

Uso:
    python src/agente.py "data/raw/mi_dataset.csv"
    python src/agente.py "data/raw/mi_dataset.csv" --todo
"""

from __future__ import annotations

import argparse
import itertools
import re
import sys
import warnings
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from graficar import graficar_resultado
from perfilar import cargar, perfilar

# Qué ES la columna: lo decide su contenido.
TIPOS = ("fecha", "numero", "codigo", "texto")

# Qué se puede HACER con ella. Un atributo es un número que describe a una entidad
# (la latitud de un peaje): no se agrega, no se correlaciona y no se grafica.
ROLES = ("medible", "agrupable", "atributo", "ignorar")

# Un número es atributo si tiene un solo valor por entidad y cada entidad se repite
# al menos estas filas en promedio. Con menos, puede ser solo una coincidencia.
MINIMO_FILAS_POR_ENTIDAD = 5

# Por encima de este ratio (únicos / filas) casi cada fila tiene un valor propio.
RATIO_IGNORAR = 0.5

# Con más valores únicos que este no caben todos en el informe.
UNICOS_INFORME = 50

# Proporción mínima de valores que deben convertirse para aceptar un tipo.
MINIMO_CONVERSION = 0.95
TAMANO_MUESTRA_FECHAS = 1_000

# Una fecha debe parecerlo antes de intentar leerla: pandas también acepta '27,25'.
# Va con / o - y 2 o 3 componentes. Con 2, uno debe ser un año de 4 cifras o el
# nombre de un mes: sin eso, un rango como '18-25' pasaría por fecha.
_COMPONENTE_FECHA = r"(?:\d{1,4}|[^\W\d_]{3,})"
_FINAL_FECHA = r"(?:[T\s].*)?"
PATRON_FECHA = (
    rf"(?:{_COMPONENTE_FECHA}[-/]{_COMPONENTE_FECHA}[-/]{_COMPONENTE_FECHA}"
    rf"|\d{{4}}[-/]\d{{1,2}}|\d{{1,2}}[-/]\d{{4}}"
    rf"|[^\W\d_]{{3,}}[-/]\d{{1,4}}|\d{{1,4}}[-/][^\W\d_]{{3,}}){_FINAL_FECHA}"
)

# Palabras que, como parte del nombre, delatan un código y no una cantidad.
PALABRAS_CODIGO = {"id", "key", "clave", "codigo", "código"}

# Los nulos de una columna de agrupación forman su propio grupo, con esta etiqueta.
ETIQUETA_NULO = "(nulo)"

# Filas que muestra el informe de una tabla recortada; el CSV siempre va completo.
FILAS_INICIO_INFORME = 10
FILAS_FIN_INFORME = 5

# Cuántas posiciones se comparan entre el ranking por filas y el ranking por suma.
TOP_COMPARACION = 10

# Desde este |r| el informe lista el par de variables por separado.
UMBRAL_CORRELACION = 0.5

# Una fusión de entidades se ve así: casi cada valor de B corresponde a un solo
# valor de A, y solo una minoría de los valores de A se reparte entre varios B.
# Si todos los valores de A se reparten es una jerarquía, no una fusión.
MINIMO_B_CON_UN_SOLO_A = 0.95
MAXIMO_A_AFECTADOS = 0.5
EJEMPLOS_AGRUPACION = 3
VALORES_POR_EJEMPLO = 4

# Un corte solo se sugiere si en lo que dejaría fuera faltan al menos esta
# proporción de días y si conserva al menos esta proporción de filas.
MINIMO_DIAS_FALTANTES_CORTE = 0.5
MINIMO_FILAS_CONSERVADAS = 0.5

# Criterio de prioridad: qué análisis pasan al informe.
MINIMO_MISMO_MES = 0.95  # dos fechas son gemelas si coinciden en el mes en esta proporción
MINIMO_PAREJA_UNICA = 0.90  # dos agrupaciones son casi 1:1 con esta proporción en cada lado
MINIMO_VALOR_DOMINANTE = 0.95  # una medida es casi constante con un valor en esta proporción
MINIMO_ETA2 = 0.01
MAXIMO_RANKINGS_POR_MEDIDA = 3
MAXIMO_RANKINGS = 8
MAXIMO_EVOLUCIONES = 5
MAXIMO_FRECUENCIAS = 8

CARPETA_TABLAS = "tablas"

LIMITES_DEL_AGENTE = [
    "\"Más informativo\" es un criterio estadístico, no importancia para el negocio. Un "
    "análisis omitido puede ser justo el que interesa: `--todo` los genera todos.",
    "No sé qué significa cada columna. Por eso cada tabla trae `filas`, `suma` y "
    "`media`: cuál es la correcta depende de si la variable es un conteo o una medida.",
    "No sé cómo se generaron los datos. Las cifras describen lo que hay en el archivo, "
    "no necesariamente lo que ocurrió en la realidad.",
    "No explico por qué cambia una cifra ni por qué dos variables se mueven juntas.",
    "Un hueco de calendario solo dice que no hay filas en esas fechas. Puede ser normal "
    "si el dato es semanal, mensual o no se registra en ciertos días.",
    "No detecto fechas con el día y el mes intercambiados cuando ambas lecturas son válidas.",
    "Un mismo texto puede referirse a cosas distintas (dos municipios con el mismo "
    "nombre, por ejemplo). Solo lo detecto si otra columna lo revela, y el aviso puede "
    "ser falso cuando la relación es una jerarquía legítima.",
    "No decido qué tramo de datos es válido. Si sugiero un filtro, es una propuesta: "
    "solo se aplica si el analista corre el comando.",
    "Convierto números con punto de miles y coma decimal ('1.234,5'), pero no uno con "
    "comas que siempre llevan 3 dígitos ('1,234'): puede ser 1234 o 1,234.",
    "La clasificación de columnas es heurística. Se corrige con "
    "`--forzar columna.tipo=valor` o `--forzar columna.rol=valor`.",
]


@dataclass
class ClasificacionColumna:
    columna: str
    tipo: str
    rol: str
    # True si hay más valores únicos de los que caben en el informe. Es
    # independiente del tipo y del rol: solo dice cuánto se puede mostrar.
    mostrar_top_n: bool
    motivo_tipo: str
    motivo_rol: str
    unicos: int
    ratio: float
    # True cuando el tipo sale de una heurística que conviene que el analista
    # confirme (códigos detectados por nombre o por ceros a la izquierda).
    revisar: bool = False
    # Columna de la que este número es atributo, si lo es por la regla automática.
    entidad: str | None = None


@dataclass
class ResultadoAnalisis:
    nombre: str
    # Expresión que produjo el resultado, para que el analista pueda verificarlo.
    calculo: str = ""
    # Nombre de archivo (sin extensión) -> tabla. Todas se guardan completas en CSV.
    tablas: dict[str, pd.DataFrame] = field(default_factory=dict)
    # Tablas que el informe muestra recortadas.
    recortar: set[str] = field(default_factory=set)
    # Tablas que van al CSV, pero de las que el informe solo da el enlace.
    solo_csv: set[str] = field(default_factory=set)
    decisiones: list[str] = field(default_factory=list)
    descripciones: list[str] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)
    # Acciones que el analista podría tomar. El agente nunca las aplica.
    sugerencias: list[str] = field(default_factory=list)
    huecos: dict | None = None
    # Corte propuesto por sugerir_corte(), si lo hay.
    corte: dict | None = None
    # Columna -> avisos que también deben aparecer en sus rankings.
    avisos_por_columna: dict[str, list[str]] = field(default_factory=dict)
    # Nombre de la tabla -> archivo CSV donde quedó guardada.
    archivos: dict[str, str] = field(default_factory=dict)
    # Lo que graficar.py necesita saber de este análisis, y el PNG que generó.
    datos_grafico: dict | None = None
    grafico: str | None = None


@dataclass
class Priorizacion:
    planes: list[tuple]
    elegidos: list[str]
    # Cada omitido: {"analisis", "puntaje", "motivo"}.
    omitidos: list[dict]
    # Columna que se agrupa -> columna que se muestra como su etiqueta.
    etiquetas: dict[str, str]
    # Fecha que no se usa -> fecha gemela que sí se usa.
    gemelas: dict[str, str]
    # Medidas casi constantes: una línea de resumen en vez de análisis completos.
    resumenes: list[ResultadoAnalisis]


@dataclass
class ResultadosAgente:
    archivo: str
    filas: int
    columnas: int
    fecha_ejecucion: str
    perfil: str
    avisos_conversion: list[str]
    chequeos: list[ResultadoAnalisis]
    clasificacion: list[ClasificacionColumna]
    elegidos: list[str]
    descartados: list[str]
    analisis: list[ResultadoAnalisis]
    # Texto del filtro aplicado, y filas del archivo antes de filtrar.
    filtro: str | None = None
    filas_archivo: int | None = None
    omitidos: list[dict] = field(default_factory=list)
    # Comando exacto para generar también los análisis omitidos.
    comando_todo: str | None = None


def _palabras_del_nombre(nombre: str) -> list[str]:
    """Parte un nombre de columna en palabras: 'codDane_2' -> ['cod', 'dane', '2']."""
    con_espacios = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(nombre))
    return [p for p in re.split(r"[^0-9a-záéíóúñ]+", con_espacios.lower()) if p]


def _nombre_de_codigo(nombre: str) -> str | None:
    """Devuelve la palabra que delata un código, o None.

    Compara palabras completas, no subcadenas: 'candidato' contiene 'id' pero
    no es un identificador.
    """
    for palabra in _palabras_del_nombre(nombre):
        if palabra in PALABRAS_CODIGO or palabra.startswith("cod"):
            return palabra
    return None


def _ceros_a_la_izquierda(valores: pd.Series) -> pd.Series:
    """Marca valores como '05001': dígitos que empiezan por cero.

    '0' solo y decimales como '0.5' no cuentan: esos sí son números.
    """
    return valores.str.fullmatch(r"0\d+")


def _proporcion_fechas(valores: pd.Series) -> float:
    """Proporción de una muestra con forma de fecha y que pandas logra interpretar."""
    muestra = valores.head(TAMANO_MUESTRA_FECHAS)
    con_forma = muestra.str.fullmatch(PATRON_FECHA)
    if not con_forma.any():
        return 0.0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        # utc=True para que fechas con zonas horarias mezcladas no den error.
        convertidas = pd.to_datetime(muestra[con_forma], errors="coerce", format="mixed", utc=True)
    return float(convertidas.notna().sum() / len(muestra))


def _decidir_tipo(nombre: str, valores: pd.Series) -> tuple[str, str, bool]:
    """Decide qué ES la columna. Devuelve (tipo, motivo, revisar)."""
    if valores.empty:
        return "texto", "no tiene valores de los cuales deducir un tipo.", False

    proporcion_numeros = pd.to_numeric(valores, errors="coerce").notna().mean()
    es_numerica = proporcion_numeros >= MINIMO_CONVERSION

    # Los ceros solo delatan un código si la columna es de dígitos: una columna
    # de texto con algún '007' suelto sigue siendo texto.
    if es_numerica:
        marcas = _ceros_a_la_izquierda(valores)
        if marcas.any():
            return (
                "codigo",
                f"sus valores son dígitos, pero {_numero_texto(marcas.sum())} empiezan por "
                f"cero (p. ej. '{valores[marcas].iloc[0]}'). Un número no lleva ceros "
                "a la izquierda.",
                True,
            )

    palabra = _nombre_de_codigo(nombre)
    if palabra:
        return "codigo", f"su nombre contiene '{palabra}', que suele indicar un código.", True

    # Número antes que fecha: pandas lee '1200' como el año 1200, y un precio
    # de cuatro cifras terminaría clasificado como fecha.
    if es_numerica:
        return "numero", f"el {proporcion_numeros:.0%} de sus valores son números.", False

    proporcion = _proporcion_fechas(valores)
    if proporcion >= MINIMO_CONVERSION:
        muestra = min(len(valores), TAMANO_MUESTRA_FECHAS)
        return (
            "fecha",
            f"el {proporcion:.0%} de una muestra de {_numero_texto(muestra)} valores se interpretó "
            f"como fecha (p. ej. '{valores.iloc[0]}').",
            False,
        )

    return "texto", "no es número, código ni fecha.", False


def _decidir_rol(tipo: str, valores: pd.Series, unicos: int, ratio: float) -> tuple[str, str]:
    """Decide qué se puede HACER con la columna. Devuelve (rol, motivo)."""
    if valores.empty:
        return "ignorar", "está totalmente vacía."
    if unicos == 1:
        return "ignorar", f"tiene un solo valor ('{valores.iloc[0]}')."

    detalle = f"ratio {_numero_texto(ratio, 6)} ({_numero_texto(unicos)} valores únicos)"
    # Una medida continua y una fecha son casi únicas por naturaleza: el ratio solo
    # sirve para reconocer identificadores entre textos y códigos.
    if tipo == "numero":
        return "medible", f"es un número con {_numero_texto(unicos)} valores distintos."
    if tipo == "fecha":
        return "agrupable", f"es una fecha con {_numero_texto(unicos)} valores distintos."
    umbral = _numero_texto(RATIO_IGNORAR, 1)
    if ratio > RATIO_IGNORAR:
        return "ignorar", f"{detalle}, mayor que {umbral}: casi único por fila, es un identificador."
    nombre_tipo = "código" if tipo == "codigo" else tipo
    return "agrupable", f"es {nombre_tipo}, no se puede sumar, y su {detalle} permite agrupar."


def _validar_forzar(forzar: dict[str, dict[str, str]], columnas: set[str]) -> None:
    desconocidas = set(forzar) - columnas
    if desconocidas:
        raise ValueError(f"Columnas en `forzar` que no existen: {sorted(desconocidas)}")

    for columna, cambios in forzar.items():
        atributos = set(cambios) - {"tipo", "rol"}
        if atributos:
            raise ValueError(f"En `forzar`, '{columna}' solo admite tipo y rol: {sorted(atributos)}")
        if cambios.get("tipo", TIPOS[0]) not in TIPOS:
            raise ValueError(f"Tipo no válido para '{columna}'. Usa uno de {TIPOS}")
        if cambios.get("rol", ROLES[0]) not in ROLES:
            raise ValueError(f"Rol no válido para '{columna}'. Usa uno de {ROLES}")


def _clasificar_una(
    serie: pd.Series,
    filas: int,
    forzado: dict[str, str],
) -> ClasificacionColumna:
    nombre = str(serie.name)
    valores = serie.dropna().astype(str).str.strip()
    valores = valores[valores != ""]
    unicos = int(valores.nunique())
    ratio = unicos / filas if filas else 0.0

    tipo, motivo_tipo, revisar = _decidir_tipo(nombre, valores)
    if "tipo" in forzado:
        motivo_tipo = (
            f"forzado por el analista (la clasificación automática era '{tipo}': {motivo_tipo})"
        )
        tipo = forzado["tipo"]
        revisar = False

    # El rol se calcula con el tipo ya definitivo: forzar el tipo lo puede cambiar.
    rol, motivo_rol = _decidir_rol(tipo, valores, unicos, ratio)
    if "rol" in forzado:
        motivo_rol = (
            f"forzado por el analista (la clasificación automática era '{rol}': {motivo_rol})"
        )
        rol = forzado["rol"]

    # Sumar un código o una fecha nunca tiene sentido, ni aunque se pida.
    if rol == "medible" and tipo != "numero":
        raise ValueError(f"'{nombre}' es de tipo {tipo}: solo un número puede ser medible.")
    if rol == "atributo" and tipo != "numero":
        raise ValueError(f"'{nombre}' es de tipo {tipo}: solo un número puede ser atributo.")

    return ClasificacionColumna(
        columna=nombre,
        tipo=tipo,
        rol=rol,
        mostrar_top_n=unicos > UNICOS_INFORME,
        motivo_tipo=motivo_tipo,
        motivo_rol=motivo_rol,
        unicos=unicos,
        ratio=ratio,
        revisar=revisar,
    )


def _marcar_atributos(
    df: pd.DataFrame,
    clasificacion: list[ClasificacionColumna],
    forzar: dict[str, dict[str, str]],
) -> None:
    """Pasa a rol atributo los números con un solo valor por entidad.

    Las fechas no cuentan como entidad: una tasa de cambio tiene un valor por día,
    pero sí es una medida que evoluciona. Un rol forzado por el analista se respeta.
    """
    filas = len(df)
    entidades = [
        c for c in clasificacion
        if c.rol == "agrupable" and c.tipo != "fecha" and c.unicos >= 2
        and filas / c.unicos >= MINIMO_FILAS_POR_ENTIDAD
    ]
    candidatas = [
        c for c in clasificacion
        if c.tipo == "numero" and c.rol == "medible" and "rol" not in forzar.get(c.columna, {})
    ]
    if not entidades or not candidatas:
        return

    codigos = {c.columna: pd.factorize(df[c.columna])[0] for c in entidades}
    for candidata in candidatas:
        codigos_numero, valores = pd.factorize(_a_numero(df[candidata.columna]))
        for entidad in entidades:
            codigos_entidad = codigos[entidad.columna]
            validas = (codigos_entidad >= 0) & (codigos_numero >= 0)
            pares = np.unique(codigos_entidad[validas].astype(np.int64) * len(valores) + codigos_numero[validas])
            if len(pares) == len(np.unique(pares // len(valores))):
                candidata.rol = "atributo"
                candidata.entidad = entidad.columna
                candidata.motivo_rol = (
                    f"tiene un solo valor por cada valor de `{entidad.columna}` "
                    f"({_numero_texto(filas / entidad.unicos, 1)} filas por valor en promedio): "
                    "describe a la entidad, no la mide."
                )
                break


def clasificar_columnas(
    df: pd.DataFrame,
    forzar: dict[str, dict[str, str]] | None = None,
) -> list[ClasificacionColumna]:
    """Asigna a cada columna un tipo, un rol y explica por qué.

    `df` debe estar leído sin inferir tipos (`cargar(ruta, como_texto=True)`),
    para poder distinguir '05001' de 5001. `forzar` permite al analista corregir
    la clasificación: {"estrato": {"tipo": "numero", "rol": "agrupable"}}. Se puede
    forzar solo uno de los dos; si se fuerza el tipo, el rol se recalcula con él.
    """
    forzar = forzar or {}
    _validar_forzar(forzar, set(map(str, df.columns)))

    filas = len(df)
    clasificacion = [
        _clasificar_una(df[columna], filas, forzar.get(str(columna), {}))
        for columna in df.columns
    ]
    _marcar_atributos(df, clasificacion, forzar)
    return clasificacion


def _a_numero(serie: pd.Series) -> pd.Series:
    """Convierte a número; lo que no se pueda queda nulo."""
    if pd.api.types.is_numeric_dtype(serie):
        return serie
    return pd.to_numeric(serie.str.strip(), errors="coerce")


def _a_fecha(serie: pd.Series) -> tuple[pd.Series, bool]:
    """Convierte a fecha. Devuelve (fechas, ambigua).

    Intenta primero ISO 8601, que es rápido y no admite dudas. Si no alcanza usa
    el modo mixto de pandas, donde '01/02/2024' puede leerse de dos formas:
    `ambigua` lo avisa para que quede en el informe.
    """
    if pd.api.types.is_datetime64_any_dtype(serie):
        return serie, False

    texto = serie.str.strip()
    no_nulos = int(texto.notna().sum())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        iso = pd.to_datetime(texto, errors="coerce", format="ISO8601", utc=True)
        if no_nulos == 0 or iso.notna().sum() / no_nulos >= MINIMO_CONVERSION:
            return iso.dt.tz_localize(None), False
        mixta = pd.to_datetime(texto, errors="coerce", format="mixed", utc=True)
    return mixta.dt.tz_localize(None), True


def _serie_de_grupos(serie: pd.Series) -> pd.Series:
    """Prepara una columna para agrupar: los nulos pasan a ser un grupo más."""
    return serie.astype("string").fillna(ETIQUETA_NULO)


def _numero_texto(valor: float, decimales: int = 2, abreviar_enteros: bool = True) -> str:
    """Formato español: 1.234,56. Un valor entero se escribe sin decimales."""
    if pd.isna(valor):
        return "—"
    if abreviar_enteros and float(valor).is_integer() and decimales == 2:
        return f"{int(valor):,}".replace(",", ".")
    return f"{float(valor):,.{decimales}f}".replace(",", "#").replace(".", ",").replace("#", ".")


def _extremos(tabla: pd.DataFrame, metrica: str) -> tuple[pd.Series, pd.Series] | None:
    """Filas con el máximo y el mínimo de una métrica, o None si no hay valores."""
    validas = tabla.dropna(subset=[metrica])
    if validas.empty:
        return None
    return validas.loc[validas[metrica].idxmax()], validas.loc[validas[metrica].idxmin()]


def huecos_calendario(fechas: pd.Series) -> dict:
    """Busca días y meses sin datos entre la primera y la última fecha."""
    dias = pd.Series(fechas.dropna().dt.normalize().unique()).sort_values().reset_index(drop=True)
    vacio = pd.DataFrame(columns=["desde", "hasta", "dias"])
    if len(dias) < 2:
        return {"rango_dias": len(dias), "dias_faltantes": 0, "tramos": vacio, "meses_faltantes": []}

    saltos = dias.diff().dt.days
    hay_hueco = saltos > 1
    tramos = pd.DataFrame({
        "desde": (dias.shift(1)[hay_hueco] + pd.Timedelta(days=1)).dt.strftime("%Y-%m-%d"),
        "hasta": (dias[hay_hueco] - pd.Timedelta(days=1)).dt.strftime("%Y-%m-%d"),
        "dias": (saltos[hay_hueco] - 1).astype(int),
    }).reset_index(drop=True)

    meses_con_datos = set(dias.dt.to_period("M"))
    calendario = pd.period_range(dias.iloc[0], dias.iloc[-1], freq="M")
    return {
        "rango_dias": (dias.iloc[-1] - dias.iloc[0]).days + 1,
        "dias_faltantes": int(tramos["dias"].sum()),
        "tramos": tramos,
        "meses_faltantes": [str(mes) for mes in calendario if mes not in meses_con_datos],
    }


def _texto_huecos(col_fecha: str, huecos: dict) -> list[str]:
    avisos = []
    if huecos["dias_faltantes"]:
        avisos.append(
            f"`{col_fecha}`: faltan {_numero_texto(huecos['dias_faltantes'])} de "
            f"{_numero_texto(huecos['rango_dias'])} días entre la primera y la última "
            f"fecha, repartidos en {_numero_texto(len(huecos['tramos']))} tramos."
        )
    if huecos["meses_faltantes"]:
        avisos.append(
            f"`{col_fecha}`: {len(huecos['meses_faltantes'])} meses completos sin datos: "
            f"{', '.join(huecos['meses_faltantes'])}."
        )
    return avisos


def sugerir_corte(fechas: pd.Series, huecos: dict, hoy: pd.Timestamp) -> dict | None:
    """Propone un corte que deje fuera el tramo sospechoso, sin aplicarlo.

    Corta en el borde de un mes para no conservar un mes a medias: si el primer
    hueco empieza el 2026-01-03, propone llegar hasta 2025-12-31. Si los huecos
    están repartidos o el corte perdería la mayoría de las filas, devuelve None.
    """
    validas = fechas.dropna().dt.normalize()
    if validas.empty:
        return None
    total = len(validas)
    corte: dict = {"desde": None, "hasta": None, "motivos": []}
    tramos = huecos["tramos"]

    if not tramos.empty:
        faltantes = huecos["dias_faltantes"]
        primero = pd.Timestamp(tramos["desde"].iloc[0])
        ultimo = pd.Timestamp(tramos["hasta"].iloc[-1])
        hasta = primero.to_period("M").start_time - pd.Timedelta(days=1)
        desde = (ultimo.to_period("M") + 1).start_time
        dias_tras_hasta = (validas.max() - hasta).days
        dias_antes_desde = (desde - validas.min()).days

        if (
            (validas <= hasta).sum() / total >= MINIMO_FILAS_CONSERVADAS
            and faltantes / dias_tras_hasta >= MINIMO_DIAS_FALTANTES_CORTE
        ):
            corte["hasta"] = hasta
            corte["motivos"].append(
                f"todos los huecos están después de {hasta.date()}, el último mes completo "
                "antes del primero"
            )
        elif (
            (validas >= desde).sum() / total >= MINIMO_FILAS_CONSERVADAS
            and faltantes / dias_antes_desde >= MINIMO_DIAS_FALTANTES_CORTE
        ):
            corte["desde"] = desde
            corte["motivos"].append(
                f"todos los huecos están antes de {desde.date()}, el primer mes completo "
                "después del último"
            )

    if validas.max() > hoy and (corte["hasta"] is None or corte["hasta"] > hoy):
        corte["hasta"] = hoy
        corte["motivos"].append("hay fechas posteriores al día de ejecución")

    if corte["desde"] is None and corte["hasta"] is None:
        return None

    conservadas = pd.Series(True, index=validas.index)
    if corte["desde"] is not None:
        conservadas &= validas >= corte["desde"]
    if corte["hasta"] is not None:
        conservadas &= validas <= corte["hasta"]
    corte["filas_excluidas"] = int((~conservadas).sum())
    corte["total"] = total
    return corte


def revisar_fechas(
    df: pd.DataFrame,
    col_fecha: str,
    hoy: pd.Timestamp | None = None,
    gemela_de: str | None = None,
) -> ResultadoAnalisis:
    """Chequeos de calidad de una columna de fecha: futuras y huecos de calendario.

    Con `gemela_de` no busca huecos: repetirían los de la fecha gemela.
    """
    resultado = ResultadoAnalisis(nombre=f"Fechas de `{col_fecha}`")
    fechas, _ = _a_fecha(df[col_fecha])
    hoy = (hoy if hoy is not None else pd.Timestamp.now()).normalize()
    if gemela_de:
        resultado.decisiones.append(
            f"Comparé las fechas con el día de ejecución ({hoy.date()}). No busqué huecos: "
            f"es gemela de `{gemela_de}` y darían el mismo aviso."
        )
    else:
        resultado.decisiones.append(
            f"Comparé las fechas con el día de ejecución ({hoy.date()}) y busqué días y meses "
            "sin filas entre la primera y la última fecha."
        )

    validas = fechas.dropna()
    if validas.empty:
        resultado.advertencias.append(f"`{col_fecha}` no tiene ninguna fecha válida.")
        return resultado

    resultado.descripciones.append(
        f"Rango de `{col_fecha}`: {validas.min().date()} a {validas.max().date()}."
    )

    futuras = validas[validas > hoy]
    if futuras.empty:
        resultado.descripciones.append("Ninguna fecha es posterior al día de ejecución.")
    else:
        resultado.advertencias.append(
            f"`{col_fecha}`: {_numero_texto(len(futuras))} filas tienen fecha posterior al "
            f"día de ejecución, hasta {futuras.max().date()}."
        )

    if gemela_de:
        sin_huecos = {"tramos": pd.DataFrame(columns=["desde", "hasta", "dias"]), "dias_faltantes": 0}
        resultado.corte = sugerir_corte(fechas, sin_huecos, hoy)
        return resultado

    huecos = huecos_calendario(fechas)
    resultado.huecos = huecos
    avisos = _texto_huecos(col_fecha, huecos)
    if avisos:
        resultado.advertencias += avisos
    else:
        resultado.descripciones.append("No faltan días entre la primera y la última fecha.")
    if not huecos["tramos"].empty:
        tabla = f"huecos_{col_fecha}"
        resultado.tablas[tabla] = huecos["tramos"]
        resultado.recortar.add(tabla)
    resultado.corte = sugerir_corte(fechas, huecos, hoy)
    return resultado


def _interpretar_fecha_filtro(texto: str | None) -> pd.Timestamp | None:
    if texto is None:
        return None
    try:
        return pd.Timestamp(datetime.strptime(texto, "%Y-%m-%d"))
    except ValueError:
        raise ValueError(f"Fecha de filtro no válida: '{texto}'. Usa el formato AAAA-MM-DD.") from None


def _columna_de_filtro(
    clasificacion: list[ClasificacionColumna],
    columna_fecha: str | None,
) -> str:
    """Elige la columna por la que se filtra. Si hay duda, pregunta en vez de adivinar."""
    fechas = [c.columna for c in clasificacion if c.tipo == "fecha"]
    if not fechas:
        raise ValueError("--desde y --hasta necesitan una columna de tipo fecha, y este archivo no tiene.")
    if columna_fecha is not None:
        if columna_fecha not in fechas:
            raise ValueError(f"'{columna_fecha}' no es una columna de tipo fecha. Las hay: {fechas}")
        return columna_fecha
    if len(fechas) > 1:
        raise ValueError(f"Hay varias columnas de fecha: {fechas}. Indica una con --columna-fecha.")
    return fechas[0]


def filtrar_por_fecha(
    df: pd.DataFrame,
    col_fecha: str,
    desde: pd.Timestamp | None = None,
    hasta: pd.Timestamp | None = None,
) -> tuple[pd.DataFrame, str]:
    """Deja las filas dentro del rango, ambos extremos incluidos. Devuelve (df, descripción)."""
    fechas, _ = _a_fecha(df[col_fecha])
    dias = fechas.dt.normalize()
    conservar = dias.notna()
    if desde is not None:
        conservar &= dias >= desde
    if hasta is not None:
        conservar &= dias <= hasta

    limites = []
    if desde is not None:
        limites.append(f"desde {desde.date()}")
    if hasta is not None:
        limites.append(f"hasta {hasta.date()}")
    sin_fecha = int(dias.isna().sum())
    fuera = len(df) - int(conservar.sum()) - sin_fecha
    descripcion = (
        f"`{col_fecha}` {' '.join(limites)}, ambos extremos incluidos. Excluye "
        f"{_numero_texto(fuera)} filas fuera del rango"
    )
    if sin_fecha:
        descripcion += f" y {_numero_texto(sin_fecha)} filas sin fecha válida"
    return df[conservar], descripcion + "."


def _citar(valor: object) -> str:
    texto = str(valor)
    return f'"{texto}"' if " " in texto else texto


def _comando(
    ruta_csv: str | Path,
    carpeta_salida: str | Path,
    forzar: dict[str, dict[str, str]] | None,
    columna_fecha: str | None,
    desde: pd.Timestamp | None,
    hasta: pd.Timestamp | None,
    unidades: dict[str, str] | None = None,
    todo: bool = False,
) -> str:
    """Arma el comando exacto para repetir esta corrida con otro filtro."""
    partes = ["python src/agente.py", _citar(ruta_csv)]
    if desde is not None:
        partes.append(f"--desde {desde.date()}")
    if hasta is not None:
        partes.append(f"--hasta {hasta.date()}")
    if columna_fecha is not None:
        partes.append(f"--columna-fecha {_citar(columna_fecha)}")
    if str(carpeta_salida) != "reports":
        partes.append(f"--salida {_citar(carpeta_salida)}")
    for columna, cambios in (forzar or {}).items():
        partes += [f"--forzar {_citar(f'{columna}.{a}={v}')}" for a, v in cambios.items()]
    partes += [f"--unidad {_citar(f'{c}={u}')}" for c, u in (unidades or {}).items()]
    if todo:
        partes.append("--todo")
    return " ".join(partes)


def analizar_tiempo(df: pd.DataFrame, col_fecha: str, col_numerica: str) -> ResultadoAnalisis:
    """Evolución de una medida por mes y por año, con chequeo de huecos."""
    resultado = ResultadoAnalisis(
        nombre=f"Evolución de `{col_numerica}` por `{col_fecha}`",
        calculo=(
            "df.groupby(periodo)[medida].agg(filas='size', suma='sum', media='mean'), "
            "con periodo = mes y año de la fecha"
        ),
    )
    fechas, _ = _a_fecha(df[col_fecha])
    trabajo = pd.DataFrame({"fecha": fechas, "valor": _a_numero(df[col_numerica])})

    sin_fecha = int(trabajo["fecha"].isna().sum())
    trabajo = trabajo.dropna(subset=["fecha"])
    resultado.decisiones.append("Agregué por mes y por año.")
    if sin_fecha:
        resultado.decisiones.append(
            f"Excluí {_numero_texto(sin_fecha)} filas sin fecha válida, porque no se pueden "
            "ubicar en un periodo."
        )
    resultado.decisiones.append(
        "Agregué la columna `dias_con_datos` para distinguir un periodo con poco valor de un "
        "periodo con pocos días registrados."
    )
    if trabajo.empty:
        resultado.advertencias.append(f"`{col_fecha}` no tiene ninguna fecha válida.")
        return resultado

    trabajo["dia"] = trabajo["fecha"].dt.normalize()

    def agregar(periodos: pd.Series) -> pd.DataFrame:
        grupos = trabajo.groupby(periodos, sort=True)
        tabla = pd.DataFrame({
            "filas": grupos["valor"].size(),
            "suma": grupos["valor"].sum(min_count=1),
            "media": grupos["valor"].mean(),
            "dias_con_datos": grupos["dia"].nunique(),
        })
        tabla.index = tabla.index.astype(str)
        return tabla.rename_axis("periodo").reset_index()

    por_mes = agregar(trabajo["fecha"].dt.to_period("M"))
    por_anio = agregar(trabajo["fecha"].dt.year)
    resultado.tablas[f"evolucion_{col_fecha}_{col_numerica}_anio"] = por_anio
    resultado.tablas[f"evolucion_{col_fecha}_{col_numerica}_mes"] = por_mes
    # El informe muestra la tabla anual; el detalle mensual queda en CSV y en el gráfico.
    resultado.solo_csv.add(f"evolucion_{col_fecha}_{col_numerica}_mes")
    resultado.datos_grafico = {
        "tipo": "tiempo",
        "tabla": f"evolucion_{col_fecha}_{col_numerica}_mes",
        "fecha": col_fecha,
        "medida": col_numerica,
        "columnas": [col_numerica],
    }

    for etiqueta, tabla in (("año", por_anio), ("mes", por_mes)):
        extremos = _extremos(tabla, "suma")
        if extremos is None:
            continue
        maximo, minimo = extremos
        resultado.descripciones.append(
            f"Por {etiqueta}, el máximo de la suma de `{col_numerica}` es "
            f"{_numero_texto(maximo['suma'])} en {maximo['periodo']} "
            f"({_numero_texto(maximo['dias_con_datos'])} días con datos) y el mínimo es "
            f"{_numero_texto(minimo['suma'])} en {minimo['periodo']} "
            f"({_numero_texto(minimo['dias_con_datos'])} días con datos)."
        )

    resultado.huecos = huecos_calendario(trabajo["fecha"])
    resultado.advertencias += _texto_huecos(col_fecha, resultado.huecos)
    return resultado


def _comparar_tops(tabla: pd.DataFrame) -> str | None:
    """Compara el ranking por filas con el ranking por suma; `tabla` ya va por suma."""
    posiciones = min(TOP_COMPARACION, max(1, len(tabla) // 2))
    por_filas = tabla.sort_values(["filas", "grupo"], ascending=[False, True])
    top_suma = tabla["grupo"].head(posiciones).tolist()
    top_filas = por_filas["grupo"].head(posiciones).tolist()
    if set(top_suma) == set(top_filas) and top_suma[0] == top_filas[0]:
        return None

    partes = [f"El top {posiciones} por filas y el top {posiciones} por suma son distintos."]
    if top_suma[0] != top_filas[0]:
        partes.append(f"El primero por filas es '{top_filas[0]}'; por suma, '{top_suma[0]}'.")
    solo_filas = [g for g in top_filas if g not in top_suma]
    solo_suma = [g for g in top_suma if g not in top_filas]
    if solo_filas:
        partes.append(f"Solo en el top por filas: {', '.join(solo_filas)}.")
    if solo_suma:
        partes.append(f"Solo en el top por suma: {', '.join(solo_suma)}.")
    partes.append("Contar filas y sumar la medida no dan el mismo orden.")
    return " ".join(partes)


def ranking_por_categoria(
    df: pd.DataFrame,
    col_categoria: str,
    col_numerica: str,
    mostrar_top_n: bool = False,
    col_etiqueta: str | None = None,
) -> ResultadoAnalisis:
    """Filas, suma y media por categoría, ordenadas por suma.

    `col_etiqueta` agrega una columna legible al lado del grupo: su valor más
    frecuente en cada grupo. Sirve para mostrar un nombre junto a un código.
    """
    nombre_tabla = f"ranking_{col_categoria}_{col_numerica}"
    titulo_grupo = f"`{col_categoria}` (con `{col_etiqueta}`)" if col_etiqueta else f"`{col_categoria}`"
    resultado = ResultadoAnalisis(
        nombre=f"Ranking de {titulo_grupo} por `{col_numerica}`",
        calculo="df.groupby(grupo)[medida].agg(filas='size', suma='sum', media='mean')",
        datos_grafico={
            "tipo": "ranking",
            "tabla": nombre_tabla,
            "grupo": col_categoria,
            "medida": col_numerica,
            "columnas": [col_numerica],
        },
    )
    grupos = _serie_de_grupos(df[col_categoria]).rename("grupo")
    numeros = _a_numero(df[col_numerica])
    agrupado = numeros.groupby(grupos, sort=False)

    tabla = pd.DataFrame({
        "filas": agrupado.size(),
        "suma": agrupado.sum(min_count=1),
        "media": agrupado.mean(),
    }).reset_index()
    tabla["grupo"] = tabla["grupo"].astype(str)
    tabla["puesto_suma"] = tabla["suma"].rank(method="min", ascending=False).astype("Int64")
    tabla["puesto_filas"] = tabla["filas"].rank(method="min", ascending=False).astype("Int64")
    tabla = tabla.sort_values(["suma", "grupo"], ascending=[False, True], na_position="last")
    tabla = tabla.reset_index(drop=True)

    if col_etiqueta:
        pares = pd.DataFrame({"grupo": grupos.astype(str), "etiqueta": df[col_etiqueta]}).dropna()
        mas_frecuente = (
            pares.value_counts().reset_index().drop_duplicates("grupo").set_index("grupo")["etiqueta"]
        )
        tabla.insert(1, "etiqueta", tabla["grupo"].map(mas_frecuente))

    resultado.tablas[nombre_tabla] = tabla

    def nombre_grupo(fila: pd.Series) -> str:
        if col_etiqueta and pd.notna(fila["etiqueta"]):
            return f"'{fila['grupo']}' ({fila['etiqueta']})"
        return f"'{fila['grupo']}'"

    resultado.decisiones.append(
        f"Ordené por suma, de mayor a menor. Los nulos del grupo forman '{ETIQUETA_NULO}' "
        "para que los totales cuadren."
    )
    if col_etiqueta:
        resultado.decisiones.append(
            f"`{col_categoria}` y `{col_etiqueta}` son casi equivalentes: una sola tabla, agrupada "
            f"por `{col_categoria}` y con el valor más frecuente de `{col_etiqueta}` como etiqueta."
        )
    nulos_medida = int(numeros.isna().sum())
    if nulos_medida:
        resultado.decisiones.append(
            f"{_numero_texto(nulos_medida)} filas sin valor en `{col_numerica}` cuentan en "
            "`filas`, pero no en `suma` ni en `media`."
        )
    if mostrar_top_n:
        resultado.recortar.add(nombre_tabla)
        resultado.decisiones.append(
            f"`{col_categoria}` tiene {_numero_texto(len(tabla))} valores: el informe muestra "
            f"los primeros {FILAS_INICIO_INFORME} y los últimos {FILAS_FIN_INFORME}; el CSV "
            "los trae todos."
        )

    if tabla.empty:
        return resultado

    extremos = _extremos(tabla, "suma")
    if extremos:
        maximo, minimo = extremos
        resultado.descripciones.append(
            f"El máximo de la suma es {_numero_texto(maximo['suma'])} en {nombre_grupo(maximo)}; "
            f"el mínimo es {_numero_texto(minimo['suma'])} en {nombre_grupo(minimo)}."
        )
        media_maxima, _ = _extremos(tabla, "media")
        resultado.descripciones.append(
            f"La media más alta es {_numero_texto(media_maxima['media'])} en {nombre_grupo(media_maxima)}."
        )
    mas_filas = tabla.loc[tabla["filas"].idxmax()]
    resultado.descripciones.append(
        f"El grupo con más filas es {nombre_grupo(mas_filas)}, con {_numero_texto(mas_filas['filas'])}."
    )

    aviso = _comparar_tops(tabla)
    if aviso:
        resultado.advertencias.append(aviso)
    return resultado


def matriz_correlacion(df: pd.DataFrame, columnas_numericas: list[str]) -> ResultadoAnalisis:
    """Correlación de Pearson entre columnas numéricas."""
    resultado = ResultadoAnalisis(
        nombre="Matriz de correlación",
        calculo=f"df[{columnas_numericas}].corr(method='pearson')",
    )
    if len(columnas_numericas) < 2:
        resultado.decisiones.append(
            f"No calculé correlación: hacen falta 2 columnas numéricas y hay {len(columnas_numericas)}."
        )
        return resultado

    datos = pd.DataFrame({columna: _a_numero(df[columna]) for columna in columnas_numericas})
    matriz = datos.corr(method="pearson")
    resultado.tablas["correlacion"] = matriz.round(4).rename_axis("r de Pearson").reset_index()
    resultado.datos_grafico = {
        "tipo": "correlacion",
        "tabla": "correlacion",
        "columnas": list(columnas_numericas),
    }
    resultado.decisiones.append(
        "Usé Pearson, que mide relación lineal. Cada par usa las filas donde ambas columnas "
        f"tienen valor. Listo por separado los pares con |r| de {UMBRAL_CORRELACION} o más."
    )

    destacados = 0
    for i, primera in enumerate(columnas_numericas):
        for segunda in columnas_numericas[i + 1:]:
            r = matriz.loc[primera, segunda]
            if pd.notna(r) and abs(r) >= UMBRAL_CORRELACION:
                destacados += 1
                n = int((datos[primera].notna() & datos[segunda].notna()).sum())
                resultado.descripciones.append(
                    f"`{primera}` y `{segunda}` se mueven juntas: r = {_numero_texto(r, 3)} "
                    f"(n = {_numero_texto(n)})."
                )
    if not destacados:
        resultado.descripciones.append(f"Ningún par alcanza |r| de {UMBRAL_CORRELACION}.")

    resultado.advertencias.append(
        "La correlación no implica causalidad: dos variables pueden moverse juntas sin que "
        "una provoque la otra."
    )
    return resultado


def frecuencias(
    df: pd.DataFrame,
    col_categoria: str,
    mostrar_top_n: bool = False,
) -> ResultadoAnalisis:
    """Conteo por valor, para cuando no hay ninguna columna medible."""
    nombre_tabla = f"frecuencias_{col_categoria}"
    resultado = ResultadoAnalisis(
        nombre=f"Frecuencias de `{col_categoria}`",
        calculo=f"df['{col_categoria}'].value_counts(dropna=False)",
        datos_grafico={
            "tipo": "frecuencias",
            "tabla": nombre_tabla,
            "grupo": col_categoria,
            "columnas": [],
        },
    )
    conteo = _serie_de_grupos(df[col_categoria]).value_counts()
    tabla = conteo.rename("conteo").rename_axis("valor").reset_index()
    tabla["valor"] = tabla["valor"].astype(str)
    tabla = tabla.sort_values(["conteo", "valor"], ascending=[False, True]).reset_index(drop=True)
    total = tabla["conteo"].sum()
    tabla["porcentaje"] = (tabla["conteo"] / total * 100).round(2) if total else 0.0
    resultado.tablas[nombre_tabla] = tabla

    resultado.decisiones.append(
        f"Conté filas por valor, de mayor a menor. Los nulos forman el grupo '{ETIQUETA_NULO}' "
        "y cuentan en el porcentaje."
    )
    if mostrar_top_n:
        resultado.recortar.add(nombre_tabla)
        resultado.decisiones.append(
            f"`{col_categoria}` tiene {_numero_texto(len(tabla))} valores: el informe muestra "
            f"los primeros {FILAS_INICIO_INFORME} y los últimos {FILAS_FIN_INFORME}; el CSV "
            "los trae todos."
        )

    if not tabla.empty:
        primero, ultimo = tabla.iloc[0], tabla.iloc[-1]
        resultado.descripciones.append(
            f"El valor más frecuente es '{primero['valor']}', con {_numero_texto(primero['conteo'])} "
            f"filas; el menos frecuente es '{ultimo['valor']}', con {_numero_texto(ultimo['conteo'])}."
        )
    return resultado


def detectar_agrupaciones(df: pd.DataFrame, columnas: list[str]) -> ResultadoAnalisis:
    """Busca columnas A que pueden estar fusionando entidades que otra columna B separa.

    Trabaja con todas las filas, sin muestra: una muestra perdería justo las
    combinaciones raras que revelan la fusión. Convierte cada columna a enteros
    una sola vez, y cada par se resuelve con un np.unique sobre esos enteros.
    """
    resultado = ResultadoAnalisis(
        nombre="Agrupaciones",
        calculo="np.unique(codigos_A * unicos_B + codigos_B), para cada par con unicos(B) > unicos(A)",
    )
    if len(columnas) < 2:
        resultado.decisiones.append(
            f"No comparé agrupaciones: hacen falta 2 columnas agrupables y hay {len(columnas)}."
        )
        return resultado

    codigos = {c: pd.factorize(df[c]) for c in columnas}
    filas_pares = []
    disparan_regla_base = 0
    omitidos = 0

    for posicion, primera in enumerate(columnas):
        for segunda in columnas[posicion + 1:]:
            if len(codigos[primera][1]) == len(codigos[segunda][1]):
                omitidos += 1
                continue
            a, b = sorted((primera, segunda), key=lambda c: len(codigos[c][1]))
            codigos_a, valores_a = codigos[a]
            codigos_b, valores_b = codigos[b]
            unicos_b = len(valores_b)

            # Los nulos valen -1: una fila sin valor no prueba ninguna relación.
            validas = (codigos_a >= 0) & (codigos_b >= 0)
            pares = np.unique(codigos_a[validas].astype(np.int64) * unicos_b + codigos_b[validas])
            indice_a, indice_b = pares // unicos_b, pares % unicos_b
            b_por_a = np.bincount(indice_a, minlength=len(valores_a))
            a_por_b = np.bincount(indice_b, minlength=unicos_b)

            presentes_a = int((b_por_a > 0).sum())
            afectados = int((b_por_a > 1).sum())
            if not afectados:
                continue
            disparan_regla_base += 1
            proporcion_afectados = afectados / presentes_a
            proporcion_un_solo_a = float((a_por_b == 1).sum() / (a_por_b > 0).sum())
            avisa = (
                proporcion_un_solo_a >= MINIMO_B_CON_UN_SOLO_A
                and proporcion_afectados < MAXIMO_A_AFECTADOS
            )
            filas_pares.append({
                "A": a,
                "B": b,
                "valores_A": presentes_a,
                "valores_B": int((a_por_b > 0).sum()),
                "A_afectados": afectados,
                "pct_A_afectados": round(proporcion_afectados * 100, 1),
                "pct_B_con_un_solo_A": round(proporcion_un_solo_a * 100, 1),
                "avisa": avisa,
            })
            if not avisa:
                continue

            en_a_afectado = b_por_a[indice_a] > 1
            detalle = pd.DataFrame({
                "valor": np.asarray(valores_a, dtype=object)[indice_a[en_a_afectado]],
                "b": np.asarray(valores_b, dtype=object)[indice_b[en_a_afectado]].astype(str),
            }).groupby("valor")["b"].agg(cantidad="size", valores=lambda v: ", ".join(sorted(v)))
            detalle = detalle.reset_index().sort_values(
                ["cantidad", "valor"], ascending=[False, True]
            ).reset_index(drop=True)

            nombre_tabla = f"agrupaciones_{a}_{b}"
            resultado.tablas[nombre_tabla] = detalle
            resultado.solo_csv.add(nombre_tabla)

            def ejemplo(fila) -> str:
                valores = fila.valores.split(", ")
                texto = ", ".join(valores[:VALORES_POR_EJEMPLO])
                if len(valores) > VALORES_POR_EJEMPLO:
                    texto += f" y {len(valores) - VALORES_POR_EJEMPLO} más"
                return f"'{fila.valor}' ({fila.cantidad} valores: {texto})"

            ejemplos = "; ".join(ejemplo(f) for f in detalle.head(EJEMPLOS_AGRUPACION).itertuples())
            aviso = (
                f"Agrupar por `{a}` puede estar mezclando entidades distintas: "
                f"{_numero_texto(afectados)} de {_numero_texto(presentes_a)} valores aparecen "
                f"junto a más de un valor de `{b}`. Ejemplos: {ejemplos}. "
                f"Sugerencia: agrupar por `{b}`."
            )
            resultado.advertencias.append(aviso)
            resultado.avisos_por_columna.setdefault(a, []).append(aviso)

    if filas_pares:
        resultado.tablas["agrupaciones_pares"] = pd.DataFrame(filas_pares)
        resultado.solo_csv.add("agrupaciones_pares")

    comparados = len(columnas) * (len(columnas) - 1) // 2 - omitidos
    resultado.decisiones += [
        f"Comparé {comparados} pares entre {len(columnas)} columnas agrupables, usando todas "
        "las filas y sin muestra. Las fechas no entran: casi cualquier valor aparece en varias.",
        f"En {disparan_regla_base} pares algún valor de A aparece junto a más de un valor de B. "
        f"Eso solo no indica una fusión, así que aviso únicamente si al menos el "
        f"{MINIMO_B_CON_UN_SOLO_A:.0%} de los valores de B corresponde a un solo A y menos del "
        f"{MAXIMO_A_AFECTADOS:.0%} de los valores de A está afectado. Si todos los valores de A "
        "se reparten, es una jerarquía o dos columnas independientes.",
    ]
    if omitidos:
        resultado.decisiones.append(f"Omití {omitidos} pares con el mismo número de valores únicos.")
    if not resultado.advertencias:
        resultado.descripciones.append("Ningún par cumple las condiciones para avisar.")
    return resultado


def elegir_analisis(
    clasificacion: list[ClasificacionColumna],
) -> tuple[list[tuple], list[str], list[str]]:
    """Decide qué análisis corren. Devuelve (planes, elegidos, descartados)."""
    medibles = [c for c in clasificacion if c.rol == "medible"]
    fechas = [c for c in clasificacion if c.tipo == "fecha" and c.rol == "agrupable"]
    grupos = [c for c in clasificacion if c.rol == "agrupable" and c.tipo != "fecha"]
    fechas_ignoradas = [c.columna for c in clasificacion if c.tipo == "fecha" and c.rol == "ignorar"]

    planes: list[tuple] = []
    elegidos: list[str] = []
    descartados: list[str] = []

    if fechas and medibles:
        for fecha in fechas:
            for medible in medibles:
                planes.append(("tiempo", fecha, medible))
                elegidos.append(
                    f"Evolución de `{medible.columna}` por `{fecha.columna}`: elegí esto porque "
                    f"`{fecha.columna}` es una fecha agrupable y `{medible.columna}` es medible."
                )
    else:
        falta = "no hay columna medible" if fechas else "no hay columna de fecha agrupable"
        if not fechas and fechas_ignoradas:
            falta += f" (`{'`, `'.join(fechas_ignoradas)}` quedó con rol ignorar)"
        descartados.append(f"Evolución en el tiempo: {falta}.")

    if grupos and medibles:
        for grupo in grupos:
            for medible in medibles:
                planes.append(("ranking", grupo, medible))
                elegidos.append(
                    f"Ranking de `{grupo.columna}` por `{medible.columna}`: elegí esto porque "
                    f"`{grupo.columna}` es agrupable (tipo {grupo.tipo}) y `{medible.columna}` es medible."
                )
    else:
        falta = "no hay columna medible" if grupos else "no hay columna agrupable"
        descartados.append(f"Ranking por categoría: {falta}.")

    if len(medibles) >= 2:
        planes.append(("correlacion", medibles))
        nombres = "`, `".join(c.columna for c in medibles)
        elegidos.append(f"Matriz de correlación: elegí esto porque hay {len(medibles)} medibles (`{nombres}`).")
    else:
        descartados.append(f"Matriz de correlación: hacen falta 2 columnas medibles y hay {len(medibles)}.")

    if medibles:
        descartados.append("Frecuencias: solo se usan cuando no hay ninguna columna medible, y aquí sí hay.")
    elif grupos:
        for grupo in grupos:
            planes.append(("frecuencias", grupo))
            elegidos.append(
                f"Frecuencias de `{grupo.columna}`: elegí esto porque no hay ninguna columna "
                f"medible y `{grupo.columna}` es agrupable."
            )
    else:
        descartados.append("Frecuencias: no hay ninguna columna agrupable.")

    for columna in clasificacion:
        if columna.rol in ("ignorar", "atributo"):
            descartados.append(f"`{columna.columna}` queda fuera de todos los análisis: {columna.motivo_rol}")
    return planes, elegidos, descartados


def fechas_gemelas(df: pd.DataFrame, columnas: list[str]) -> dict[str, str]:
    """Busca fechas que darían casi el mismo análisis. Devuelve {descartada: conservada}.

    Son gemelas si caen en el mismo mes casi siempre y una nunca es anterior a la
    otra, como el inicio y el fin de un periodo. Se conserva la más temprana.
    """
    gemelas: dict[str, str] = {}
    for a, b in itertools.combinations(columnas, 2):
        if a in gemelas or b in gemelas:
            continue
        fecha_a, _ = _a_fecha(df[a])
        fecha_b, _ = _a_fecha(df[b])
        ambas = fecha_a.notna() & fecha_b.notna()
        if not ambas.any():
            continue
        fecha_a, fecha_b = fecha_a[ambas], fecha_b[ambas]
        if (fecha_a.dt.to_period("M") == fecha_b.dt.to_period("M")).mean() < MINIMO_MISMO_MES:
            continue
        if (fecha_b >= fecha_a).all():
            gemelas[b] = a
        elif (fecha_a >= fecha_b).all():
            gemelas[a] = b
    return gemelas


def agrupaciones_equivalentes(
    df: pd.DataFrame,
    clasificacion: list[ClasificacionColumna],
) -> dict[str, str]:
    """Busca agrupaciones casi 1:1. Devuelve {columna que no se agrupa: columna que sí}.

    Se agrupa por la más fina, que no fusiona nada, y la otra queda como etiqueta. Con
    los mismos únicos gana el código, porque el texto es mejor etiqueta.
    """
    columnas = [c for c in clasificacion if c.rol == "agrupable" and c.tipo != "fecha"]
    equivalentes: dict[str, str] = {}
    for a, b in itertools.combinations(columnas, 2):
        if a.columna in equivalentes or b.columna in equivalentes:
            continue
        pares = df[[a.columna, b.columna]].dropna().drop_duplicates()
        if pares.empty:
            continue
        pareja_unica_a = (pares.groupby(a.columna)[b.columna].nunique() == 1).mean()
        pareja_unica_b = (pares.groupby(b.columna)[a.columna].nunique() == 1).mean()
        if min(pareja_unica_a, pareja_unica_b) < MINIMO_PAREJA_UNICA:
            continue
        fina, otra = sorted((a, b), key=lambda c: (c.unicos, c.tipo == "codigo"), reverse=True)
        equivalentes[otra.columna] = fina.columna
    return equivalentes


def _eta2_ajustado(df: pd.DataFrame, grupo: str, medida: str) -> float:
    """Qué parte de la variación de la medida explican los grupos, de 0 a 1.

    El ajuste penaliza tener muchos grupos. Los nulos del grupo forman uno más, como
    en el ranking; las filas sin valor en la medida no cuentan.
    """
    numeros = _a_numero(df[medida]).to_numpy(dtype=float)
    # factorize devuelve -1 para los nulos: al sumar 1 quedan como el grupo 0.
    codigos = pd.factorize(df[grupo])[0] + 1
    validas = ~np.isnan(numeros)
    numeros, codigos = numeros[validas], codigos[validas]
    n = len(numeros)
    if n == 0:
        return 0.0

    tamanos = np.bincount(codigos)
    sumas = np.bincount(codigos, weights=numeros)
    con_filas = tamanos > 0
    grupos = int(con_filas.sum())
    media = numeros.mean()
    entre_grupos = float((sumas[con_filas] ** 2 / tamanos[con_filas]).sum() - n * media**2)
    total = float(((numeros - media) ** 2).sum())
    if total <= 0 or n <= grupos:
        return 0.0
    return 1 - (1 - entre_grupos / total) * (n - 1) / (n - grupos)


def _variacion_mensual(df: pd.DataFrame, col_fecha: str, medida: str) -> float:
    """Coeficiente de variación de la suma mensual: ordena evoluciones si sobran."""
    fechas, _ = _a_fecha(df[col_fecha])
    sumas = _a_numero(df[medida]).groupby(fechas.dt.to_period("M")).sum()
    media = sumas.mean()
    return float(sumas.std() / abs(media)) if len(sumas) > 1 and media else 0.0


def priorizar_analisis(
    df: pd.DataFrame,
    clasificacion: list[ClasificacionColumna],
    planes: list[tuple],
    elegidos: list[str],
    todo: bool = False,
) -> Priorizacion:
    """Decide qué análisis pasan al informe. Omitir uno nunca excluye datos.

    Primero quita lo redundante: fechas gemelas, agrupaciones casi 1:1 y medidas casi
    constantes. Después ordena los rankings por η² ajustado y aplica los topes.
    """
    if todo:
        return Priorizacion(planes, elegidos, [], {}, {}, [])

    fechas = [c.columna for c in clasificacion if c.tipo == "fecha" and c.rol == "agrupable"]
    gemelas = fechas_gemelas(df, fechas)
    equivalentes = agrupaciones_equivalentes(df, clasificacion)
    etiquetas = {conservada: descartada for descartada, conservada in equivalentes.items()}

    resumenes = []
    casi_constantes = set()
    for columna in (c.columna for c in clasificacion if c.rol == "medible"):
        conteo = _a_numero(df[columna]).value_counts(normalize=True)
        if not conteo.empty and conteo.iloc[0] >= MINIMO_VALOR_DOMINANTE:
            casi_constantes.add(columna)
            resumenes.append(ResultadoAnalisis(
                nombre=f"`{columna}`: medida casi constante",
                descripciones=[
                    f"El valor {_numero_texto(conteo.index[0])} aparece en el "
                    f"{_numero_texto(conteo.iloc[0] * 100, 1)} % de las filas con dato. No genero "
                    "evolución ni rankings; sí entra en la matriz de correlación."
                ],
            ))

    omitidos: list[dict] = []

    def omitir(texto: str, motivo: str, puntaje: str = "—") -> None:
        omitidos.append({"analisis": texto, "puntaje": puntaje, "motivo": motivo})

    motivo_constante = "medida casi constante; ver el resumen en la sección 5"
    evoluciones, rankings, otros, frecuencias_plan = [], [], [], []

    for plan, texto in zip(planes, elegidos):
        nombre = texto.split(":")[0]
        if plan[0] == "tiempo":
            fecha, medida = plan[1].columna, plan[2].columna
            if fecha in gemelas:
                omitir(nombre, f"`{fecha}` es gemela de `{gemelas[fecha]}`: caen en el mismo mes casi siempre")
            elif medida in casi_constantes:
                omitir(nombre, motivo_constante)
            else:
                evoluciones.append((plan, texto))
        elif plan[0] == "ranking":
            grupo, medida = plan[1].columna, plan[2].columna
            if grupo in equivalentes:
                omitir(nombre, f"casi equivalente a `{equivalentes[grupo]}`, que lo lleva como etiqueta")
            elif medida in casi_constantes:
                omitir(nombre, motivo_constante)
            else:
                rankings.append((plan, texto, _eta2_ajustado(df, grupo, medida)))
        elif plan[0] == "frecuencias":
            if plan[1].columna in equivalentes:
                omitir(nombre, f"casi equivalente a `{equivalentes[plan[1].columna]}`")
            else:
                frecuencias_plan.append((plan, texto))
        else:
            otros.append((plan, texto))

    if len(evoluciones) > MAXIMO_EVOLUCIONES:
        evoluciones.sort(key=lambda e: _variacion_mensual(df, e[0][1].columna, e[0][2].columna), reverse=True)
        for _, texto in evoluciones[MAXIMO_EVOLUCIONES:]:
            omitir(texto.split(":")[0], f"tope de {MAXIMO_EVOLUCIONES} evoluciones; varía menos que las elegidas")
        evoluciones = evoluciones[:MAXIMO_EVOLUCIONES]

    # Un empate a tres decimales lo gana la columna con menos grupos.
    rankings.sort(key=lambda r: (-round(r[2], 3), r[0][1].unicos, r[0][1].columna))
    rankings_elegidos: list[tuple] = []
    por_medida: dict[str, int] = {}
    for plan, texto, eta2 in rankings:
        nombre, medida = texto.split(":")[0], plan[2].columna
        puntaje = _numero_texto(eta2, 3)
        if eta2 < MINIMO_ETA2:
            omitir(nombre, f"η² ajustado menor que {_numero_texto(MINIMO_ETA2)}", puntaje)
        elif por_medida.get(medida, 0) >= MAXIMO_RANKINGS_POR_MEDIDA:
            omitir(nombre, f"tope de {MAXIMO_RANKINGS_POR_MEDIDA} rankings por medida", puntaje)
        elif len(rankings_elegidos) >= MAXIMO_RANKINGS:
            omitir(nombre, f"tope de {MAXIMO_RANKINGS} rankings en total", puntaje)
        else:
            por_medida[medida] = por_medida.get(medida, 0) + 1
            rankings_elegidos.append((plan, f"{texto} η² ajustado: {puntaje}."))

    frecuencias_plan.sort(key=lambda f: f[0][1].unicos)
    for _, texto in frecuencias_plan[MAXIMO_FRECUENCIAS:]:
        omitir(texto.split(":")[0], f"tope de {MAXIMO_FRECUENCIAS} frecuencias; tiene más valores que las elegidas")

    seleccion = evoluciones + rankings_elegidos + otros + frecuencias_plan[:MAXIMO_FRECUENCIAS]
    return Priorizacion(
        planes=[plan for plan, _ in seleccion],
        elegidos=[texto for _, texto in seleccion],
        omitidos=omitidos,
        etiquetas=etiquetas,
        gemelas=gemelas,
        resumenes=resumenes,
    )


def _tipar(
    df_texto: pd.DataFrame,
    clasificacion: list[ClasificacionColumna],
) -> tuple[pd.DataFrame, list[str]]:
    """Convierte cada columna según su tipo y avisa de lo que no se pudo convertir."""
    df = df_texto.copy()
    avisos = []
    for c in clasificacion:
        if c.tipo not in ("numero", "fecha"):
            continue
        original = df_texto[c.columna]
        if c.tipo == "numero":
            df[c.columna] = _a_numero(original)
        else:
            df[c.columna], ambigua = _a_fecha(original)
            if ambigua:
                avisos.append(
                    f"`{c.columna}` no está en formato ISO (AAAA-MM-DD). En valores como "
                    "'01/02/2024', donde el día y el mes se pueden confundir, pandas asume "
                    "el mes primero. Conviene comprobarlo."
                )
        perdidos = int(original.notna().sum() - df[c.columna].notna().sum())
        if perdidos:
            avisos.append(
                f"`{c.columna}`: {_numero_texto(perdidos)} valores no se pudieron convertir a "
                f"{c.tipo} y quedaron nulos."
            )
    return df, avisos


def _celda(valor: object, abreviar_enteros: bool = True) -> str:
    if pd.isna(valor):
        return "—"
    if pd.api.types.is_number(valor):
        return _numero_texto(valor, abreviar_enteros=abreviar_enteros)
    return str(valor).replace("|", "\\|").replace("\n", " ")


def _tabla_markdown(tabla: pd.DataFrame) -> list[str]:
    alineacion = ["--:" if pd.api.types.is_numeric_dtype(tabla[c]) else "---" for c in tabla.columns]
    # En una columna con decimales todos los valores los llevan: 1,00 junto a 1,94.
    abreviar = [
        not (pd.api.types.is_float_dtype(tabla[c]) and (tabla[c].dropna() % 1 != 0).any())
        for c in tabla.columns
    ]
    lineas = [
        "| " + " | ".join(map(str, tabla.columns)) + " |",
        "|" + "|".join(alineacion) + "|",
    ]
    lineas += [
        "| " + " | ".join(_celda(v, a) for v, a in zip(fila, abreviar)) + " |"
        for fila in tabla.itertuples(index=False)
    ]
    return lineas


def _bloque_tabla(resultado: ResultadoAnalisis, nombre: str) -> list[str]:
    """Una tabla para el informe, recortada si corresponde, con enlace a su CSV."""
    tabla = resultado.tablas[nombre]
    archivo = resultado.archivos.get(nombre)
    visibles = FILAS_INICIO_INFORME + FILAS_FIN_INFORME
    enlace = f"[{archivo}]({archivo})" if archivo else "el CSV"

    if nombre in resultado.recortar and len(tabla) > visibles:
        # Se formatea la tabla entera y luego se recorta, para que el formato de
        # cada columna no cambie entre el inicio y el final.
        completa = _tabla_markdown(tabla)
        lineas = completa[: 2 + FILAS_INICIO_INFORME]
        lineas.append(
            f"| … {_numero_texto(len(tabla) - visibles)} filas omitidas |"
            + " |" * (len(tabla.columns) - 1)
        )
        lineas += completa[-FILAS_FIN_INFORME:]
        lineas += ["", f"Tabla completa ({_numero_texto(len(tabla))} filas) en {enlace}."]
        return lineas

    lineas = _tabla_markdown(tabla)
    if archivo:
        lineas += ["", f"Archivo: {enlace}."]
    return lineas


def _bloque_resultado(
    resultado: ResultadoAnalisis,
    con_advertencias: bool = True,
    referencias: dict[str, str] | None = None,
    comunes: set[str] | None = None,
) -> list[str]:
    """Un análisis para el informe.

    `referencias` lleva cada advertencia ya listada en la sección 2 a su número, y
    `comunes` son los textos que ya están en "Cómo leer las tablas": no se repiten.
    """
    referencias = referencias or {}
    comunes = comunes or set()
    decisiones = [d for d in resultado.decisiones if d not in comunes]

    lineas = [f"### {resultado.nombre}", ""]
    if resultado.calculo and resultado.calculo not in comunes:
        lineas += [f"Cálculo: `{resultado.calculo}`", ""]
    if decisiones:
        lineas += ["Decisiones:", ""] + [f"- {d}" for d in decisiones] + [""]
    if resultado.descripciones:
        lineas += ["Lo calculado:", ""] + [f"- {d}" for d in resultado.descripciones] + [""]
    if con_advertencias and resultado.advertencias:
        hallazgos = sorted(
            {referencias[a] for a in resultado.advertencias if a in referencias},
            key=lambda h: int(h[1:]),
        )
        if hallazgos:
            lineas += [f"> Aplica lo dicho en la sección 2: {', '.join(hallazgos)}.\n"]
        lineas += [f"> **Advertencia:** {a}\n" for a in resultado.advertencias if a not in referencias]
    if resultado.grafico:
        lineas += [f"![{resultado.nombre.replace('`', '')}]({resultado.grafico})", ""]
    for nombre in resultado.tablas:
        if nombre in resultado.solo_csv:
            archivo = resultado.archivos.get(nombre, f"{nombre}.csv")
            lineas += [f"Detalle: [{archivo}]({archivo}).", ""]
        else:
            lineas += _bloque_tabla(resultado, nombre) + [""]
    return lineas


def _hallazgos_del_perfil(perfil: str) -> list[str]:
    """Extrae los avisos del bloque de calidad del texto que devuelve perfilar()."""
    encontrado = re.search(r"CALIDAD DE DATOS.*?(?=\nVARIABLES NUMÉRICAS|\Z)", perfil, re.DOTALL)
    if not encontrado:
        return []
    lineas = (linea.strip() for linea in encontrado.group(0).splitlines())
    return [linea[2:] for linea in lineas if linea.startswith("- ")]


def _hallazgos(resultados: ResultadosAgente) -> tuple[list[str], dict[str, str]]:
    """Una sola lista de hallazgos de calidad, venga de donde venga cada uno.

    Devuelve (textos, referencias): cada aviso original y el número que le tocó, para
    que los análisis a los que aplica lo citen en vez de repetirlo.
    """
    hallazgos = [f"**perfilar():** {h}" for h in _hallazgos_del_perfil(resultados.perfil)]
    hallazgos += [f"**Conversión de tipos:** {a}" for a in resultados.avisos_conversion]
    referencias: dict[str, str] = {}
    for chequeo in resultados.chequeos:
        for aviso in chequeo.advertencias:
            # El nombre del chequeo ya dice la columna: no se repite "`fecha`: ".
            texto = re.sub(r"^`[^`]+`: ", "", aviso)
            hallazgos.append(f"**{chequeo.nombre}:** {texto[0].upper()}{texto[1:]}")
            referencias[aviso] = f"H{len(hallazgos)}"
    return hallazgos, referencias


def _textos_comunes(analisis: list[ResultadoAnalisis]) -> list[str]:
    """Decisiones y cálculos que se repiten en varios análisis, en orden de aparición."""
    apariciones: dict[str, int] = {}
    for resultado in analisis:
        for texto in set(resultado.decisiones + ([resultado.calculo] if resultado.calculo else [])):
            apariciones[texto] = apariciones.get(texto, 0) + 1
    comunes = []
    for resultado in analisis:
        for texto in ([resultado.calculo] if resultado.calculo else []) + resultado.decisiones:
            if apariciones[texto] > 1 and texto not in comunes:
                comunes.append(texto)
    return comunes


def escribir_informe(resultados: ResultadosAgente, ruta: Path) -> None:
    """Escribe el informe en markdown. Describe lo calculado, sin interpretarlo."""
    lineas = [
        f"# Informe: {resultados.archivo}",
        "",
        "## 1. Resumen",
        "",
        f"- **Archivo:** {resultados.archivo}",
    ]
    if resultados.filtro:
        lineas += [
            f"- **Filas del archivo:** {_numero_texto(resultados.filas_archivo)}",
            f"- **Filas analizadas:** {_numero_texto(resultados.filas)}",
            f"- **Filtro aplicado por el analista:** {resultados.filtro}",
        ]
    else:
        lineas.append(f"- **Filas:** {_numero_texto(resultados.filas)}")
    lineas += [
        f"- **Columnas:** {_numero_texto(resultados.columnas)}",
        f"- **Fecha de ejecución:** {resultados.fecha_ejecucion}",
        "",
        "## 2. Calidad de datos",
        "",
        "### Hallazgos",
        "",
    ]

    hallazgos, referencias = _hallazgos(resultados)
    if hallazgos:
        lineas += [f"- **H{numero}.** {h}" for numero, h in enumerate(hallazgos, start=1)] + [""]
    else:
        lineas += [
            "No hay problemas de calidad en lo que el agente revisa: `perfilar()`, conversión "
            "de tipos, fechas y agrupaciones.",
            "",
        ]

    sugerencias = [s for chequeo in resultados.chequeos for s in chequeo.sugerencias]
    if sugerencias:
        lineas += ["### Sugerencias (no aplicadas)", ""]
        lineas += [f"> {s}\n" for s in sugerencias]
    for chequeo in resultados.chequeos:
        lineas += _bloque_resultado(chequeo, con_advertencias=False)

    lineas += ["## 3. Clasificación de columnas", ""]
    if resultados.filtro:
        lineas += [
            "La clasificación se calculó sobre el archivo completo, antes de aplicar el filtro.",
            "",
        ]
    lineas += [
        "| Columna | Tipo | Rol | Top N | Únicos | Ratio | Por qué ese tipo | Por qué ese rol |",
        "|---|---|---|---|--:|--:|---|---|",
    ]
    for c in resultados.clasificacion:
        lineas.append(
            f"| `{c.columna}` | {c.tipo} | {c.rol} | {'sí' if c.mostrar_top_n else 'no'} | "
            f"{_numero_texto(c.unicos)} | {_numero_texto(c.ratio, 6)} | "
            f"{c.motivo_tipo.replace('|', chr(92) + '|')} | {c.motivo_rol.replace('|', chr(92) + '|')} |"
        )
    lineas.append("")
    por_revisar = [c for c in resultados.clasificacion if c.revisar]
    if por_revisar:
        lineas += ["Códigos detectados por heurística; corrígelos si no lo son:", ""]
        lineas += [
            f"- `{c.columna}`: {c.motivo_tipo} Para corregirlo: `--forzar {c.columna}.tipo=numero`."
            for c in por_revisar
        ]
        lineas.append("")
    atributos = [c for c in resultados.clasificacion if c.entidad]
    if atributos:
        lineas += ["Atributos detectados por heurística; corrígelos si son medidas:", ""]
        lineas += [
            f"- `{c.columna}`: {c.motivo_rol} Para corregirlo: `--forzar {c.columna}.rol=medible`."
            for c in atributos
        ]
        lineas.append("")

    lineas += ["## 4. Análisis elegidos y descartados", "", "### Elegidos", ""]
    lineas += [f"- {e}" for e in resultados.elegidos] or ["- Ninguno."]
    if resultados.omitidos:
        lineas += [
            "",
            "### Omitidos por prioridad",
            "",
            "Omitir un análisis no excluye datos: solo evita repetir o mostrar lo menos "
            f"informativo. Los rankings se ordenan por η² ajustado, que mide qué parte de la "
            f"variación explican los grupos, con mínimo {_numero_texto(MINIMO_ETA2)}, hasta "
            f"{MAXIMO_RANKINGS_POR_MEDIDA} por medida y {MAXIMO_RANKINGS} en total.",
            "",
        ]
        if resultados.comando_todo:
            lineas += [f"Para generarlos todos: `{resultados.comando_todo}`", ""]
        lineas += ["| Análisis | η² ajustado | Motivo |", "|---|--:|---|"]
        lineas += [
            f"| {o['analisis']} | {o['puntaje']} | {o['motivo']} |" for o in resultados.omitidos
        ]
    lineas += ["", "### Descartados", ""]
    lineas += [f"- {d}" for d in resultados.descartados] or ["- Ninguno."]

    lineas += ["", "## 5. Resultados", ""]
    if not resultados.analisis:
        lineas += ["No se ejecutó ningún análisis.", ""]
    comunes = _textos_comunes(resultados.analisis)
    if comunes:
        lineas += ["### Cómo leer las tablas", "", "Vale para todos los análisis de esta sección:", ""]
        calculos = {r.calculo for r in resultados.analisis if r.calculo}
        lineas += [f"- Cálculo: `{t}`" if t in calculos else f"- {t}" for t in comunes]
        lineas.append("")
    for analisis in resultados.analisis:
        lineas += _bloque_resultado(analisis, referencias=referencias, comunes=set(comunes))

    lineas += ["## 6. Límites", ""]
    lineas += [f"- {limite}" for limite in LIMITES_DEL_AGENTE]

    lineas += [
        "",
        "## 7. Anexo: perfil completo",
        "",
        "Salida literal de `perfilar()`. Su bloque de calidad solo cubre sus propios chequeos; "
        "la lista completa de hallazgos está en la sección 2.",
        "",
        "```text",
        resultados.perfil.strip(),
        "```",
        "",
    ]
    ruta.write_text("\n".join(lineas), encoding="utf-8")


def _validar_salida(carpeta: Path) -> None:
    """data/raw es intocable: ninguna salida puede quedar dentro."""
    partes = [parte.lower() for parte in carpeta.resolve().parts]
    if any(partes[i:i + 2] == ["data", "raw"] for i in range(len(partes) - 1)):
        raise ValueError(f"No se puede escribir en data/raw: {carpeta}")


def _limpiar_salida(carpeta: Path) -> None:
    """Borra lo que dejó una corrida anterior, para no mezclar resultados viejos.

    Solo toca los archivos que genera el agente: otros archivos en la carpeta quedan.
    """
    for archivo in (*(carpeta / CARPETA_TABLAS).glob("*.csv"), *carpeta.glob("grafico_*.png")):
        archivo.unlink()


def _guardar_tablas(resultado: ResultadoAnalisis, carpeta: Path, usados: set[str]) -> None:
    for nombre, tabla in resultado.tablas.items():
        base = re.sub(r"[^\w-]+", "_", nombre)
        archivo = f"{base}.csv"
        # Columnas como 'a b' y 'a_b' darían el mismo nombre de archivo.
        contador = 2
        while archivo in usados:
            archivo = f"{base}_{contador}.csv"
            contador += 1
        usados.add(archivo)
        tabla.to_csv(carpeta / CARPETA_TABLAS / archivo, index=False, encoding="utf-8")
        resultado.archivos[nombre] = f"{CARPETA_TABLAS}/{archivo}"


def _avisos_decimales(df_texto: pd.DataFrame) -> list[str]:
    """Lo que cargar() hizo con los decimales con coma, para que quede en el informe."""
    avisos = [
        f"`{columna}`: valores como '{ejemplo}' tenían punto de miles y coma decimal. Los "
        "convertí a número. El archivo original no se modificó."
        for columna, ejemplo in df_texto.attrs.get("decimales_coma", {}).items()
    ]
    avisos += [
        f"`{columna}`: valores como '{ejemplo}' son ambiguos, porque la coma puede separar miles "
        "o decimales. No los convertí y la columna sigue como texto."
        for columna, ejemplo in df_texto.attrs.get("decimales_ambiguos", {}).items()
    ]
    return avisos


def _sugerencias_de_fechas(
    chequeo: ResultadoAnalisis,
    col_fecha: str,
    plantilla_comando: dict,
    desde: pd.Timestamp | None,
    hasta: pd.Timestamp | None,
    varias_fechas: bool,
) -> list[str]:
    """Convierte lo detectado en un comando que el analista puede correr. No filtra nada."""
    columna = col_fecha if varias_fechas else None
    corte = chequeo.corte
    if corte:
        comando = _comando(
            **plantilla_comando,
            columna_fecha=columna,
            desde=corte["desde"] if corte["desde"] is not None else desde,
            hasta=corte["hasta"] if corte["hasta"] is not None else hasta,
        )
        excluidas = corte["filas_excluidas"]
        return [
            f"**Sugerencia, no aplicada.** Para excluir el tramo sospechoso de `{col_fecha}`: "
            f"`{comando}`. Por qué ese corte: {'; '.join(corte['motivos'])}. Dejaría fuera "
            f"{_numero_texto(excluidas)} filas ({_numero_texto(excluidas / corte['total'] * 100)} %). "
            "No excluí nada: este informe sigue incluyendo ese tramo. Decidir si son válidas "
            "le corresponde al analista."
        ]
    if chequeo.huecos and chequeo.huecos["dias_faltantes"]:
        comando = _comando(
            **plantilla_comando,
            columna_fecha=columna,
            desde=pd.Timestamp("2000-01-01"),
            hasta=pd.Timestamp("2000-12-31"),
        ).replace("2000-01-01", "AAAA-MM-DD").replace("2000-12-31", "AAAA-MM-DD")
        return [
            f"**Sugerencia, no aplicada.** Los huecos de `{col_fecha}` no dejan un corte claro. "
            f"Si quieres limitar el rango, reemplaza las fechas en: `{comando}`. No excluí nada."
        ]
    return []


def analizar(
    ruta_csv: str | Path,
    carpeta_salida: str | Path = "reports",
    forzar: dict[str, dict[str, str]] | None = None,
    desde: str | None = None,
    hasta: str | None = None,
    columna_fecha: str | None = None,
    todo: bool = False,
    unidades: dict[str, str] | None = None,
) -> Path:
    """Perfila, clasifica, analiza y escribe el informe. Devuelve la ruta del informe.

    `desde` y `hasta` (AAAA-MM-DD) filtran por la columna de fecha. Es lo único que
    excluye filas: el agente solo sugiere cortes, nunca los aplica por su cuenta.
    `todo` genera también los análisis que la prioridad dejaría fuera. `unidades` da
    la unidad de cada medida para los ejes: {"Trafico": "vehículos"}.
    """
    ruta = Path(ruta_csv)
    if not ruta.exists():
        raise FileNotFoundError(f"No existe el archivo: {ruta}")

    fecha_desde = _interpretar_fecha_filtro(desde)
    fecha_hasta = _interpretar_fecha_filtro(hasta)
    if fecha_desde is not None and fecha_hasta is not None and fecha_desde > fecha_hasta:
        raise ValueError(f"--desde ({desde}) es posterior a --hasta ({hasta}).")

    # Un informe filtrado va a su propia carpeta: no pisa el del archivo completo.
    nombre_carpeta = ruta.stem
    if desde:
        nombre_carpeta += f"_desde_{desde}"
    if hasta:
        nombre_carpeta += f"_hasta_{hasta}"
    carpeta = Path(carpeta_salida) / nombre_carpeta
    _validar_salida(carpeta)

    df_texto = cargar(ruta, como_texto=True)
    clasificacion = clasificar_columnas(df_texto, forzar=forzar)
    df, avisos_conversion = _tipar(df_texto, clasificacion)
    avisos_conversion = _avisos_decimales(df_texto) + avisos_conversion

    filas_archivo = len(df)
    filtro = None
    if fecha_desde is not None or fecha_hasta is not None:
        col_filtro = _columna_de_filtro(clasificacion, columna_fecha)
        df, filtro = filtrar_por_fecha(df, col_filtro, fecha_desde, fecha_hasta)
        if df.empty:
            raise ValueError(f"El filtro no deja ninguna fila: {filtro}")

    perfil = perfilar(df, ruta.name)

    planes, elegidos, descartados = elegir_analisis(clasificacion)
    prioridad = priorizar_analisis(df, clasificacion, planes, elegidos, todo=todo)
    elegidos = prioridad.elegidos

    fechas = [c.columna for c in clasificacion if c.tipo == "fecha"]
    plantilla_comando = {
        "ruta_csv": ruta_csv,
        "carpeta_salida": carpeta_salida,
        "forzar": forzar,
        "unidades": unidades,
    }
    chequeos = []
    for col_fecha in fechas:
        chequeo = revisar_fechas(df, col_fecha, gemela_de=prioridad.gemelas.get(col_fecha))
        chequeo.sugerencias = _sugerencias_de_fechas(
            chequeo, col_fecha, plantilla_comando, fecha_desde, fecha_hasta, len(fechas) > 1
        )
        chequeos.append(chequeo)

    agrupables = [c.columna for c in clasificacion if c.rol == "agrupable" and c.tipo != "fecha"]
    agrupaciones = detectar_agrupaciones(df, agrupables)
    chequeos.append(agrupaciones)

    elegidos.append(
        f"Detección de agrupaciones: elegí esto porque hay {len(agrupables)} columnas "
        "agrupables que no son fecha. Resultado en la sección 2."
        if len(agrupables) >= 2
        else "Detección de agrupaciones: corre siempre, pero hacen falta 2 columnas agrupables."
    )
    if filtro:
        elegidos.insert(0, f"Filtro por fecha, pedido por el analista: {filtro}")
    else:
        descartados.insert(0, "Filtro por fecha: no excluí ninguna fila porque nadie lo pidió.")

    analisis = []
    for plan in prioridad.planes:
        if plan[0] == "tiempo":
            analisis.append(analizar_tiempo(df, plan[1].columna, plan[2].columna))
        elif plan[0] == "ranking":
            analisis.append(ranking_por_categoria(
                df,
                plan[1].columna,
                plan[2].columna,
                plan[1].mostrar_top_n,
                col_etiqueta=prioridad.etiquetas.get(plan[1].columna),
            ))
        elif plan[0] == "correlacion":
            analisis.append(matriz_correlacion(df, [c.columna for c in plan[1]]))
        else:
            analisis.append(frecuencias(df, plan[1].columna, plan[1].mostrar_top_n))
        # El aviso aplica también al ranking que lleva esa columna como etiqueta.
        if plan[0] in ("ranking", "frecuencias"):
            columna = plan[1].columna
            for afectada in (columna, prioridad.etiquetas.get(columna)):
                analisis[-1].advertencias += agrupaciones.avisos_por_columna.get(afectada, [])
    analisis += prioridad.resumenes

    (carpeta / CARPETA_TABLAS).mkdir(parents=True, exist_ok=True)
    _limpiar_salida(carpeta)
    usados: set[str] = set()
    for resultado in chequeos + analisis:
        _guardar_tablas(resultado, carpeta, usados)

    roles = {c.columna: c.rol for c in clasificacion}
    graficos: set[str] = set()
    for resultado in analisis:
        resultado.grafico = graficar_resultado(resultado, roles, carpeta, unidades, graficos)

    resultados = ResultadosAgente(
        archivo=ruta.name,
        filas=len(df),
        columnas=df.shape[1],
        fecha_ejecucion=datetime.now().strftime("%Y-%m-%d %H:%M"),
        perfil=perfil,
        avisos_conversion=avisos_conversion,
        chequeos=chequeos,
        clasificacion=clasificacion,
        elegidos=elegidos,
        descartados=descartados,
        analisis=analisis,
        filtro=filtro,
        filas_archivo=filas_archivo,
        omitidos=prioridad.omitidos,
        comando_todo=_comando(
            **plantilla_comando,
            columna_fecha=columna_fecha,
            desde=fecha_desde,
            hasta=fecha_hasta,
            todo=True,
        ),
    )
    destino = carpeta / "informe.md"
    escribir_informe(resultados, destino)
    return destino


def _interpretar_forzar(pares: list[str]) -> dict[str, dict[str, str]]:
    """Convierte ['cod_dane.tipo=numero'] en {'cod_dane': {'tipo': 'numero'}}."""
    forzar: dict[str, dict[str, str]] = {}
    for par in pares:
        clave, igual, valor = par.partition("=")
        columna, punto, atributo = clave.rpartition(".")
        if not (igual and punto and columna):
            raise ValueError(f"Usa el formato columna.tipo=valor o columna.rol=valor: '{par}'")
        forzar.setdefault(columna, {})[atributo] = valor
    return forzar


def _interpretar_unidades(pares: list[str]) -> dict[str, str]:
    """Convierte ['Trafico=vehículos'] en {'Trafico': 'vehículos'}."""
    unidades: dict[str, str] = {}
    for par in pares:
        columna, igual, unidad = par.partition("=")
        if not (igual and columna and unidad):
            raise ValueError(f"Usa el formato columna=unidad: '{par}'")
        unidades[columna] = unidad
    return unidades


def main() -> int:
    parser = argparse.ArgumentParser(description="Analiza un dataset y escribe un informe.")
    parser.add_argument("ruta", help="Ruta al CSV o Excel")
    parser.add_argument("--salida", default="reports", help="Carpeta de salida (por defecto, reports)")
    parser.add_argument(
        "--forzar",
        action="append",
        default=[],
        metavar="COLUMNA.ATRIBUTO=VALOR",
        help="Corrige la clasificación, p. ej. cod_dane.tipo=numero. Se puede repetir.",
    )
    parser.add_argument("--desde", metavar="AAAA-MM-DD", help="Analiza solo desde esta fecha, incluida")
    parser.add_argument("--hasta", metavar="AAAA-MM-DD", help="Analiza solo hasta esta fecha, incluida")
    parser.add_argument(
        "--columna-fecha",
        help="Columna por la que filtrar, si el archivo tiene varias de tipo fecha",
    )
    parser.add_argument(
        "--todo",
        action="store_true",
        help="Genera también los análisis que la prioridad deja fuera del informe",
    )
    parser.add_argument(
        "--unidad",
        action="append",
        default=[],
        metavar="COLUMNA=UNIDAD",
        help="Unidad de una medida para los ejes, p. ej. Trafico=vehículos. Se puede repetir.",
    )
    args = parser.parse_args()

    try:
        destino = analizar(
            args.ruta,
            args.salida,
            forzar=_interpretar_forzar(args.forzar),
            desde=args.desde,
            hasta=args.hasta,
            columna_fecha=args.columna_fecha,
            todo=args.todo,
            unidades=_interpretar_unidades(args.unidad),
        )
    except (FileNotFoundError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1

    print(f"Informe guardado en {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
