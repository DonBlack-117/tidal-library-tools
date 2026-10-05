// Ventana con todas las canciones de My Tracks, una playlist, un álbum…
// Cada una tiene su casilla; arriba "Descargar todo" y "Descargar seleccionadas".

import { postJSON } from './api.js';
import { $, libraryDir, nf } from './dom.js';
import * as operacion from './operacion.js';

let fuente = null;    // { texto } o { mytracks: true }: lo que se pide al servidor
let datos = null;     // respuesta de /api/canciones
const elegidas = new Set();

const ESTADOS = {
  tienes: { texto: 'en disco', clase: 'text-[#9FD6B4]' },
  no_disponible: { texto: 'no disponible', clase: 'text-[#E3C38A]' },
};

const plural = (n, uno, varios) => `${nf.format(n)} ${n === 1 ? uno : varios}`;
const normalizar = (t) => t.normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase();

function duracion(segundos) {
  if (!segundos) return '';
  return `${Math.floor(segundos / 60)}:${String(segundos % 60).padStart(2, '0')}`;
}

// ── Abrir y cargar ────────────────────────────────────────────────────────────

/** Abre la ventana para `origen`: { mytracks: true } o { texto: '<link>' }. */
export async function abrir(origen, titulo = '') {
  fuente = origen;
  datos = null;
  elegidas.clear();
  $('songs-type').textContent = '';
  $('songs-title').textContent = titulo || 'Cargando…';
  $('songs-detail').textContent = '';
  $('songs-search').value = '';
  $('songs-toggle').checked = false;
  $('songs-counts').textContent = 'Cargando canciones de Tidal…';
  $('songs-list').innerHTML = '';
  $('songs-all').disabled = true;
  actualizarBotones();

  const dialog = $('songs-dialog');
  if (!dialog.open) dialog.showModal();

  try {
    const res = await postJSON('/api/canciones', { ...origen, output_dir: libraryDir() });
    datos = await res.json();
  } catch (e) {
    $('songs-counts').textContent = '';
    $('songs-title').textContent = 'No se pudo cargar';
    $('songs-detail').textContent = e.message;
    return;
  }
  if (fuente !== origen) return;  // se abrió otra lista mientras cargaba
  pintar();
}

function pintar() {
  const tipo = datos.tipo_legible;
  // En My Tracks el tipo y el nombre son lo mismo: no se repite
  $('songs-type').textContent = datos.tipo === 'mytracks' ? '' : tipo.charAt(0).toUpperCase() + tipo.slice(1);
  $('songs-title').textContent = datos.nombre;
  $('songs-detail').textContent = datos.detalle;

  const lista = $('songs-list');
  const fragmento = document.createDocumentFragment();
  for (const c of datos.canciones) fragmento.appendChild(fila(c));
  lista.replaceChildren(fragmento);

  const todo = $('songs-all');
  if (datos.por_descargar > 0) {
    todo.textContent = `Descargar todo (${plural(datos.por_descargar, 'falta', 'faltan')})`;
    todo.disabled = false;
  } else if (datos.crea_lista) {
    todo.textContent = 'Ya las tienes: actualizar la lista .m3u8';
    todo.disabled = false;
  } else {
    todo.textContent = 'Ya las tienes todas';
    todo.disabled = true;
  }
  contar();
}

