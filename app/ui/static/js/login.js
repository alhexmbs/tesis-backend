async (username, password) => {
  // Handler del botón "Iniciar sesión" (login.py). Gradio lo lee como string: debe ser una sola función.
  // Gradio lo envuelve como `await (<este archivo>)(...args)`: NO poner `;` al final,
  // o el navegador da SyntaxError y la página se queda en "Cargando…" para siempre.
  const error = (t) =>
    '<div class="msg msg-err"><div class="msg-titulo"><i class="bi bi-exclamation-triangle"></i> ' + t + "</div></div>";
  if (!username || !password) {
    return error("Ingresa usuario y contraseña.");
  }
  try {
    const body = new URLSearchParams({ username, password });
    const resp = await fetch("/inicio/login", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body,
    });
    if (resp.ok) {
      window.location.href = "/inicio";
      return "";
    }
    return error("Usuario o contraseña incorrectos.");
  } catch (e) {
    return error("No se pudo conectar con el servidor.");
  }
}
