'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');

const v = require('../src/main/validation');
const engine = require('../src/main/engine');

function tmpDir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'dgm-app-test-'));
}

test('tile paths must be existing dgm_*.tif files, never dom_ files', () => {
  const d = tmpDir();
  const dgm = path.join(d, 'dgm_5417-5202b.tif');
  const dom = path.join(d, 'dom_5417-5202b.tif');
  const txt = path.join(d, 'dgm_notes.txt');
  for (const f of [dgm, dom, txt]) fs.writeFileSync(f, 'x');
  assert.equal(v.validateTilePath(dgm).ok, true);
  assert.equal(v.validateTilePath(dom).ok, false);
  assert.match(v.validateTilePath(dom).reason, /dom_/);
  assert.equal(v.validateTilePath(txt).ok, false);
  assert.equal(v.validateTilePath(path.join(d, 'dgm_missing.tif')).ok, false);
  assert.equal(v.validateTilePath('relative/dgm_a.tif').ok, false);
  assert.equal(v.validateTilePath(`${d}/dgm_a\0.tif`).ok, false);
});

test('folder listing returns only dgm tiles and skips dom tiles', () => {
  const d = tmpDir();
  for (const n of ['dgm_a.tif', 'dgm_b.TIF', 'dom_a.tif', 'readme.txt']) fs.writeFileSync(path.join(d, n), 'x');
  fs.mkdirSync(path.join(d, 'dgm_folder.tif'));
  const names = v.listTilesInFolder(d).map((p) => path.basename(p));
  assert.deepEqual(names, ['dgm_a.tif', 'dgm_b.TIF']);
});

test('tile list validation rejects an empty or mixed list', () => {
  const d = tmpDir();
  const dom = path.join(d, 'dom_1.tif');
  fs.writeFileSync(dom, 'x');
  assert.throws(() => v.validateTileList([]), /No tiles/);
  assert.throws(() => v.validateTileList([dom]), /DOM|dom_/);
});

test('bounding box must be four finite numbers in order', () => {
  assert.equal(v.validateBbox(null), null);
  assert.deepEqual(v.validateBbox([1, 2, 3, 4]), [1, 2, 3, 4]);
  assert.throws(() => v.validateBbox([1, 2, 3]), /four/);
  assert.throws(() => v.validateBbox([3, 2, 1, 4]), /xmin < xmax/);
  assert.throws(() => v.validateBbox([1, 2, NaN, 4]), /numbers/);
  assert.throws(() => v.validateBbox([1, 2, 3, 1e12]), /range/);
});

test('prefix allows only safe characters', () => {
  assert.equal(v.validatePrefix('Villach_2024-a'), 'Villach_2024-a');
  assert.throws(() => v.validatePrefix('../x'));
  assert.throws(() => v.validatePrefix('a b'));
  assert.throws(() => v.validatePrefix(''));
});

test('isInside keeps job folders within the chosen output folder', () => {
  const base = path.resolve('/tmp/out');
  assert.equal(v.isInside(base, path.join(base, 'a.dxf')), true);
  assert.equal(v.isInside(base, base), true);
  assert.equal(v.isInside(base, path.join(base, '..', 'evil')), false);
  assert.equal(v.isInside(base, path.resolve('/etc/passwd')), false);
});

test('only engine-created job folder names are removable', () => {
  assert.equal(v.isJobDirName('.dgm-job-0123456789'), true);
  assert.equal(v.isJobDirName('.dgm-job-../..'), false);
  assert.equal(v.isJobDirName('Documents'), false);
});

test('engine events are parsed; other stdout lines are ignored', () => {
  assert.deepEqual(engine.parseEventLine('{"event":"progress","fraction":0.5}'),
    { event: 'progress', fraction: 0.5 });
  assert.equal(engine.parseEventLine('Warning: something'), null);
  assert.equal(engine.parseEventLine('{not json'), null);
  assert.equal(engine.parseEventLine('{"no_event":1}'), null);
});

test('engine command: bundled executable when packaged, Python module in development', () => {
  const packaged = engine.resolveEngine({
    isPackaged: true, resourcesPath: '/res', platform: 'linux', env: {}, engineDir: '/src/engine',
  });
  assert.equal(packaged.command, path.join('/res', 'engine', 'dgm-engine'));
  assert.deepEqual(packaged.args, []);

  const packagedWin = engine.resolveEngine({
    isPackaged: true, resourcesPath: 'C:\\app\\resources', platform: 'win32', env: {}, engineDir: 'x',
  });
  assert.match(packagedWin.command, /dgm-engine\.exe$/);

  const dev = engine.resolveEngine({
    isPackaged: false, resourcesPath: '', platform: 'linux', env: { DGM_PYTHON: '/usr/bin/python3' }, engineDir: '/src/engine',
  });
  assert.equal(dev.command, '/usr/bin/python3');
  assert.deepEqual(dev.args, ['-m', 'dgm_engine']);
  assert.equal(dev.cwd, '/src/engine');
});
