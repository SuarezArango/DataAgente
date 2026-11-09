"""Gráficos de DataAgente: uno por cada análisis que pasó el corte de prioridad.

Evolución -> línea. Ranking y frecuencias -> barras horizontales, top 10. Correlación
-> mapa de calor con escala divergente centrada en 0. Los valores se rotulan sobre los datos,
y el color nunca es la única forma de distinguir algo: los puntos especiales cambian
de forma, y cada celda del mapa de calor lleva su número con signo.

No se llama directamente: agente.py lo usa al escribir el informe.
"""

from __future__ import annotations

import re
from pathlib import Path

import matplotlib
import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
from matplotlib.dates import AutoDateLocator, ConciseDateFormatter
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

RESOLUCION = 150
TOP_RANKING = 10
LARGO_ETIQUETA = 44

# Paleta validada para daltonismo. Una sola serie usa un solo color; la escala
# divergente va de azul a rojo, pasando por un gris neutro en el 0.
SERIE = "#2a78d6"
POLO_NEGATIVO = "#2a78d6"
POLO_POSITIVO = "#e34948"
PUNTO_MEDIO = "#f0efec"
SUPERFICIE = "#fcfcfb"
TINTA = "#0b0b0b"
TINTA_SECUNDARIA = "#52514e"
TINTA_TENUE = "#898781"
CUADRICULA = "#e1e0d9"
EJE = "#c3c2b7"

ESTILO = {
    "font.family": "sans-serif",
    "font.sans-serif": ["Segoe UI", "DejaVu Sans"],
    "font.size": 10,
    "axes.edgecolor": EJE,
    "axes.labelcolor": TINTA_SECUNDARIA,
    "text.color": TINTA,
    "xtick.color": TINTA_SECUNDARIA,
    "ytick.color": TINTA_SECUNDARIA,
}

ESCALA_DIVERGENTE = LinearSegmentedColormap.from_list(
    "divergente", [POLO_NEGATIVO, PUNTO_MEDIO, POLO_POSITIVO]
)


def _numero(valor: float, decimales: int = 2) -> str:
    """Formato español: 1.234,56. Un valor entero se escribe sin decimales."""
    if pd.isna(valor):
        return "—"
    if float(valor).is_integer():
        return f"{int(valor):,}".replace(",", ".")
    return f"{float(valor):,.{decimales}f}".replace(",", "#").replace(".", ",").replace("#", ".")


def _acortar(texto: str, largo: int = LARGO_ETIQUETA) -> str:
    return texto if len(texto) <= largo else texto[: largo - 1].rstrip() + "…"


def _titulos(figura: Figure, titulo: str, subtitulo: str) -> None:
    figura.text(0.02, 0.97, titulo, fontsize=13, fontweight="bold", va="top", color=TINTA)
    figura.text(0.02, 0.91, subtitulo, fontsize=9.5, va="top", color=TINTA_SECUNDARIA)


def _guardar(figura: Figure, ruta: Path) -> None:
    FigureCanvasAgg(figura)
    figura.savefig(ruta, dpi=RESOLUCION, facecolor=SUPERFICIE)


def graficar_evolucion(
    tabla: pd.DataFrame,
    col_fecha: str,
    medida: str,
    ruta: Path,
    unidad: str | None = None,
) -> bool:
    """Línea de la suma mensual, con el máximo y el mínimo rotulados.

    Un mes con menos de la mitad de los días con datos de un mes típico va con un
    círculo vacío: se distingue por la forma, no por el color.
    """
    datos = tabla.dropna(subset=["suma"])
    if len(datos) < 2:
        return False

    fechas = pd.PeriodIndex(datos["periodo"], freq="M").to_timestamp()
    valores = datos["suma"].to_numpy()
    pocos_dias = (datos["dias_con_datos"] < datos["dias_con_datos"].median() / 2).to_numpy()

    with matplotlib.rc_context(ESTILO):
        figura = Figure(figsize=(9, 4.4), facecolor=SUPERFICIE)
        # El margen crece con el largo de las cifras, para que el eje Y no se corte.
        izquierda = 0.07 + 0.0085 * len(_numero(abs(valores).max()))
        eje = figura.add_axes((izquierda, 0.1, 0.96 - izquierda, 0.72), facecolor=SUPERFICIE)
        eje.plot(fechas, valores, color=SERIE, linewidth=1.6, zorder=2)

        if pocos_dias.any():
            eje.plot(
                fechas[pocos_dias], valores[pocos_dias], linestyle="none", marker="o", markersize=6,
                markerfacecolor=SUPERFICIE, markeredgecolor=SERIE, markeredgewidth=1.3, zorder=3,
            )

        rango_x = fechas[-1] - fechas[0]
        # Un mínimo pegado a la base se rotula arriba: abajo chocaría con el eje X.
        minimo_en_la_base = valores.min() >= 0 and valores.min() < valores.max() * 0.12
        extremos = ((valores.argmax(), 9), (valores.argmin(), 9 if minimo_en_la_base else -14))
        for posicion, desplazamiento in extremos:
            eje.plot(fechas[posicion], valores[posicion], marker="o", markersize=6, color=SERIE, zorder=4)
            cerca_del_final = fechas[posicion] > fechas[0] + rango_x * 0.85
            cerca_del_inicio = fechas[posicion] < fechas[0] + rango_x * 0.15
            eje.annotate(
                f"{_numero(valores[posicion])} ({datos['periodo'].iloc[posicion]})",
                (fechas[posicion], valores[posicion]),
                xytext=(0, desplazamiento), textcoords="offset points", fontsize=9, color=TINTA,
                ha="right" if cerca_del_final else "left" if cerca_del_inicio else "center",
            )

        if valores.min() >= 0:
            eje.set_ylim(bottom=0)
        eje.margins(y=0.14)
        if valores.min() >= 0:
            eje.set_ylim(bottom=0)
        localizador = AutoDateLocator()
        eje.xaxis.set_major_locator(localizador)
        eje.xaxis.set_major_formatter(ConciseDateFormatter(localizador))
        eje.yaxis.set_major_formatter(FuncFormatter(lambda valor, _: _numero(valor)))
        eje.set_ylabel(unidad or f"Suma de {medida}")
        eje.grid(axis="y", color=CUADRICULA, linewidth=0.7)
        eje.set_axisbelow(True)
        eje.tick_params(length=0)
        for lado in ("top", "right", "left"):
            eje.spines[lado].set_visible(False)

        subtitulo = f"Mes a mes según {col_fecha}. Rotulados: máximo y mínimo."
        if pocos_dias.any():
            subtitulo += " Círculo vacío: mes con menos de la mitad de los días habituales."
        _titulos(figura, f"Suma mensual de {medida}", subtitulo)
        _guardar(figura, ruta)
    return True


