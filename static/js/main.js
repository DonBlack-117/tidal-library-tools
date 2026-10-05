// Punto de entrada: conecta los botones (data-action) y carga el estado inicial.

import * as biblioteca from './biblioteca.js';
import * as descargar from './descargar.js';
import * as herramientas from './herramientas.js';
import * as operacion from './operacion.js';
import { $ } from './dom.js';

const ACTIONS = {
  'run-tool': (btn) => herramientas.runTool(btn.dataset.tool),
  'run-hires': () => herramientas.runHires(),
  'run-phone': () => herramientas.runPhoneSync(),
  'check-phone': () => biblioteca.checkPhone(),
  'load-playlists': () => descargar.loadPlaylists(),
  'pick-music-folder': () => herramientas.pickMusicFolder(),
  'pick-download-folder': () => herramientas.pickDownloadFolder(),
  'save-config': () => herramientas.saveConfig(),
  stop: () => operacion.stop(),
  exit: () => herramientas.exitApp(),
};

document.addEventListener('click', (event) => {
  const btn = event.target.closest('[data-action]');
  if (btn && ACTIONS[btn.dataset.action]) ACTIONS[btn.dataset.action](btn);
});

// La biblioteca y el teléfono pueden cambiar después de cada operación
operacion.onFinish(() => {
  biblioteca.loadLibraryStats();
  biblioteca.checkPhone();
});

herramientas.restoreConfig();
descargar.init();
// Si cambia la carpeta de la biblioteca, cambian las cifras
$('download-dir').addEventListener('change', () => {
  biblioteca.loadLibraryStats();
  biblioteca.checkPhone();
  descargar.loadMyTracksInfo();
});

biblioteca.checkTiddl();
biblioteca.checkHires();
biblioteca.checkPhone();
biblioteca.loadLibraryStats();
descargar.loadPlaylists();
descargar.loadMyTracksInfo();
