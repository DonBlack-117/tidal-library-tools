// Panel de operación: registro en vivo, barra de progreso y resumen.
// Solo corre una operación a la vez; el servidor también lo impide (409).

import { postJSON, readEvents } from './api.js';
import { $, C_ERR, C_OK, C_WARN } from './dom.js';

const BASE_TITLE = document.title;

let activeReader = null;   // ReadableStream reader de la operación en curso
let running = false;
let stats = {};            // cifras que se leen de las líneas del registro
let progress = { done: 0, total: 0 };
let existsDiv = null;      // línea única que agrupa los "Exists …" de tiddl
let existsCount = 0;
const listeners = [];      // se avisan al terminar (estado de la biblioteca, teléfono)

export const isRunning = () => running;
export const onFinish = (fn) => listeners.push(fn);

// ── Iconos ────────────────────────────────────────────────────────────────────
// Un solo acento (#7CC6D6); los iconos comparten trazo de 1.8
const icon = (d) => `<svg class="w-4 h-4 text-accent" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.8" aria-hidden="true">
             <path stroke-linecap="round" stroke-linejoin="round" d="${d}"/></svg>`;

export const ICONS = {
  sync: icon('M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15'),
  quality: icon('M9 19V6l12-3v13M9 19a3 2 0 11-6 0 3 2 0 016 0zm12-3a3 2 0 11-6 0 3 2 0 016 0zM9 10l12-3'),
  dupes: icon('M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16'),
  download: icon('M12 4v11m0 0l-4.5-4.5M12 15l4.5-4.5M5 20h14'),
  playlist: icon('M4 6h11M4 12h11M4 18h7m9-9v8.5a2 2 0 11-2-2h2'),
  hires: icon('M3 12h2l2-6 3 12 3-9 2 5 2-2h4'),
  phone: icon('M8 3h8a1.5 1.5 0 011.5 1.5v15A1.5 1.5 0 0116 21H8a1.5 1.5 0 01-1.5-1.5v-15A1.5 1.5 0 018 3zm3 15h2'),
};

// ── Lanzar una operación ──────────────────────────────────────────────────────

/**
 * POST a `endpoint` y muestra su salida SSE en el panel.
 * Devuelve true si terminó con código 0.
 */
export async function run(endpoint, body, { title, icon: kind = 'download' }) {
  if (running) return false;
  running = true;

  resetStats();
  askNotify();
  document.querySelectorAll('.btn-run').forEach((b) => { b.disabled = true; });
  setupPanel(title, ICONS[kind] || ICONS.download);
  setSession('loading', 'Trabajando…');

  let response;
  try {
    response = await postJSON(endpoint, body);
  } catch (e) {
    appendLog(`❌ ${e.message}`, 'error');
    return finish(false);
  }

  $('stop-btn').classList.remove('hidden');
  setProgressIndeterminate();

  let code = null;
  try {
    code = await readEvents(response, processLine, (reader) => { activeReader = reader; });
  } catch (e) {
    if (e.name !== 'AbortError') appendLog(`⚠️  Conexión interrumpida: ${e.message}`, 'warn');
  }
  if (code !== null && code !== 0) appendLog(`❌ El proceso terminó con código ${code}`, 'error');
  return finish(code === 0);
}

export async function stop() {
  appendLog('— Operación detenida por el usuario —', 'warn');
  if (activeReader) {
    try { await activeReader.cancel(); } catch { /* ya estaba cerrado */ }
  }
}

// ── Panel ─────────────────────────────────────────────────────────────────────

