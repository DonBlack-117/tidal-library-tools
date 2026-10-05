// Descargar: pegar un link (canción, álbum, playlist, artista o mix), My Tracks
// con un clic y la lista de playlists de la cuenta.
//
// Flujo: el texto pegado va a /api/vista-previa, que dice qué es y cuántas
// canciones faltan; el botón de la vista previa lanza /run/descargar.

import { getJSON, postJSON } from './api.js';
import { $, flashError, libraryDir, nf } from './dom.js';
import * as canciones from './canciones.js';
import * as operacion from './operacion.js';

let current = null;   // { texto, preview } de la última vista previa

const plural = (n, uno, varios) => `${nf.format(n)} ${n === 1 ? uno : varios}`;

// ── Vista previa ──────────────────────────────────────────────────────────────

async function checkLink(texto) {
  const input = $('link-input');
  texto = (texto ?? input.value).trim();
  hideError();
  if (!texto) {
    flashError(input);
    showError('Pega un link de Tidal');
    return;
  }

  const btn = $('link-check');
  btn.disabled = true;
  btn.textContent = 'Revisando…';
  try {
    const res = await postJSON('/api/vista-previa', { texto, output_dir: libraryDir() });
    current = { texto, preview: await res.json() };
    renderPreview(current.preview);
  } catch (e) {
    hidePreview();
    showError(e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Revisar';
  }
}

function renderPreview(p) {
  $('preview-type').textContent = p.tipo_legible.charAt(0).toUpperCase() + p.tipo_legible.slice(1);
  $('preview-name').textContent = p.nombre;
  $('preview-detail').textContent = p.detalle;
  $('preview-pending').textContent = nf.format(p.por_descargar);
  $('preview-have').textContent = nf.format(p.ya_tienes);
  $('preview-unavailable').textContent = nf.format(p.no_disponibles);

  const sample = $('preview-sample');
  sample.innerHTML = '';
  for (const titulo of p.muestra) {
    const li = document.createElement('li');
    li.className = 'truncate';
    li.textContent = `· ${titulo}`;
    sample.appendChild(li);
  }
  if (p.por_descargar > p.muestra.length) {
    const li = document.createElement('li');
    li.className = 'text-mute';
    li.textContent = `y ${plural(p.por_descargar - p.muestra.length, 'más', 'más')}`;
    sample.appendChild(li);
  }

  // Artistas y mixes pueden ser cientos de canciones: se avisa antes
  const warning = $('preview-warning');
  warning.classList.toggle('hidden', !(p.requiere_confirmar && p.por_descargar > 0));
  if (p.tipo === 'artist') {
    warning.textContent = `Es la discografía completa de ${p.nombre}: ${plural(p.total, 'canción', 'canciones')}. Revisa que sea lo que quieres antes de descargar.`;
  } else if (p.tipo === 'mix') {
    warning.textContent = `Este mix lo arma Tidal y cambia con el tiempo: ${plural(p.total, 'canción', 'canciones')}.`;
  }

  // Para listas y álbumes se puede abrir la ventana y elegir canción por canción
  $('preview-choose').classList.toggle('hidden', p.tipo === 'track');

  const btn = $('preview-download');
  btn.disabled = false;
  if (p.por_descargar > 0) {
    const cuantas = plural(p.por_descargar, 'canción', 'canciones');
    btn.textContent = p.requiere_confirmar ? `Sí, descargar ${cuantas}` : `Descargar ${cuantas}`;
  } else if (p.crea_lista) {
    btn.textContent = 'Ya las tienes: actualizar la lista .m3u8';
  } else {
    btn.textContent = p.total ? 'Ya la tienes en tu biblioteca' : 'No hay canciones para descargar';
    btn.disabled = true;
  }

  $('preview').classList.remove('hidden');
}

function hidePreview() {
  current = null;
  $('preview').classList.add('hidden');
}

function showError(message) {
  const el = $('link-error');
  el.textContent = message;
  el.classList.remove('hidden');
}

function hideError() {
  $('link-error').classList.add('hidden');
}

async function downloadPreview() {
  if (!current) return;
  const { texto, preview } = current;
  const title = `${preview.tipo_legible.charAt(0).toUpperCase()}${preview.tipo_legible.slice(1)}: ${preview.nombre}`;
  const ok = await operacion.run('/run/descargar',
    { texto, output_dir: libraryDir(), confirmado: preview.requiere_confirmar },
    { title, icon: preview.crea_lista ? 'playlist' : 'download' });
  if (ok) {
    hidePreview();
    $('link-input').value = '';
  }
}

// ── My Tracks ─────────────────────────────────────────────────────────────────

export async function loadMyTracksInfo() {
  const info = $('mytracks-info');
  try {
    const res = await postJSON('/api/vista-previa', { mytracks: true, output_dir: libraryDir() });
    const p = await res.json();
    info.textContent = p.por_descargar > 0
      ? `${plural(p.total, 'favorito', 'favoritos')} · ${plural(p.por_descargar, 'nueva', 'nuevas')} por descargar · elige cuáles`
      : `${plural(p.total, 'favorito', 'favoritos')} · todo al día`;
  } catch (e) {
    info.textContent = e.code === 'SIN_SESION'
      ? 'Ver tus favoritos y elegir cuáles bajar'
      : `No se pudo consultar My Tracks: ${e.message}`;
  }
}

function openMyTracks() {
  return canciones.abrir({ mytracks: true }, 'My Tracks');
}

function chooseSongs() {
  if (current) canciones.abrir({ texto: current.texto }, current.preview.nombre);
}

// ── Playlists de la cuenta ────────────────────────────────────────────────────

export async function loadPlaylists() {
  const select = $('playlist-select');
  select.innerHTML = '<option value="">Cargando playlists…</option>';
  try {
    const { playlists } = await getJSON('/playlists');
    select.innerHTML = '<option value="">Elige una playlist…</option>';
    for (const p of playlists) {
      const opt = document.createElement('option');
      opt.value = p.id;
      opt.textContent = `${p.name} (${p.tracks})`;
      select.appendChild(opt);
    }
  } catch (e) {
    select.innerHTML = '';
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = e.code === 'SIN_SESION' ? 'Falta la sesión de Tidal' : 'No se pudieron cargar';
    select.appendChild(opt);
  }
}

// Elegir una playlist abre la ventana con sus canciones
function choosePlaylist(event) {
  const select = event.target;
  const id = select.value;
  if (!id) return;
  const nombre = select.options[select.selectedIndex].textContent.replace(/\s*\(\d+\)$/, '');
  select.value = '';
  canciones.abrir({ texto: `https://tidal.com/playlist/${id}` }, nombre);
}

// ── Pegar en cualquier parte ──────────────────────────────────────────────────

function isEditable(el) {
  return el && (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName));
}

