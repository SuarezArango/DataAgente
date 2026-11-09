# Agente de análisis de datos

## Qué es este proyecto

Agente de análisis de datos operado por un analista. Recibe un dataset,
lo perfila, ejecuta el análisis y explica los resultados en lenguaje claro.

Estado: pruebas locales con datasets descargados de Kaggle, simulando casos
de empresas. No es un producto público.

## Reglas permanentes

Estas reglas aplican a toda sesión de trabajo en este proyecto.

### Manejo de datos

- NUNCA modifiques, sobrescribas ni borres nada en `data/raw/`. Es la copia
  original e intocable del dataset.
- Todo resultado intermedio o limpio va a `data/processed/`.
- Informes, tablas y gráficos van a `reports/`.
- Antes de analizar un dataset nuevo, perfílalo primero: número de filas y
  columnas, tipos de dato, nulos por columna, duplicados, y rango de las
  variables numéricas.

### Análisis

- Antes de responder una pregunta, declara en una línea qué vas a calcular
  y con qué columnas.
- Revisa la calidad de los datos ANTES de concluir: nulos, duplicados, fechas
  mal interpretadas, y categorías escritas de varias formas
  ("Bogota" vs "Bogotá", "BOGOTA").
- Si un resultado depende de una decisión de limpieza (cómo tratar los nulos,
  qué considerar un valor atípico), dilo explícitamente en la respuesta.
- No inventes cifras ni rellenes datos que no estén en el dataset. Si falta
  información para responder, dilo.
- Distingue correlación de causalidad. Si dos variables se mueven juntas,
  dilo así, no como causa y efecto.

### Código

- SQL sobre archivos con DuckDB; pandas para transformaciones.
- Muestra siempre la consulta o el código que produjo el resultado, para que
  el analista pueda verificarlo.
- Nombres de variables y comentarios en español.
- Scripts reutilizables van a `src/`; la exploración va a `notebooks/`.

### Entrega

- Cada análisis termina con tres cosas: qué encontré, qué significa, y qué
  revisaría después.
- Incluye un gráfico solo si aclara algo que la tabla no muestra.

## Entorno

- Entorno virtual: `.venv`
- Activar en Windows (PowerShell): `.venv\Scripts\Activate.ps1`
- Librerías: ver `requirements.txt` (pandas, duckdb, matplotlib, numpy, jupyter)

## Estructura

```
data/raw/          datasets originales, intocables
data/processed/    datos ya limpios
notebooks/         exploración
src/               scripts reutilizables del agente
tests/             pruebas del agente (python -m unittest discover tests)
reports/           informes y gráficos generados
```