def _barras_horizontales(
    nombres: list[str],
    valores,
    rotulos: list[str],
    titulo: str,
    subtitulo: str,
    eje_x: str,
    ruta: Path,
) -> None:
    """Barras de mayor a menor con el valor rotulado al final de cada una."""
    nombres = [_acortar(nombre) for nombre in nombres]
    posiciones = list(range(len(nombres)))
    maximo = max(abs(valores).max(), 1)

    with matplotlib.rc_context(ESTILO):
        figura = Figure(figsize=(9, 1.5 + 0.38 * len(nombres)), facecolor=SUPERFICIE)
        alto_superior = 0.95 / figura.get_figheight()
        eje = figura.add_axes(
            (0.38, 0.45 / figura.get_figheight(), 0.54, 1 - alto_superior - 0.45 / figura.get_figheight()),
            facecolor=SUPERFICIE,
        )
        eje.barh(posiciones, valores, height=0.68, color=SERIE, zorder=2)
        for posicion, valor, rotulo in zip(posiciones, valores, rotulos):
            separacion = maximo * 0.012
            eje.text(
                valor + (separacion if valor >= 0 else -separacion), posicion, rotulo,
                va="center", ha="left" if valor >= 0 else "right", fontsize=9, color=TINTA,
            )
        eje.set_yticks(posiciones, nombres)
        eje.invert_yaxis()
        eje.set_xlim(min(0, valores.min() * 1.2), max(0, valores.max()) * 1.2 or None)
        eje.set_xticks([])
        eje.set_xlabel(eje_x)
        eje.tick_params(length=0)
        for lado in ("top", "right", "bottom"):
            eje.spines[lado].set_visible(False)

        titulo_y = 1 - 0.2 / figura.get_figheight()
        figura.text(0.02, titulo_y, titulo, fontsize=13, fontweight="bold", va="top")
        figura.text(
            0.02, titulo_y - 0.3 / figura.get_figheight(),
            subtitulo, fontsize=9.5, va="top", color=TINTA_SECUNDARIA,
        )
        _guardar(figura, ruta)


def graficar_ranking(
    tabla: pd.DataFrame,
    col_grupo: str,
    medida: str,
    ruta: Path,
    unidad: str | None = None,
) -> bool:
    """Barras horizontales del top 10 por suma, de mayor a menor."""
    datos = tabla.dropna(subset=["suma"]).sort_values("suma", ascending=False, kind="stable")
    if len(datos) < 2:
        return False

    top = datos.head(TOP_RANKING)
    if "etiqueta" in top.columns:
        nombres = [f"{g} · {e}" if pd.notna(e) else str(g) for g, e in zip(top["grupo"], top["etiqueta"])]
    else:
        nombres = top["grupo"].astype(str).tolist()
    valores = top["suma"].to_numpy()
    total = len(datos)
    alcance = f"Top {len(top)} de {_numero(total)} grupos" if total > len(top) else f"Los {total} grupos"
    _barras_horizontales(
        nombres, valores, [_numero(v) for v in valores],
        f"{medida} por {col_grupo}", f"{alcance}, ordenados por suma.",
        unidad or f"Suma de {medida}", ruta,
    )
    return True


