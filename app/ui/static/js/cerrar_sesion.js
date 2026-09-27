// js_on_load del botón "Cerrar sesión" de /inicio: Gradio lo corre con `element` = el gr.HTML que lo contiene.
const link = element.querySelector('#cerrar-sesion');
if (link) {
    link.addEventListener('click', function (e) {
        e.preventDefault();
        fetch('/inicio/logout').finally(function () {
            window.location.href = '/login';
        });
    });
}
