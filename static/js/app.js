'use strict';

// ── State ─────────────────────────────────────────────────────────────────────
let activeReader   = null;   // ReadableStream reader
let currentScript  = null;   // 'sync' | 'quality' | 'dupes'
let stats          = {};     // counters extracted from log lines
let progress       = { done: 0, total: 0 };   // descargas: "Downloaded" frente a "N por descargar"
let existsDiv      = null;   // línea única que agrupa los "Exists …" de tiddl
let existsCount    = 0;
const BASE_TITLE   = document.title;

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

// ── Tool metadata ─────────────────────────────────────────────────────────────
// Un solo acento (#7CC6D6); los iconos comparten trazo de 1.8
const ICON_BG = 'bg-accent/10';
const icon = d => `<svg class="w-4 h-4 text-accent" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.8" aria-hidden="true">
             <path stroke-linecap="round" stroke-linejoin="round" d="${d}"/></svg>`;

const TOOLS = {
  sync: {
    title:  'Sincronizando música local con Tidal',
    iconBg: ICON_BG,
    icon:   icon('M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15'),
  },
  quality: {
    title:  'Cambiando por versiones de mayor calidad',
    iconBg: ICON_BG,
    icon:   icon('M9 19V6l12-3v13M9 19a3 2 0 11-6 0 3 2 0 016 0zm12-3a3 2 0 11-6 0 3 2 0 016 0zM9 10l12-3'),
  },
  dupes: {
    title:  'Quitando duplicados',
    iconBg: ICON_BG,
    icon:   icon('M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16'),
  },
  download: {
    title:  'Descargando de Tidal',
    iconBg: ICON_BG,
    icon:   icon('M12 4v11m0 0l-4.5-4.5M12 15l4.5-4.5M5 20h14'),
  },
  playlist: {
    title:  'Descargando playlist',
    iconBg: ICON_BG,
    icon:   icon('M4 6h11M4 12h11M4 18h7m9-9v8.5a2 2 0 11-2-2h2'),
  },
  hires: {
    title:  'Mejorando a Hi-Res',
    iconBg: ICON_BG,
    icon:   icon('M3 12h2l2-6 3 12 3-9 2 5 2-2h4'),
  },
  phone: {
    title:  'Enviando al teléfono',
    iconBg: ICON_BG,
    icon:   icon('M8 3h8a1.5 1.5 0 011.5 1.5v15A1.5 1.5 0 0116 21H8a1.5 1.5 0 01-1.5-1.5v-15A1.5 1.5 0 018 3zm3 15h2'),
  },
};

// ── Entry point ───────────────────────────────────────────────────────────────
async function runTool(toolName, btn) {
  if (activeReader) {
    // Already running — do nothing
    return;
  }

  currentScript = toolName;
  const meta    = TOOLS[toolName];
  const musicDir = document.getElementById('music-dir').value.trim();

  resetStats();
  askNotify();

  // ── Disable all run buttons
  document.querySelectorAll('.btn-run').forEach(b => b.disabled = true);

  // ── Show operation panel
  setupPanel(meta);

  // ── Session dot → loading
  setSession('loading', 'Conectando con Tidal...');

  // ── Fetch + stream
  let response;
  try {
    response = await fetch(`/run/${toolName}`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ music_dir: musicDir }),
    });
  } catch (e) {
    appendLog(`❌ No se pudo conectar con el servidor: ${e.message}`, 'error');
    finishOperation(false);
    return;
  }

  if (!response.ok) {
    appendLog(`❌ Error del servidor: ${response.status}`, 'error');
    finishOperation(false);
    return;
  }

  const reader  = response.body.getReader();
  const decoder = new TextDecoder();
  activeReader  = reader;

  document.getElementById('stop-btn').classList.remove('hidden');
  setProgressIndeterminate();

  // ── Read stream
  let buffer = '';
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop(); // keep incomplete chunk

      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith('data: ')) continue;
        try {
          const data = JSON.parse(line.slice(6));
          if (data.line !== undefined) {
            processLine(data.line);
          }
          if (data.done) {
            finishOperation(data.code === 0);
            return;
          }
        } catch (_) { /* ignore malformed JSON */ }
      }
    }
  } catch (e) {
    if (e.name !== 'AbortError') {
      appendLog(`⚠️  Conexión interrumpida: ${e.message}`, 'warn');
    }
  }

  finishOperation(false);
}

