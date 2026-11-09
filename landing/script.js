/* ===================================================================
   DataAgente — comportamiento de la landing

   Por ahora el formulario solo valida y muestra un mensaje; no envía
   nada a ningún servidor. Ver README.md para conectarlo.
   =================================================================== */

(function () {
  "use strict";

  const formulario = document.getElementById("formulario-acceso");
  const campoCorreo = document.getElementById("correo");
  const mensaje = document.getElementById("mensaje");

  if (!formulario) return;

  /**
   * Valida un correo de forma razonable.
   *
   * No se usa una expresión regular exhaustiva a propósito: validar correos
   * con precisión es sorprendentemente difícil y rechazar direcciones
   * válidas molesta más que aceptar alguna inválida. El servidor (cuando
   * lo haya) es quien debe confirmarlo de verdad.
   */
  function correoValido(valor) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(valor.trim());
  }

  function mostrar(texto, tipo) {
    mensaje.textContent = texto;
    mensaje.className = "mensaje " + tipo;
  }

  formulario.addEventListener("submit", function (evento) {
    // Evita que el navegador recargue la página al enviar.
    evento.preventDefault();

    const correo = campoCorreo.value.trim();

    if (!correo) {
      mostrar("Escribe tu correo electrónico.", "error");
      campoCorreo.focus();
      return;
    }

    if (!correoValido(correo)) {
      mostrar("Ese correo no parece válido. Revísalo.", "error");
      campoCorreo.focus();
      return;
    }

    // Aquí iría el envío real. Mientras tanto, se registra en la consola
    // para poder comprobar que la validación funciona.
    console.log("Correo capturado:", correo);

    mostrar("Listo. Te avisaremos cuando haya novedades.", "exito");
    formulario.reset();
  });

  // Quita el mensaje de error en cuanto el usuario corrige el campo.
  campoCorreo.addEventListener("input", function () {
    if (mensaje.classList.contains("error")) {
      mostrar("", "");
    }
  });
})();
