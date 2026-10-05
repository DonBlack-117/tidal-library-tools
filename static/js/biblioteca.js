// Estado de la biblioteca, del teléfono y de las sesiones (barra y pastillas).

import { getJSON } from './api.js';
import { $, libraryDir, nf, setMiniStatus } from './dom.js';

const dirParam = () => encodeURIComponent(libraryDir());

export async function loadLibraryStats() {
  try {
    const s = await getJSON(`/library-stats?output_dir=${dirParam()}`);
    const pct = s.canciones ? Math.round((s.hires / s.canciones) * 100) : 0;
    $('lib-songs').textContent = nf.format(s.canciones);
    $('lib-hires').textContent = `${nf.format(s.hires)} (${pct}%)`;
    $('lib-lyrics').textContent = nf.format(s.letras);
    $('lib-playlists').textContent = nf.format(s.playlists.length);
    $('lib-playlists').title = s.playlists.join(', ');
    $('lib-size').textContent = `${s.gb} GB`;
  } catch { /* la franja se queda con guiones */ }
}

export async function checkPhone() {
  const cell = $('lib-phone');
  try {
    const data = await getJSON(`/check-phone?output_dir=${dirParam()}`);
    setMiniStatus('phone-status', data.ok, data.message, data.hint);
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
  } catch { /* sin servidor: se queda como estaba */ }
}

export async function checkHires() {
  try {
    const data = await getJSON('/check-hires');
    setMiniStatus('hires-status', data.ok, data.ok ? 'sesión activa' : 'sin sesión', data.message);
  } catch { /* sin servidor */ }
}

export async function checkTiddl() {
  const badge = $('tiddl-status');
  try {
    const data = await getJSON('/check-tiddl');
    const base = 'hidden sm:flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-md border border-line transition-opacity duration-500';
    badge.className = `${base} ${data.ok ? 'text-soft' : 'text-[#E3C38A]'}`;
    badge.innerHTML = data.ok
      ? '<span class="w-1.5 h-1.5 rounded-full bg-[#9FD6B4]"></span> tiddl conectado'
      : '<span class="w-1.5 h-1.5 rounded-full bg-[#E3C38A]"></span> falta tiddl auth login';
  } catch { /* sin servidor */ }
}
