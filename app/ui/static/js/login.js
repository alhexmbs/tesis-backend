async (username, password) => {
  // Handler del botón "Iniciar sesión" (login.py). Gradio lo lee como string: debe ser una sola función.
  const error = (t) =>
    '<div class="msg msg-err"><div class="msg-titulo">⚠️ ' + t + "</div></div>";
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
};
