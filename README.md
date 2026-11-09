# Agente de análisis de datos

Proyecto de la especialización en ciencia de datos y analítica.

Un agente que recibe un dataset, revisa su calidad, ejecuta el análisis que
se le pide y explica los resultados en lenguaje claro, mostrando siempre el
código que usó.

**Estado:** pruebas locales con datasets de Kaggle, simulando casos de empresas.

## Estructura

| Carpeta | Para qué |
|---|---|
| `data/raw/` | Datasets originales. No se modifican nunca. |
| `data/processed/` | Datos ya limpios, listos para analizar. |
| `notebooks/` | Exploración interactiva en Jupyter. |
| `src/` | Scripts reutilizables del agente. |
| `tests/` | Pruebas del agente. Se corren con `python -m unittest discover tests`. |
| `reports/` | Informes y gráficos generados. |

Las reglas de comportamiento del agente están en `CLAUDE.md`.

## Puesta en marcha

Activar el entorno virtual (Windows, PowerShell):

```powershell
.venv\Scripts\Activate.ps1
```

Si el entorno no existe o faltan librerías:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Uso

### Analizar un dataset

```powershell
python src/agente.py data/raw/peajes_colombia.csv
```

El agente perfila el archivo, clasifica sus columnas, elige los análisis que
tienen sentido y escribe un informe. Describe lo que calcula, sin interpretarlo:
la conclusión queda en manos del analista.

Con ese comando, el resultado queda en `reports/peajes_colombia/`:

```
informe.md      el informe, con los gráficos insertados
grafico_*.png   un gráfico por cada análisis que pasó el corte de prioridad
tablas/*.csv    las tablas completas
```

Volver a correr el agente reemplaza sus propios archivos en esa carpeta. Otros
archivos que hayas dejado ahí no se tocan. Nunca escribe en `data/raw/`.

### Ejemplos

```powershell
# Solo hasta una fecha. Va a su propia carpeta: reports/v_delitos_hasta_2025-12-31/
python src/agente.py data/raw/v_delitos.csv --hasta 2025-12-31

# Un rango, eligiendo la columna si el archivo tiene varias fechas
python src/agente.py data/raw/peajes_colombia.csv --desde 2018-01-01 --hasta 2019-12-31 --columna-fecha FechaDesde

# Corregir una clasificación
python src/agente.py data/raw/v_delitos.csv --forzar genero.rol=ignorar

# Poner la unidad en los ejes de los gráficos
python src/agente.py data/raw/peajes_colombia.csv --unidad Trafico=vehículos --unidad ValorTarifa=pesos

# Generar también los análisis que la prioridad deja fuera
python src/agente.py data/raw/peajes_colombia.csv --todo

# Guardar en otra carpeta
python src/agente.py data/raw/v_delitos.csv --salida reports/pruebas
```

| Opción | Para qué |
|---|---|
| `--desde AAAA-MM-DD` | Analiza desde esta fecha, incluida |
| `--hasta AAAA-MM-DD` | Analiza hasta esta fecha, incluida |
| `--columna-fecha COLUMNA` | Columna por la que filtrar, si hay varias de tipo fecha |
| `--forzar COLUMNA.tipo=VALOR` | Corrige el tipo de una columna. Se puede repetir |
| `--forzar COLUMNA.rol=VALOR` | Corrige el rol de una columna. Se puede repetir |
| `--unidad COLUMNA=UNIDAD` | Unidad de una medida en los gráficos. Se puede repetir |
| `--todo` | Genera también los análisis omitidos por prioridad |
| `--salida CARPETA` | Carpeta de salida. Por defecto, `reports` |

El agente nunca excluye datos por su cuenta. Si encuentra fechas futuras o un
tramo sospechoso, el informe sugiere el comando exacto para excluirlo, y solo se
aplica si tú lo corres.

### Solo perfilar

```powershell
python src/perfilar.py "data/raw/mi_dataset.csv"
python src/perfilar.py "data/raw/mi_dataset.csv" --guardar
```

Esto reporta filas, columnas, tipos, nulos, duplicados y posibles problemas de
calidad. Con `--guardar`, deja el resumen en `reports/`. `agente.py` ya incluye
este perfil en su informe.

