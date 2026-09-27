// js_on_load del reloj de /inicio: Gradio lo corre con `element` = el gr.HTML que lo contiene.
function actualizarReloj() {
    const el = element.querySelector('#reloj-inicio');
    if (el) {
        el.textContent = new Date().toLocaleString('es-PE');
    }
}
actualizarReloj();
setInterval(actualizarReloj, 1000);