function onGlobalPaste(event) {
  if (isEditable(event.target)) return;
  const texto = event.clipboardData?.getData('text') || '';
  if (!/tidal\.com|^\s*\d+\s*$|^\s*[0-9a-f-]{36}\s*$/i.test(texto)) return;
  event.preventDefault();
  const input = $('link-input');
  input.value = texto.trim();
  input.focus();
  checkLink(texto);
}

// ── Conexión con la página ────────────────────────────────────────────────────

export function init() {
  const input = $('link-input');
  $('link-form').addEventListener('submit', (e) => { e.preventDefault(); checkLink(); });
  // Al pegar en el campo se revisa sin tener que dar clic
  input.addEventListener('paste', () => setTimeout(() => checkLink(), 0));
  // Si cambia el texto, la vista previa ya no corresponde
  input.addEventListener('input', () => { hideError(); if (current && input.value.trim() !== current.texto) hidePreview(); });
  input.addEventListener('keydown', (e) => { if (e.key === 'Escape') hidePreview(); });
  $('preview-download').addEventListener('click', downloadPreview);
  $('preview-cancel').addEventListener('click', hidePreview);
  $('mytracks-btn').addEventListener('click', openMyTracks);
  $('preview-choose').addEventListener('click', chooseSongs);
  canciones.init();
  $('playlist-select').addEventListener('change', choosePlaylist);
  document.addEventListener('paste', onGlobalPaste);
  operacion.onFinish(() => loadMyTracksInfo());
}
