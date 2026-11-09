# Informe: pequeno.csv

## 1. Resumen

- **Archivo:** pequeno.csv
- **Filas:** 200
- **Columnas:** 2
- **Fecha de ejecución:** 2026-11-06 23:05

## 2. Calidad de datos

### Hallazgos

No hay problemas de calidad en lo que el agente revisa: `perfilar()`, conversión de tipos, fechas y agrupaciones.

### Agrupaciones

Cálculo: `np.unique(codigos_A * unicos_B + codigos_B), para cada par con unicos(B) > unicos(A)`

Decisiones:

- No comparé agrupaciones: hacen falta 2 columnas agrupables y hay 1.

## 3. Clasificación de columnas

| Columna | Tipo | Rol | Top N | Únicos | Ratio | Por qué ese tipo | Por qué ese rol |
|---|---|---|---|--:|--:|---|---|
| `categoria` | texto | agrupable | sí | 60 | 0,300000 | no es número, código ni fecha. | es texto, no se puede sumar, y su ratio 0,300000 (60 valores únicos) permite agrupar. |
| `valor` | numero | medible | sí | 183 | 0,915000 | el 100% de sus valores son números. | es un número con 183 valores distintos. |

## 4. Análisis elegidos y descartados

### Elegidos

- Detección de agrupaciones: corre siempre, pero hacen falta 2 columnas agrupables.

### Omitidos por prioridad

Omitir un análisis no excluye datos: solo evita repetir o mostrar lo menos informativo. Los rankings se ordenan por η² ajustado, que mide qué parte de la variación explican los grupos, con mínimo 0,01, hasta 3 por medida y 8 en total.

Para generarlos todos: `python src/agente.py tests/datos_prueba/pequeno.csv --salida reports/pruebas --todo`

| Análisis | η² ajustado | Motivo |
|---|--:|---|
| Ranking de `categoria` por `valor` | -0,051 | η² ajustado menor que 0,01 |

### Descartados

- Filtro por fecha: no excluí ninguna fila porque nadie lo pidió.
- Evolución en el tiempo: no hay columna de fecha agrupable.
- Matriz de correlación: hacen falta 2 columnas medibles y hay 1.
- Frecuencias: solo se usan cuando no hay ninguna columna medible, y aquí sí hay.

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
PERFIL DE: pequeno.csv
============================================================

RESUMEN GENERAL
  Filas:    200
  Columnas: 2
  Memoria:  0.0 MB

COLUMNAS

  columna                      tipo              nulos     únicos
  ---------------------------------------------------------------
  categoria                    str               0 (  0%)         60
  valor                        int64             0 (  0%)        183

CALIDAD DE DATOS
  Sin problemas evidentes.

VARIABLES NUMÉRICAS

       min  media  mediana    max
valor 5.00 450.27   387.00 996.00
```
