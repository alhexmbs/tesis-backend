// js_on_load del encabezado de /inicio: Gradio lo corre con `element` = el gr.HTML que lo contiene.

// Fecha de hoy, una sola vez (sin reloj que cambie cada segundo).
const hoy = element.querySelector("#fecha-hoy");
if (hoy) {
  hoy.textContent = new Date().toLocaleDateString("es-PE", { dateStyle: "full" });
}

// "Cerrar sesión": borra la cookie de Gradio y vuelve al login.
const link = element.querySelector("#cerrar-sesion");
if (link) {
  link.addEventListener("click", function (e) {
    e.preventDefault();
    fetch("/inicio/logout").finally(function () {
      window.location.href = "/login";
    });
  });
}
