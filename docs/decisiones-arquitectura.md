# DataAgente — decisiones de arquitectura

Registro del **porqué** del diseño. El código dice qué hace; este
documento dice por qué se hizo así y qué se descartó.

Escrito el 2026-11-06, al cerrar el motor.

---

## Estructura general

El proyecto tiene tres capas, deliberadamente separadas:

| Capa | Dónde | Qué hace |
|---|---|---|
| Cara | `landing/` | Presenta el producto. No ejecuta nada. |
| Cerebro | `CLAUDE.md` | Reglas de conducta del agente. |
| Motor | `src/` | Hace el trabajo. |

**Decisión:** las reglas de conducta viven en `CLAUDE.md`, no en el
código ni en la cabeza del usuario.

**Por qué:** un agente que depende de que el operador recuerde pedirle
"revisa la calidad antes de concluir" no es un agente. Al estar en
`CLAUDE.md`, la regla se aplica sola en cada sesión.

**Evidencia:** al pedirle una comparación entre departamentos, el agente
verificó por su cuenta si Bogotá estaba incluida dentro de Cundinamarca
antes de describir la tabla. Nadie se lo pidió en ese momento.

---

## Genérico vs específico del dominio

- `agente.py` y `graficar.py` funcionan con **cualquier** CSV. No saben
  nada de ningún dominio.
- `consultas.py` es específico de la base de delitos.

**Por qué:** el motor genérico es el producto; las consultas de un
dominio son un caso de uso. Mezclarlos convertiría cada dataset nuevo
en una reescritura.

**Validación:** se probó con dos datasets sin nada en común —
`v_delitos.csv` (2,4M filas, 1 numérica, 1 fecha, UTF-8) y
`peajes_colombia.csv` (98K filas, 6 numéricas, 2 fechas, latin-1,
fechas en formato mes/día/año).

---

## Decisión 1 — Clasificar columnas por dos atributos, no por uno

**Problema.** La primera versión usaba una sola etiqueta por columna:
fecha, categoría, identificador o número. Con esa clasificación,
`cod_dane` salía como *identificador*, lo que lo excluía de todos los
rankings. Pero agrupar por `cod_dane` es la forma correcta de rankear
municipios.

**Causa.** Una etiqueta intentaba responder dos preguntas distintas:

- ¿Qué **es** la columna? (`cod_dane` es un código: no se suma)
- ¿Qué se puede **hacer** con ella? (`cod_dane` es agrupable: 1.111
  valores en 2,4M filas)

**Decisión.** Dos atributos independientes por columna:

```
tipo = fecha | numero | codigo | texto
rol  = medible | agrupable | atributo | ignorar
```

`cod_dane` queda `tipo=codigo, rol=agrupable`: se rankea, nunca se suma.

**Lección transferible.** Cuando cuesta decidir qué etiqueta poner a
algo, suele ser señal de que hacen falta dos. Este mismo error apareció
dos veces en el proyecto.

---

## Decisión 2 — Ratio de cardinalidad, no umbral absoluto

**Problema.** El primer criterio era "más de 50 valores únicos = no es
categoría". Con él, `municipio` (1.029 valores) quedaba fuera de los
rankings.

**Causa.** 1.029 municipios en 2,4 millones de filas es poquísima
variedad: cada uno se repite unas 2.300 veces. Los mismos 1.029 valores
en 1.100 filas serían casi un identificador. El número absoluto no
distingue los dos casos.

**Decisión.**

```
ratio = valores_únicos / número_de_filas

ratio > 0,5  → rol = ignorar (casi único por fila)
resto        → agrupable o medible según el tipo
```

**Corrección posterior.** El ratio decide si una columna es agrupable.
Pero "son demasiadas categorías para mostrarlas todas" es una pregunta
sobre el **número absoluto**. Por eso existe un flag aparte,
`mostrar_top_n`, que se activa con más de 50 valores únicos y solo
afecta cuántas filas entran al informe.

---

## Decisión 3 — Detectar códigos por los ceros a la izquierda

**Problema.** `cod_dane` vale `05001`. Leído como número se vuelve
`5001`, y el agente intentaría sumarlo.

**Decisión.** Dos señales, en orden de confianza:

1. **Ceros a la izquierda.** `"05001"` no es un número; ningún número se
   escribe así. Señal fuerte y sin dependencia del idioma.
2. **Nombre de la columna** (`id`, `cod`, `codigo`, `key`, `clave`),
   comparando palabras completas y no fragmentos, para que `candidatos`
   no se confunda con `id`.

Requiere leer el CSV sin inferir tipos. Por eso `cargar()` en
`perfilar.py` recibió un parámetro `como_texto`, con valor por defecto
que **no cambia el comportamiento anterior**.

**Resultado en la práctica:** detectó `cod_dane` por los ceros, y
`IdPeaje` por el nombre en camelCase.

---

## Decisión 4 — El agente avisa y propone, pero no decide

**Problema.** El agente detectó que las fechas de 2026 en `v_delitos`
estaban corruptas. ¿Debía excluirlas por su cuenta?

**Decisión: no.** Excluir datos ya es interpretar, y eso le corresponde
al analista. Pero avisar sin dar salida deja al usuario adivinando.

La postura adoptada: **avisa, explica y sugiere el comando exacto**, sin
ejecutarlo.

```
Para excluir el tramo sospechoso:
python src/agente.py <archivo> --hasta 2025-12-31
```

**Por qué:** mantiene al humano en control sin hacerlo adivinar qué
hacer con la advertencia.

---

## Decisión 5 — Huecos de calendario como chequeo genérico

