'use strict';
// The only bridge between the renderer and the main process. It exposes a fixed
// list of functions; the renderer never receives ipcRenderer or Node APIs.
const { contextBridge, ipcRenderer, webUtils } = require('electron');

function on(channel, cb) {
  const handler = (_event, payload) => cb(payload);
  ipcRenderer.on(channel, handler);
  return () => ipcRenderer.removeListener(channel, handler);
}

contextBridge.exposeInMainWorld('dgm', {
  pickTiles: () => ipcRenderer.invoke('dialog:pickTiles'),
  pickTileFolder: () => ipcRenderer.invoke('dialog:pickTileFolder'),
  pickOutputDir: () => ipcRenderer.invoke('dialog:pickOutputDir'),
  // Dropped files: only their on-disk paths are passed on; contents are never read here.
  pathsForDroppedFiles: (files) => Array.from(files || [])
    .map((f) => {
      try { return webUtils.getPathForFile(f); } catch (_e) { return ''; }
    })
    .filter((p) => typeof p === 'string' && p.length > 0),
  filterTiles: (paths) => ipcRenderer.invoke('tiles:filter', paths),
  inspect: (tiles, bbox) => ipcRenderer.invoke('tiles:inspect', { tiles, bbox }),
  startJob: (cfg) => ipcRenderer.invoke('job:start', cfg),
  cancelJob: () => ipcRenderer.invoke('job:cancel'),
  openFolder: (folder) => ipcRenderer.invoke('folder:open', folder),
  appInfo: () => ipcRenderer.invoke('app:info'),
  onJobEvent: (cb) => on('job:event', cb),
});
