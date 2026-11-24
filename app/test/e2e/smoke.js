'use strict';
// End-to-end smoke test: runs the real main process and renderer. Only the native
// file dialogs are replaced by fixed paths. Run it with Electron, not Node:
//
//   DGM_E2E_TILE=/path/dgm_x.tif DGM_E2E_OUT=/empty/folder \
//   DGM_ENGINE_EXE=/path/to/dgm-engine npx electron test/e2e/smoke.js
//
// Exit code 0 when every check passes.
const { app, dialog, BrowserWindow } = require('electron');
const fs = require('fs');
const path = require('path');

const TILE = process.env.DGM_E2E_TILE;
const OUT = process.env.DGM_E2E_OUT;
const results = [];
const check = (name, ok, detail = '') => {
  results.push({ name, ok });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? `  (${detail})` : ''}`);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitFor(fn, timeoutMs, label) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    try {
      const v = await fn();
      if (v) return v;
    } catch (_e) { /* retry */ }
    await sleep(200);
  }
  throw new Error(`timeout waiting for ${label}`);
}

if (!TILE || !OUT) {
  console.error('Set DGM_E2E_TILE and DGM_E2E_OUT.');
  app.exit(2);
} else {
  dialog.showOpenDialog = async (_win, opts) => {
    if ((opts.properties || []).includes('multiSelections')) return { canceled: false, filePaths: [TILE] };
    if ((opts.properties || []).includes('openDirectory') && /output/i.test(opts.title || '')) {
      return { canceled: false, filePaths: [OUT] };
    }
    return { canceled: true, filePaths: [] };
  };
  require('../../src/main/main.js');

  app.whenReady().then(async () => {
    let code = 0;
    try {
      const win = await waitFor(() => BrowserWindow.getAllWindows()[0], 15000, 'window');
      const wc = win.webContents;
      await waitFor(() => wc.executeJavaScript('document.readyState === "complete" && !!window.dgm'), 15000, 'renderer');

      const js = (c) => wc.executeJavaScript(c);
      const text = (id) => js(`document.getElementById('${id}').textContent`);

      // Security: the renderer must not expose Node or Electron internals.
      const exposure = await js(`JSON.stringify({ req: typeof require, proc: typeof process, dgm: Object.keys(window.dgm).sort() })`);
      const ex = JSON.parse(exposure);
      check('renderer has no Node require/process', ex.req === 'undefined' && ex.proc === 'undefined', exposure);
      check('bridge exposes only the fixed API', ex.dgm.includes('startJob') && !ex.dgm.includes('ipcRenderer'), ex.dgm.join(','));

      // Start button disabled until tiles, output and settings are present.
      check('start disabled initially', await js(`document.getElementById('btn-start').disabled`));

      // Choose output folder and tile(s) via the (patched) dialogs.
      await js(`document.getElementById('btn-pick-output').click()`);
      await waitFor(async () => (await text('output-path')).includes(OUT), 5000, 'output folder');
      check('output folder chosen', true, OUT);

      await js(`document.getElementById('btn-pick-files').click()`);
      await waitFor(async () => (await text('tile-status')).includes('accepted'), 60000, 'tile inspection');
      const tileText = await js(`document.querySelector('#tile-table tbody').textContent`);
      check('tile listed as accepted', tileText.includes(path.basename(TILE)) && tileText.includes('accepted'));
      check('elevation range shown', (await text('tile-status')).includes('elevation'), await text('tile-status'));

      // Coverage: a box that is only partly covered must be reported as such.
      await js(`document.getElementById('use-bbox').click()`);
      const setBox = (x0, y0, x1, y1) => js(`(() => {
        const set = (id, v) => { const e = document.getElementById(id); e.value = String(v); e.dispatchEvent(new Event('input')); };
        set('bb-xmin', ${x0}); set('bb-ymin', ${y0}); set('bb-xmax', ${x1}); set('bb-ymax', ${y1});
      })()`);
      await setBox(531000, 161300, 531400, 161500);
      await js(`document.getElementById('btn-check-cover').click()`);
      await waitFor(async () => (await text('coverage-status')).includes('do NOT'), 60000, 'partial coverage warning');
      check('partial coverage is flagged', true, (await text('coverage-status')).slice(0, 90));

      await setBox(531300, 161300, 531500, 161500);
      await js(`document.getElementById('btn-check-cover').click()`);
      await waitFor(async () => (await text('coverage-status')).includes('completely cover'), 60000, 'full coverage');
      check('full coverage is confirmed', true);

      // Settings: invalid major interval blocks the run.
      await js(`(() => { const e = document.getElementById('major'); e.value = '2.5'; e.dispatchEvent(new Event('input')); })()`);
      check('invalid major interval blocks start', await js(`document.getElementById('btn-start').disabled`));
      await js(`(() => { const e = document.getElementById('major'); e.value = '5'; e.dispatchEvent(new Event('input')); })()`);
      check('valid settings enable start', !(await js(`document.getElementById('btn-start').disabled`)));

      // Full run with contours and points.
      await js(`document.getElementById('out-points').click()`);
      await js(`document.getElementById('prefix').value = 'E2E'`);
      await js(`document.getElementById('btn-start').click()`);
      await waitFor(async () => (await text('run-status')).includes('Conversion finished'), 180000, 'conversion to finish');
      check('conversion finished', true);
      const files = fs.readdirSync(OUT).sort();
      for (const f of ['E2E_Hoehenlinien.dxf', 'E2E_Hoehenpunkte.dxf', 'E2E_README.txt', 'E2E_DGM_EPSG31258.zip']) {
        check(`output present: ${f}`, files.includes(f));
      }
      check('no hidden job folder left behind', !files.some((f) => f.startsWith('.dgm-job')));
      const rows = await js(`document.querySelector('#result-table tbody').textContent`);
      check('results table lists the DXF files', rows.includes('E2E_Hoehenpunkte.dxf'));
      const pointsSize = fs.statSync(path.join(OUT, 'E2E_Hoehenpunkte.dxf')).size;
      check('points DXF is non-empty', pointsSize > 1000, `${pointsSize} bytes`);

      // Cancel: start the whole tile with TIN, cancel shortly after, expect cleanup.
      await js(`document.getElementById('out-tin').click()`);
      await js(`document.getElementById('use-bbox').click()`);
      await js(`document.getElementById('prefix').value = 'CANCEL'`);
      await js(`document.getElementById('btn-start').click()`);
      await waitFor(async () => (await js(`document.getElementById('btn-cancel').disabled`)) === false, 5000, 'cancel button');
      await sleep(2500);
      await js(`document.getElementById('btn-cancel').click()`);
      await waitFor(async () => (await text('run-status')).includes('Cancelled'), 60000, 'cancel');
      await sleep(500);
      const after = fs.readdirSync(OUT);
      check('cancel removes incomplete output', !after.some((f) => f.startsWith('CANCEL') || f.startsWith('.dgm-job')),
        after.filter((f) => f.startsWith('CANCEL') || f.startsWith('.dgm')).join(',') || 'clean');
    } catch (err) {
      code = 1;
      check('smoke run completed', false, err.message);
    }
    const failed = results.filter((r) => !r.ok).length;
    console.log(`\n${results.length - failed}/${results.length} checks passed`);
    app.exit(code || (failed ? 1 : 0));
  });
}
