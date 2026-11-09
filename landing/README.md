# Landing de DataAgente

Página de presentación del agente de análisis de datos. HTML, CSS y
JavaScript puros, sin dependencias ni paso de compilación.

## Archivos

| Archivo | Contenido |
|---|---|
| `index.html` | Estructura y contenido |
| `estilos.css` | Todo el diseño, organizado en 9 secciones numeradas |
| `script.js` | Validación del formulario |

## Verla en el navegador

**Opción 1 — abrir el archivo.** Doble clic en `index.html`. Suficiente
para revisar el diseño.

**Opción 2 — servidor local (recomendado).** En la terminal de VS Code:

```powershell
cd landing
python -m http.server 8000
```

Y abre `http://localhost:8000`. Es más fiel a cómo se comportará en
producción.

**Opción 3 — extensión Live Server.** Instálala en VS Code, haz clic
derecho sobre `index.html` y elige "Open with Live Server". Recarga sola
al guardar, que es lo más cómodo mientras editas.

## Cómo está organizado el CSS

Las variables de color y medida están al inicio de `estilos.css`, en
`:root`. Cambiar el color de acento en toda la página es editar una línea:

```css
--acento: #5EEAD4;   /* cámbialo y se actualiza todo */
```

Las secciones están numeradas del 1 al 9 en comentarios, para que puedas
saltar directo a lo que buscas.

## Qué falta: conectar el formulario

Hoy `script.js` valida el correo y lo escribe en la consola del
navegador, pero no lo guarda en ningún lado. Para capturarlo de verdad
hay tres caminos, de menor a mayor esfuerzo:

### 1. Servicio de formularios (sin backend)

Servicios como Formspree o Basin dan una URL a la que enviar el formulario
y guardan las respuestas por ti. Se cambia el `<form>` en `index.html`:

```html
<form action="https://TU-ENDPOINT" method="POST">
```

y se quita el `preventDefault()` de `script.js`.

### 2. Backend propio

Un servidor pequeño en Python (FastAPI o Flask) que reciba el correo y lo
guarde en SQLite. Tiene sentido cuando el mismo servidor vaya a alojar el
motor del agente.

### 3. Hoja de cálculo

Google Apps Script puede exponer una hoja de cálculo como endpoint. Útil
si quieres ver los correos en una hoja sin montar nada.

Para las pruebas locales simulando empresas no hace falta ninguna: la
landing cumple su función de presentar el proyecto tal como está.

## Pendientes

- [ ] Nombre definitivo (hoy es "DataAgente", provisional)
- [ ] Correo de contacto real en el pie
- [ ] Conectar el formulario, si se necesita capturar correos
