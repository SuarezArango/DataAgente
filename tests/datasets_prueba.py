"""Genera CSV adversarios para probar el motor contra casos difíciles.

Cada caso existe para activar un camino concreto de src/agente.py. Los datos salen
de semillas fijas: correr el generador dos veces da los mismos archivos.

Uso:
    python tests/datasets_prueba.py
    python src/agente.py tests/datos_prueba/sucio.csv --salida reports/pruebas
"""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

CARPETA = Path(__file__).resolve().parent / "datos_prueba"
SEMILLA = 2026


def _escribir(nombre: str, encabezado: list[str], filas: list[list], separador: str = ",") -> Path:
    ruta = CARPETA / nombre
    with ruta.open("w", newline="", encoding="utf-8") as archivo:
        escritor = csv.writer(archivo, delimiter=separador)
        escritor.writerow(encabezado)
        escritor.writerows(filas)
    return ruta


def solo_texto() -> Path:
    """Ninguna columna numérica: debe activar frecuencias()."""
    azar = random.Random(SEMILLA + 1)
    ciudades = ["Bogotá", "Medellín", "Cali", "Pasto", "Neiva", "Tunja", "Ibagué", "Riohacha"]
    colores = ["rojo", "azul", "verde", "negro"]
    estados = ["activo", "inactivo", "pendiente"]
    filas = [
        [azar.choice(ciudades), azar.choice(colores), azar.choice(estados), f"Comentario número {i}"]
        for i in range(500)
    ]
    return _escribir("solo_texto.csv", ["ciudad", "color", "estado", "comentario"], filas)


def sin_fechas() -> Path:
    """Categorías y números, ninguna fecha: no debe haber evolución."""
    azar = random.Random(SEMILLA + 2)
    regiones = ["Norte", "Sur", "Oriente", "Occidente", "Centro"]
    productos = [f"producto_{i}" for i in range(12)]
    filas = []
    for _ in range(1000):
        region = azar.randrange(len(regiones))
        unidades = (region + 1) * 20 + azar.randrange(15)
        precio = round(azar.uniform(10, 500), 2)
        filas.append([
            regiones[region],
            azar.choice(productos),
            unidades,
            precio,
            round(unidades * precio * azar.uniform(0.9, 1.1), 2),
        ])
    return _escribir("sin_fechas.csv", ["region", "producto", "unidades", "precio", "ingreso"], filas)


def pequeno() -> Path:
    """200 filas con 60 categorías: más de las que caben en el informe."""
    azar = random.Random(SEMILLA + 3)
    categorias = [f"categoria_{i:02d}" for i in range(60)]
    # Las 60 aparecen al menos una vez; el resto se reparte al azar.
    asignadas = categorias + [azar.choice(categorias) for _ in range(140)]
    azar.shuffle(asignadas)
    filas = [[categoria, azar.randrange(1, 1000)] for categoria in asignadas]
    return _escribir("pequeno.csv", ["categoria", "valor"], filas)


def decimales_eu() -> Path:
    """Separador ';', números '1.234,5' y fechas día/mes/año."""
    azar = random.Random(SEMILLA + 4)
    ciudades = ["Madrid", "Lisboa", "Roma", "París", "Berlín"]
    inicio = date(2023, 1, 1)

    def europeo(valor: float, decimales: int) -> str:
        texto = f"{valor:,.{decimales}f}"
        return texto.replace(",", "#").replace(".", ",").replace("#", ".")

    filas = []
    for i in range(300):
        dia = inicio + timedelta(days=i % 365)
        filas.append([
            dia.strftime("%d/%m/%Y"),
            azar.choice(ciudades),
            europeo(azar.uniform(100, 50_000), 1),
            europeo(azar.uniform(0, 30), 2),
        ])
    return _escribir("decimales_eu.csv", ["fecha", "ciudad", "monto", "tasa"], filas, separador=";")


def muy_ancho() -> Path:
    """50 columnas mezcladas: pone a prueba los topes y la explosión de combinaciones."""
    azar = random.Random(SEMILLA + 5)
    filas_totales = 2000
    columnas: dict[str, list] = {}

    for k in range(15):
        valores = [f"v{i}" for i in range(k + 2)]
        columnas[f"categoria_{k:02d}"] = [azar.choice(valores) for _ in range(filas_totales)]
    for k in range(20):
        # Las primeras dependen de categoria_00, para que haya rankings con señal.
        peso = 100 * (20 - k) if k < 10 else 0
        columnas[f"medida_{k:02d}"] = [
            round(int(columnas["categoria_00"][i][1:]) * peso + azar.gauss(0, 50), 2)
            for i in range(filas_totales)
        ]
    inicio = date(2020, 1, 1)
    for k in range(5):
        # Fechas de eventos distintos: no son gemelas entre sí.
        columnas[f"fecha_{k}"] = [
            (inicio + timedelta(days=azar.randrange(1500))).isoformat() for _ in range(filas_totales)
        ]
    for k in range(5):
        columnas[f"cod_{k}"] = [f"{azar.randrange(1, 300):05d}" for _ in range(filas_totales)]
    for k in range(5):
        columnas[f"texto_{k}"] = [f"nota {k}-{i}" for i in range(filas_totales)]

    encabezado = list(columnas)
    filas = [[columnas[c][i] for c in encabezado] for i in range(filas_totales)]
    return _escribir("muy_ancho.csv", encabezado, filas)


def sucio() -> Path:
    """Nulos sobre 40 %, duplicados, constante, vacía y categorías que solo cambian en mayúsculas."""
    azar = random.Random(SEMILLA + 6)
    variantes = ["Bogota", "BOGOTA", "bogota", "Cali", "CALI", " cali ", "Pasto", "pasto"]
    filas = []
    for _ in range(450):
        filas.append([
            azar.choice(variantes),
            azar.randrange(1, 500),
            "" if azar.random() < 0.45 else round(azar.uniform(1, 100), 2),
            "Colombia",
            "",
        ])
    # Duplicados exactos: el 10 % extra.
    filas += [list(fila) for fila in azar.sample(filas, 50)]
    azar.shuffle(filas)
    return _escribir("sucio.csv", ["ciudad", "ventas", "descuento", "pais", "observaciones"], filas)


def una_fila() -> Path:
    """Caso degenerado: un encabezado y una sola fila."""
    return _escribir(
        "una_fila.csv",
        ["fecha", "categoria", "codigo", "valor"],
        [["2024-03-15", "A", "00123", 42.5]],
    )


def jerarquia() -> Path:
    """Dos códigos comparten nombre: debe disparar la regla de entidades fusionadas."""
    azar = random.Random(SEMILLA + 8)
    entidades = [(f"{i:05d}", f"Municipio {i}") for i in range(1, 29)]
    # Dos municipios distintos, en la misma época, con el mismo nombre.
    entidades += [("00091", "La Unión"), ("00092", "La Unión")]
    filas = []
    for codigo, nombre in entidades:
        base = azar.randrange(100, 5000)
        filas += [[codigo, nombre, base + azar.randrange(-50, 50)] for _ in range(20)]
    azar.shuffle(filas)
    return _escribir("jerarquia.csv", ["codigo", "nombre", "valor"], filas)


CASOS = (solo_texto, sin_fechas, pequeno, decimales_eu, muy_ancho, sucio, una_fila, jerarquia)


def main() -> None:
    CARPETA.mkdir(parents=True, exist_ok=True)
    for caso in CASOS:
        ruta = caso()
        print(f"{ruta.name}: {ruta.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
