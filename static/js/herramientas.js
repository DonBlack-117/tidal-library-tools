// Hi-Res, teléfono, herramientas de My Tracks, carpetas y salir.

import { postJSON } from './api.js';
import { $, libraryDir } from './dom.js';
import * as operacion from './operacion.js';

const TOOL_TITLES = {
  sync: 'Sincronizando música local con Tidal',
  quality: 'Cambiando por versiones de mayor calidad',
  dupes: 'Quitando duplicados',
};

// Duplicados en dos clics: el primero solo muestra la lista; si hay copias, el
// botón pasa a «Eliminar N» y el segundo clic confirma.
let dupesPendientes = 0;

export function runTool(tool) {
  if (tool === 'dupes') return runDupes();
  return operacion.run(`/run/${tool}`, { music_dir: $('music-dir').value.trim() },
                       { title: TOOL_TITLES[tool], icon: tool });
}

async function runDupes() {
  const btn = document.querySelector('[data-tool="dupes"]');
  const confirmar = dupesPendientes > 0;
  dupesPendientes = 0;
  btn.textContent = 'Ejecutar';
  const body = { music_dir: $('music-dir').value.trim() };
  if (confirmar) body.confirmado = true;
  const ok = await operacion.run('/run/dupes', body, {
    title: confirmar ? TOOL_TITLES.dupes : 'Buscando duplicados (vista previa)',
    icon: 'dupes',
  });
  const n = operacion.lastStats().dupesPending || 0;
  if (!confirmar && ok && n > 0) {
    dupesPendientes = n;
    btn.textContent = `Eliminar ${n}`;
  }
}

export function runHires() {
  return operacion.run('/run/hires', { output_dir: libraryDir() }, { title: 'Mejorando a Hi-Res', icon: 'hires' });
}

export function runPhoneSync() {
  const simular = $('phone-simulate').checked;
  return operacion.run('/run/phone-sync', { output_dir: libraryDir(), simular },
                       { title: simular ? 'Teléfono (simulación)' : 'Enviando al teléfono', icon: 'phone' });
}

// ── Carpetas ──────────────────────────────────────────────────────────────────

async function pickFolder() {
  try {
    const res = await postJSON('/pick-folder');
    return (await res.json()).path || '';
  } catch (e) {
    console.error('No se pudo abrir el selector de carpetas:', e.message);
    return '';
  }
}

export async function pickMusicFolder() {
  const btn = $('pick-btn');
  btn.disabled = true;
  const path = await pickFolder();
  btn.disabled = false;
  if (path) {
    $('music-dir').value = path;
    saveConfig();
  }
}

export async function pickDownloadFolder() {
  const path = await pickFolder();
  if (path) {
    $('download-dir').value = path;
    $('download-dir').dispatchEvent(new Event('change'));
  }
}

export function saveConfig() {
  try { localStorage.setItem('tidal_music_dir', $('music-dir').value.trim()); } catch { return; }
  const btn = $('save-btn');
  btn.textContent = 'Guardado';
  btn.classList.add('text-[#9FD6B4]');
  setTimeout(() => {
    btn.textContent = 'Guardar';
    btn.classList.remove('text-[#9FD6B4]');
  }, 1500);
}

export function restoreConfig() {
  let saved = '';
  try { saved = localStorage.getItem('tidal_music_dir') || ''; } catch { return; }
  // Rutas de Windows de una versión vieja: no sirven en Linux
  if (/^[A-Za-z]:[\\/]/.test(saved)) {
    try { localStorage.removeItem('tidal_music_dir'); } catch { /* sin almacenamiento */ }
    return;
  }
  $('music-dir').value = saved;
}

// ── Salir ─────────────────────────────────────────────────────────────────────

export async function exitApp() {
  if (operacion.isRunning()) await operacion.stop();
  const btn = $('exit-btn');
  btn.disabled = true;
  btn.textContent = 'Cerrando…';
  try { await postJSON('/shutdown'); } catch { /* el servidor se cerró antes de responder: es normal */ }
  document.body.innerHTML = `
    <main class="min-h-[100dvh] bg-ink font-sans flex flex-col items-center justify-center gap-2 text-center px-6">
      <p class="font-mono text-xs text-mute">$ servidor detenido</p>
      <p class="text-lg font-semibold text-[#E7EBEE] tracking-[-0.015em]">Puedes cerrar esta pestaña.</p>
      <p class="text-[13px] text-mute">Para volver a abrirlo: <code class="font-mono">python app.py</code></p>
    </main>`;
}