## Cómo clasifica las columnas

Cada columna tiene un **tipo** (qué es) y un **rol** (qué se puede hacer con ella).

| Tipo | Qué significa |
|---|---|
| `fecha` | Sus valores se interpretan como fechas |
| `numero` | Sus valores son números |
| `codigo` | Identifica algo, aunque parezca un número: tiene ceros a la izquierda (`05001`) o un nombre como `id` o `cod` |
| `texto` | Todo lo demás |

| Rol | Qué significa | Qué hace el agente | Ejemplo |
|---|---|---|---|
| `medible` | Un número que se puede sumar o promediar | Lo usa en evoluciones, rankings y correlaciones | `Trafico` |
| `agrupable` | Sirve para formar grupos | Agrupa por ella. Una fecha agrupable sirve para la evolución en el tiempo | `departamento`, `cod_dane` |
| `atributo` | Un número con un solo valor por entidad: describe, no mide | No lo agrega, no lo correlaciona ni lo grafica | `Lat` por cada `IdPeaje` |
| `ignorar` | Vacía, constante, o texto o código casi único por fila | La deja fuera de los análisis | Un correo electrónico |

Que una columna sea casi única solo descarta textos y códigos, porque ahí indica un
identificador. Un número es `medible` y una fecha es `agrupable` aunque casi no
repitan valores. Por eso un consecutivo numérico (1, 2, 3…) queda como `medible`, salvo
que su nombre lo delate como código. Si no, corrígelo con
`--forzar consecutivo.rol=ignorar`.

Una fecha no cuenta como entidad: una tasa de cambio con un valor por día sigue
siendo `medible`.

### Números con coma decimal

Los números como `19.312,7` o `27,25` se convierten solos, y la sección 2 del informe
lo dice. El archivo original no se toca. Una columna cuyas comas siempre llevan 3 dígitos,
como `1,234`, se deja como texto y con un aviso, porque puede ser 1234 o 1,234.

### Corregir una clasificación

La clasificación es heurística y se puede equivocar. La sección 3 del informe
explica el motivo de cada columna y da el comando para corregir las detectadas
por heurística.

```powershell
# Es un número aunque su nombre diga "cod". El rol se recalcula con el tipo nuevo
python src/agente.py data/raw/x.csv --forzar codigo_barras.tipo=numero

# Es una medida, no un atributo
python src/agente.py data/raw/x.csv --forzar precio.rol=medible

# Es un número, pero sirve para agrupar
python src/agente.py data/raw/x.csv --forzar estrato.rol=agrupable

# Corregir el tipo y el rol de la misma columna
python src/agente.py data/raw/x.csv --forzar estrato.tipo=numero --forzar estrato.rol=agrupable
```

Solo un `numero` puede ser `medible` o `atributo`. Pedirlo para otro tipo da
error, para que un código nunca se sume por accidente.

## Qué análisis aparecen en el informe

Omitir un análisis no excluye datos: todos los cálculos usan todas las filas. El
agente quita primero lo redundante:

- **Fechas gemelas:** dos fechas que caen casi siempre en el mismo mes, como el
  inicio y el fin de un periodo. Usa la más temprana.
- **Agrupaciones casi 1:1:** por ejemplo, un código y su nombre. Una sola tabla,
  agrupada por la más fina, con la otra como etiqueta.
- **Medidas casi constantes:** un mismo valor en al menos el 95 % de las filas con
  dato. Una línea de resumen en vez de evolución y rankings.

Después ordena los rankings por **η² ajustado**, que mide qué parte de la variación
de la medida explican los grupos. Muestra los que llegan a 0,01, hasta 3 por medida
y 8 en total. Además, hasta 5 evoluciones y la matriz de correlación.

Es un criterio estadístico, no de importancia para el negocio. La sección 4 lista
cada análisis omitido con su motivo, y `--todo` los genera todos.

## Pruebas

```powershell
python -m unittest discover tests
```

## Librerías principales

- **pandas** — manipulación de tablas
- **DuckDB** — SQL directamente sobre archivos CSV, sin servidor de base de datos
- **matplotlib** — gráficos
- **Jupyter** — exploración interactiva
