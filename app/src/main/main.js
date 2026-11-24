'use strict';
const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const engine = require('./engine');
const v = require('./validation');

const ENGINE_DIR = path.resolve(__dirname, '..', '..', '..', 'engine');
const PRELOAD = path.join(__dirname, '..', 'preload', 'preload.js');
const RENDERER = path.join(__dirname, '..', 'renderer', 'index.html');

let win = null;
let outputDirChosen = null; // set only through the folder dialog
let job = null;             // { child, jobDir, cancelled, configPath, outputDir }

function resolvedEngine() {
  return engine.resolveEngine({
    isPackaged: app.isPackaged,
    resourcesPath: process.resourcesPath,
    platform: process.platform,
    env: process.env,
    engineDir: ENGINE_DIR,
  });
}

function createWindow() {
  win = new BrowserWindow({
    width: 1240,
    height: 860,
    minWidth: 980,
    minHeight: 680,
    title: 'TerraTech',
    backgroundColor: '#f5f6f8',
    webPreferences: {
      preload: PRELOAD,
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
      spellcheck: false,
    },
  });
  win.setMenuBarVisibility(false);
  // The window must never navigate away or open new windows.
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.webContents.on('will-navigate', (e) => e.preventDefault());
  win.loadFile(RENDERER);
  win.on('closed', () => { win = null; });
}

function sendToRenderer(channel, payload) {
  if (win && !win.isDestroyed()) win.webContents.send(channel, payload);
}

function safeError(err) {
  return (err && err.message) ? err.message : String(err);
}

/** Remove a job folder the engine created, but only if it is where we expect. */
function removeJobDir(jobDir, outputDir) {
  if (!jobDir || !outputDir) return;
  const resolved = path.resolve(jobDir);
  if (path.dirname(resolved) !== path.resolve(outputDir)) return;
  if (!v.isJobDirName(path.basename(resolved))) return;
  fs.rmSync(resolved, { recursive: true, force: true });
}

// ---------------------------------------------------------------- IPC handlers

function registerIpc() {
  ipcMain.handle('dialog:pickTiles', async () => {
    const res = await dialog.showOpenDialog(win, {
      title: 'Select KAGIS DGM tiles (dgm_*.tif)',
      properties: ['openFile', 'multiSelections'],
      filters: [{ name: 'GeoTIFF', extensions: ['tif', 'tiff'] }],
    });
    if (res.canceled) return [];
    return res.filePaths.filter((p) => v.validateTilePath(p).ok);
  });

  ipcMain.handle('dialog:pickTileFolder', async () => {
    const res = await dialog.showOpenDialog(win, {
      title: 'Select the folder that contains the dgm_*.tif tiles',
      properties: ['openDirectory'],
    });
    if (res.canceled || !res.filePaths[0]) return [];
    return v.listTilesInFolder(res.filePaths[0]);
  });

  ipcMain.handle('dialog:pickOutputDir', async () => {
    const res = await dialog.showOpenDialog(win, {
      title: 'Choose the output folder',
      properties: ['openDirectory', 'createDirectory'],
    });
    if (res.canceled || !res.filePaths[0]) return null;
    outputDirChosen = v.validateOutputDir(res.filePaths[0]);
    return outputDirChosen;
  });

  ipcMain.handle('tiles:filter', (_e, paths) => {
    if (!Array.isArray(paths)) return [];
    return paths.filter((p) => typeof p === 'string' && v.validateTilePath(p).ok);
  });

  ipcMain.handle('tiles:inspect', async (_e, payload) => {
    const tiles = v.validateTileList(payload && payload.tiles);
    const bbox = v.validateBbox(payload && payload.bbox);
    return engine.runInspect(resolvedEngine(), tiles, bbox);
  });

  ipcMain.handle('job:start', (_e, cfg) => startJob(cfg));

  ipcMain.handle('job:cancel', () => {
    if (!job) return false;
    job.cancelled = true;
    job.child.kill();
    return true;
  });

  ipcMain.handle('folder:open', async (_e, folder) => {
    if (!outputDirChosen) throw new Error('No output folder has been chosen.');
    const target = v.isSafeAbsolutePath(folder) ? folder : null;
    if (!target || !v.isInside(outputDirChosen, target) || !fs.existsSync(target)) {
      throw new Error('That folder is not an output folder of this session.');
    }
    const err = await shell.openPath(target);
    if (err) throw new Error(err);
    return true;
  });

  ipcMain.handle('app:info', () => ({
    version: app.getVersion(),
    engine: resolvedEngine().command,
    packaged: app.isPackaged,
  }));
}