function fila(c) {
  const li = document.createElement('li');
  li.dataset.busqueda = normalizar(`${c.titulo} ${c.artista}`);

  const label = document.createElement('label');
  label.className = 'flex items-center gap-3 px-5 py-2 hover:bg-raised/60 '
    + (c.estado === 'falta' ? 'cursor-pointer' : 'opacity-60');

  const casilla = document.createElement('input');
  casilla.type = 'checkbox';
  casilla.value = c.id;
  casilla.className = 'accent-[#7CC6D6] w-4 h-4 shrink-0';
  casilla.disabled = c.estado !== 'falta';
  casilla.checked = elegidas.has(c.id);
  casilla.setAttribute('aria-label', `${c.titulo} de ${c.artista}`);
  casilla.addEventListener('change', () => {
    if (casilla.checked) elegidas.add(c.id); else elegidas.delete(c.id);
    actualizarBotones();
  });

  const texto = document.createElement('span');
  texto.className = 'flex-1 min-w-0';
  const titulo = document.createElement('span');
  titulo.className = 'block text-[13px] truncate';
  titulo.textContent = c.titulo;
  const artista = document.createElement('span');
  artista.className = 'block text-xs text-mute truncate';
  artista.textContent = c.artista;
  texto.append(titulo, artista);

  label.append(casilla, texto);
  if (ESTADOS[c.estado]) {
    const estado = document.createElement('span');
    estado.className = `text-[11px] shrink-0 ${ESTADOS[c.estado].clase}`;
    estado.textContent = ESTADOS[c.estado].texto;
    label.appendChild(estado);
  }
  const dur = document.createElement('span');
  dur.className = 'font-mono text-[11px] text-mute tabular-nums w-10 text-right shrink-0';
  dur.textContent = duracion(c.duracion);
  label.appendChild(dur);

  li.appendChild(label);
  return li;
}

// ── Selección y búsqueda ──────────────────────────────────────────────────────

function filasVisibles() {
  return [...$('songs-list').children].filter((li) => !li.hidden);
}

function buscar() {
  const q = normalizar($('songs-search').value.trim());
  for (const li of $('songs-list').children) li.hidden = q !== '' && !li.dataset.busqueda.includes(q);
  $('songs-toggle').checked = false;
  contar();
}

// Marca o desmarca las que faltan entre las visibles (respeta la búsqueda)
function alternar() {
  const marcar = $('songs-toggle').checked;
  for (const li of filasVisibles()) {
    const casilla = li.querySelector('input');
    if (casilla.disabled) continue;
    casilla.checked = marcar;
    if (marcar) elegidas.add(Number(casilla.value)); else elegidas.delete(Number(casilla.value));
  }
  actualizarBotones();
}

function actualizarBotones() {
  const btn = $('songs-selected');
  btn.textContent = `Descargar seleccionadas (${nf.format(elegidas.size)})`;
  btn.disabled = elegidas.size === 0;
}

function contar() {
  if (!datos) return;
  const visibles = filasVisibles().length;
  const filtro = visibles < datos.canciones.length ? ` · ${nf.format(visibles)} con la búsqueda` : '';
  $('songs-counts').textContent = `${plural(datos.total, 'canción', 'canciones')} · `
    + `${plural(datos.por_descargar, 'falta', 'faltan')} · ${nf.format(datos.ya_tienes)} en disco`
    + (datos.no_disponibles ? ` · ${plural(datos.no_disponibles, 'no disponible', 'no disponibles')}` : '')
    + filtro;
}

// ── Descargar ─────────────────────────────────────────────────────────────────

function titulo() {
  const tipo = datos.tipo_legible;
  return datos.tipo === 'mytracks' ? 'Descargando My Tracks' : `${tipo.charAt(0).toUpperCase()}${tipo.slice(1)}: ${datos.nombre}`;
}

function descargar(extra) {
  const cuerpo = { ...fuente, output_dir: libraryDir(), ...extra };
  const opciones = { title: titulo(), icon: datos.crea_lista ? 'playlist' : 'download' };
  $('songs-dialog').close();
  return operacion.run('/run/descargar', cuerpo, opciones);
}

export function init() {
  $('songs-close').addEventListener('click', () => $('songs-dialog').close());
  // Clic en el fondo oscuro: cierra
  $('songs-dialog').addEventListener('click', (e) => { if (e.target === e.currentTarget) e.currentTarget.close(); });
  $('songs-search').addEventListener('input', buscar);
  $('songs-toggle').addEventListener('change', alternar);
  // "Todo" pasa la confirmación de artistas y mixes: el usuario ya vio la lista completa
  $('songs-all').addEventListener('click', () => descargar({ confirmado: true }));
  $('songs-selected').addEventListener('click', () => descargar({ ids: [...elegidas] }));
}
