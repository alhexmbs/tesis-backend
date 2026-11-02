// js_on_load del calendario (app/ui/calendario.py). Gradio lo corre con:
//   element = el gr.HTML del campo, props = sus datos (value, minimo, maximo),
//   watch   = avisa cuando Python cambia esos datos.
// Flatpickr (static/vendor/flatpickr) dibuja el calendario. El campo es de solo
// lectura: la fecha se elige con clics y los días fuera de [minimo, maximo] salen
// deshabilitados. Hacia Python viaja siempre "AAAA-MM-DD".

const es = {
  firstDayOfWeek: 1,
  weekdays: {
    shorthand: ["Do", "Lu", "Ma", "Mi", "Ju", "Vi", "Sá"],
    longhand: ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"],
  },
  months: {
    shorthand: ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"],
    longhand: [
      "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
      "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ],
  },
};

const input = element.querySelector(".campo-fecha-input");

const calendario = flatpickr(input, {
  locale: es,
  dateFormat: "Y-m-d", // lo que recibe Python
  altInput: true, // lo que ve el usuario: "29 de septiembre de 2026"
  altFormat: "j \\d\\e F \\d\\e Y",
  altInputClass: "campo-fecha-input",
  disableMobile: true,
  onChange: (_fechas, texto) => {
    // Asignar props.value dispara el evento .change del componente en Python.
    props.value = texto;
  },
});

// Copia al calendario lo que mandó Python: límites y fecha elegida.
function aplicar() {
  calendario.set("minDate", props.minimo || null);
  calendario.set("maxDate", props.maximo || null);
  calendario.setDate(props.value || null, false); // false: no vuelve a avisar
}

aplicar();
watch(["value", "minimo", "maximo"], aplicar);
