function() {
    // Fuerza modo claro al cargar, sin importar el tema del sistema/navegador.
    // Gradio lee este archivo como string (js= no acepta rutas): debe ser una sola función.
    const url = new URL(window.location.href);
    if (url.searchParams.get('__theme') !== 'light') {
        url.searchParams.set('__theme', 'light');
        window.location.replace(url.href);
    }
}