function startJob(cfg) {
  if (job) throw new Error('A conversion is already running.');
  if (!cfg || typeof cfg !== 'object') throw new Error('Invalid job settings.');

  const tiles = v.validateTileList(cfg.tiles);
  const bbox = v.validateBbox(cfg.bbox);
  const prefix = v.validatePrefix(cfg.prefix || 'KAGIS');
  const outputs = Array.isArray(cfg.outputs) ? cfg.outputs.filter((o) => ['contours', 'points', 'tin'].includes(o)) : [];
  if (outputs.length === 0) throw new Error('Select at least one output.');
  if (!outputDirChosen) throw new Error('Choose an output folder first.');
  const outputDir = v.validateOutputDir(outputDirChosen);
  const interval = Number(cfg.contour_interval);
  const major = Number(cfg.major_interval);
  if (!(Number.isFinite(interval) && interval > 0 && Number.isFinite(major) && major > 0)) {
    throw new Error('Contour intervals must be positive numbers.');
  }

  const jobId = crypto.randomUUID();
  const configDir = path.join(app.getPath('userData'), 'jobs');
  fs.mkdirSync(configDir, { recursive: true });
  const configPath = path.join(configDir, `${jobId}.json`);
  const config = {
    tiles, bbox, outputs, prefix,
    contour_interval: interval,
    major_interval: major,
    output_dir: outputDir,
    make_zip: Boolean(cfg.make_zip),
  };
  fs.writeFileSync(configPath, JSON.stringify(config), { encoding: 'utf8', mode: 0o600 });

  const state = { child: null, jobDir: null, cancelled: false, configPath, outputDir, finished: false };
  job = state;
  state.child = engine.spawnEngine(resolvedEngine(), ['convert', '--config', configPath], {
    onEvent: (ev) => {
      if (ev.event === 'job' && typeof ev.job_dir === 'string') state.jobDir = ev.job_dir;
      if (ev.event === 'done') state.finished = true;
      sendToRenderer('job:event', ev);
    },
  });

  state.child.on('error', (err) => {
    sendToRenderer('job:event', { event: 'error', kind: 'internal', message: `Cannot start the engine: ${err.message}` });
  });

  state.child.on('close', (code) => {
    try {
      if (state.cancelled) {
        removeJobDir(state.jobDir, state.outputDir);
        sendToRenderer('job:event', { event: 'cancelled', message: 'Cancelled. Incomplete files were removed.' });
      } else if (!state.finished && code !== 0) {
        removeJobDir(state.jobDir, state.outputDir);
        const tail = state.child.stderrTail().trim().split('\n').slice(-3).join(' ');
        sendToRenderer('job:event', { event: 'error', kind: 'failed', message: `The conversion stopped (exit ${code}). ${tail}`.trim() });
      } else {
        removeJobDir(state.jobDir, state.outputDir);
      }
    } catch (err) {
      sendToRenderer('job:event', { event: 'error', kind: 'cleanup', message: `Cleanup failed: ${safeError(err)}` });
    } finally {
      try { fs.rmSync(state.configPath, { force: true }); } catch (_e) { /* ignore */ }
      job = null;
    }
  });

  return { started: true };
}

// ---------------------------------------------------------------- lifecycle

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (win) {
      if (win.isMinimized()) win.restore();
      win.focus();
    }
  });

  app.whenReady().then(() => {
    registerIpc();
    createWindow();
    app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
  });

  app.on('window-all-closed', () => {
    if (job) job.child.kill();
    app.quit();
  });

  app.on('web-contents-created', (_e, contents) => {
    contents.on('will-attach-webview', (ev) => ev.preventDefault());
  });
}

module.exports = { startJob };