// ── Panel setup ───────────────────────────────────────────────────────────────
function setupPanel(meta) {
  const panel = document.getElementById('operation-panel');
  panel.classList.remove('hidden');

  document.getElementById('op-idle')?.classList.add('hidden');
  document.getElementById('op-active')?.classList.remove('hidden');
  document.getElementById('op-title').textContent    = meta.title;
  document.getElementById('op-icon').className       = `w-7 h-7 rounded-lg flex items-center justify-center ${meta.iconBg}`;
  document.getElementById('op-icon').innerHTML       = meta.icon;
  document.getElementById('log-output').innerHTML    = '';
  existsDiv = null;
  existsCount = 0;
  document.getElementById('summary').classList.add('hidden');
  document.getElementById('summary-content').innerHTML = '';

  if (window.innerWidth < 1024) {
    panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

// ── Line processing ───────────────────────────────────────────────────────────
function processLine(line) {
  if (!line) return;

  // Update session status based on line content
  if (line.includes('Conectando con Tidal') || line.includes('abrirá tu navegador')) {
    setSession('loading', 'Abriendo Tidal...');
  } else if (line.includes('Sesión iniciada')) {
    setSession('ok', 'Sesión activa');
  } else if (line.includes('RESUMEN FINAL')) {
    setSession('ok', 'Completado');
  }

  // Herramientas de la etapa 2 y de importación
  if (line.includes('➕') || line.includes('Agregada')) stats.added++;
  if (line.includes('❌ No encontrada'))                 stats.notFound++;
  if (line.includes('✅ Mejoradas'))                     tryExtract(line, 'improved');
  if (line.includes('✅ Total eliminados'))              tryExtract(line, 'removed');

  // Errores (sin contar los "no encontrada", que ya tienen su cifra)
  if (/^(Error|API Error|Can't stream)/.test(line) ||
      (line.includes('❌') && !line.includes('No encontrada')) ||
      (line.includes('⚠️') && line.includes('Error'))) stats.errors++;

  // Descargas, playlists, Hi-Res y teléfono: cifras que escriben core/*.py
  let m;
  if (/^(Downloaded|Overwrited) /.test(line)) { stats.downloaded++; progress.done++; showDownloadProgress(); }
  if ((m = line.match(/(\d+) por (descargar|copiar)/)))  { progress.total = +m[1]; progress.done = 0; showDownloadProgress(); }
  if ((m = line.match(/(\d+) ya descargad/)))              stats.already     = +m[1];
  if ((m = line.match(/(\d+) no disponibles/)))            stats.unavailable = +m[1];
  if ((m = line.match(/^📂 (\d+) canci/)))                 stats.newSongs    = +m[1];
  if ((m = line.match(/^↩ (\d+) descartada/)))             stats.discarded   = +m[1];
  if ((m = line.match(/Hi-Res: (\d+) mejorada/)))          stats.hires       = +m[1];
  if ((m = line.match(/Copiados (\d+)/)))                  stats.copied      = +m[1];
  if ((m = line.match(/^🗑 (\d+) borrada/)))               stats.phoneDeleted = +m[1];
  if ((m = line.match(/Lista con (\d+) canciones/)))       stats.inList      = +m[1];

  // Avance "n/total": mueve la barra y no se escribe en el log
  if ((m = line.match(/^\s*(\d+)\/(\d+)\s*$/))) { setProgressValue(+m[1], +m[2]); return; }

  // tiddl repite "Exists …" por cada archivo ya presente: se agrupa en una línea
  if (/^(Exists|Skipping) /.test(line)) { stats.skipped++; collapseExists(); return; }

  // Ruido sin valor para el usuario
  if (/^(Auth token expires|Loaded \d+ resources|Tracks: \d+$|Total downloads: )/.test(line)) return;

  appendLog(line);
}

function collapseExists() {
  existsCount++;
  if (!existsDiv) {
    existsDiv = document.createElement('div');
    existsDiv.className = 'log-line text-mute';
    document.getElementById('log-output').appendChild(existsDiv);
  }
  existsDiv.textContent = `· ${existsCount} ya estaban en disco (se omiten del registro)`;
}

function showDownloadProgress() {
  if (progress.total > 0) setProgressValue(Math.min(progress.done, progress.total), progress.total);
}

function tryExtract(line, key) {
  const m = line.match(/:?\s*(\d+)/);
  if (m) stats[key] = parseInt(m[1], 10);
}

// ── Append colored log line ───────────────────────────────────────────────────
function appendLog(line, forceType) {
  const el  = document.getElementById('log-output');
  const div = document.createElement('div');
  div.className = 'log-line ' + colorFor(line, forceType);
  div.textContent = line;
  el.appendChild(div);
  el.scrollTop = el.scrollHeight;
}

// Colores de estado desaturados: solo para ok / aviso / error
const C_OK = 'text-[#9FD6B4]', C_WARN = 'text-[#E3C38A]', C_ERR = 'text-[#E7A6A6]';

function colorFor(line, forceType) {
  if (forceType === 'error') return C_ERR;
  if (forceType === 'warn')  return C_WARN;

  if (line.includes('✅') || line.includes('➕') || line.includes('⬆') || line.includes('Sesión iniciada'))
    return C_OK;
  if (line.includes('❌') || line.includes('✗ Eliminar'))
    return C_ERR;
  if (line.includes('⚠') || line.includes('⚡'))
    return C_WARN;
  if (line.startsWith('==') || line.startsWith('--') || line.includes('RESUMEN'))
    return 'text-[#59616A]';
  if (line.match(/^\s*\[?\d+\/\d+\]?/) || line.includes('✓') || line.includes('Ya existe') || /^(Exists|Skipping) /.test(line))
    return 'text-mute';
  return 'text-soft';
}

// ── Progress bar helpers ──────────────────────────────────────────────────────
function setProgressIndeterminate() {
  const bar = document.getElementById('progress-bar');
  bar.className = 'h-full rounded-full progress-indeterminate';
  bar.style.width = '100%';
  document.getElementById('progress-status').textContent = 'En progreso...';
  document.getElementById('progress-pct').textContent    = '';
}

// Progreso real cuando el proceso informa "n/total"
function setProgressValue(done, total) {
  if (!total) return;
  const pct = Math.round((done / total) * 100);
  const bar = document.getElementById('progress-bar');
  bar.className   = 'h-full rounded-full bg-accent transition-[width] duration-300 ease-out';
  bar.style.width = `${pct}%`;
  document.getElementById('progress-status').textContent = `${done} de ${total}`;
  document.getElementById('progress-pct').textContent    = `${pct}%`;
  document.title = `${pct}% · ${BASE_TITLE}`;
}

function setProgressDone(success) {
  const bar = document.getElementById('progress-bar');
  bar.className = `h-full rounded-full transition-all duration-500 ${success ? 'bg-[#9FD6B4]' : 'bg-[#E7A6A6]'}`;
  bar.style.width = '100%';
  document.getElementById('progress-status').textContent = success ? 'Completado' : 'Finalizado con errores';
  document.getElementById('progress-pct').textContent = '';
  document.title = BASE_TITLE;
}

// ── Finish operation ──────────────────────────────────────────────────────────
function finishOperation(success) {
  activeReader  = null;
  currentScript = null;

  setProgressDone(success);
  document.getElementById('stop-btn').classList.add('hidden');

  // Re-enable buttons
  document.querySelectorAll('.btn-run').forEach(b => b.disabled = false);

  setSession(success ? 'ok' : 'error', success ? 'Completado' : 'Finalizado');

  const resumen = renderSummary(success);
  notifyDone(success, resumen);

  // La biblioteca y el teléfono pueden haber cambiado
  loadLibraryStats();
  checkPhone();
}

// Notificación del sistema si la pestaña no está a la vista
function notifyDone(success, resumen) {
  if (!('Notification' in window) || Notification.permission !== 'granted' || !document.hidden) return;
  const title = document.getElementById('op-title').textContent || 'Tidal Library Tools';
  try {
    new Notification(success ? title : `${title}: terminó con errores`, {
      body: resumen, icon: '/static/img/icontidal.png', tag: 'tidal-op',
    });
  } catch (_) {}
}

// ── Summary cards ─────────────────────────────────────────────────────────────
function renderSummary(success) {
  const container = document.getElementById('summary-content');
  container.innerHTML = '';

  const items = [];
  const add = (value, label, color) => { if (value > 0) items.push({ value, label, color }); };

  // Canciones nuevas: la cifra del aplanado es la real; si no la hay, las de tiddl
  const nuevas = stats.newSongs ?? stats.downloaded;

  add(nuevas,             'nuevas',                  'text-accent');
  add(stats.hires,        'a Hi-Res',                C_OK);
  add(stats.copied,       'copiadas al teléfono',    'text-accent');
  add(stats.inList,       'en la playlist',          'text-soft');
  add(stats.already ?? stats.skipped, 'ya estaban',  'text-soft');
  add(stats.discarded,    'repetidas descartadas',   'text-soft');
  add(stats.phoneDeleted, 'borradas en el teléfono', 'text-soft');
  add(stats.unavailable,  'no disponibles',          C_WARN);
  add(stats.added,        'agregadas',               C_OK);
  add(stats.improved,     'mejoradas',               C_OK);
  add(stats.removed,      'eliminadas',              C_WARN);
  add(stats.notFound,     'no encontradas',          C_ERR);
  add(stats.errors,       'errores',                 C_ERR);

  if (items.length === 0) {
    items.push({ label: success ? 'Sin cambios' : 'Proceso finalizado', value: '', color: 'text-soft' });
  }

  for (const item of items) {
    const chip = document.createElement('div');
    chip.className = 'flex items-baseline gap-2 px-3 py-2 rounded-lg bg-raised';
    chip.innerHTML = `
      <span class="text-base font-semibold tabular-nums ${item.color}">${item.value}</span>
      <span class="text-xs text-mute">${item.label}</span>
    `;
    container.appendChild(chip);
  }

  document.getElementById('summary').classList.remove('hidden');
  // Texto para la notificación: "12 nuevas · 3 a Hi-Res · 970 ya estaban"
  return items.map(i => `${i.value} ${i.label}`.trim()).join(' · ');
}

// ── Stop operation ────────────────────────────────────────────────────────────
async function stopOperation() {
  if (activeReader) {
    try { await activeReader.cancel(); } catch (_) {}
    activeReader = null;
  }
  appendLog('— Operación detenida por el usuario —', 'warn');
  finishOperation(false);
}

// ── Session badge ─────────────────────────────────────────────────────────────
function setSession(state, label) {
  const dot  = document.getElementById('session-dot');
  const text = document.getElementById('session-label');

  const map = {
    idle:    'bg-[#4A525A]',
    loading: 'bg-[#E3C38A] animate-pulse',
    ok:      'bg-[#9FD6B4]',
    error:   'bg-[#E7A6A6]',
  };

  dot.className  = `w-2 h-2 rounded-full transition-colors duration-500 ${map[state] || map.idle}`;
  text.textContent = label;
}

// ── Config persistence ────────────────────────────────────────────────────────
function saveConfig() {
  const val = document.getElementById('music-dir').value.trim();
  localStorage.setItem('tidal_music_dir', val);

  const btn = document.getElementById('save-btn');
  const original = btn.textContent;
  btn.textContent = 'Guardado';
  btn.classList.add('text-[#9FD6B4]');
  setTimeout(() => {
    btn.textContent = original;
    btn.classList.remove('text-[#9FD6B4]');
  }, 1500);
}

// ── Seleccionar carpeta ───────────────────────────────────────────────────────
// Llama al backend, que abre el diálogo nativo del SO (tkinter).
// Cuando el usuario elige una carpeta, el path se escribe en el input.
async function pickFolder() {
  const btn = document.getElementById('pick-btn');
  btn.disabled = true;
  btn.classList.add('text-accent');

  try {
    const res  = await fetch('/pick-folder', { method: 'POST' });
    const data = await res.json();
    if (data.path) {
      document.getElementById('music-dir').value = data.path;
      saveConfig();   // guarda automáticamente en localStorage
    }
  } catch (e) {
    console.error('Error al abrir selector de carpetas:', e);
  } finally {
    btn.disabled = false;
    btn.classList.remove('text-accent');
  }
}

// ── Salir ─────────────────────────────────────────────────────────────────────
// Detiene cualquier operación activa, le avisa al servidor que se cierre
// y muestra un mensaje de despedida en la página.
async function exitApp() {
  // Si hay un script corriendo, lo cancelamos primero
  if (activeReader) {
    try { await activeReader.cancel(); } catch (_) {}
    activeReader = null;
  }

  const btn = document.getElementById('exit-btn');
  btn.disabled = true;
  btn.textContent = 'Cerrando…';

  try {
    await fetch('/shutdown', { method: 'POST' });
  } catch (_) {
    // El servidor ya se cerró antes de devolver la respuesta — es normal
  }

  // Reemplaza la página con un mensaje de cierre limpio
  document.body.innerHTML = `
    <main class="min-h-[100dvh] bg-ink font-sans flex flex-col items-center justify-center gap-2 text-center px-6">
      <p class="font-mono text-xs text-mute">$ servidor detenido</p>
      <p class="text-lg font-semibold text-[#E7EBEE] tracking-[-0.015em]">Puedes cerrar esta pestaña.</p>
      <p class="text-[13px] text-mute">Para volver a abrirlo: <code class="font-mono">python app.py</code></p>
    </main>`;
}

// ── Descarga desde Tidal (tiddl) ──────────────────────────────────────────────
// Siempre en calidad máxima; metadatos, letras y carátula se configuran en
// ~/.tiddl/config.toml. El servidor envía el código de salida real de tiddl.
async function runDownload(btn) {
  if (activeReader) return;

  const url    = document.getElementById('tidal-url').value.trim();
  const outDir = document.getElementById('download-dir').value.trim();

  if (!url) {
    const input = document.getElementById('tidal-url');
    input.classList.add('border-red-500/50');
    setTimeout(() => input.classList.remove('border-red-500/50'), 1500);
    return;
  }

  await streamDownload('/run/download', { tidal_url: url, output_dir: outDir }, 'Descargando de Tidal');
}

// Un clic: todas las pistas favoritas (My Tracks). Sin carpeta → ~/Music/Tidal
async function runDownloadMyTracks(btn) {
  if (activeReader) return;

  const outDir = document.getElementById('download-dir').value.trim();
  await streamDownload('/run/download-mytracks', { output_dir: outDir }, 'Descargando My Tracks');
}

// Playlist elegida de la lista (propias y favoritas). Solo baja lo que falta y crea el .m3u8
async function runDownloadPlaylist(btn) {
  if (activeReader) return;

  const select = document.getElementById('playlist-select');
  if (!select.value) {
    select.classList.add('border-red-500/50');
    setTimeout(() => select.classList.remove('border-red-500/50'), 1500);
    return;
  }
  const outDir = document.getElementById('download-dir').value.trim();
  const name   = select.options[select.selectedIndex].dataset.name || select.value;
  await streamDownload('/run/download-playlist', { playlist: select.value, output_dir: outDir },
                       `Playlist: ${name}`, 'playlist');
}

async function runHires(btn) {
  if (activeReader) return;
  const outDir = document.getElementById('download-dir').value.trim();
  await streamDownload('/run/hires', { output_dir: outDir }, 'Mejorando a Hi-Res', 'hires');
}

async function runPhoneSync(btn) {
  if (activeReader) return;
  const outDir  = document.getElementById('download-dir').value.trim();
  const simular = document.getElementById('phone-simulate').checked;
  await streamDownload('/run/phone-sync', { output_dir: outDir, simular },
                       simular ? 'Teléfono (simulación)' : 'Enviando al teléfono', 'phone');
  checkPhone();
}

async function loadPlaylists() {
  const select = document.getElementById('playlist-select');
  if (!select) return;
  select.innerHTML = '<option value="">Cargando playlists…</option>';
  try {
    const res  = await fetch('/playlists');
    const data = await res.json();
    if (!data.ok) {
      select.innerHTML = `<option value="">${data.message}</option>`;
      return;
    }
    select.innerHTML = '<option value="">Elige una playlist…</option>';
    for (const p of data.playlists) {
      const opt = document.createElement('option');
      opt.value        = p.id;
      opt.dataset.name = p.name;
      opt.textContent  = `${p.name} (${p.tracks})`;
      select.appendChild(opt);
    }
  } catch (_) {
    select.innerHTML = '<option value="">No se pudieron cargar</option>';
  }
}

function setMiniStatus(id, ok, text, hint) {
  const el = document.getElementById(id);
  if (!el) return;
  el.innerHTML = `<span class="inline-block w-1.5 h-1.5 rounded-full mr-1.5 align-middle ${ok ? 'bg-[#9FD6B4]' : 'bg-[#E3C38A]'}"></span>`;
  el.append(text);
  el.title = hint || text;
  el.classList.toggle('text-soft', ok);
  el.classList.toggle('text-[#E3C38A]', !ok);
  el.classList.remove('text-mute');
}

async function checkHires() {
  try {
    const data = await (await fetch('/check-hires')).json();
    setMiniStatus('hires-status', data.ok, data.ok ? 'sesión activa' : 'sin sesión', data.message);
  } catch (_) {}
}

function libDir() {
  return encodeURIComponent(document.getElementById('download-dir')?.value.trim() || '');
}

async function checkPhone() {
  const cell = document.getElementById('lib-phone');
  try {
    const data = await (await fetch(`/check-phone?output_dir=${libDir()}`)).json();
    setMiniStatus('phone-status', data.ok, data.message, data.hint);
    if (!cell) return;
    if (!data.ok) {
      cell.textContent = 'sin conectar';
      cell.className = 'font-mono text-[15px] font-medium mt-0.5 text-mute';
    } else if (data.pending > 0) {
      cell.textContent = `${data.pending} por enviar`;
      cell.className = 'font-mono text-[15px] font-medium mt-0.5 text-[#E3C38A]';
    } else {
      cell.textContent = 'al día';
      cell.className = 'font-mono text-[15px] font-medium mt-0.5 text-[#9FD6B4]';
    }
  } catch (_) {}
}

async function loadLibraryStats() {
  try {
    const s = await (await fetch(`/library-stats?output_dir=${libDir()}`)).json();
    const nf = new Intl.NumberFormat('es-MX');
    const pct = s.canciones ? Math.round((s.hires / s.canciones) * 100) : 0;
    document.getElementById('lib-songs').textContent     = nf.format(s.canciones);
    document.getElementById('lib-hires').textContent     = `${nf.format(s.hires)} (${pct}%)`;
    document.getElementById('lib-lyrics').textContent    = nf.format(s.letras);
    document.getElementById('lib-playlists').textContent = nf.format(s.playlists.length);
    document.getElementById('lib-playlists').title       = s.playlists.join(', ');
    document.getElementById('lib-size').textContent      = `${s.gb} GB`;
  } catch (_) {}
}

async function streamDownload(endpoint, body, title, kind = 'download') {
  currentScript = 'download';
  resetStats();
  askNotify();

  document.querySelectorAll('.btn-run').forEach(b => b.disabled = true);
  setupPanel({ ...(TOOLS[kind] || TOOLS.download), title });
  setSession('loading', 'Iniciando descarga...');

  let response;
  try {
    response = await fetch(endpoint, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(body),
    });
  } catch (e) {
    appendLog(`❌ No se pudo conectar con el servidor: ${e.message}`, 'error');
    finishOperation(false);
    return;
  }

  if (!response.ok) {
    appendLog(`❌ Error del servidor: ${response.status}`, 'error');
    finishOperation(false);
    return;
  }

  const reader  = response.body.getReader();
  const decoder = new TextDecoder();
  activeReader  = reader;

  document.getElementById('stop-btn').classList.remove('hidden');
  setProgressIndeterminate();

  let buffer = '';
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop();

      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith('data: ')) continue;
        try {
          const data = JSON.parse(line.slice(6));
          if (data.line !== undefined) processLine(data.line);
          if (data.done) {
            if (data.code !== 0) appendLog(`❌ El proceso terminó con código ${data.code}`, 'error');
            finishOperation(data.code === 0);
            return;
          }
        } catch (_) {}
      }
    }
  } catch (e) {
    if (e.name !== 'AbortError') appendLog(`⚠️  Conexión interrumpida: ${e.message}`, 'warn');
  }

  finishOperation(false);
}

