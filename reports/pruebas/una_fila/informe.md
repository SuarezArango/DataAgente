# Informe: una_fila.csv

## 1. Resumen

- **Archivo:** una_fila.csv
- **Filas:** 1
- **Columnas:** 4
- **Fecha de ejecución:** 2026-11-06 23:05

## 2. Calidad de datos

### Hallazgos

- **H1.** **perfilar():** Columnas con un solo valor: fecha, categoria, codigo, valor

### Fechas de `fecha`

Decisiones:

- Comparé las fechas con el día de ejecución (2026-11-06) y busqué días y meses sin filas entre la primera y la última fecha.

Lo calculado:

- Rango de `fecha`: 2024-03-15 a 2024-03-15.
- Ninguna fecha es posterior al día de ejecución.
- No faltan días entre la primera y la última fecha.

### Agrupaciones

Cálculo: `np.unique(codigos_A * unicos_B + codigos_B), para cada par con unicos(B) > unicos(A)`

Decisiones:

- No comparé agrupaciones: hacen falta 2 columnas agrupables y hay 0.

## 3. Clasificación de columnas

| Columna | Tipo | Rol | Top N | Únicos | Ratio | Por qué ese tipo | Por qué ese rol |
|---|---|---|---|--:|--:|---|---|
| `fecha` | fecha | ignorar | no | 1 | 1,000000 | el 100% de una muestra de 1 valores se interpretó como fecha (p. ej. '2024-03-15'). | tiene un solo valor ('2024-03-15'). |
| `categoria` | texto | ignorar | no | 1 | 1,000000 | no es número, código ni fecha. | tiene un solo valor ('A'). |
| `codigo` | codigo | ignorar | no | 1 | 1,000000 | sus valores son dígitos, pero 1 empiezan por cero (p. ej. '00123'). Un número no lleva ceros a la izquierda. | tiene un solo valor ('00123'). |
| `valor` | numero | ignorar | no | 1 | 1,000000 | el 100% de sus valores son números. | tiene un solo valor ('42.5'). |

Códigos detectados por heurística; corrígelos si no lo son:

- `codigo`: sus valores son dígitos, pero 1 empiezan por cero (p. ej. '00123'). Un número no lleva ceros a la izquierda. Para corregirlo: `--forzar codigo.tipo=numero`.

## 4. Análisis elegidos y descartados

### Elegidos

- Detección de agrupaciones: corre siempre, pero hacen falta 2 columnas agrupables.

### Descartados

- Filtro por fecha: no excluí ninguna fila porque nadie lo pidió.
- Evolución en el tiempo: no hay columna de fecha agrupable (`fecha` quedó con rol ignorar).
- Ranking por categoría: no hay columna agrupable.
- Matriz de correlación: hacen falta 2 columnas medibles y hay 0.
- Frecuencias: no hay ninguna columna agrupable.
- `fecha` queda fuera de todos los análisis: tiene un solo valor ('2024-03-15').
- `categoria` queda fuera de todos los análisis: tiene un solo valor ('A').
- `codigo` queda fuera de todos los análisis: tiene un solo valor ('00123').
- `valor` queda fuera de todos los análisis: tiene un solo valor ('42.5').

## 5. Resultados

No se ejecutó ningún análisis.

## 6. Límites

- "Más informativo" es un criterio estadístico, no importancia para el negocio. Un análisis omitido puede ser justo el que interesa: `--todo` los genera todos.
- No sé qué significa cada columna. Por eso cada tabla trae `filas`, `suma` y `media`: cuál es la correcta depende de si la variable es un conteo o una medida.
- No sé cómo se generaron los datos. Las cifras describen lo que hay en el archivo, no necesariamente lo que ocurrió en la realidad.
- No explico por qué cambia una cifra ni por qué dos variables se mueven juntas.
- Un hueco de calendario solo dice que no hay filas en esas fechas. Puede ser normal si el dato es semanal, mensual o no se registra en ciertos días.
- No detecto fechas con el día y el mes intercambiados cuando ambas lecturas son válidas.
- Un mismo texto puede referirse a cosas distintas (dos municipios con el mismo nombre, por ejemplo). Solo lo detecto si otra columna lo revela, y el aviso puede ser falso cuando la relación es una jerarquía legítima.
- No decido qué tramo de datos es válido. Si sugiero un filtro, es una propuesta: solo se aplica si el analista corre el comando.
- Convierto números con punto de miles y coma decimal ('1.234,5'), pero no uno con comas que siempre llevan 3 dígitos ('1,234'): puede ser 1234 o 1,234.
- La clasificación de columnas es heurística. Se corrige con `--forzar columna.tipo=valor` o `--forzar columna.rol=valor`.

## 7. Anexo: perfil completo

Salida literal de `perfilar()`. Su bloque de calidad solo cubre sus propios chequeos; la lista completa de hallazgos está en la sección 2.

```text
PERFIL DE: una_fila.csv
============================================================

RESUMEN GENERAL
  Filas:    1
  Columnas: 4
  Memoria:  0.0 MB

COLUMNAS

  columna                      tipo              nulos     únicos
  ---------------------------------------------------------------
  fecha                        datetime64[       0 (  0%)          1
  categoria                    str               0 (  0%)          1
  codigo                       str               0 (  0%)          1
  valor                        float64           0 (  0%)          1

CALIDAD DE DATOS

  - Columnas con un solo valor: fecha, categoria, codigo, valor

VARIABLES NUMÉRICAS

        min  media  mediana   max
valor 42.50  42.50    42.50 42.50
```
