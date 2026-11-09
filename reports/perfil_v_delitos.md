# Perfil: v_delitos.csv

Fecha del perfilado: 2026-10-30

## Resumen general

| Métrica | Valor |
|---|---|
| Registros | 2.382.453 |
| Columnas | 10 |
| Tamaño | 344 MB |
| Casos totales (suma de `cantidad`) | 4.945.470 |
| Rango de fechas declarado | 2020-01-01 a 2026-12-02 |
| Duplicados exactos | 0 |

Cada fila es una combinación de tipo de delito, arma, lugar, género, rango de
edad y fecha, con una columna `cantidad` que cuenta los casos. **No es una fila
por caso**: hay que sumar `cantidad`, nunca contar filas.

## Columnas

| Columna | Valores distintos | Nulos |
|---|---|---|
| `tipo` | 18 | 0 |
| `delito` | 54 | 0 |
| `tipo_arma` | 56 | 0 |
| `departamento` | 32 | 0 |
| `municipio` | 1.029 | 1 |
| `cod_dane` | 1.111 | 0 |
| `genero` | 3 | 0 |
| `rango_edad` | 4 | 0 |
| `fecha` | — | 0 |
| `cantidad` | — | 0 |

## Problemas de calidad encontrados

### 1. Fechas corruptas en 2026 (grave)

Aproximadamente **42.000 casos de 2026 tienen el día y el mes intercambiados**,
y unos 7.900 quedan fechados en el futuro.

La evidencia:

| Año | Días con datos por mes |
|---|---|
| 2025 (control) | 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31 — completo |
| 2026, meses 3 al 12 | solo los días 1 y 2 |
| 2026, enero | días 1, 2 y 13 al 31 — faltan el 3 al 12 |
| 2026, febrero | días 1, 2 y 13 al 28 — faltan el 3 al 12 |

El patrón encaja exactamente con un intercambio día/mes en los registros donde
el día es menor o igual a 12. Un caso del 5 de enero (`2026-01-05`) quedó
guardado como `2026-05-01`, o sea el 1 de mayo. Por eso los días 3 al 12
desaparecieron de enero y febrero, y reaparecieron como los días 1 y 2 de los
meses 3 al 12.

**Conclusión:** el archivo cubre realmente desde el 1 de enero de 2020 hasta
finales de febrero de 2026. Los datos de 2026 no son usables hasta corregir
las fechas.

**Qué hacer:** analizar solo 2020-2025, que está íntegro, o corregir el
intercambio antes de tocar 2026.

### 2. Un municipio nulo

Un único registro tiene `municipio` vacío, con `cod_dane` = 52000 y
departamento Nariño. Los códigos DANE terminados en `000` corresponden al
departamento completo, no a un municipio. Es un registro agregado que se
coló entre los municipales. Afecta 1 caso de 4.945.470: se descarta.

### 3. Nombres de municipio repetidos entre departamentos

"La Unión", "Buenavista" y "Villanueva" existen en 4 departamentos distintos
cada uno; varios más se repiten en 3.

**Consecuencia:** agrupar por `municipio` suma municipios que no tienen nada
que ver entre sí. Hay que agrupar por `cod_dane`, que sí es único, o por la
pareja `departamento` + `municipio`.

Esto explica también por qué hay 1.111 códigos DANE pero solo 1.029 nombres
de municipio.

## Distribuciones principales

### Casos por año

| Año | Casos |
|---|---|
| 2020 | 655.220 |
| 2021 | 764.354 |
| 2022 | 866.659 |
| 2023 | 919.963 |
| 2024 | 834.143 |
| 2025 | 780.225 |
| 2026 (parcial y con fechas corruptas) | 124.906 |

2020 es el año más bajo de la serie: coincide con los confinamientos por
covid-19. Conviene tenerlo presente antes de leer el crecimiento 2020-2023
como una tendencia natural.

### Tipos de delito

| Tipo | Casos |
|---|---|
| Hurto personas | 1.888.830 |
| Violencia intrafamiliar | 778.914 |
| Lesiones personales | 576.004 |
| Amenazas | 344.548 |
| Lesiones en accidentes de tránsito | 261.935 |
| Hurto comercio | 239.370 |
| Hurto motocicletas | 214.172 |
| Hurto residencias | 190.796 |
| Delitos sexuales | 189.821 |
| Homicidios intencionales | 82.250 |
| Hurto vehículos | 61.778 |
| Extorsión | 57.568 |
| Homicidios en accidentes de tránsito | 43.076 |
| Hurto cabezas de ganado | 11.014 |
| Secuestro | 1.923 |
| Terrorismo | 1.884 |
| Hurto piratería terrestre | 1.039 |
| Hurto entidades financieras | 548 |

### Género y rango de edad

| Género | Casos |
|---|---|
| Masculino | 2.546.775 |
| Femenino | 2.145.008 |
| No reportado | 253.687 |

| Rango de edad | Casos |
|---|---|
| Adultos | 4.611.448 |
| No reportado | 142.014 |
| Adolescentes | 115.541 |
| Menores | 76.467 |

"No reportado" es una categoría real del dataset, no un nulo. Al calcular
proporciones por género o edad hay que decidir explícitamente si se incluye
o se excluye, y decirlo.

## Advertencia de interpretación

Estos son **delitos denunciados**, no delitos ocurridos. Un aumento puede
significar más delitos o más denuncias, y no hay forma de distinguirlo con
este archivo. Toda conclusión debe decir "denuncias registradas", no
"delitos cometidos".
