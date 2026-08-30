import gradio as gr

LOGIN_JS = """
async (username, password) => {
    if (!username || !password) {
        return "❌ Ingresa usuario y contraseña.";
    }
    try {
        const body = new URLSearchParams({ username, password });
        const resp = await fetch('/inicio/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body,
        });
        if (resp.ok) {
            window.location.href = '/inicio';
            return '';
        }
        return '❌ Usuario o contraseña incorrectos.';
    } catch (e) {
        return '❌ No se pudo conectar con el servidor.';
    }
}
"""

with gr.Blocks(title="Iniciar sesión") as demo:
    gr.Markdown("## Iniciar sesión")

    username = gr.Textbox(label="Usuario")
    password = gr.Textbox(label="Contraseña", type="password")
    login_error = gr.Markdown()

    boton = gr.Button("Iniciar sesión", variant="primary")

    gr.Markdown("¿No tienes cuenta? [Regístrate aquí](/registro)")

    boton.click(
        fn=None,
        inputs=[username, password],
        outputs=login_error,
        js=LOGIN_JS,
    )