**Problema.** Las fechas de 2026 tenían el día y el mes intercambiados
en los registros donde el día era ≤ 12. Detectar eso requiere conocer el
dataset.

**Decisión.** No intentar detectar el intercambio. En su lugar, un
chequeo genérico: **si faltan días en medio del rango de fechas,
reportarlo.**

**Por qué funciona.** El intercambio deja un rastro estructural: los días
3 al 12 desaparecen de enero y febrero, y reaparecen como los días 1 y 2
de los meses 3 al 12. Son huecos de calendario, detectables sin saber
nada del dominio.

**Resultado:** el chequeo genérico encontró el error concreto que había
costado una sesión descubrir a mano, comparando 2025 contra 2026.

---

## Decisión 6 — Detectar agrupaciones que fusionan entidades

**Problema.** "La Unión" existe en cuatro departamentos. Agrupar por
`municipio` los suma como si fueran uno. El agente no sabe geografía.

**Decisión.** Una regla puramente estructural:

> Para dos columnas agrupables A y B con `únicos(B) > únicos(A)`: si
> algún valor de A aparece junto a varios valores de B, agrupar por A
> puede estar mezclando entidades distintas. Sugerir agrupar por B.

**Segundo criterio, contra falsos positivos.** La regla sola gritaría en
casi cualquier par de columnas. Se añadió una condición: en una
jerarquía real, cada valor de B pertenece a **un solo** valor de A.

| Par | Valores de A afectados | ¿B tiene un solo A? | ¿Avisa? |
|---|---|---|---|
| `Peaje` ↔ `IdPeaje` | 0,7% | 100% | Sí |
| `IdCategoriaTarifa` ↔ `IdPeaje` | 66,7% | 0% | No |

El segundo par tiene cien veces más valores afectados y aun así no
avisa: no es una jerarquía, son dos dimensiones independientes.

**Resultado:** detectó que dos peajes distintos se llaman LA LIZAMA.

---

## Decisión 7 — Atributos no son medidas

**Problema.** `Lat` y `Lon` son numéricas, así que el agente las trataba
como medibles: promedio mensual de latitud, latitud en la matriz de
correlación. Sin sentido.

**Decisión.** Un tercer rol:

> Si una columna numérica tiene exactamente un valor por cada valor de
> alguna columna agrupable, es un **atributo** de esa entidad, no una
> medida. No se agrega, no entra en correlaciones, no se grafica.

`Lat` tiene 145 valores únicos; `IdPeaje` tiene 145. Cada peaje tiene
una sola latitud, que nunca cambia. `Trafico` sí varía dentro del mismo
peaje: es una medida.

**Por qué es buena.** Es puramente estructural. No necesita saber qué es
una coordenada, y resuelve el caso general de "columna numérica que
describe la entidad en vez de medirla": precio de lista, año de
fundación, capacidad instalada.

---

## Decisión 8 — Priorizar análisis, no enumerarlos

**Problema.** Con `v_delitos` (1 numérica, 1 fecha) el agente generaba
11 archivos. Con `peajes_colombia` (6 numéricas, 2 fechas) generó **49
archivos y un informe de 83 KB**. La combinatoria explotó.

**Decisión.** El informe tiene un tope de análisis. Entran los más
informativos, medidos por la dispersión de la medida entre grupos: un
ranking donde todos los grupos valen casi lo mismo no dice nada. El
resto queda en CSV, fuera del informe.

Además: columnas de fecha que producen análisis casi idénticos
(`FechaDesde` y `FechaHasta`) se reducen a una, diciendo por qué. Y las
advertencias repetidas aparecen una sola vez.

**Resultado:** de 49 archivos a 10, y de 83 KB a 33 KB.

**Lección transferible.** Un agente genérico sin sentido de relevancia
produce volumen, no información. Enumerar lo posible es fácil; elegir lo
que importa es el trabajo real.

---

## Límites conocidos y aceptados

Están declarados en la sección 6 de cada informe. Los principales:

- **No sabe qué significa ninguna columna.** Por eso cada tabla trae
  `filas`, `suma` y `media`: cuál es la correcta depende del dominio.
- **No detecta fechas con día y mes intercambiados** cuando ambas
  lecturas son válidas. En `peajes_colombia`, el 92% de las fechas son
  ambiguas.
- **No detecta datos incorrectos, solo datos raros.** En
  `peajes_colombia` las columnas `Lat` y `Lon` están intercambiadas: la
  llamada `Lat` contiene longitudes. Verlo requiere saber dónde queda
  Colombia. El agente nunca lo encontrará.
- **No interpreta.** Describe lo calculado y no concluye por qué cambia
  una cifra.
- **La clasificación es heurística.** Se corrige con
  `--forzar columna.tipo=valor` o `--forzar columna.rol=valor`.

---

## Pendientes menores

- `src/agente.py` pesa 82 KB en un solo archivo. Funciona, pero conviene
  partirlo por responsabilidad antes de que crezca más.
- El mapa de calor dibuja la diagonal de +1,00 en color fuerte, y esa
  franja compite visualmente con las correlaciones reales. Ocultarla
  mejoraría la lectura.
- `requirements.txt` no se ha regenerado desde la Fase 0. Las librerías
  que usa el motor (pandas, duckdb, matplotlib, numpy) ya están, pero
  conviene actualizarlo antes de compartir el proyecto.

---

## Lo que no se decidió todavía

El motor está cerrado. Lo siguiente son opciones abiertas, no tareas
pendientes:

- Interfaz web para subir un CSV desde el navegador
- Publicarlo para terceros (requiere API de pago y alojamiento)
- Módulos de limpieza automática o de modelos de ML