function setupPanel(title, iconHtml) {
  const panel = $('operation-panel');
  panel.classList.remove('hidden');
  $('op-idle')?.classList.add('hidden');
  $('op-active')?.classList.remove('hidden');
  $('op-title').textContent = title;
  $('op-icon').className = 'w-7 h-7 rounded-lg flex items-center justify-center bg-accent/10';
  $('op-icon').innerHTML = iconHtml;
  $('log-output').innerHTML = '';
  existsDiv = null;
  existsCount = 0;
  $('summary').classList.add('hidden');
  $('summary-content').innerHTML = '';
  if (window.innerWidth < 1024) panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function resetStats() {
  stats = { added: 0, notFound: 0, errors: 0, improved: 0, removed: 0, downloaded: 0, skipped: 0 };
  progress = { done: 0, total: 0 };
}

// Pide permiso de notificaciones la primera vez que se lanza algo (requiere un clic)
function askNotify() {
  if ('Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission().catch(() => {});
  }
}

// ── Líneas del registro ───────────────────────────────────────────────────────

export function processLine(line) {
  if (!line) return;

  if (line.includes('Conectando con Tidal')) setSession('loading', 'Conectando con Tidal…');
  else if (line.includes('Sesión iniciada')) setSession('ok', 'Sesión activa');
  else if (line.includes('RESUMEN FINAL')) setSession('ok', 'Completado');

  // Herramientas de My Tracks e importación
  if (line.includes('➕') || line.includes('Agregada')) stats.added++;
  if (line.includes('❌ No encontrada')) stats.notFound++;
  if (line.includes('✅ Mejoradas')) extract(line, 'improved');
  if (line.includes('✅ Total eliminados')) extract(line, 'removed');

  // Errores (sin contar los "no encontrada", que ya tienen su cifra)
  if (/^(Error|API Error|Can't stream)/.test(line)
      || (line.includes('❌') && !line.includes('No encontrada'))
      || (line.includes('⚠️') && line.includes('Error'))) stats.errors++;

  // Descargas, Hi-Res y teléfono: cifras que escriben core/*.py
  let m;
  if (/^(Downloaded|Overwrited) /.test(line)) { stats.downloaded++; progress.done++; showDownloadProgress(); }
  if ((m = line.match(/(\d+) por (descargar|copiar)/))) { progress.total = +m[1]; progress.done = 0; showDownloadProgress(); }
  if ((m = line.match(/(\d+) ya descargad/))) stats.already = +m[1];
  if ((m = line.match(/(\d+) no disponibles/))) stats.unavailable = +m[1];
  if ((m = line.match(/^📂 (\d+) canci/))) stats.newSongs = +m[1];
  if ((m = line.match(/^↩ (\d+) descartada/))) stats.discarded = +m[1];
  if ((m = line.match(/Hi-Res: (\d+) mejorada/))) stats.hires = +m[1];
  if ((m = line.match(/Copiados (\d+)/))) stats.copied = +m[1];
  if ((m = line.match(/^🗑 (\d+) borrada/))) stats.phoneDeleted = +m[1];
  if ((m = line.match(/Lista con (\d+) canciones/))) stats.inList = +m[1];

  // Avance "n/total": mueve la barra y no se escribe en el registro
  if ((m = line.match(/^\s*(\d+)\/(\d+)\s*$/))) { setProgressValue(+m[1], +m[2]); return; }

  // tiddl repite "Exists …" por cada archivo ya presente: se agrupa en una línea
  if (/^(Exists|Skipping) /.test(line)) { stats.skipped++; collapseExists(); return; }

  // Ruido sin valor para el usuario
  if (/^(Auth token expires|Loaded \d+ resources|Tracks: \d+$|Total downloads: )/.test(line)) return;

  appendLog(line);
}

function extract(line, key) {
  const m = line.match(/:?\s*(\d+)/);
  if (m) stats[key] = parseInt(m[1], 10);
}

function collapseExists() {
  existsCount++;
  if (!existsDiv) {
    existsDiv = document.createElement('div');
    existsDiv.className = 'log-line text-mute';
    $('log-output').appendChild(existsDiv);
  }
  existsDiv.textContent = `· ${existsCount} ya estaban en disco (se omiten del registro)`;
}

function appendLog(line, forceType) {
  const el = $('log-output');
  const div = document.createElement('div');
  div.className = `log-line ${colorFor(line, forceType)}`;
  div.textContent = line;
  el.appendChild(div);
  el.scrollTop = el.scrollHeight;
}

function colorFor(line, forceType) {
  if (forceType === 'error') return C_ERR;
  if (forceType === 'warn') return C_WARN;
  if (line.includes('✅') || line.includes('➕') || line.includes('⬆') || line.includes('Sesión iniciada')) return C_OK;
  if (line.includes('❌') || line.includes('✗ Eliminar')) return C_ERR;
  if (line.includes('⚠') || line.includes('⚡')) return C_WARN;
  if (line.startsWith('==') || line.startsWith('--') || line.includes('RESUMEN')) return 'text-[#59616A]';
  if (/^\s*\[?\d+\/\d+\]?/.test(line) || line.includes('✓') || line.includes('Ya existe')) return 'text-mute';
  return 'text-soft';
}

// ── Progreso ──────────────────────────────────────────────────────────────────

function showDownloadProgress() {
  if (progress.total > 0) setProgressValue(Math.min(progress.done, progress.total), progress.total);
}

function setProgressIndeterminate() {
  const bar = $('progress-bar');
  bar.className = 'h-full rounded-full progress-indeterminate';
  bar.style.width = '100%';
  $('progress-status').textContent = 'En progreso…';
  $('progress-pct').textContent = '';
}

// Progreso real cuando el proceso informa "n/total"
function setProgressValue(done, total) {
  if (!total) return;
  const pct = Math.round((done / total) * 100);
  const bar = $('progress-bar');
  bar.className = 'h-full rounded-full bg-accent transition-[width] duration-300 ease-out';
  bar.style.width = `${pct}%`;
  $('progress-status').textContent = `${done} de ${total}`;
  $('progress-pct').textContent = `${pct}%`;
  document.title = `${pct}% · ${BASE_TITLE}`;
}

function setProgressDone(success) {
  const bar = $('progress-bar');
  bar.className = `h-full rounded-full transition-all duration-500 ${success ? 'bg-[#9FD6B4]' : 'bg-[#E7A6A6]'}`;
  bar.style.width = '100%';
  $('progress-status').textContent = success ? 'Completado' : 'Finalizado con errores';
  $('progress-pct').textContent = '';
  document.title = BASE_TITLE;
}

// ── Fin ───────────────────────────────────────────────────────────────────────

function finish(success) {
  activeReader = null;
  running = false;
  setProgressDone(success);
  $('stop-btn').classList.add('hidden');
  document.querySelectorAll('.btn-run').forEach((b) => { b.disabled = false; });
  setSession(success ? 'ok' : 'error', success ? 'Completado' : 'Finalizado');
  notifyDone(success, renderSummary(success));
  listeners.forEach((fn) => fn(success));
  return success;
}

// Notificación del sistema si la pestaña no está a la vista
function notifyDone(success, resumen) {
  if (!('Notification' in window) || Notification.permission !== 'granted' || !document.hidden) return;
  const title = $('op-title').textContent || 'Tidal Library Tools';
  try {
    new Notification(success ? title : `${title}: terminó con errores`, {
      body: resumen, icon: '/static/img/icontidal.png', tag: 'tidal-op',
    });
  } catch { /* el navegador puede negarse aunque haya permiso */ }
}

function renderSummary(success) {
  const container = $('summary-content');
  container.innerHTML = '';

  const items = [];
  const add = (value, label, color) => { if (value > 0) items.push({ value, label, color }); };

  // Canciones nuevas: la cifra del aplanado es la real; si no la hay, las de tiddl
  add(stats.newSongs ?? stats.downloaded, 'nuevas', 'text-accent');
  add(stats.hires, 'a Hi-Res', C_OK);
  add(stats.copied, 'copiadas al teléfono', 'text-accent');
  add(stats.inList, 'en la playlist', 'text-soft');
  add(stats.already ?? stats.skipped, 'ya estaban', 'text-soft');
  add(stats.discarded, 'repetidas descartadas', 'text-soft');
  add(stats.phoneDeleted, 'borradas en el teléfono', 'text-soft');
  add(stats.unavailable, 'no disponibles', C_WARN);
  add(stats.added, 'agregadas', C_OK);
  add(stats.improved, 'mejoradas', C_OK);
  add(stats.removed, 'eliminadas', C_WARN);
  add(stats.notFound, 'no encontradas', C_ERR);
  add(stats.errors, 'errores', C_ERR);

  if (items.length === 0) {
    items.push({ label: success ? 'Sin cambios' : 'Proceso finalizado', value: '', color: 'text-soft' });
  }

  for (const item of items) {
    const chip = document.createElement('div');
    chip.className = 'flex items-baseline gap-2 px-3 py-2 rounded-lg bg-raised';
    const value = document.createElement('span');
    value.className = `text-base font-semibold tabular-nums ${item.color}`;
    value.textContent = item.value;
    const label = document.createElement('span');
    label.className = 'text-xs text-mute';
    label.textContent = item.label;
    chip.append(value, label);
    container.appendChild(chip);
  }

  $('summary').classList.remove('hidden');
  // Texto para la notificación: "12 nuevas · 3 a Hi-Res · 970 ya estaban"
  return items.map((i) => `${i.value} ${i.label}`.trim()).join(' · ');
}

// ── Indicador de sesión de la barra superior ─────────────────────────────────

export function setSession(state, label) {
  const map = {
    idle: 'bg-[#4A525A]',
    loading: 'bg-[#E3C38A] animate-pulse',
    ok: 'bg-[#9FD6B4]',
    error: 'bg-[#E7A6A6]',
  };
  $('session-dot').className = `w-2 h-2 rounded-full transition-colors duration-500 ${map[state] || map.idle}`;
  $('session-label').textContent = label;
}
