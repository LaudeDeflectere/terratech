#!/usr/bin/env node
// Builds the bundled conversion engine with PyInstaller into engine/dist/dgm-engine/.
// PyInstaller cannot cross-compile: run this on Windows to produce the Windows engine
// and on Linux to produce the Linux engine. Uses the Python interpreter in
// DGM_PYTHON (default: python3 on Linux/macOS, python on Windows).
'use strict';
const { spawnSync } = require('child_process');
const path = require('path');

const here = __dirname;
const py = process.env.DGM_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const args = [
  '-m', 'PyInstaller',
  '--noconfirm', '--clean',
  '--onedir', '--console',
  '--name', 'dgm-engine',
  '--distpath', path.join(here, 'dist'),
  '--workpath', path.join(here, 'build'),
  '--specpath', path.join(here, 'build'),
  '--collect-all', 'rasterio',
  '--collect-all', 'shapely',
  '--collect-submodules', 'dgm_engine',
  '--paths', here,
  path.join(here, 'entry.py'),
];
console.log(`> ${py} ${args.join(' ')}`);
const r = spawnSync(py, args, { cwd: here, stdio: 'inherit', shell: false });
if (r.status !== 0) {
  console.error('Engine build failed.');
  process.exit(r.status || 1);
}
console.log('Engine built at', path.join(here, 'dist', 'dgm-engine'));
