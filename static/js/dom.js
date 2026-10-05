// Utilidades de DOM compartidas por los módulos

export const $ = (id) => document.getElementById(id);

// Colores de estado desaturados: solo para ok / aviso / error
export const C_OK = 'text-[#9FD6B4]';
export const C_WARN = 'text-[#E3C38A]';
export const C_ERR = 'text-[#E7A6A6]';

export const nf = new Intl.NumberFormat('es-MX');

/** Punto de color + texto en las pastillas de estado (Hi-Res, teléfono). */
export function setMiniStatus(id, ok, text, hint) {
  const el = $(id);
  if (!el) return;
  el.innerHTML = `<span class="inline-block w-1.5 h-1.5 rounded-full mr-1.5 align-middle ${ok ? 'bg-[#9FD6B4]' : 'bg-[#E3C38A]'}"></span>`;
  el.append(text);
  el.title = hint || text;
  el.classList.toggle('text-soft', ok);
  el.classList.toggle('text-[#E3C38A]', !ok);
  el.classList.remove('text-mute');
}

/** Marca un campo en rojo un momento. */
export function flashError(el) {
  el.classList.add('border-red-500/50');
  setTimeout(() => el.classList.remove('border-red-500/50'), 1500);
}

/** Carpeta de la biblioteca elegida (vacío: ~/Music/Tidal en el servidor). */
export function libraryDir() {
  return $('download-dir')?.value.trim() || '';
}