def graficar_frecuencias(tabla: pd.DataFrame, col_grupo: str, ruta: Path) -> bool:
    """Barras horizontales de los 10 valores más frecuentes, con conteo y porcentaje."""
    datos = tabla.sort_values("conteo", ascending=False, kind="stable")
    if len(datos) < 2:
        return False

    top = datos.head(TOP_RANKING)
    valores = top["conteo"].to_numpy()
    rotulos = [
        f"{_numero(conteo)} ({_numero(round(porcentaje, 1), 1)} %)"
        for conteo, porcentaje in zip(top["conteo"], top["porcentaje"])
    ]
    total = len(datos)
    alcance = f"Top {len(top)} de {_numero(total)} valores" if total > len(top) else f"Los {total} valores"
    _barras_horizontales(
        top["valor"].astype(str).tolist(), valores, rotulos,
        f"Frecuencia de {col_grupo}", f"{alcance}, ordenados por número de filas.",
        "Filas", ruta,
    )
    return True


def graficar_correlacion(tabla: pd.DataFrame, ruta: Path) -> bool:
    """Mapa de calor de -1 a 1 centrado en 0, con el valor de r escrito en cada celda."""
    matriz = tabla.set_index(tabla.columns[0])
    columnas = [str(c) for c in matriz.columns]
    n = len(columnas)
    if n < 2:
        return False

    with matplotlib.rc_context(ESTILO):
        ancho = max(6.5, 2.4 + 1.25 * n)
        alto = max(4.8, 2.2 + 0.85 * n)
        figura = Figure(figsize=(ancho, alto), facecolor=SUPERFICIE)
        eje = figura.add_axes(
            (2.0 / ancho, 0.9 / alto, 1 - 2.2 / ancho, 1 - 1.85 / alto), facecolor=SUPERFICIE
        )
        eje.pcolormesh(
            matriz.to_numpy(dtype=float), cmap=ESCALA_DIVERGENTE,
            norm=TwoSlopeNorm(vmin=-1, vcenter=0, vmax=1), edgecolors=SUPERFICIE, linewidth=2,
        )
        for fila in range(n):
            for columna in range(n):
                valor = matriz.iloc[fila, columna]
                # Un signo explícito: positivo y negativo no dependen solo del color.
                if pd.isna(valor):
                    texto = "—"
                else:
                    texto = f"{valor:+.2f}".replace(".", ",").replace("-", "−")
                eje.text(
                    columna + 0.5, fila + 0.5, texto, ha="center", va="center", fontsize=10,
                    color="#ffffff" if pd.notna(valor) and abs(valor) >= 0.75 else TINTA,
                )
        eje.set_xticks([i + 0.5 for i in range(n)], columnas, rotation=30, ha="right")
        eje.set_yticks([i + 0.5 for i in range(n)], columnas)
        eje.invert_yaxis()
        eje.tick_params(length=0)
        for lado in eje.spines.values():
            lado.set_visible(False)

        figura.text(0.03, 1 - 0.18 / alto, "Correlación de Pearson", fontsize=13, fontweight="bold", va="top")
        figura.text(
            0.03, 1 - 0.5 / alto, "De −1 (azul) a +1 (rojo), con gris en 0. No implica causalidad.",
            fontsize=9.5, va="top", color=TINTA_SECUNDARIA,
        )
        _guardar(figura, ruta)
    return True


def _nombre_libre(base: str, usados: set[str]) -> str:
    base = re.sub(r"[^\w-]+", "_", base)
    nombre = f"{base}.png"
    contador = 2
    while nombre in usados:
        nombre = f"{base}_{contador}.png"
        contador += 1
    usados.add(nombre)
    return nombre


def graficar_resultado(
    resultado,
    roles: dict[str, str],
    carpeta: Path,
    unidades: dict[str, str] | None = None,
    usados: set[str] | None = None,
) -> str | None:
    """Grafica un análisis si le corresponde. Devuelve el nombre del PNG, o None.

    Una columna con rol atributo nunca se grafica, aunque alguien la pida.
    """
    datos = resultado.datos_grafico
    if not datos or any(roles.get(c) == "atributo" for c in datos["columnas"]):
        return None

    unidades = unidades or {}
    usados = usados if usados is not None else set()
    tabla = resultado.tablas[datos["tabla"]]

    if datos["tipo"] == "tiempo":
        nombre = _nombre_libre(f"grafico_evolucion_{datos['fecha']}_{datos['medida']}", usados)
        hecho = graficar_evolucion(
            tabla, datos["fecha"], datos["medida"], carpeta / nombre, unidades.get(datos["medida"])
        )
    elif datos["tipo"] == "ranking":
        nombre = _nombre_libre(f"grafico_ranking_{datos['grupo']}_{datos['medida']}", usados)
        hecho = graficar_ranking(
            tabla, datos["grupo"], datos["medida"], carpeta / nombre, unidades.get(datos["medida"])
        )
    elif datos["tipo"] == "frecuencias":
        nombre = _nombre_libre(f"grafico_frecuencias_{datos['grupo']}", usados)
        hecho = graficar_frecuencias(tabla, datos["grupo"], carpeta / nombre)
    else:
        nombre = _nombre_libre("grafico_correlacion", usados)
        hecho = graficar_correlacion(tabla, carpeta / nombre)

    return nombre if hecho else None
