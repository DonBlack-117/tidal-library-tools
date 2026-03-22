'use strict';

// ── State ─────────────────────────────────────────────────────────────────────
let activeReader   = null;   // ReadableStream reader
let currentScript  = null;   // 'sync' | 'quality' | 'dupes'
let stats          = {};     // counters extracted from log lines

// ── Tool metadata ─────────────────────────────────────────────────────────────
const TOOLS = {
  sync: {
    title:    'Sincronizando música local → Tidal',
    color:    'text-accent',
    iconBg:   'bg-accent/10',
    icon: `<svg class="w-4 h-4 text-[#00D4FF]" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
             <path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
           </svg>`,
  },
  quality: {
    title:    'Mejorando calidad de audio',
    color:    'text-emerald-400',
    iconBg:   'bg-emerald-500/10',
    icon: `<svg class="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
             <path stroke-linecap="round" stroke-linejoin="round" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3"/>
           </svg>`,
  },
  dupes: {
    title:    'Limpiando duplicados',
    color:    'text-amber-400',
    iconBg:   'bg-amber-500/10',
    icon: `<svg class="w-4 h-4 text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
             <path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
           </svg>`,
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

  // Reset stats
  stats = { added: 0, notFound: 0, errors: 0, improved: 0, removed: 0 };

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

  document.getElementById('op-title').textContent    = meta.title;
  document.getElementById('op-icon').className       = `w-7 h-7 rounded-lg flex items-center justify-center ${meta.iconBg}`;
  document.getElementById('op-icon').innerHTML       = meta.icon;
  document.getElementById('log-output').innerHTML    = '';
  document.getElementById('summary').classList.add('hidden');
  document.getElementById('summary-content').innerHTML = '';

  panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
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

  // Count stats
  if (line.includes('➕') || line.includes('Agregada')) stats.added++;
  if (line.includes('❌ No encontrada'))                 stats.notFound++;
  if (line.includes('⚠️') && line.includes('Error'))    stats.errors++;
  if (line.includes('✅ Mejoradas'))                     tryExtract(line, 'improved');
  if (line.includes('✅ Total eliminados'))              tryExtract(line, 'removed');

  appendLog(line);
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

function colorFor(line, forceType) {
  if (forceType === 'error') return 'text-red-400';
  if (forceType === 'warn')  return 'text-amber-400';

  if (line.includes('✅') || line.includes('➕') || line.includes('Sesión iniciada'))
    return 'text-emerald-400';
  if (line.includes('❌') || line.includes('✗ Eliminar'))
    return 'text-red-400';
  if (line.includes('⚠️') || line.includes('⚡'))
    return 'text-amber-400';
  if (line.startsWith('==') || line.startsWith('--') || line.includes('RESUMEN'))
    return 'text-gray-600';
  if (line.match(/^\s*\[?\d+\/\d+\]?/))
    return 'text-gray-500';
  if (line.includes('✓') || line.includes('Ya existe'))
    return 'text-gray-500';
  return 'text-gray-300';
}

// ── Progress bar helpers ──────────────────────────────────────────────────────
function setProgressIndeterminate() {
  const bar = document.getElementById('progress-bar');
  bar.className = 'h-full rounded-full progress-indeterminate';
  bar.style.width = '100%';
  document.getElementById('progress-status').textContent = 'En progreso...';
  document.getElementById('progress-pct').textContent    = '';
}

function setProgressDone(success) {
  const bar = document.getElementById('progress-bar');
  bar.className = `h-full rounded-full transition-all duration-500 ${success ? 'bg-emerald-500' : 'bg-red-500'}`;
  bar.style.width = '100%';
  document.getElementById('progress-status').textContent = success ? 'Completado' : 'Finalizado con errores';
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

  renderSummary(success);
}

// ── Summary cards ─────────────────────────────────────────────────────────────
function renderSummary(success) {
  const container = document.getElementById('summary-content');
  container.innerHTML = '';

  const items = [];

  if (stats.added     > 0) items.push({ label: 'Agregadas',  value: stats.added,    color: 'text-emerald-400', bg: 'bg-emerald-500/10' });
  if (stats.notFound  > 0) items.push({ label: 'No encontradas', value: stats.notFound, color: 'text-red-400', bg: 'bg-red-500/10' });
  if (stats.improved  > 0) items.push({ label: 'Mejoradas',  value: stats.improved, color: 'text-emerald-400', bg: 'bg-emerald-500/10' });
  if (stats.removed   > 0) items.push({ label: 'Eliminadas', value: stats.removed,  color: 'text-amber-400',  bg: 'bg-amber-500/10' });
  if (stats.errors    > 0) items.push({ label: 'Errores',    value: stats.errors,   color: 'text-red-400',    bg: 'bg-red-500/10' });

  if (items.length === 0) {
    items.push({
      label: success ? 'Sin cambios' : 'Proceso finalizado',
      value: '',
      color: 'text-gray-400',
      bg: 'bg-gray-500/10',
    });
  }

  for (const item of items) {
    const chip = document.createElement('div');
    chip.className = `flex items-center gap-2 px-3 py-2 rounded-xl ${item.bg}`;
    chip.innerHTML = `
      <span class="text-lg font-bold ${item.color}">${item.value}</span>
      <span class="text-xs text-gray-500">${item.label}</span>
    `;
    container.appendChild(chip);
  }

  document.getElementById('summary').classList.remove('hidden');
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
    idle:    'bg-gray-600',
    loading: 'bg-amber-400 animate-pulse',
    ok:      'bg-emerald-400',
    error:   'bg-red-400',
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
  btn.textContent = '✓ Guardado';
  btn.classList.add('text-emerald-400');
  setTimeout(() => {
    btn.textContent = original;
    btn.classList.remove('text-emerald-400');
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
    <div class="min-h-screen bg-[#0D0D0D] flex flex-col items-center justify-center gap-4 text-gray-500">
      <svg class="w-10 h-10 text-gray-700" fill="currentColor" viewBox="0 0 24 24">
        <path d="M12 3v10.55A4 4 0 1014 17V7h4V3h-6z"/>
      </svg>
      <p class="text-sm">Servidor cerrado. Puedes cerrar esta pestaña.</p>
    </div>`;
}

// ── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  const saved = localStorage.getItem('tidal_music_dir');
  if (saved) document.getElementById('music-dir').value = saved;
});