// ── Selector de carpeta para descarga ─────────────────────────────────────────
async function pickDownloadFolder() {
  try {
    const res  = await fetch('/pick-folder', { method: 'POST' });
    const data = await res.json();
    if (data.path) document.getElementById('download-dir').value = data.path;
  } catch (e) {
    console.error('Error al abrir selector de carpetas:', e);
  }
}

// ── Estado de autenticación de tiddl ──────────────────────────────────────────
async function checkTiddlStatus() {
  const badge = document.getElementById('tiddl-status');
  if (!badge) return;
  try {
    const res  = await fetch('/check-tiddl');
    const data = await res.json();
    const base = 'hidden sm:flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-md border border-line transition-opacity duration-500';
    if (data.ok) {
      badge.className = `${base} text-soft`;
      badge.innerHTML = '<span class="w-1.5 h-1.5 rounded-full bg-[#9FD6B4]"></span> tiddl conectado';
    } else {
      badge.className = `${base} text-[#E3C38A]`;
      badge.innerHTML = '<span class="w-1.5 h-1.5 rounded-full bg-[#E3C38A]"></span> falta tiddl auth login';
    }
  } catch (_) {}
}

// ── Init ──────────────────────────────────────────────────────────────────────
function isWindowsPath(p) {
  return /^[A-Za-z]:[\\\/]/.test(p);
}

document.addEventListener('DOMContentLoaded', () => {
  const saved = localStorage.getItem('tidal_music_dir');
  if (saved && !isWindowsPath(saved)) {
    document.getElementById('music-dir').value = saved;
  } else if (saved && isWindowsPath(saved)) {
    localStorage.removeItem('tidal_music_dir');
  }
  checkTiddlStatus();
  checkHires();
  checkPhone();
  loadPlaylists();
  loadLibraryStats();
  // Si cambia la carpeta de la biblioteca, las cifras también
  document.getElementById('download-dir')?.addEventListener('change', () => { loadLibraryStats(); checkPhone(); });
});
